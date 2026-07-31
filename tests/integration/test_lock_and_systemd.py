"""File lock and SystemdManager integration tests."""

from __future__ import annotations

import subprocess

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
