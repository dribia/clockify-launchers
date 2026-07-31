"""Fake Clockify backend and demo context construction.

The demo backend never reads the real keyring, real database, real desktop
directory, or the network. All state lives in a temporary directory.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from clockify_launchers.demo import fixtures
from clockify_launchers.domain.models import (
    Project,
    Tag,
    Task,
    TimeEntry,
    Workspace,
)
from clockify_launchers.infrastructure.clockify_api import (
    AuthError,
    NotFoundError,
    OfflineError,
)
from clockify_launchers.infrastructure.config_store import ConfigStore
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.infrastructure.secret_store import InMemorySecretStore
from clockify_launchers.infrastructure.systemd import SystemdManager
from clockify_launchers.infrastructure.xdg_paths import XdgPaths
from clockify_launchers.services.account_service import AccountService
from clockify_launchers.services.icon_service import IconService
from clockify_launchers.services.launcher_service import LauncherService
from clockify_launchers.services.notification_service import RecordingNotifier

if TYPE_CHECKING:
    from clockify_launchers.context import AppContext


class FakeClockifyClient:
    """Duck-typed stand-in for ClockifyClient used by demo and tests."""

    def __init__(
        self,
        workspaces: list[Workspace] | None = None,
        projects: list[Project] | None = None,
        tasks: list[Task] | None = None,
        tags: list[Tag] | None = None,
        time_entries: list[TimeEntry] | None = None,
        running_entry: TimeEntry | None = None,
        offline: bool = False,
        auth_error: bool = False,
    ) -> None:
        self.workspaces = workspaces if workspaces is not None else list(fixtures.WORKSPACES)
        self.projects = projects if projects is not None else list(fixtures.PROJECTS)
        self.tasks = tasks if tasks is not None else list(fixtures.TASKS)
        self.tags = tags if tags is not None else list(fixtures.TAGS)
        self.time_entries = (
            time_entries if time_entries is not None else fixtures.demo_time_entries()
        )
        self.running_entry = running_entry
        self.offline = offline
        self.auth_error = auth_error
        self.started_entries: list[TimeEntry] = []
        self.stopped_at: list[datetime] = []

    def _check(self) -> None:
        if self.offline:
            raise OfflineError("Could not reach Clockify (demo offline state).")
        if self.auth_error:
            raise AuthError("Clockify rejected the API key.")

    def close(self) -> None: ...

    def get_current_user(self) -> dict[str, object]:
        self._check()
        return {
            "id": fixtures.DEMO_USER_ID,
            "email": fixtures.DEMO_EMAIL,
            "name": fixtures.DEMO_NAME,
            "activeWorkspace": fixtures.WS_MAIN.id,
        }

    def get_workspaces(self) -> list[Workspace]:
        self._check()
        return list(self.workspaces)

    def get_projects(self, workspace_id: str, archived: bool = False) -> list[Project]:
        self._check()
        return [
            p for p in self.projects if p.workspace_id == workspace_id and p.archived == archived
        ]

    def get_project(self, workspace_id: str, project_id: str) -> Project:
        self._check()
        for p in self.projects:
            if p.id == project_id:
                return p
        raise NotFoundError("project not found")

    def get_tags(self, workspace_id: str) -> list[Tag]:
        self._check()
        return [t for t in self.tags if t.workspace_id == workspace_id]

    def get_tasks(self, workspace_id: str, project_id: str) -> list[Task]:
        self._check()
        return [t for t in self.tasks if t.project_id == project_id]

    def get_time_entries(
        self, workspace_id: str, user_id: str, start: datetime, end: datetime
    ) -> list[TimeEntry]:
        self._check()
        return [
            e
            for e in self.time_entries
            if e.workspace_id == workspace_id and e.start >= start and e.start <= end
        ]

    def get_in_progress_entry(self, workspace_id: str, user_id: str) -> TimeEntry | None:
        self._check()
        return self.running_entry

    def start_time_entry(
        self,
        workspace_id: str,
        project_id: str,
        start: datetime,
        task_id: str | None = None,
        tag_ids: tuple[str, ...] = (),
        description: str | None = None,
    ) -> TimeEntry:
        self._check()
        entry = TimeEntry(
            id=f"te-started-{len(self.started_entries)}",
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            tag_ids=tuple(sorted(tag_ids)),
            description=description or "",
            start=start,
            end=None,
        )
        self.started_entries.append(entry)
        self.running_entry = entry
        return entry

    def stop_current_entry(
        self, workspace_id: str, user_id: str, end: datetime
    ) -> TimeEntry | None:
        self._check()
        if self.running_entry is None:
            raise NotFoundError("no running entry")
        stopped = TimeEntry(
            id=self.running_entry.id,
            workspace_id=self.running_entry.workspace_id,
            project_id=self.running_entry.project_id,
            task_id=self.running_entry.task_id,
            tag_ids=self.running_entry.tag_ids,
            description=self.running_entry.description,
            start=self.running_entry.start,
            end=end,
        )
        self.running_entry = None
        self.stopped_at.append(end)
        return stopped


def demo_paths(root: Path) -> XdgPaths:
    name = "clockify-launchers"
    return XdgPaths(
        config_dir=root / "config" / name,
        state_dir=root / "state" / name,
        cache_dir=root / "cache" / name,
        runtime_dir=root / "runtime" / name,
        applications_dir=root / "share" / "applications",
        icons_dir=root / "share" / name / "icons",
        systemd_user_dir=root / "config" / "systemd" / "user",
    )


def build_demo_context(state: str) -> AppContext:
    """Build an AppContext wired against temporary directories and fakes."""
    from clockify_launchers.context import AppContext
    from clockify_launchers.demo.states import apply_state

    root = Path(tempfile.mkdtemp(prefix="clockify-launchers-demo-"))
    atexit.register(shutil.rmtree, root, True)
    paths = demo_paths(root)
    paths.ensure_private_dirs()
    config_store = ConfigStore(paths.config_file)
    db = Database(paths.state_db)
    secrets = InMemorySecretStore()
    icon_service = IconService(paths.icons_dir)
    launcher_service = LauncherService(db, icon_service, paths.applications_dir)
    account_service = AccountService(config_store, db, secrets)
    systemd = SystemdManager(paths.systemd_user_dir, runner=_fake_run)
    notifier = RecordingNotifier()
    context = AppContext(
        paths=paths,
        config_store=config_store,
        db=db,
        secrets=secrets,
        icon_service=icon_service,
        launcher_service=launcher_service,
        account_service=account_service,
        systemd=systemd,
        notifier=notifier,
        demo=True,
    )
    apply_state(context, state)
    return context


def _fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def make_stale(dt_days: int) -> datetime:
    return fixtures.DEMO_NOW - timedelta(days=dt_days)
