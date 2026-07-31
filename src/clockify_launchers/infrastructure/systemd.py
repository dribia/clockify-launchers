"""systemd user timer management.

Uses ``systemctl --user`` without a shell. Interval changes are written to a
drop-in override atomically. All calls are injectable/testable via ``runner``.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from clockify_launchers import constants
from clockify_launchers.infrastructure.config_store import atomic_write_text

log = logging.getLogger(__name__)

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _default_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        args, capture_output=True, text=True, timeout=30, check=False
    )


class SystemdManager:
    def __init__(self, systemd_user_dir: Path, runner: Runner = _default_runner) -> None:
        self._user_dir = systemd_user_dir
        self._run = runner

    def _systemctl(self, *args: str) -> bool:
        result = self._run(["systemctl", "--user", *args])
        if result.returncode != 0:
            log.warning("systemctl --user %s failed: %s", " ".join(args), result.stderr.strip())
            return False
        return True

    def write_interval_dropin(self, minutes: int) -> Path:
        dropin_dir = self._user_dir / f"{constants.SYSTEMD_TIMER}.d"
        path = dropin_dir / "override.conf"
        content = f"[Timer]\nOnUnitActiveSec=\nOnUnitActiveSec={minutes}min\n"
        atomic_write_text(path, content, mode=0o644)
        return path

    def apply_interval(self, minutes: int) -> bool:
        self.write_interval_dropin(minutes)
        ok = self._systemctl("daemon-reload")
        return self._systemctl("restart", constants.SYSTEMD_TIMER) and ok

    def enable_timer(self) -> bool:
        return self._systemctl("enable", "--now", constants.SYSTEMD_TIMER)

    def disable_timer(self) -> bool:
        return self._systemctl("disable", "--now", constants.SYSTEMD_TIMER)

    def timer_active(self) -> bool:
        result = self._run(["systemctl", "--user", "is-active", constants.SYSTEMD_TIMER])
        return result.returncode == 0 and result.stdout.strip() == "active"
