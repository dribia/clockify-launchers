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
        # systemd parses every On*Sec directive into ONE shared spec list, so
        # the empty ``OnUnitActiveSec=`` reset below clears not just the
        # shipped interval but also the shipped OnStartupSec/OnActiveSec
        # re-arm anchors, leaving the timer eventless (ADR 0019, observed on
        # systemd 255). The drop-in therefore re-declares the anchors along
        # with the custom interval.
        content = (
            "[Timer]\n"
            "OnUnitActiveSec=\n"
            f"OnStartupSec={constants.TIMER_ON_STARTUP_MINUTES}min\n"
            f"OnActiveSec={minutes}min\n"
            f"OnUnitActiveSec={minutes}min\n"
        )
        atomic_write_text(path, content, mode=0o644)
        return path

    def apply_interval(self, minutes: int) -> bool:
        self.write_interval_dropin(minutes)
        ok = self._systemctl("daemon-reload")
        return self._systemctl("restart", constants.SYSTEMD_TIMER) and ok

    def reconcile(self, enabled: bool, minutes: int) -> bool:
        """Converge the timer with the mode and interval, re-arming it.

        Called at application startup (and after mode changes): rewrites the
        interval drop-in (re-declaring the re-arm anchors, healing installs
        whose old drop-in left the timer eventless - ADR 0019), reloads the
        shipped unit definitions, then enables + restarts the timer so the
        ``OnActiveSec`` anchor arms a sync even when the
        ``OnUnitActiveSec`` chain is broken (service never activated in
        this session - see ADR 0018). Disabling is idempotent.
        """
        if not enabled:
            return self._systemctl("disable", "--now", constants.SYSTEMD_TIMER)
        self.write_interval_dropin(minutes)
        ok = self._systemctl("daemon-reload")
        ok = self._systemctl("enable", "--now", constants.SYSTEMD_TIMER) and ok
        return self._systemctl("restart", constants.SYSTEMD_TIMER) and ok

    def enable_timer(self) -> bool:
        return self._systemctl("enable", "--now", constants.SYSTEMD_TIMER)

    def disable_timer(self) -> bool:
        return self._systemctl("disable", "--now", constants.SYSTEMD_TIMER)

    def timer_active(self) -> bool:
        result = self._run(["systemctl", "--user", "is-active", constants.SYSTEMD_TIMER])
        return result.returncode == 0 and result.stdout.strip() == "active"

    def timer_armed(self) -> bool:
        """Whether the timer has at least one armed elapse (not merely active).

        An ``active (elapsed)`` timer whose next elapse is ``infinity`` never
        fires - the exact state the pre-ADR-0019 interval drop-in left behind
        after every reboot. ``is-active`` alone cannot detect it.
        """
        result = self._run(
            [
                "systemctl",
                "--user",
                "show",
                constants.SYSTEMD_TIMER,
                "-p",
                "NextElapseUSecRealtime",
                "-p",
                "NextElapseUSecMonotonic",
            ]
        )
        if result.returncode != 0:
            return False
        for line in result.stdout.splitlines():
            if "=" not in line:
                continue
            value = line.split("=", 1)[1].strip()
            if value and value not in ("0", "infinity"):
                return True
        return False
