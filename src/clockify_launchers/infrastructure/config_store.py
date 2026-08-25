"""Atomic JSON configuration store.

The config file never contains secrets. Writes are atomic (tmp + fsync +
os.replace). Malformed configs are preserved with a timestamped suffix and
replaced with defaults rather than crashing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from clockify_launchers import constants
from clockify_launchers.domain.models import ManagementMode
from clockify_launchers.domain.policies import PolicySettings

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


def _to_int(value: object) -> int:
    """Convert JSON scalars to int; raise TypeError like int() for other objects."""
    if isinstance(value, bool | int | float | str):
        return int(value)
    raise TypeError(f"cannot convert {type(value).__name__} to int")


@dataclass(slots=True)
class NotificationPrefs:
    timer_success: bool = True
    timer_noop: bool = True
    timer_failure: bool = True
    background_additions: bool = True
    removal_suggestions: bool = False
    autopilot_removals: bool = True


@dataclass(slots=True)
class AppConfig:
    schema_version: int = SCHEMA_VERSION
    active_account_id: str | None = None
    api_base_url: str = constants.DEFAULT_API_BASE_URL
    clockify_user_id: str | None = None
    email: str | None = None
    active_workspace_id: str | None = None
    management_mode: ManagementMode = ManagementMode.ASSISTED
    policy: PolicySettings = field(default_factory=PolicySettings)
    notifications: NotificationPrefs = field(default_factory=NotificationPrefs)
    onboarding_complete: bool = False
    start_in_background: bool = True
    last_app_version: str = constants.VERSION

    def to_json(self) -> str:
        data = asdict(self)
        data["management_mode"] = self.management_mode.value
        return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AppConfig:
        cfg = cls()
        cfg.schema_version = _to_int(data.get("schema_version", SCHEMA_VERSION))

        def _opt_str(key: str) -> str | None:
            value = data.get(key)
            return value if isinstance(value, str) and value else None

        cfg.active_account_id = _opt_str("active_account_id")
        base = _opt_str("api_base_url")
        cfg.api_base_url = base or constants.DEFAULT_API_BASE_URL
        cfg.clockify_user_id = _opt_str("clockify_user_id")
        cfg.email = _opt_str("email")
        cfg.active_workspace_id = _opt_str("active_workspace_id")
        try:
            cfg.management_mode = ManagementMode(str(data.get("management_mode", "assisted")))
        except ValueError:
            cfg.management_mode = ManagementMode.ASSISTED
        policy_data = data.get("policy")
        if isinstance(policy_data, dict):
            policy_map = cast("dict[str, object]", policy_data)
            valid = {
                f: policy_map[f] for f in PolicySettings.__dataclass_fields__ if f in policy_map
            }
            try:
                cfg.policy = PolicySettings(**{k: _to_int(v) for k, v in valid.items()}).validated()
            except (TypeError, ValueError):
                cfg.policy = PolicySettings()
        notif_data = data.get("notifications")
        if isinstance(notif_data, dict):
            notif_map = cast("dict[str, object]", notif_data)
            valid_n = {
                f: bool(notif_map[f])
                for f in NotificationPrefs.__dataclass_fields__
                if f in notif_map
            }
            cfg.notifications = NotificationPrefs(**valid_n)
        cfg.onboarding_complete = bool(data.get("onboarding_complete", False))
        cfg.start_in_background = bool(data.get("start_in_background", True))
        cfg.last_app_version = str(data.get("last_app_version", constants.VERSION))
        return cfg


def atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Write text atomically: tmp file in the same directory, fsync, replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class ConfigStore:
    def __init__(self, config_file: Path) -> None:
        self._path = config_file

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppConfig:
        if not self._path.exists():
            return AppConfig()
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("config root is not an object")
            return AppConfig.from_dict(data)
        except (OSError, ValueError) as exc:
            log.warning("Malformed config preserved and reset: %s", exc)
            backup = self._path.with_name(f"{self._path.name}.broken.{int(time.time())}")
            with contextlib.suppress(OSError):
                self._path.replace(backup)
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        atomic_write_text(self._path, config.to_json() + "\n")
