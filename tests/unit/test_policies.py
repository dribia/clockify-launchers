"""Policy tests: scoring, staleness, validation, naming."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from clockify_launchers.domain.models import Launcher, LauncherTarget
from clockify_launchers.domain.policies import (
    PolicySettings,
    default_name,
    effective_last_use,
    is_snoozed,
    is_stale,
    recency_score,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
LID = "6d17b662-5ba4-4c39-903b-cc319a633fe7"


def _launcher(**kwargs: object) -> Launcher:
    defaults: dict = {
        "id": LID,
        "account_id": "acc1",
        "target": LauncherTarget(workspace_id="ws1", project_id="p1"),
        "display_name": "Test",
        "created_at": NOW - timedelta(days=100),
        "updated_at": NOW - timedelta(days=100),
    }
    defaults.update(kwargs)
    return Launcher(**defaults)


class TestRecencyScore:
    def test_deterministic(self) -> None:
        times = [NOW - timedelta(days=d) for d in (1, 5, 10)]
        assert recency_score(times, NOW, 21) == recency_score(times, NOW, 21)

    def test_values(self) -> None:
        assert recency_score([NOW], NOW, 21) == 1.0
        one = recency_score([NOW - timedelta(days=21)], NOW, 21)
        assert math.isclose(one, math.exp(-1.0))
        assert recency_score([], NOW, 21) == 0.0

    def test_future_use_clamped(self) -> None:
        assert recency_score([NOW + timedelta(days=5)], NOW, 21) == 1.0

    def test_ordering(self) -> None:
        recent = recency_score([NOW - timedelta(days=1)] * 2, NOW, 21)
        old = recency_score([NOW - timedelta(days=60)] * 2, NOW, 21)
        assert recent > old
        more = recency_score([NOW - timedelta(days=1)] * 3, NOW, 21)
        assert more > recent


class TestEffectiveLastUse:
    def test_created_at_only(self) -> None:
        lc = _launcher()
        assert effective_last_use(lc) == lc.created_at

    def test_newest_wins(self) -> None:
        lc = _launcher(
            last_clockify_use_at=NOW - timedelta(days=10),
            last_start_success_at=NOW - timedelta(days=5),
        )
        assert effective_last_use(lc) == NOW - timedelta(days=5)

    def test_grace_counts(self) -> None:
        lc = _launcher(auto_add_grace_until=NOW - timedelta(days=2))
        assert effective_last_use(lc) == NOW - timedelta(days=2)


class TestIsStale:
    def test_not_stale_when_recent(self) -> None:
        lc = _launcher(last_clockify_use_at=NOW - timedelta(days=10))
        assert not is_stale(lc, NOW, PolicySettings())

    def test_stale_after_threshold(self) -> None:
        lc = _launcher(last_clockify_use_at=NOW - timedelta(days=46))
        assert is_stale(lc, NOW, PolicySettings())

    def test_exactly_at_threshold_not_stale(self) -> None:
        lc = _launcher(last_clockify_use_at=NOW - timedelta(days=45))
        assert not is_stale(lc, NOW, PolicySettings())

    def test_grace_period_prevents_staleness(self) -> None:
        lc = _launcher(auto_add_grace_until=NOW + timedelta(days=1))
        assert not is_stale(lc, NOW, PolicySettings())

    def test_snoozed(self) -> None:
        assert is_snoozed(_launcher(removal_snoozed_until=NOW + timedelta(days=1)), NOW)
        assert not is_snoozed(_launcher(removal_snoozed_until=NOW - timedelta(days=1)), NOW)
        assert not is_snoozed(_launcher(), NOW)


class TestPolicySettingsValidated:
    def test_defaults_pass_through(self) -> None:
        assert PolicySettings().validated() == PolicySettings()

    def test_clamping(self) -> None:
        s = PolicySettings(
            sync_interval_minutes=1,
            lookback_days=1000,
            half_life_days=0,
            recent_use_days=0,
            min_uses=0,
            min_uses_window_days=0,
            stale_days=1,
            grace_days=-3,
            snooze_days=0,
            max_auto_launchers=500,
        ).validated()
        assert s.sync_interval_minutes == 5
        assert s.lookback_days == 365
        assert s.half_life_days == 1
        assert s.recent_use_days == 1
        assert s.min_uses == 1
        assert s.min_uses_window_days == 1
        assert s.stale_days == 14
        assert s.grace_days == 0
        assert s.snooze_days == 1
        assert s.max_auto_launchers == 100

    def test_upper_bounds(self) -> None:
        s = PolicySettings(sync_interval_minutes=10_000, stale_days=9999).validated()
        assert s.sync_interval_minutes == 24 * 60
        assert s.stale_days == 365


class TestDefaultName:
    def test_base_project_only(self) -> None:
        assert default_name("Proj", None, (), set(), LID) == "Proj"

    def test_base_with_task(self) -> None:
        assert default_name("Proj", "Task", (), set(), LID) == "Proj - Task"

    def test_tag_qualifier_on_conflict(self) -> None:
        name = default_name("Proj", None, ("dev", "ops"), {"Proj"}, LID)
        assert name == "Proj (dev, ops)"

    def test_uuid_suffix_when_all_taken(self) -> None:
        existing = {"Proj", "Proj (dev)"}
        name = default_name("Proj", None, ("dev",), existing, LID)
        assert name == f"Proj (dev) [{LID[:8]}]"

    def test_uuid_suffix_without_tags(self) -> None:
        name = default_name("Proj", None, (), {"Proj"}, LID)
        assert name == f"Proj [{LID[:8]}]"
