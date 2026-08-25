"""Contract tests for TimerService start/stop/switch semantics (AGENTS.md section 14)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from clockify_launchers.demo.backend import FakeClockifyClient
from clockify_launchers.domain.models import (
    Account,
    Launcher,
    LauncherTarget,
    Project,
    Tag,
    Task,
    TimeEntry,
    utc_now,
)
from clockify_launchers.infrastructure.clockify_api import (
    AmbiguousResultError,
    OfflineError,
    RequiredCustomFieldError,
    ValidationFailedError,
)
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.services.timer_service import StartOutcome, TimerService

WS = "ws1"
USER = "user-1"
ACCOUNT_ID = "acc-1"


class ScriptedClient(FakeClockifyClient):
    """FakeClockifyClient with injectable failures and call counting."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.start_exc: Exception | None = None
        self.start_calls = 0
        self.start_kwargs: dict | None = None
        self.readback_entry: TimeEntry | None = None
        self._readback_armed = False

    def start_time_entry(self, *args, **kwargs) -> TimeEntry:
        self.start_calls += 1
        self.start_kwargs = kwargs
        if self.start_exc is not None:
            self._readback_armed = True
            raise self.start_exc
        return super().start_time_entry(*args, **kwargs)

    def get_in_progress_entry(self, workspace_id: str, user_id: str) -> TimeEntry | None:
        if self._readback_armed:
            return self.readback_entry
        return super().get_in_progress_entry(workspace_id, user_id)


def _running(project_id: str, task_id=None, tag_ids=(), description="") -> TimeEntry:
    return TimeEntry(
        id="te-running",
        workspace_id=WS,
        project_id=project_id,
        task_id=task_id,
        tag_ids=tuple(sorted(tag_ids)),
        description=description,
        start=utc_now() - timedelta(minutes=30),
        end=None,
    )


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    now = utc_now()
    database.save_account(
        Account(
            id=ACCOUNT_ID,
            api_base_url="https://api.clockify.me/api",
            clockify_user_id=USER,
            email="a@b.c",
            display_name="A",
            active_workspace_id=WS,
            created_at=now,
            last_validated_at=now,
        )
    )
    database.cache_projects([Project(id="p1", workspace_id=WS, name="Tank")], now)
    database.cache_tasks([Task(id="k1", project_id="p1", name="Build", active=True)], now)
    database.cache_tags([Tag(id="t1", workspace_id=WS, name="Project")], now)
    return database


def make_launcher(db: Database, task_id=None, tag_ids=(), description=None) -> Launcher:
    launcher = Launcher(
        id="6d17b662-5ba4-4c39-903b-cc319a633fe7",
        account_id=ACCOUNT_ID,
        target=LauncherTarget(
            workspace_id=WS,
            project_id="p1",
            task_id=task_id,
            tag_ids=tuple(tag_ids),
            description=description,
        ),
        display_name="Kaito",
    )
    db.save_launcher(launcher)
    return launcher


def make_service(db: Database, client, tmp_path) -> TimerService:
    return TimerService(db, client, USER, tmp_path / "timer.lock")


def test_start_with_no_running_timer(db, tmp_path):
    client = ScriptedClient(running_entry=None)
    launcher = make_launcher(db, task_id="k1", tag_ids=("t1",))
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.STARTED
    assert client.start_calls == 1
    started = client.started_entries[0]
    assert started.project_id == "p1"
    assert started.task_id == "k1"
    assert started.tag_ids == ("t1",)
    saved = db.get_launcher(launcher.id)
    assert saved.last_start_success_at is not None
    assert saved.last_invoked_at is not None


def test_start_passes_project_billable_default(db, tmp_path):
    now = utc_now()
    db.cache_projects(
        [Project(id="p1", workspace_id=WS, name="Tank", billable_by_default=True)], now
    )
    client = ScriptedClient(running_entry=None)
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.STARTED
    assert client.start_kwargs["billable"] is True


def test_start_passes_billable_false_for_non_billable_project(db, tmp_path):
    client = ScriptedClient(running_entry=None)
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.STARTED
    assert client.start_kwargs["billable"] is False


def test_switch_from_another_running_timer_same_timestamp(db, tmp_path):
    now = utc_now()
    db.cache_projects([Project(id="p2", workspace_id=WS, name="Other")], now)
    client = ScriptedClient(running_entry=_running("p2"))
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.SWITCHED
    assert len(client.stopped_at) == 1
    assert client.started_entries[0].start == client.stopped_at[0]


def test_same_target_running_is_noop(db, tmp_path):
    # launcher has no fixed description: any running description matches
    client = ScriptedClient(
        running_entry=_running("p1", task_id="k1", tag_ids=("t1",), description="whatever")
    )
    launcher = make_launcher(db, task_id="k1", tag_ids=("t1",))
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.NOOP
    assert client.start_calls == 0
    assert client.stopped_at == []
    assert "Already tracking" in result.message


def test_stop_succeeds_start_fails_is_partial_switch(db, tmp_path):
    client = ScriptedClient(running_entry=_running("p2"))
    client.start_exc = ValidationFailedError("Clockify rejected the request")
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.PARTIAL_SWITCH
    assert "No timer may be running" in result.message
    assert len(client.stopped_at) == 1
    saved = db.get_launcher(launcher.id)
    assert saved.last_start_success_at is None


def test_ambiguous_start_confirmed_by_readback(db, tmp_path):
    client = ScriptedClient(running_entry=None)
    client.start_exc = AmbiguousResultError("timed out")
    client.readback_entry = TimeEntry(
        id="te-confirmed",
        workspace_id=WS,
        project_id="p1",
        task_id=None,
        tag_ids=(),
        description="",
        start=utc_now(),  # within the 90s tolerance of T
        end=None,
    )
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.STARTED
    assert client.start_calls == 1  # never re-POSTed
    saved = db.get_launcher(launcher.id)
    assert saved.last_start_success_at is not None


def test_ambiguous_start_unconfirmed_stays_ambiguous_no_second_post(db, tmp_path):
    client = ScriptedClient(running_entry=None)
    client.start_exc = AmbiguousResultError("timed out")
    client.readback_entry = None
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.AMBIGUOUS
    assert client.start_calls == 1
    assert "uncertain" in result.message
    saved = db.get_launcher(launcher.id)
    assert saved.last_start_success_at is None


def test_target_validation_failure_before_any_stop(db, tmp_path):
    now = utc_now()
    # project is archived both in the cache and per the client refresh
    archived = Project(id="p1", workspace_id=WS, name="Tank", archived=True)
    db.cache_projects([archived], now)
    client = ScriptedClient(projects=[archived], running_entry=_running("p2"))
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.FAILED
    assert "archived" in result.message
    assert client.stopped_at == []  # stop never attempted
    assert client.start_calls == 0


def test_required_custom_field_error_is_failed_and_not_marked_started(db, tmp_path):
    client = ScriptedClient(running_entry=None)
    client.start_exc = RequiredCustomFieldError(
        "Clockify requires a custom field this launcher does not provide."
    )
    launcher = make_launcher(db)
    result = make_service(db, client, tmp_path).start_launcher(launcher)
    assert result.outcome is StartOutcome.FAILED
    assert "custom field" in result.message
    saved = db.get_launcher(launcher.id)
    assert saved.last_start_success_at is None


def test_stop_current_noop_when_nothing_running(db, tmp_path):
    client = ScriptedClient(running_entry=None)
    result = make_service(db, client, tmp_path).stop_current(WS)
    assert result.outcome is StartOutcome.NOOP


class StopScriptedClient(ScriptedClient):
    """ScriptedClient that can also fail the stop request."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.stop_exc: Exception | None = None
        self.probe_exc: Exception | None = None
        self.probe_entry: TimeEntry | None = None
        self._stop_failed = False

    def stop_current_entry(self, *args, **kwargs) -> TimeEntry | None:
        if self.stop_exc is not None:
            self._stop_failed = True
            raise self.stop_exc
        return super().stop_current_entry(*args, **kwargs)

    def get_in_progress_entry(self, workspace_id: str, user_id: str) -> TimeEntry | None:
        if self._stop_failed:
            if self.probe_exc is not None:
                raise self.probe_exc
            return self.probe_entry
        return super().get_in_progress_entry(workspace_id, user_id)


def test_stop_ambiguous_readback_confirms_stop(db, tmp_path):
    """A lost stop response that actually applied is reported as success."""
    client = StopScriptedClient(running_entry=_running("p1"))
    client.stop_exc = AmbiguousResultError("timed out")
    client.probe_entry = None  # nothing running any more: stop applied
    result = make_service(db, client, tmp_path).stop_current(WS)
    assert result.outcome is StartOutcome.STARTED
    assert result.message == "Timer stopped."


def test_stop_ambiguous_readback_still_running(db, tmp_path):
    """A lost stop response with the timer still running stays ambiguous."""
    running = _running("p1")
    client = StopScriptedClient(running_entry=running)
    client.stop_exc = AmbiguousResultError("timed out")
    client.probe_entry = running
    result = make_service(db, client, tmp_path).stop_current(WS)
    assert result.outcome is StartOutcome.AMBIGUOUS
    assert "still running" in result.message


def test_stop_ambiguous_and_probe_fails_stays_ambiguous(db, tmp_path):
    """If the verification read also fails, never claim success."""
    client = StopScriptedClient(running_entry=_running("p1"))
    client.stop_exc = AmbiguousResultError("timed out")
    client.probe_exc = OfflineError("offline")
    result = make_service(db, client, tmp_path).stop_current(WS)
    assert result.outcome is StartOutcome.AMBIGUOUS
    assert "may or may not" in result.message
