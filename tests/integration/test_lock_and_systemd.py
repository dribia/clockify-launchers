"""File lock and SystemdManager integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clockify_launchers import constants
from clockify_launchers.infrastructure.file_lock import LockBusyError, acquire_lock
from clockify_launchers.infrastructure.systemd import SystemdManager


def test_lock_blocks_second_acquisition(tmp_path):
    lock_path = tmp_path / "runtime" / "sync.lock"
    with acquire_lock(lock_path):
        with pytest.raises(LockBusyError):
            with acquire_lock(lock_path):
                pass  # pragma: no cover
    # Released after exit: can acquire again.
    with acquire_lock(lock_path):
        pass


def test_lock_writes_pid_and_private_dir(tmp_path):
    lock_path = tmp_path / "runtime" / "sync.lock"
    with acquire_lock(lock_path):
        pass
    assert lock_path.exists()
    mode = lock_path.parent.stat().st_mode & 0o777
    assert mode == 0o700


class RecordingRunner:
    """Test runner returning canned stdout for every systemctl invocation."""

    def __init__(self, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.stdout = stdout

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=self.stdout, stderr="")


def test_write_interval_dropin(tmp_path):
    runner = RecordingRunner()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=runner)
    path = mgr.write_interval_dropin(45)
    assert path == tmp_path / "systemd" / "user" / f"{constants.SYSTEMD_TIMER}.d" / "override.conf"
    # ADR 0019: an empty On*Sec= assignment resets systemd's SHARED timer
    # spec list, so the drop-in must re-declare the re-arm anchors, not just
    # the interval - otherwise the timer is left eventless after every
    # daemon-reload+restart.
    assert path.read_text() == (
        "[Timer]\n"
        "OnUnitActiveSec=\n"
        f"OnStartupSec={constants.TIMER_ON_STARTUP_MINUTES}min\n"
        "OnActiveSec=45min\n"
        "OnUnitActiveSec=45min\n"
    )
    assert runner.calls == []  # writing the drop-in alone runs no systemctl
    # No leftover temp files from the atomic write.
    assert [p.name for p in path.parent.iterdir()] == ["override.conf"]


def test_apply_interval_and_enable_disable_argv(tmp_path):
    runner = RecordingRunner()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=runner)
    assert mgr.apply_interval(45)
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "restart", constants.SYSTEMD_TIMER],
    ]
    runner.calls.clear()
    assert mgr.enable_timer()
    assert runner.calls == [["systemctl", "--user", "enable", "--now", constants.SYSTEMD_TIMER]]
    runner.calls.clear()
    assert mgr.disable_timer()
    assert runner.calls == [["systemctl", "--user", "disable", "--now", constants.SYSTEMD_TIMER]]


def test_reconcile_enabled_argv(tmp_path):
    runner = RecordingRunner()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=runner)
    assert mgr.reconcile(True, 45)
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", constants.SYSTEMD_TIMER],
        ["systemctl", "--user", "restart", constants.SYSTEMD_TIMER],
    ]
    dropin = tmp_path / "systemd" / "user" / f"{constants.SYSTEMD_TIMER}.d" / "override.conf"
    assert dropin.read_text() == (
        "[Timer]\n"
        "OnUnitActiveSec=\n"
        f"OnStartupSec={constants.TIMER_ON_STARTUP_MINUTES}min\n"
        "OnActiveSec=45min\n"
        "OnUnitActiveSec=45min\n"
    )


def test_reconcile_disabled_argv(tmp_path):
    runner = RecordingRunner()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=runner)
    assert mgr.reconcile(False, 45)
    # Disabling must not touch the drop-in or run a reload.
    assert runner.calls == [["systemctl", "--user", "disable", "--now", constants.SYSTEMD_TIMER]]


def test_timer_armed_states():
    armed = RecordingRunner(
        stdout="NextElapseUSecRealtime=\nNextElapseUSecMonotonic=17874952570000\n"
    )
    assert SystemdManager(Path("/unused"), runner=armed).timer_armed() is True
    unarmed = RecordingRunner(stdout="NextElapseUSecRealtime=\nNextElapseUSecMonotonic=infinity\n")
    assert SystemdManager(Path("/unused"), runner=unarmed).timer_armed() is False
    # "active (elapsed)" with no properties at all: the pre-ADR-0019 state.
    empty = RecordingRunner(stdout="")
    assert SystemdManager(Path("/unused"), runner=empty).timer_armed() is False


def test_timer_armed_false_when_show_fails():
    def failing_runner(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="boom")

    assert SystemdManager(Path("/unused"), runner=failing_runner).timer_armed() is False


def test_shipped_units_have_arming_anchors():
    """ADR 0018: the timer must re-arm without a prior service activation.

    - ``OnActiveSec`` anchors a sync to every (re)start of the timer, so a
      restart can never leave it eventless.
    - The service must not order after ``graphical-session.target``: a
      stalled ordering consumes the boot trigger without activating the
      service, stillborn-ing the ``OnUnitActiveSec`` chain.
    """
    repo_root = Path(__file__).resolve().parents[2]
    timer = (repo_root / "data" / "systemd" / "clockify-launchers-sync.timer").read_text()
    service = (repo_root / "data" / "systemd" / "clockify-launchers-sync.service").read_text()
    assert "OnStartupSec=" in timer
    assert "OnActiveSec=" in timer
    assert "OnUnitActiveSec=" in timer
    assert "After=graphical-session.target" not in service
    assert "ExecStart=/usr/bin/clockify-launchers sync --background" in service


def test_dropin_anchor_matches_shipped_unit(tmp_path):
    """ADR 0019: the anchors re-declared in the drop-in must match the shipped
    unit (and constants), or the drop-in would silently override them."""

    def timer_value(text: str, key: str) -> str | None:
        value = None
        for line in text.splitlines():
            if line.startswith(key + "="):
                # A reset line ("Key=") may precede the effective assignment;
                # the last match wins.
                value = line.split("=", 1)[1].strip()
        return value

    repo_root = Path(__file__).resolve().parents[2]
    shipped = (repo_root / "data" / "systemd" / "clockify-launchers-sync.timer").read_text()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=RecordingRunner())
    dropin = mgr.write_interval_dropin(30).read_text()

    assert timer_value(shipped, "OnStartupSec") == timer_value(dropin, "OnStartupSec")
    assert timer_value(dropin, "OnStartupSec") == f"{constants.TIMER_ON_STARTUP_MINUTES}min"
    # OnActiveSec follows the user's interval; the shipped default must be
    # the default policy interval.
    from clockify_launchers.domain.policies import DEFAULT_SYNC_INTERVAL_MINUTES

    assert timer_value(shipped, "OnActiveSec") == f"{DEFAULT_SYNC_INTERVAL_MINUTES}min"
    assert timer_value(dropin, "OnActiveSec") == f"{DEFAULT_SYNC_INTERVAL_MINUTES}min"
    assert timer_value(dropin, "OnUnitActiveSec") == f"{DEFAULT_SYNC_INTERVAL_MINUTES}min"
