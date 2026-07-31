"""SQLite database roundtrip and migration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from clockify_launchers.domain.models import (
    Account,
    ActivityEvent,
    EventSeverity,
    IconKind,
    Launcher,
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementPolicy,
    Suggestion,
    SuggestionState,
    SuggestionType,
    Tombstone,
)
from clockify_launchers.infrastructure.database import Database

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
LID = "6d17b662-5ba4-4c39-903b-cc319a633fe7"

ACCOUNT = Account(
    id="acc1",
    api_base_url="https://api.clockify.me/api",
    clockify_user_id="u1",
    email="a@b.c",
    display_name="A B",
    active_workspace_id="ws1",
    created_at=NOW - timedelta(days=30),
    last_validated_at=NOW,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "state.db")
    yield database
    database.close()


def _full_launcher() -> Launcher:
    return Launcher(
        id=LID,
        account_id="acc1",
        target=LauncherTarget(
            workspace_id="ws1",
            project_id="p1",
            task_id="t1",
            tag_ids=("b", "a"),
            description="fixed desc",
        ),
        display_name="Kaito",
        comment="Start Clockify timer",
        icon_kind=IconKind.SELECTED,
        icon_path="/tmp/icon.png",
        source=LauncherSource.IMPORTED,
        management_policy=ManagementPolicy.MANAGED,
        status=LauncherStatus.STALE,
        created_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=5),
        last_invoked_at=NOW - timedelta(days=4),
        last_start_success_at=NOW - timedelta(days=3),
        last_clockify_use_at=NOW - timedelta(days=2),
        auto_add_grace_until=NOW + timedelta(days=1),
        removal_snoozed_until=NOW + timedelta(days=7),
        desktop_path="/tmp/x.desktop",
        desktop_hash="abc123",
        icon_hash="def456",
        removed_at=NOW - timedelta(days=1),
        removal_reason="stale",
    )


class TestMigrations:
    def test_idempotent_reopen(self, tmp_path: Path) -> None:
        path = tmp_path / "state.db"
        db1 = Database(path)
        db1.close()
        db2 = Database(path)  # applying again must not fail
        row = db2.connection.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] >= 1
        assert db2.connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
        db2.close()


class TestAccountAndLauncher:
    def test_account_roundtrip(self, db: Database) -> None:
        db.save_account(ACCOUNT)
        assert db.get_account("acc1") == ACCOUNT
        assert db.get_account("nope") is None

    def test_launcher_roundtrip_all_fields(self, db: Database) -> None:
        db.save_account(ACCOUNT)
        lc = _full_launcher()
        db.save_launcher(lc)
        loaded = db.get_launcher(LID)
        assert loaded == lc
        assert loaded.target.tag_ids == ("a", "b")  # normalized tuple preserved
        assert loaded.created_at.tzinfo is UTC
        assert loaded.last_clockify_use_at == NOW - timedelta(days=2)

    def test_launcher_upsert(self, db: Database) -> None:
        db.save_account(ACCOUNT)
        lc = _full_launcher()
        db.save_launcher(lc)
        db.save_launcher(lc.with_(display_name="Renamed"))
        assert db.get_launcher(LID).display_name == "Renamed"
        assert len(db.list_launchers(include_removed=True)) == 1

    def test_list_launchers_excludes_removed(self, db: Database) -> None:
        db.save_account(ACCOUNT)
        db.save_launcher(_full_launcher().with_(status=LauncherStatus.REMOVED))
        assert db.list_launchers() == []
        assert len(db.list_launchers(include_removed=True)) == 1

    def test_delete_launcher_row(self, db: Database) -> None:
        db.save_account(ACCOUNT)
        db.save_launcher(_full_launcher())
        db.delete_launcher_row(LID)
        assert db.get_launcher(LID) is None


class TestSuggestions:
    def test_roundtrip(self, db: Database) -> None:
        s = Suggestion(
            id="s1",
            type=SuggestionType.ADD,
            launcher_id=None,
            target=LauncherTarget(workspace_id="ws1", project_id="p1", tag_ids=("t",)),
            explanation="used 3 times",
            evidence="entries e1..e3",
            created_at=NOW,
        )
        db.save_suggestion(s)
        loaded = db.list_suggestions()
        assert loaded == [s]

    def test_remove_suggestion_without_target(self, db: Database) -> None:
        s = Suggestion(
            id="s2",
            type=SuggestionType.REMOVE,
            launcher_id=LID,
            target=None,
            explanation="stale for 52 days",
            evidence="",
            state=SuggestionState.SNOOZED,
            created_at=NOW,
            snoozed_until=NOW + timedelta(days=30),
        )
        db.save_suggestion(s)
        assert db.list_suggestions(SuggestionState.SNOOZED) == [s]
        assert db.list_suggestions(SuggestionState.OPEN) == []
        assert db.get_suggestion("s2") == s


class TestDismissals:
    def test_roundtrip_and_upsert(self, db: Database) -> None:
        target = LauncherTarget(
            workspace_id="ws1", project_id="p1", task_id="t1", tag_ids=("b", "a")
        )
        db.record_dismissal(target, NOW, cooldown_days=15)
        db.record_dismissal(target, NOW + timedelta(days=1), cooldown_days=20)
        records = db.list_dismissals()
        assert len(records) == 1
        rec = records[0]
        assert rec.signature == ("ws1", "p1", "t1", ("a", "b"))
        assert rec.dismissed_at == NOW + timedelta(days=1)
        assert rec.cooldown_days == 20


class TestEvents:
    def test_roundtrip(self, db: Database) -> None:
        e = ActivityEvent(
            id="ev1",
            event_type="timer-start",
            severity=EventSeverity.INFO,
            summary="started",
            details="detail",
            launcher_id=None,
            created_at=NOW,
        )
        db.record_event(e)
        assert db.list_events() == [e]

    def test_compact_events_retention(self, db: Database) -> None:
        old = ActivityEvent(
            id="old",
            event_type="x",
            severity=EventSeverity.INFO,
            summary="old",
            created_at=NOW - timedelta(days=100),
        )
        recent = ActivityEvent(
            id="recent",
            event_type="x",
            severity=EventSeverity.INFO,
            summary="recent",
            created_at=NOW - timedelta(days=1),
        )
        db.record_event(old)
        db.record_event(recent)
        db.compact_events(NOW)
        ids = {e.id for e in db.list_events()}
        # only two events: both within the 2000-event cap, so both retained
        assert ids == {"old", "recent"}

    def test_compact_events_deletes_old_beyond_cap(self, db: Database) -> None:
        # Fill beyond the cap with recent events, plus one ancient event.
        from clockify_launchers.infrastructure.database import ACTIVITY_MAX_EVENTS

        with db.connection:
            for i in range(ACTIVITY_MAX_EVENTS):
                db.connection.execute(
                    "INSERT INTO activity_events (id, event_type, severity, summary, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (f"e{i}", "x", "info", "s", int((NOW - timedelta(days=1)).timestamp())),
                )
            db.connection.execute(
                "INSERT INTO activity_events (id, event_type, severity, summary, created_at)"
                " VALUES (?,?,?,?,?)",
                ("ancient", "x", "info", "s", int((NOW - timedelta(days=100)).timestamp())),
            )
        db.compact_events(NOW)
        row = db.connection.execute(
            "SELECT COUNT(*) FROM activity_events WHERE id = 'ancient'"
        ).fetchone()
        assert row[0] == 0


class TestTombstones:
    def test_roundtrip_and_prune(self, db: Database) -> None:
        t = Tombstone(
            launcher_id=LID, removed_at=NOW - timedelta(days=10), reason="stale", launcher_json="{}"
        )
        db.save_tombstone(t)
        assert db.get_tombstone(LID) == t
        assert db.list_tombstones() == [t]
        db.prune_tombstones(NOW)
        assert db.get_tombstone(LID) == t  # only 10 days old, retained
        db.prune_tombstones(NOW + timedelta(days=100))
        assert db.get_tombstone(LID) is None

    def test_delete(self, db: Database) -> None:
        t = Tombstone(launcher_id=LID, removed_at=NOW, reason="r", launcher_json="{}")
        db.save_tombstone(t)
        db.delete_tombstone(LID)
        assert db.get_tombstone(LID) is None


class TestSyncRuns:
    def test_record_and_query(self, db: Database) -> None:
        db.record_sync_run(NOW - timedelta(minutes=5), NOW - timedelta(minutes=4), "offline", False)
        db.record_sync_run(NOW - timedelta(minutes=2), NOW - timedelta(minutes=1), "success", True)
        last = db.last_sync_run()
        assert last["outcome"] == "success"
        assert last["safe_to_remove"] is True
        assert db.last_successful_sync() == NOW - timedelta(minutes=1)
