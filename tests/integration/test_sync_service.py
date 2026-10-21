"""SyncService end-to-end with the FakeClockifyClient and demo fixtures."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from clockify_launchers.demo import fixtures
from clockify_launchers.demo.backend import FakeClockifyClient
from clockify_launchers.domain.models import (
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementMode,
    SuggestionType,
)
from clockify_launchers.domain.policies import PolicySettings
from clockify_launchers.services.sync_service import SyncService

NOW = fixtures.DEMO_NOW


def make_sync(env, client: FakeClockifyClient | None = None) -> SyncService:
    return SyncService(
        env.db,
        env.launcher_service,
        client or FakeClockifyClient(),
        env.account.id,
        fixtures.DEMO_USER_ID,
        fixtures.WS_MAIN.id,
    )


def stale_auto_launcher(env, project_id: str = "prj-ops", days_old: int = 60):
    """An automatic, unpinned launcher created long ago with no matching activity."""
    target = LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id=project_id)
    return env.launcher_service.create(
        account_id=env.account.id,
        target=target,
        display_name="Stale Ops",
        source=LauncherSource.AUTOMATIC,
        now=NOW - timedelta(days=days_old),
    )


def test_assisted_creates_launchers_from_frequent_activity(env):
    sync = make_sync(env)
    result = sync.run(ManagementMode.ASSISTED, PolicySettings(), now=NOW)
    assert result.outcome == "success"
    assert result.removed == ()
    added_signatures = {lc.target.signature for lc in result.added}
    tank_sig = (fixtures.WS_MAIN.id, "prj-tank", "task-model", ("tag-project",))
    assert tank_sig in added_signatures
    for launcher in result.added:
        assert launcher.source is LauncherSource.AUTOMATIC
        assert not launcher.pinned
        assert Path(launcher.desktop_path).exists()
    # Below-threshold single use never becomes a launcher.
    assert (fixtures.WS_MAIN.id, "prj-website", None, ()) not in added_signatures


def test_assisted_stale_launcher_produces_remove_suggestion(env):
    stale = stale_auto_launcher(env)
    sync = make_sync(env)
    result = sync.run(ManagementMode.ASSISTED, PolicySettings(), now=NOW)
    assert result.outcome == "success"
    assert result.removed == ()
    assert Path(stale.desktop_path).exists()
    suggestions = [
        s
        for s in env.db.list_suggestions()
        if s.type is SuggestionType.REMOVE and s.launcher_id == stale.id
    ]
    assert len(suggestions) == 1
    assert "days" in suggestions[0].explanation
    # The explanation cites a concrete day count >= the 45-day stale threshold.
    days = [int(w) for w in suggestions[0].explanation.split() if w.isdigit()]
    assert days and days[0] >= 45


def test_autopilot_removes_stale_unpinned_with_tombstone(env):
    stale = stale_auto_launcher(env)
    sync = make_sync(env)
    result = sync.run(ManagementMode.AUTOPILOT, PolicySettings(), now=NOW)
    assert result.outcome == "success"
    removed_ids = {lc.id for lc in result.removed}
    assert stale.id in removed_ids
    assert not Path(stale.desktop_path).exists()
    assert env.db.get_tombstone(stale.id) is not None
    assert env.db.get_launcher(stale.id).status is LauncherStatus.REMOVED


def test_autopilot_never_removes_pinned(env):
    stale = stale_auto_launcher(env)
    stale = env.launcher_service.set_pinned(stale, True)
    sync = make_sync(env)
    result = sync.run(ManagementMode.AUTOPILOT, PolicySettings(), now=NOW)
    assert result.outcome == "success"
    assert stale.id not in {lc.id for lc in result.removed}
    assert Path(stale.desktop_path).exists()


def test_offline_changes_nothing_on_disk(env):
    stale = stale_auto_launcher(env)
    files_before = sorted(env.paths.applications_dir.iterdir())
    sync = make_sync(env, FakeClockifyClient(offline=True))
    result = sync.run(ManagementMode.AUTOPILOT, PolicySettings(), now=NOW)
    assert result.outcome == "offline"
    assert not result.safe_to_remove
    assert result.added == () and result.removed == ()
    assert sorted(env.paths.applications_dir.iterdir()) == files_before
    assert Path(stale.desktop_path).exists()


def test_auth_error_outcome(env):
    sync = make_sync(env, FakeClockifyClient(auth_error=True))
    result = sync.run(ManagementMode.ASSISTED, PolicySettings(), now=NOW)
    assert result.outcome == "auth-error"
    assert not result.safe_to_remove


def test_last_successful_sync_preserved_after_failed_run(env):
    make_sync(env).run(ManagementMode.ASSISTED, PolicySettings(), now=NOW)
    last_ok = env.db.last_successful_sync()
    assert last_ok is not None
    make_sync(env, FakeClockifyClient(offline=True)).run(
        ManagementMode.ASSISTED, PolicySettings(), now=NOW
    )
    assert env.db.last_successful_sync() == last_ok
    assert env.db.last_sync_run()["outcome"] == "offline"


def test_externally_modified_file_poisons_removals(env):
    stale = stale_auto_launcher(env)
    path = Path(stale.desktop_path)
    path.write_text(path.read_text() + "\n# hand edit\n")
    sync = make_sync(env)
    result = sync.run(ManagementMode.AUTOPILOT, PolicySettings(), now=NOW)
    assert result.removed == ()
    assert not result.safe_to_remove
    assert path.exists()


def test_running_sync_twice_does_not_duplicate(env):
    sync = make_sync(env)
    first = sync.run(ManagementMode.ASSISTED, PolicySettings(), now=NOW)
    assert first.added
    count_after_first = len(env.db.list_launchers())
    second = sync.run(ManagementMode.ASSISTED, PolicySettings(), now=NOW)
    assert second.added == ()
    assert len(env.db.list_launchers()) == count_after_first


def test_manual_mode_is_a_skip(env):
    sync = make_sync(env)
    result = sync.run(ManagementMode.MANUAL, PolicySettings(), now=NOW)
    assert result.outcome == "skipped"
    assert result.added == () and result.removed == ()
    assert env.db.list_launchers() == []


def test_full_cap_blocks_additions_visibly(env):
    """A full automatic-launcher cap must not silently hide candidates."""
    settings = PolicySettings(max_auto_launchers=1)
    env.launcher_service.create(
        account_id=env.account.id,
        target=LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id="prj-ops"),
        display_name="Ops",
        source=LauncherSource.AUTOMATIC,
        now=NOW,
    )
    sync = make_sync(env)
    result = sync.run(ManagementMode.ASSISTED, settings, now=NOW)
    assert result.outcome == "success"
    assert result.added == ()
    assert {c.project_name for c in result.blocked} >= {"Tank", "Research"}
    assert "cap reached" in result.detail and "free slot" in result.detail


def test_autopilot_reuses_slot_freed_by_removal_in_same_run(env):
    """The run that removes a stale launcher can add within the freed slot."""
    settings = PolicySettings(max_auto_launchers=1)
    stale = stale_auto_launcher(env)
    sync = make_sync(env)
    result = sync.run(ManagementMode.AUTOPILOT, settings, now=NOW)
    assert result.outcome == "success"
    assert stale.id in {lc.id for lc in result.removed}
    added_projects = {lc.target.project_id for lc in result.added}
    assert "prj-tank" in added_projects
    # Only one slot was freed: the runner-up candidate waits, visibly.
    assert [c.project_name for c in result.blocked] == ["Research"]
    assert "cap reached" in result.detail
