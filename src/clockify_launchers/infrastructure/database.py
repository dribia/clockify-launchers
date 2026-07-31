"""SQLite persistence layer.

One ``Database`` class owns the connection and exposes typed repository
methods. Timestamps are stored as integer Unix seconds (UTC). No secrets,
authorization headers, or raw HTTP bodies are ever stored.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from clockify_launchers.domain.autopilot import DismissalRecord
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
    Project,
    Suggestion,
    SuggestionState,
    SuggestionType,
    Tag,
    Task,
    Tombstone,
    Workspace,
)
from clockify_launchers.infrastructure.migrations import apply_migrations

ACTIVITY_MAX_EVENTS = 2000
ACTIVITY_MAX_AGE_DAYS = 90
TOMBSTONE_MIN_AGE_DAYS = 90


def _ts(dt: datetime | None) -> int | None:
    return int(dt.timestamp()) if dt else None


def _dt(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value is not None else None


def _dt_req(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


class Database:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        with contextlib.suppress(sqlite3.OperationalError):  # WAL unsupported FS
            self._conn.execute("PRAGMA journal_mode = WAL")
        apply_migrations(self._conn)

    def close(self) -> None:
        self._conn.close()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    # -- accounts ---------------------------------------------------------

    def save_account(self, account: Account) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO accounts
                   (id, api_base_url, clockify_user_id, email, display_name,
                    active_workspace_id, created_at, last_validated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     api_base_url=excluded.api_base_url,
                     clockify_user_id=excluded.clockify_user_id,
                     email=excluded.email,
                     display_name=excluded.display_name,
                     active_workspace_id=excluded.active_workspace_id,
                     last_validated_at=excluded.last_validated_at""",
                (
                    account.id,
                    account.api_base_url,
                    account.clockify_user_id,
                    account.email,
                    account.display_name,
                    account.active_workspace_id,
                    _ts(account.created_at),
                    _ts(account.last_validated_at),
                ),
            )

    def get_account(self, account_id: str) -> Account | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None:
            return None
        return Account(
            id=row["id"],
            api_base_url=row["api_base_url"],
            clockify_user_id=row["clockify_user_id"],
            email=row["email"],
            display_name=row["display_name"],
            active_workspace_id=row["active_workspace_id"],
            created_at=_dt_req(row["created_at"]),
            last_validated_at=_dt_req(row["last_validated_at"]),
        )

    # -- metadata caches --------------------------------------------------

    def cache_workspaces(self, workspaces: list[Workspace], now: datetime) -> None:
        with self._conn:
            for ws in workspaces:
                self._conn.execute(
                    """INSERT INTO workspaces (id, name, archived, last_seen_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                         archived=excluded.archived, last_seen_at=excluded.last_seen_at""",
                    (ws.id, ws.name, int(ws.archived), _ts(now)),
                )

    def cache_projects(self, projects: list[Project], now: datetime) -> None:
        with self._conn:
            for p in projects:
                self._conn.execute(
                    """INSERT INTO projects
                       (id, workspace_id, name, color, client_name, archived, last_seen_at)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET workspace_id=excluded.workspace_id,
                         name=excluded.name, color=excluded.color,
                         client_name=excluded.client_name, archived=excluded.archived,
                         last_seen_at=excluded.last_seen_at""",
                    (
                        p.id,
                        p.workspace_id,
                        p.name,
                        p.color,
                        p.client_name,
                        int(p.archived),
                        _ts(now),
                    ),
                )

    def cache_tasks(self, tasks: list[Task], now: datetime) -> None:
        with self._conn:
            for t in tasks:
                self._conn.execute(
                    """INSERT INTO tasks (id, project_id, name, active, last_seen_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,
                         name=excluded.name, active=excluded.active,
                         last_seen_at=excluded.last_seen_at""",
                    (t.id, t.project_id, t.name, int(t.active), _ts(now)),
                )

    def cache_tags(self, tags: list[Tag], now: datetime) -> None:
        with self._conn:
            for t in tags:
                self._conn.execute(
                    """INSERT INTO tags (id, workspace_id, name, archived, last_seen_at)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET workspace_id=excluded.workspace_id,
                         name=excluded.name, archived=excluded.archived,
                         last_seen_at=excluded.last_seen_at""",
                    (t.id, t.workspace_id, t.name, int(t.archived), _ts(now)),
                )

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        return Project(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            color=row["color"],
            client_name=row["client_name"],
            archived=bool(row["archived"]),
        )

    def get_projects(self, workspace_id: str) -> list[Project]:
        rows = self._conn.execute(
            "SELECT * FROM projects WHERE workspace_id = ? ORDER BY name", (workspace_id,)
        ).fetchall()
        return [
            Project(
                id=r["id"],
                workspace_id=r["workspace_id"],
                name=r["name"],
                color=r["color"],
                client_name=r["client_name"],
                archived=bool(r["archived"]),
            )
            for r in rows
        ]

    def get_task(self, task_id: str) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return Task(
            id=row["id"], project_id=row["project_id"], name=row["name"], active=bool(row["active"])
        )

    def get_tasks(self, project_id: str) -> list[Task]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY name", (project_id,)
        ).fetchall()
        return [
            Task(id=r["id"], project_id=r["project_id"], name=r["name"], active=bool(r["active"]))
            for r in rows
        ]

    def get_tag(self, tag_id: str) -> Tag | None:
        row = self._conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
        if row is None:
            return None
        return Tag(
            id=row["id"],
            workspace_id=row["workspace_id"],
            name=row["name"],
            archived=bool(row["archived"]),
        )

    def get_tags(self, workspace_id: str) -> list[Tag]:
        rows = self._conn.execute(
            "SELECT * FROM tags WHERE workspace_id = ? ORDER BY name", (workspace_id,)
        ).fetchall()
        return [
            Tag(
                id=r["id"],
                workspace_id=r["workspace_id"],
                name=r["name"],
                archived=bool(r["archived"]),
            )
            for r in rows
        ]

    # -- launchers --------------------------------------------------------

    def save_launcher(self, launcher: Launcher) -> None:
        t = launcher.target
        with self._conn:
            self._conn.execute(
                """INSERT INTO launchers
                   (id, account_id, workspace_id, project_id, task_id, tag_ids, description,
                    display_name, comment, icon_kind, icon_path, source, management_policy,
                    status, created_at, updated_at, last_invoked_at, last_start_success_at,
                    last_clockify_use_at, auto_add_grace_until, removal_snoozed_until,
                    desktop_path, desktop_hash, icon_hash, removed_at, removal_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     account_id=excluded.account_id, workspace_id=excluded.workspace_id,
                     project_id=excluded.project_id, task_id=excluded.task_id,
                     tag_ids=excluded.tag_ids, description=excluded.description,
                     display_name=excluded.display_name, comment=excluded.comment,
                     icon_kind=excluded.icon_kind, icon_path=excluded.icon_path,
                     source=excluded.source, management_policy=excluded.management_policy,
                     status=excluded.status, updated_at=excluded.updated_at,
                     last_invoked_at=excluded.last_invoked_at,
                     last_start_success_at=excluded.last_start_success_at,
                     last_clockify_use_at=excluded.last_clockify_use_at,
                     auto_add_grace_until=excluded.auto_add_grace_until,
                     removal_snoozed_until=excluded.removal_snoozed_until,
                     desktop_path=excluded.desktop_path, desktop_hash=excluded.desktop_hash,
                     icon_hash=excluded.icon_hash, removed_at=excluded.removed_at,
                     removal_reason=excluded.removal_reason""",
                (
                    launcher.id,
                    launcher.account_id,
                    t.workspace_id,
                    t.project_id,
                    t.task_id,
                    json.dumps(list(t.tag_ids)),
                    t.description,
                    launcher.display_name,
                    launcher.comment,
                    launcher.icon_kind.value,
                    launcher.icon_path,
                    launcher.source.value,
                    launcher.management_policy.value,
                    launcher.status.value,
                    _ts(launcher.created_at),
                    _ts(launcher.updated_at),
                    _ts(launcher.last_invoked_at),
                    _ts(launcher.last_start_success_at),
                    _ts(launcher.last_clockify_use_at),
                    _ts(launcher.auto_add_grace_until),
                    _ts(launcher.removal_snoozed_until),
                    launcher.desktop_path,
                    launcher.desktop_hash,
                    launcher.icon_hash,
                    _ts(launcher.removed_at),
                    launcher.removal_reason,
                ),
            )

    def _row_to_launcher(self, row: sqlite3.Row) -> Launcher:
        return Launcher(
            id=row["id"],
            account_id=row["account_id"],
            target=LauncherTarget(
                workspace_id=row["workspace_id"],
                project_id=row["project_id"],
                task_id=row["task_id"],
                tag_ids=tuple(json.loads(row["tag_ids"])),
                description=row["description"],
            ),
            display_name=row["display_name"],
            comment=row["comment"],
            icon_kind=IconKind(row["icon_kind"]),
            icon_path=row["icon_path"],
            source=LauncherSource(row["source"]),
            management_policy=ManagementPolicy(row["management_policy"]),
            status=LauncherStatus(row["status"]),
            created_at=_dt_req(row["created_at"]),
            updated_at=_dt_req(row["updated_at"]),
            last_invoked_at=_dt(row["last_invoked_at"]),
            last_start_success_at=_dt(row["last_start_success_at"]),
            last_clockify_use_at=_dt(row["last_clockify_use_at"]),
            auto_add_grace_until=_dt(row["auto_add_grace_until"]),
            removal_snoozed_until=_dt(row["removal_snoozed_until"]),
            desktop_path=row["desktop_path"],
            desktop_hash=row["desktop_hash"],
            icon_hash=row["icon_hash"],
            removed_at=_dt(row["removed_at"]),
            removal_reason=row["removal_reason"],
        )

    def get_launcher(self, launcher_id: str) -> Launcher | None:
        row = self._conn.execute("SELECT * FROM launchers WHERE id = ?", (launcher_id,)).fetchone()
        return self._row_to_launcher(row) if row else None

    def list_launchers(self, include_removed: bool = False) -> list[Launcher]:
        query = "SELECT * FROM launchers"
        if not include_removed:
            query += " WHERE status != 'removed'"
        query += " ORDER BY display_name"
        return [self._row_to_launcher(r) for r in self._conn.execute(query).fetchall()]

    def delete_launcher_row(self, launcher_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM launchers WHERE id = ?", (launcher_id,))

    # -- suggestions ------------------------------------------------------

    def save_suggestion(self, s: Suggestion) -> None:
        t = s.target
        with self._conn:
            self._conn.execute(
                """INSERT INTO suggestions
                   (id, type, launcher_id, workspace_id, project_id, task_id, tag_ids,
                    explanation, evidence, state, created_at, dismissed_at, snoozed_until,
                    accepted_at, executed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET state=excluded.state,
                     explanation=excluded.explanation, evidence=excluded.evidence,
                     dismissed_at=excluded.dismissed_at, snoozed_until=excluded.snoozed_until,
                     accepted_at=excluded.accepted_at, executed_at=excluded.executed_at""",
                (
                    s.id,
                    s.type.value,
                    s.launcher_id,
                    t.workspace_id if t else None,
                    t.project_id if t else None,
                    t.task_id if t else None,
                    json.dumps(list(t.tag_ids)) if t else None,
                    s.explanation,
                    s.evidence,
                    s.state.value,
                    _ts(s.created_at),
                    _ts(s.dismissed_at),
                    _ts(s.snoozed_until),
                    _ts(s.accepted_at),
                    _ts(s.executed_at),
                ),
            )

    def list_suggestions(
        self, state: SuggestionState | None = SuggestionState.OPEN
    ) -> list[Suggestion]:
        if state is None:
            rows = self._conn.execute(
                "SELECT * FROM suggestions ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM suggestions WHERE state = ? ORDER BY created_at DESC", (state.value,)
            ).fetchall()
        result = []
        for r in rows:
            target = None
            if r["project_id"]:
                target = LauncherTarget(
                    workspace_id=r["workspace_id"],
                    project_id=r["project_id"],
                    task_id=r["task_id"],
                    tag_ids=tuple(json.loads(r["tag_ids"] or "[]")),
                )
            result.append(
                Suggestion(
                    id=r["id"],
                    type=SuggestionType(r["type"]),
                    launcher_id=r["launcher_id"],
                    target=target,
                    explanation=r["explanation"],
                    evidence=r["evidence"],
                    state=SuggestionState(r["state"]),
                    created_at=_dt_req(r["created_at"]),
                    dismissed_at=_dt(r["dismissed_at"]),
                    snoozed_until=_dt(r["snoozed_until"]),
                    accepted_at=_dt(r["accepted_at"]),
                    executed_at=_dt(r["executed_at"]),
                )
            )
        return result

    def get_suggestion(self, suggestion_id: str) -> Suggestion | None:
        for s in self.list_suggestions(state=None):
            if s.id == suggestion_id:
                return s
        return None

    # -- dismissals -------------------------------------------------------

    def record_dismissal(
        self, target: LauncherTarget, now: datetime, cooldown_days: int = 30
    ) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO dismissals
                   (workspace_id, project_id, task_id, tag_ids, dismissed_at, cooldown_days)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(workspace_id, project_id, task_id, tag_ids)
                   DO UPDATE SET dismissed_at=excluded.dismissed_at,
                     cooldown_days=excluded.cooldown_days""",
                (
                    target.workspace_id,
                    target.project_id,
                    target.task_id,
                    json.dumps(list(target.tag_ids)),
                    _ts(now),
                    cooldown_days,
                ),
            )

    def list_dismissals(self) -> list[DismissalRecord]:
        rows = self._conn.execute("SELECT * FROM dismissals").fetchall()
        return [
            DismissalRecord(
                signature=(
                    r["workspace_id"],
                    r["project_id"],
                    r["task_id"],
                    tuple(json.loads(r["tag_ids"])),
                ),
                dismissed_at=_dt_req(r["dismissed_at"]),
                cooldown_days=r["cooldown_days"],
            )
            for r in rows
        ]

    # -- activity ---------------------------------------------------------

    def record_event(self, event: ActivityEvent) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO activity_events
                   (id, event_type, severity, summary, details, launcher_id, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    event.id,
                    event.event_type,
                    event.severity.value,
                    event.summary,
                    event.details,
                    event.launcher_id,
                    _ts(event.created_at),
                ),
            )

    def list_events(self, limit: int = 200) -> list[ActivityEvent]:
        rows = self._conn.execute(
            "SELECT * FROM activity_events ORDER BY created_at DESC, id LIMIT ?", (limit,)
        ).fetchall()
        return [
            ActivityEvent(
                id=r["id"],
                event_type=r["event_type"],
                severity=EventSeverity(r["severity"]),
                summary=r["summary"],
                details=r["details"],
                launcher_id=r["launcher_id"],
                created_at=_dt_req(r["created_at"]),
            )
            for r in rows
        ]

    def compact_events(self, now: datetime) -> None:
        """Retain at least 90 days or 2000 events, whichever is smaller."""
        cutoff = int(now.timestamp()) - ACTIVITY_MAX_AGE_DAYS * 86400
        with self._conn:
            self._conn.execute(
                """DELETE FROM activity_events WHERE created_at < ? AND id NOT IN
                   (SELECT id FROM activity_events ORDER BY created_at DESC LIMIT ?)""",
                (cutoff, ACTIVITY_MAX_EVENTS),
            )

    # -- tombstones -------------------------------------------------------

    def save_tombstone(self, tomb: Tombstone) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO tombstones (launcher_id, removed_at, reason, launcher_json)
                   VALUES (?,?,?,?)
                   ON CONFLICT(launcher_id) DO UPDATE SET removed_at=excluded.removed_at,
                     reason=excluded.reason, launcher_json=excluded.launcher_json""",
                (tomb.launcher_id, _ts(tomb.removed_at), tomb.reason, tomb.launcher_json),
            )

    def get_tombstone(self, launcher_id: str) -> Tombstone | None:
        row = self._conn.execute(
            "SELECT * FROM tombstones WHERE launcher_id = ?", (launcher_id,)
        ).fetchone()
        if row is None:
            return None
        return Tombstone(
            launcher_id=row["launcher_id"],
            removed_at=_dt_req(row["removed_at"]),
            reason=row["reason"],
            launcher_json=row["launcher_json"],
        )

    def list_tombstones(self) -> list[Tombstone]:
        rows = self._conn.execute("SELECT * FROM tombstones ORDER BY removed_at DESC").fetchall()
        return [
            Tombstone(
                launcher_id=r["launcher_id"],
                removed_at=_dt_req(r["removed_at"]),
                reason=r["reason"],
                launcher_json=r["launcher_json"],
            )
            for r in rows
        ]

    def delete_tombstone(self, launcher_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM tombstones WHERE launcher_id = ?", (launcher_id,))

    def prune_tombstones(self, now: datetime) -> None:
        cutoff = int(now.timestamp()) - TOMBSTONE_MIN_AGE_DAYS * 86400
        with self._conn:
            self._conn.execute("DELETE FROM tombstones WHERE removed_at < ?", (cutoff,))

    # -- sync runs --------------------------------------------------------

    def record_sync_run(
        self,
        started_at: datetime,
        finished_at: datetime,
        outcome: str,
        safe_to_remove: bool,
        detail: str = "",
    ) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO sync_runs (started_at, finished_at, outcome, safe_to_remove, detail)
                   VALUES (?,?,?,?,?)""",
                (_ts(started_at), _ts(finished_at), outcome, int(safe_to_remove), detail),
            )

    def last_sync_run(self) -> dict[str, object] | None:
        row = self._conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {
            "started_at": _dt(row["started_at"]),
            "finished_at": _dt(row["finished_at"]),
            "outcome": row["outcome"],
            "safe_to_remove": bool(row["safe_to_remove"]),
            "detail": row["detail"],
        }

    def last_successful_sync(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT finished_at FROM sync_runs WHERE outcome = 'success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _dt(row["finished_at"]) if row else None
