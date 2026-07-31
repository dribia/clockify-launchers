"""XDG base-directory resolution.

All filesystem locations are derived here at runtime; no other module may
hard-code home paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from clockify_launchers import constants


def _env_path(var: str, default: Path) -> Path:
    value = os.environ.get(var, "").strip()
    if value and os.path.isabs(value):
        return Path(value)
    return default


@dataclass(frozen=True, slots=True)
class XdgPaths:
    """Resolved per-user application paths."""

    config_dir: Path
    state_dir: Path
    cache_dir: Path
    runtime_dir: Path
    applications_dir: Path
    icons_dir: Path
    systemd_user_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def state_db(self) -> Path:
        return self.state_dir / "state.db"

    @property
    def sync_lock(self) -> Path:
        return self.runtime_dir / "sync.lock"

    @property
    def timer_action_lock(self) -> Path:
        return self.runtime_dir / "timer-action.lock"

    def ensure_private_dirs(self) -> None:
        for path in (
            self.config_dir,
            self.state_dir,
            self.cache_dir,
            self.runtime_dir,
            self.icons_dir,
        ):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.applications_dir.mkdir(parents=True, exist_ok=True)


def resolve_paths(environ: dict[str, str] | None = None) -> XdgPaths:
    env = environ if environ is not None else dict(os.environ)
    home = Path(env.get("HOME", os.path.expanduser("~")))

    def get(var: str, default: Path) -> Path:
        value = env.get(var, "").strip()
        if value and os.path.isabs(value):
            return Path(value)
        return default

    config_home = get("XDG_CONFIG_HOME", home / ".config")
    state_home = get("XDG_STATE_HOME", home / ".local" / "state")
    cache_home = get("XDG_CACHE_HOME", home / ".cache")
    data_home = get("XDG_DATA_HOME", home / ".local" / "share")
    runtime_root = get("XDG_RUNTIME_DIR", cache_home)

    name = constants.CONFIG_DIR_NAME
    return XdgPaths(
        config_dir=config_home / name,
        state_dir=state_home / name,
        cache_dir=cache_home / name,
        runtime_dir=runtime_root / name,
        applications_dir=data_home / "applications",
        icons_dir=data_home / constants.DATA_DIR_NAME / "icons",
        systemd_user_dir=config_home / "systemd" / "user",
    )
