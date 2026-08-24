"""Timer start/stop/switch semantics (AGENTS.md section 14)."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from clockify_launchers.domain.models import (
    ActivityEvent,
    EventSeverity,
    Launcher,
    LauncherStatus,
    TimeEntry,
    new_id,
    utc_now,
)
from clockify_launchers.domain.signatures import entry_matches_target
from clockify_launchers.infrastructure.clockify_api import (
    AmbiguousResultError,
    ClockifyClientProtocol,
    ClockifyError,
    NotFoundError,
)
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.infrastructure.file_lock import LockBusyError, acquire_lock

log = logging.getLogger(__name__)

AMBIGUOUS_START_TOLERANCE = timedelta(seconds=90)


class StartOutcome(enum.StrEnum):
    STARTED = "started"
    SWITCHED = "switched"
    NOOP = "noop"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    PARTIAL_SWITCH = "partial-switch"


@dataclass(frozen=True, slots=True)
class StartResult:
    outcome: StartOutcome
    message: str
    launcher: Launcher | None = None
    entry: TimeEntry | None = None


class TimerService:
    def __init__(
        self,
        db: Database,
        client: ClockifyClientProtocol,
        user_id: str,
        lock_path: Path,
    ) -> None:
        self._db = db
        self._client = client
        self._user_id = user_id
        self._lock_path = lock_path

    def start_launcher(self, launcher: Launcher) -> StartResult:
        try:
            with acquire_lock(self._lock_path):
                return self._start_locked(launcher)
        except LockBusyError:
            return StartResult(StartOutcome.FAILED, "Another timer action is already in progress.")

    def _start_locked(self, launcher: Launcher) -> StartResult:
        now = utc_now()
        launcher = launcher.with_(last_invoked_at=now, updated_at=now)
        self._db.save_launcher(launcher)
        target = launcher.target

        # Validate target metadata before touching the current timer.
        problem = self._validate_target(launcher)
        if problem:
            self._event("timer-target-invalid", problem, launcher.id, EventSeverity.ERROR)
            self._db.save_launcher(launcher.with_(status=LauncherStatus.TARGET_MISSING))
            return StartResult(StartOutcome.FAILED, problem, launcher)

        try:
            current = self._client.get_in_progress_entry(target.workspace_id, self._user_id)
        except ClockifyError as exc:
            self._event("timer-check-failed", str(exc), launcher.id, EventSeverity.ERROR)
            return StartResult(StartOutcome.FAILED, str(exc), launcher)

        if current is not None and entry_matches_target(current, target):
            self._event("timer-noop", f"Already tracking '{launcher.display_name}'", launcher.id)
            return StartResult(
                StartOutcome.NOOP, f"Already tracking {launcher.display_name}.", launcher, current
            )

        # One timestamp T for both the stop and the start.
        t = utc_now()
        switched = False
        if current is not None:
            try:
                self._client.stop_current_entry(target.workspace_id, self._user_id, t)
                switched = True
            except AmbiguousResultError:
                # Stop may or may not have applied; verify before proceeding.
                verified = self._probe_running(target.workspace_id)
                if verified is not None and verified.id == current.id:
                    msg = "Could not stop the current timer (network problem)."
                    self._event("timer-stop-failed", msg, launcher.id, EventSeverity.ERROR)
                    return StartResult(StartOutcome.FAILED, msg, launcher)
                switched = True
            except ClockifyError as exc:
                msg = f"Could not stop the current timer: {exc}"
                self._event("timer-stop-failed", msg, launcher.id, EventSeverity.ERROR)
                return StartResult(StartOutcome.FAILED, msg, launcher)

        try:
            entry = self._client.start_time_entry(
                target.workspace_id,
                target.project_id,
                t,
                task_id=target.task_id,
                tag_ids=target.tag_ids,
                description=target.description,
            )
        except AmbiguousResultError:
            return self._reconcile_ambiguous_start(launcher, t, switched)
        except ClockifyError as exc:
            if switched:
                msg = (
                    f"The previous timer was stopped but '{launcher.display_name}' could not be "
                    f"started: {exc}. No timer may be running."
                )
                self._event("timer-partial-switch", msg, launcher.id, EventSeverity.ERROR)
                return StartResult(StartOutcome.PARTIAL_SWITCH, msg, launcher)
            msg = f"Could not start '{launcher.display_name}': {exc}"
            self._event("timer-start-failed", msg, launcher.id, EventSeverity.ERROR)
            return StartResult(StartOutcome.FAILED, msg, launcher)

        success_now = utc_now()
        updated = launcher.with_(
            last_start_success_at=success_now,
            last_clockify_use_at=success_now,
            status=LauncherStatus.HEALTHY,
            updated_at=success_now,
        )
        self._db.save_launcher(updated)
        outcome = StartOutcome.SWITCHED if switched else StartOutcome.STARTED
        verb = "Switched to" if switched else "Started"
        self._event("timer-started", f"{verb} '{launcher.display_name}'", launcher.id)
        return StartResult(outcome, f"{verb} {launcher.display_name}.", updated, entry)

    def _reconcile_ambiguous_start(
        self, launcher: Launcher, t: datetime, switched: bool
    ) -> StartResult:
        """POST response was lost: read back before ever re-POSTing."""
        target = launcher.target
        probe = self._probe_running(target.workspace_id)
        if (
            probe is not None
            and entry_matches_target(probe, target)
            and abs((probe.start - t).total_seconds()) <= AMBIGUOUS_START_TOLERANCE.total_seconds()
        ):
            success_now = utc_now()
            updated = launcher.with_(
                last_start_success_at=success_now,
                last_clockify_use_at=success_now,
                status=LauncherStatus.HEALTHY,
                updated_at=success_now,
            )
            self._db.save_launcher(updated)
            self._event(
                "timer-started-after-retry-read",
                f"Started '{launcher.display_name}' (confirmed by read-back)",
                launcher.id,
            )
            outcome = StartOutcome.SWITCHED if switched else StartOutcome.STARTED
            return StartResult(outcome, f"Started {launcher.display_name}.", updated, probe)
        msg = (
            f"The result of starting '{launcher.display_name}' is uncertain. "
            "Check Clockify before trying again."
        )
        self._event("timer-ambiguous", msg, launcher.id, EventSeverity.ERROR)
        return StartResult(StartOutcome.AMBIGUOUS, msg, launcher)

    def _probe_running(self, workspace_id: str) -> TimeEntry | None:
        try:
            return self._client.get_in_progress_entry(workspace_id, self._user_id)
        except ClockifyError:
            return None

    def stop_current(self, workspace_id: str) -> StartResult:
        try:
            with acquire_lock(self._lock_path):
                try:
                    entry = self._client.stop_current_entry(workspace_id, self._user_id, utc_now())
                except AmbiguousResultError:
                    # The response was lost; read back whether the stop applied.
                    try:
                        still_running = self._client.get_in_progress_entry(
                            workspace_id, self._user_id
                        )
                    except ClockifyError:
                        msg = "The stop request timed out; the timer may or may not have stopped."
                        self._event("timer-stop-failed", msg, None, EventSeverity.ERROR)
                        return StartResult(StartOutcome.AMBIGUOUS, msg)
                    if still_running is None:
                        self._event("timer-stopped", "Stopped the running timer")
                        return StartResult(StartOutcome.STARTED, "Timer stopped.")
                    msg = "The stop request timed out and the timer is still running. Try again."
                    self._event("timer-stop-failed", msg, None, EventSeverity.ERROR)
                    return StartResult(StartOutcome.AMBIGUOUS, msg)
        except LockBusyError:
            return StartResult(StartOutcome.FAILED, "Another timer action is already in progress.")
        except NotFoundError:
            return StartResult(StartOutcome.NOOP, "No timer is running.")
        except ClockifyError as exc:
            self._event("timer-stop-failed", str(exc), None, EventSeverity.ERROR)
            return StartResult(StartOutcome.FAILED, f"Could not stop the timer: {exc}")
        if entry is None:
            return StartResult(StartOutcome.NOOP, "No timer is running.")
        self._event("timer-stopped", "Stopped the running timer")
        return StartResult(StartOutcome.STARTED, "Timer stopped.", entry=entry)

    def _validate_target(self, launcher: Launcher) -> str | None:
        """Refresh suspect metadata and report any missing/archived target part."""
        target = launcher.target
        project = self._db.get_project(target.project_id)
        if project is None or project.archived:
            try:
                project = self._client.get_project(target.workspace_id, target.project_id)
                self._db.cache_projects([project], utc_now())
            except NotFoundError:
                return "The project for this launcher no longer exists in Clockify."
            except ClockifyError as exc:
                return f"Could not verify the project: {exc}"
        if project.archived:
            return f"Project '{project.name}' is archived in Clockify."
        if target.task_id:
            task = self._db.get_task(target.task_id)
            if task is None or not task.active:
                try:
                    tasks = self._client.get_tasks(target.workspace_id, target.project_id)
                    self._db.cache_tasks(tasks, utc_now())
                    task = next((t for t in tasks if t.id == target.task_id), None)
                except ClockifyError as exc:
                    return f"Could not verify the task: {exc}"
            if task is None:
                return "The task for this launcher no longer exists in Clockify."
            if not task.active:
                return f"Task '{task.name}' is no longer active in Clockify."
        for tag_id in target.tag_ids:
            tag = self._db.get_tag(tag_id)
            if tag is None:
                try:
                    tags = self._client.get_tags(target.workspace_id)
                    self._db.cache_tags(tags, utc_now())
                    tag = next((t for t in tags if t.id == tag_id), None)
                except ClockifyError as exc:
                    return f"Could not verify tags: {exc}"
            if tag is None:
                return "A tag for this launcher no longer exists in Clockify."
            if tag.archived:
                return f"Tag '{tag.name}' is archived in Clockify."
        return None

    def _event(
        self,
        event_type: str,
        summary: str,
        launcher_id: str | None = None,
        severity: EventSeverity = EventSeverity.INFO,
    ) -> None:
        self._db.record_event(
            ActivityEvent(
                id=new_id(),
                event_type=event_type,
                severity=severity,
                summary=summary,
                launcher_id=launcher_id,
            )
        )
