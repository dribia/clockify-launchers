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
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_write_interval_dropin(tmp_path):
    runner = RecordingRunner()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=runner)
    path = mgr.write_interval_dropin(45)
    assert path == tmp_path / "systemd" / "user" / f"{constants.SYSTEMD_TIMER}.d" / "override.conf"
    assert path.read_text() == "[Timer]\nOnUnitActiveSec=\nOnUnitActiveSec=45min\n"
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
    assert dropin.read_text() == "[Timer]\nOnUnitActiveSec=\nOnUnitActiveSec=45min\n"


def test_reconcile_disabled_argv(tmp_path):
    runner = RecordingRunner()
    mgr = SystemdManager(tmp_path / "systemd" / "user", runner=runner)
    assert mgr.reconcile(False, 45)
    # Disabling must not touch the drop-in or run a reload.
    assert runner.calls == [["systemctl", "--user", "disable", "--now", constants.SYSTEMD_TIMER]]


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
