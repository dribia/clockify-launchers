"""Autopilot decision-engine tests."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from clockify_launchers.domain.autopilot import (
    DismissalRecord,
    RunHealth,
    build_plan,
    eligible_additions,
    removable,
)
from clockify_launchers.domain.models import (
    Candidate,
    Launcher,
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementMode,
    ManagementPolicy,
)
from clockify_launchers.domain.policies import PolicySettings
from clockify_launchers.domain.signatures import signature_of

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
SETTINGS = PolicySettings()
HEALTHY = RunHealth()


def _target(
    project: str = "p1", task: str | None = None, tags: tuple[str, ...] = ()
) -> LauncherTarget:
    return LauncherTarget(workspace_id="ws1", project_id=project, task_id=task, tag_ids=tags)


def _launcher(project: str = "p1", **kwargs: object) -> Launcher:
    defaults: dict = {
        "id": f"00000000-0000-0000-0000-0000000000{project[-2:].zfill(2)}",
        "account_id": "acc1",
        "target": _target(project),
        "display_name": project,
        "source": LauncherSource.AUTOMATIC,
        "management_policy": ManagementPolicy.MANAGED,
        "created_at": NOW - timedelta(days=200),
        "updated_at": NOW - timedelta(days=200),
        "last_clockify_use_at": NOW - timedelta(days=100),  # stale by default
    }
    defaults.update(kwargs)
    return Launcher(**defaults)


def _candidate(
    project: str = "p9", count: int = 5, last_days: int = 1, score: float = 3.0
) -> Candidate:
    return Candidate(
        target=_target(project),
        count=count,
        last_use=NOW - timedelta(days=last_days),
        score=score,
        representative_entry_id="e1",
        project_name=project,
    )


class TestRunHealth:
    def test_all_flags_ok(self) -> None:
        assert HEALTHY.safe_to_remove
        assert HEALTHY.safe_to_add
        assert HEALTHY.problems() == ()

    def test_each_flag_poisons(self) -> None:
        for f in dataclasses.fields(RunHealth):
            unhealthy = RunHealth(**{f.name: False})
            assert not unhealthy.safe_to_remove
            assert not unhealthy.safe_to_add
            assert len(unhealthy.problems()) == 1


class TestBuildPlanModes:
    def test_manual_does_nothing(self) -> None:
        plan = build_plan(
            ManagementMode.MANUAL, [_candidate()], [_launcher()], [], HEALTHY, SETTINGS, NOW
        )
        assert plan.additions == ()
        assert plan.removals == ()
        assert plan.removal_suggestions == ()
        assert plan.skipped_reasons == ("manual mode: no automation",)

    def test_assisted_suggests_not_removes(self) -> None:
        stale = _launcher()
        plan = build_plan(ManagementMode.ASSISTED, [], [stale], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == ()
        assert plan.removal_suggestions == (stale,)

    def test_autopilot_removes_stale_unpinned_automatic(self) -> None:
        stale = _launcher()
        plan = build_plan(ManagementMode.AUTOPILOT, [], [stale], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == (stale,)

    def test_pinned_never_removed(self) -> None:
        pinned = _launcher(management_policy=ManagementPolicy.PINNED)
        plan = build_plan(ManagementMode.AUTOPILOT, [], [pinned], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == ()
        assert plan.removal_suggestions == ()

    def test_manual_source_never_removed(self) -> None:
        manual = _launcher(source=LauncherSource.MANUAL)
        plan = build_plan(ManagementMode.AUTOPILOT, [], [manual], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == ()

    def test_snoozed_not_removed(self) -> None:
        snoozed = _launcher(removal_snoozed_until=NOW + timedelta(days=10))
        plan = build_plan(ManagementMode.AUTOPILOT, [], [snoozed], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == ()

    def test_grace_period_respected(self) -> None:
        graced = _launcher(auto_add_grace_until=NOW + timedelta(days=1))
        plan = build_plan(ManagementMode.AUTOPILOT, [], [graced], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == ()

    def test_fresh_launcher_not_removed(self) -> None:
        fresh = _launcher(last_clockify_use_at=NOW - timedelta(days=5))
        plan = build_plan(ManagementMode.AUTOPILOT, [], [fresh], [], HEALTHY, SETTINGS, NOW)
        assert plan.removals == ()

    def test_unhealthy_run_blocks_removals_and_additions(self) -> None:
        bad = RunHealth(complete_pagination=False)
        plan = build_plan(
            ManagementMode.AUTOPILOT, [_candidate()], [_launcher()], [], bad, SETTINGS, NOW
        )
        assert plan.removals == ()
        assert plan.additions == ()
        assert plan.safe_to_remove is False
        assert any("removals skipped" in r for r in plan.skipped_reasons)
        assert any("additions skipped" in r for r in plan.skipped_reasons)

    def test_every_health_flag_blocks_removal(self) -> None:
        for f in dataclasses.fields(RunHealth):
            bad = RunHealth(**{f.name: False})
            plan = build_plan(ManagementMode.AUTOPILOT, [], [_launcher()], [], bad, SETTINGS, NOW)
            assert plan.removals == ()
            assert plan.safe_to_remove is False


class TestAdditions:
    def test_healthy_addition(self) -> None:
        plan = build_plan(ManagementMode.ASSISTED, [_candidate()], [], [], HEALTHY, SETTINGS, NOW)
        assert len(plan.additions) == 1

    def test_dismissal_cooldown_respected(self) -> None:
        cand = _candidate()
        dismissal = DismissalRecord(
            signature=signature_of(cand.target), dismissed_at=NOW - timedelta(days=10)
        )
        assert eligible_additions([cand], [], [dismissal], SETTINGS, NOW) == []

    def test_expired_dismissal_allows_addition(self) -> None:
        cand = _candidate()
        dismissal = DismissalRecord(
            signature=signature_of(cand.target), dismissed_at=NOW - timedelta(days=40)
        )
        assert eligible_additions([cand], [], [dismissal], SETTINGS, NOW) == [cand]

    def test_duplicate_signature_not_added(self) -> None:
        cand = _candidate("p1")
        existing = _launcher("p1", last_clockify_use_at=NOW - timedelta(days=1))
        assert eligible_additions([cand], [existing], [], SETTINGS, NOW) == []

    def test_removed_launcher_signature_does_not_block(self) -> None:
        cand = _candidate("p1")
        removed = _launcher("p1", status=LauncherStatus.REMOVED)
        assert eligible_additions([cand], [removed], [], SETTINGS, NOW) == [cand]

    def test_budget_respected(self) -> None:
        settings = PolicySettings(max_auto_launchers=2)
        existing = [_launcher("a1", last_clockify_use_at=NOW)]
        cands = [_candidate(f"p{i}", score=float(10 - i)) for i in range(5)]
        picked = eligible_additions(cands, existing, [], settings, NOW)
        assert len(picked) == 1  # budget 2 - 1 existing automatic
        assert picked[0].target.project_id == "p0"  # highest score first

    def test_recent_use_shortcut(self) -> None:
        # count below min_uses but used within recent window
        cand = _candidate(count=1, last_days=3)
        assert eligible_additions([cand], [], [], SETTINGS, NOW) == [cand]

    def test_min_uses_threshold(self) -> None:
        # not recent but enough uses
        cand = _candidate(count=2, last_days=20)
        assert eligible_additions([cand], [], [], SETTINGS, NOW) == [cand]

    def test_neither_recent_nor_enough_uses(self) -> None:
        cand = _candidate(count=1, last_days=20)
        assert eligible_additions([cand], [], [], SETTINGS, NOW) == []

    def test_ineligible_candidate_skipped(self) -> None:
        cand = dataclasses.replace(_candidate(), eligible=False)
        assert eligible_additions([cand], [], [], SETTINGS, NOW) == []


class TestCapBudget:
    def test_removal_frees_slot_in_same_run(self) -> None:
        """A cap-filling stale launcher removed by this run must not block it."""
        settings = PolicySettings(max_auto_launchers=1)
        stale = _launcher()  # automatic, unpinned, stale
        plan = build_plan(
            ManagementMode.AUTOPILOT, [_candidate()], [stale], [], HEALTHY, settings, NOW
        )
        assert plan.removals == (stale,)
        assert len(plan.additions) == 1

    def test_assisted_removal_suggestion_frees_no_slot(self) -> None:
        """Assisted never removes, so suggestions must not inflate the budget."""
        settings = PolicySettings(max_auto_launchers=1)
        stale = _launcher()
        plan = build_plan(
            ManagementMode.ASSISTED, [_candidate()], [stale], [], HEALTHY, settings, NOW
        )
        assert plan.removal_suggestions == (stale,)
        assert plan.additions == ()
        assert plan.blocked_additions == (_candidate(),)

    def test_full_cap_records_blocked_and_reason(self) -> None:
        settings = PolicySettings(max_auto_launchers=1)
        fresh = _launcher("a1", last_clockify_use_at=NOW - timedelta(days=1))
        cands = [_candidate("p0", score=3.0), _candidate("p1", score=2.0)]
        plan = build_plan(ManagementMode.AUTOPILOT, cands, [fresh], [], HEALTHY, settings, NOW)
        assert plan.removals == ()
        assert plan.additions == ()
        assert plan.blocked_additions == (cands[0], cands[1])
        assert any(
            "automatic launcher cap reached" in r and "waiting for a free slot" in r
            for r in plan.skipped_reasons
        )

    def test_unsafe_run_blocks_additions_without_cap_reason(self) -> None:
        """Health skips are not cap skips: nothing may be reported blocked."""
        bad = RunHealth(complete_pagination=False)
        settings = PolicySettings(max_auto_launchers=1)
        fresh = _launcher("a1", last_clockify_use_at=NOW - timedelta(days=1))
        plan = build_plan(ManagementMode.AUTOPILOT, [_candidate()], [fresh], [], bad, settings, NOW)
        assert plan.additions == ()
        assert plan.blocked_additions == ()
        assert not any("cap reached" in r for r in plan.skipped_reasons)
        assert plan.safe_to_remove is False


class TestRemovable:
    def test_ok(self) -> None:
        ok, reason = removable(_launcher(), NOW, SETTINGS)
        assert ok and reason == ""

    def test_reasons(self) -> None:
        cases = [
            (_launcher(status=LauncherStatus.REMOVED), "already removed"),
            (_launcher(management_policy=ManagementPolicy.PINNED), "pinned"),
            (_launcher(source=LauncherSource.MANUAL), "not automatically managed"),
            (_launcher(source=LauncherSource.IMPORTED), "not automatically managed"),
            (
                _launcher(status=LauncherStatus.EXTERNALLY_MODIFIED),
                "modified outside the application",
            ),
            (_launcher(removal_snoozed_until=NOW + timedelta(days=1)), "removal snoozed"),
            (
                _launcher(auto_add_grace_until=NOW + timedelta(days=1)),
                "within new-launcher grace period",
            ),
            (_launcher(last_clockify_use_at=NOW - timedelta(days=1)), "not stale"),
        ]
        for lc, expected in cases:
            ok, reason = removable(lc, NOW, SETTINGS)
            assert not ok
            assert reason == expected
