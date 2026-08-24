"""Launcher lifecycle: create, edit, pin, delete, restore, disk reconciliation."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from clockify_launchers.domain.models import (
    ActivityEvent,
    EventSeverity,
    IconKind,
    Launcher,
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementPolicy,
    Tombstone,
    new_id,
    utc_now,
)
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.infrastructure.desktop_entries import (
    DesktopEntrySpec,
    check_ownership,
    content_hash,
    desktop_file_name,
    safe_delete_owned,
    scan_owned_files,
    serialize_desktop_entry,
    write_desktop_file_atomic,
)
from clockify_launchers.services.icon_service import IconService

log = logging.getLogger(__name__)


def launcher_to_json(launcher: Launcher) -> str:
    data = asdict(launcher)

    def convert(obj: object) -> object:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [convert(v) for v in obj]
        return obj

    return json.dumps(convert(data), sort_keys=True)


def launcher_from_json(raw: str) -> Launcher:
    data = json.loads(raw)
    target_data = data.pop("target")

    def parse_dt(value: object) -> datetime | None:
        return datetime.fromisoformat(value) if isinstance(value, str) else None

    target = LauncherTarget(
        workspace_id=target_data["workspace_id"],
        project_id=target_data["project_id"],
        task_id=target_data.get("task_id"),
        tag_ids=tuple(target_data.get("tag_ids") or ()),
        description=target_data.get("description"),
    )
    dt_fields = {
        "created_at",
        "updated_at",
        "last_invoked_at",
        "last_start_success_at",
        "last_clockify_use_at",
        "auto_add_grace_until",
        "removal_snoozed_until",
        "removed_at",
    }
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key in dt_fields:
            kwargs[key] = parse_dt(value)
        elif key == "icon_kind":
            kwargs[key] = IconKind(value)
        elif key == "source":
            kwargs[key] = LauncherSource(value)
        elif key == "management_policy":
            kwargs[key] = ManagementPolicy(value)
        elif key == "status":
            kwargs[key] = LauncherStatus(value)
        else:
            kwargs[key] = value
    return Launcher(target=target, **kwargs)


class LauncherService:
    def __init__(
        self,
        db: Database,
        icon_service: IconService,
        applications_dir: Path,
        exec_path: str | None = None,
    ) -> None:
        self._db = db
        self._icons = icon_service
        self._apps_dir = applications_dir
        self._exec_path = exec_path

    # -- helpers -----------------------------------------------------------

    def _desktop_path(self, launcher_id: str) -> Path:
        return self._apps_dir / desktop_file_name(launcher_id)

    def _keywords_for(self, launcher: Launcher) -> tuple[str, ...]:
        words = [launcher.display_name]
        project = self._db.get_project(launcher.target.project_id)
        if project:
            words.append(project.name)
            if project.client_name:
                words.append(project.client_name)
        if launcher.target.task_id:
            task = self._db.get_task(launcher.target.task_id)
            if task:
                words.append(task.name)
        for tag_id in launcher.target.tag_ids:
            tag = self._db.get_tag(tag_id)
            if tag:
                words.append(tag.name)
        return tuple(dict.fromkeys(words))

    def _comment_for(self, launcher: Launcher) -> str:
        if launcher.comment:
            return launcher.comment
        parts = []
        project = self._db.get_project(launcher.target.project_id)
        parts.append(project.name if project else launcher.target.project_id)
        if launcher.target.task_id:
            task = self._db.get_task(launcher.target.task_id)
            if task:
                parts.append(task.name)
        for tag_id in launcher.target.tag_ids:
            tag = self._db.get_tag(tag_id)
            if tag:
                parts.append(tag.name)
        return "Start Clockify timer: " + " - ".join(parts)

    def write_desktop_file(self, launcher: Launcher) -> Launcher:
        spec = DesktopEntrySpec(
            launcher_id=launcher.id,
            name=launcher.display_name,
            comment=self._comment_for(launcher),
            icon_path=launcher.icon_path,
            keywords=self._keywords_for(launcher),
            **({"exec_path": self._exec_path} if self._exec_path else {}),
        )
        content = serialize_desktop_entry(spec)
        path = self._desktop_path(launcher.id)
        digest = write_desktop_file_atomic(path, content)
        updated = launcher.with_(desktop_path=str(path), desktop_hash=digest, updated_at=utc_now())
        self._db.save_launcher(updated)
        return updated

    # -- CRUD ---------------------------------------------------------------

    def create(
        self,
        account_id: str,
        target: LauncherTarget,
        display_name: str,
        comment: str = "",
        source: LauncherSource = LauncherSource.MANUAL,
        policy: ManagementPolicy | None = None,
        icon_source: Path | None = None,
        grace_until: datetime | None = None,
        now: datetime | None = None,
    ) -> Launcher:
        now = now or utc_now()
        if policy is None:
            policy = (
                ManagementPolicy.MANAGED
                if source is LauncherSource.AUTOMATIC
                else ManagementPolicy.PINNED
            )
        launcher = Launcher(
            id=new_id(),
            account_id=account_id,
            target=target,
            display_name=display_name.strip() or "Clockify launcher",
            comment=comment.strip(),
            source=source,
            management_policy=policy,
            created_at=now,
            updated_at=now,
            auto_add_grace_until=grace_until,
        )
        project = self._db.get_project(target.project_id)
        if icon_source is not None:
            icon_path = self._icons.import_selected(launcher.id, icon_source)
            launcher = launcher.with_(icon_kind=IconKind.SELECTED, icon_path=str(icon_path))
        else:
            icon_path = self._icons.write_generated(
                launcher.id,
                project.name if project else launcher.display_name,
                project.color if project else None,
            )
            launcher = launcher.with_(icon_kind=IconKind.GENERATED, icon_path=str(icon_path))
        launcher = launcher.with_(icon_hash=self._icons.hash_of(icon_path))
        self._db.save_launcher(launcher)
        launcher = self.write_desktop_file(launcher)
        self._event("launcher-created", f"Created launcher '{launcher.display_name}'", launcher.id)
        return launcher

    def duplicate_of(self, target: LauncherTarget) -> Launcher | None:
        """An exact duplicate: same signature AND same fixed description.

        Several launchers may share a target (signature) as long as their
        fixed descriptions differ; only a full match counts as a duplicate.
        """
        for launcher in self._db.list_launchers():
            if (
                launcher.target.signature == target.signature
                and launcher.target.description == target.description
            ):
                return launcher
        return None

    def same_target_of(self, target: LauncherTarget) -> Launcher | None:
        """A launcher sharing the signature (ignoring description), if any."""
        for launcher in self._db.list_launchers():
            if launcher.target.signature == target.signature:
                return launcher
        return None

    def update(
        self,
        launcher: Launcher,
        display_name: str | None = None,
        comment: str | None = None,
        target: LauncherTarget | None = None,
        icon_source: Path | None = None,
        regenerate_icon: bool = False,
    ) -> Launcher:
        if display_name is not None:
            launcher = launcher.with_(display_name=display_name.strip() or launcher.display_name)
        if comment is not None:
            launcher = launcher.with_(comment=comment.strip())
        if target is not None:
            launcher = launcher.with_(target=target)
        if icon_source is not None:
            path = self._icons.import_selected(launcher.id, icon_source)
            launcher = launcher.with_(
                icon_kind=IconKind.SELECTED,
                icon_path=str(path),
                icon_hash=self._icons.hash_of(path),
            )
        elif regenerate_icon:
            project = self._db.get_project(launcher.target.project_id)
            path = self._icons.write_generated(
                launcher.id,
                project.name if project else launcher.display_name,
                project.color if project else None,
            )
            launcher = launcher.with_(
                icon_kind=IconKind.GENERATED,
                icon_path=str(path),
                icon_hash=self._icons.hash_of(path),
            )
        launcher = launcher.with_(updated_at=utc_now())
        self._db.save_launcher(launcher)
        launcher = self.write_desktop_file(launcher)
        self._event("launcher-updated", f"Updated launcher '{launcher.display_name}'", launcher.id)
        return launcher

    def set_pinned(self, launcher: Launcher, pinned: bool) -> Launcher:
        policy = ManagementPolicy.PINNED if pinned else ManagementPolicy.MANAGED
        updated = launcher.with_(management_policy=policy, updated_at=utc_now())
        self._db.save_launcher(updated)
        verb = "Pinned" if pinned else "Unpinned"
        self._event("launcher-pin", f"{verb} launcher '{launcher.display_name}'", launcher.id)
        return updated

    def snooze(self, launcher: Launcher, until: datetime) -> Launcher:
        updated = launcher.with_(removal_snoozed_until=until, updated_at=utc_now())
        self._db.save_launcher(updated)
        return updated

    def delete(self, launcher: Launcher, reason: str = "deleted by user") -> Launcher:
        """Delete the desktop file (with safety checks) and keep a tombstone."""
        now = utc_now()
        tomb = Tombstone(
            launcher_id=launcher.id,
            removed_at=now,
            reason=reason,
            launcher_json=launcher_to_json(launcher),
        )
        self._db.save_tombstone(tomb)
        if launcher.desktop_path:
            path = Path(launcher.desktop_path)
            if path.exists() and launcher.desktop_hash:
                try:
                    safe_delete_owned(path, launcher.desktop_hash, self._apps_dir)
                except Exception as exc:
                    log.warning("Safe delete refused: %s", exc)
                    self._event(
                        "launcher-delete-blocked",
                        f"Could not delete file for '{launcher.display_name}': {exc}",
                        launcher.id,
                        EventSeverity.WARNING,
                    )
                    # State still marks it removed; file mismatch recorded for next run.
        updated = launcher.with_(
            status=LauncherStatus.REMOVED,
            removed_at=now,
            removal_reason=reason,
            updated_at=now,
        )
        self._db.save_launcher(updated)
        self._event(
            "launcher-removed", f"Removed launcher '{launcher.display_name}': {reason}", launcher.id
        )
        return updated

    def restore(self, launcher_id: str, as_pinned: bool = True) -> Launcher | None:
        tomb = self._db.get_tombstone(launcher_id)
        if tomb is None:
            return None
        launcher = launcher_from_json(tomb.launcher_json)
        policy = ManagementPolicy.PINNED if as_pinned else ManagementPolicy.MANAGED
        launcher = launcher.with_(
            status=LauncherStatus.HEALTHY,
            management_policy=policy,
            removed_at=None,
            removal_reason=None,
            updated_at=utc_now(),
        )
        icon_path = Path(launcher.icon_path) if launcher.icon_path else None
        if icon_path is None or not icon_path.exists():
            project = self._db.get_project(launcher.target.project_id)
            new_icon = self._icons.write_generated(
                launcher.id,
                project.name if project else launcher.display_name,
                project.color if project else None,
            )
            launcher = launcher.with_(
                icon_kind=IconKind.GENERATED,
                icon_path=str(new_icon),
                icon_hash=self._icons.hash_of(new_icon),
            )
        self._db.save_launcher(launcher)
        launcher = self.write_desktop_file(launcher)
        self._db.delete_tombstone(launcher_id)
        self._event(
            "launcher-restored", f"Restored launcher '{launcher.display_name}'", launcher.id
        )
        return launcher

    # -- disk reconciliation -------------------------------------------------

    def reconcile_disk(self) -> list[Launcher]:
        """Compare owned files on disk with state; mark drift, recreate missing.

        Never deletes anything; returns the launchers whose status changed.
        """
        changed: list[Launcher] = []
        on_disk = scan_owned_files(self._apps_dir)
        for launcher in self._db.list_launchers():
            path = on_disk.pop(launcher.id, None)
            if launcher.status is LauncherStatus.REMOVED:
                continue
            if path is None:
                expected = Path(launcher.desktop_path) if launcher.desktop_path else None
                if expected is None or not expected.exists():
                    recreated = self.write_desktop_file(launcher)
                    self._event(
                        "launcher-recreated",
                        f"Recreated missing desktop file for '{launcher.display_name}'",
                        launcher.id,
                        EventSeverity.WARNING,
                    )
                    changed.append(recreated)
                continue
            current = content_hash(path.read_bytes())
            if launcher.desktop_hash and current != launcher.desktop_hash:
                if launcher.status is not LauncherStatus.EXTERNALLY_MODIFIED:
                    updated = launcher.with_(
                        status=LauncherStatus.EXTERNALLY_MODIFIED, updated_at=utc_now()
                    )
                    self._db.save_launcher(updated)
                    self._event(
                        "launcher-modified-externally",
                        f"'{launcher.display_name}' was modified outside "
                        f"{(__package__ or 'clockify_launchers').split('.')[0]}",
                        launcher.id,
                        EventSeverity.WARNING,
                    )
                    changed.append(updated)
            elif launcher.status is LauncherStatus.EXTERNALLY_MODIFIED:
                updated = launcher.with_(status=LauncherStatus.HEALTHY, updated_at=utc_now())
                self._db.save_launcher(updated)
                changed.append(updated)
        # Orphans on disk that claim our ownership but have no state: adopt as error state.
        for orphan_id, path in on_disk.items():
            check = check_ownership(path)
            if check.owned:
                self._event(
                    "orphan-desktop-file",
                    f"Found owned desktop file without state: {path.name}",
                    orphan_id,
                    EventSeverity.WARNING,
                )
        return changed

    def restore_managed_version(self, launcher: Launcher) -> Launcher:
        """Overwrite an externally modified file with the managed version."""
        updated = launcher.with_(status=LauncherStatus.HEALTHY)
        return self.write_desktop_file(updated)

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
