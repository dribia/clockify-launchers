"""Tests for CLI-to-GUI refresh signalling."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from clockify_launchers.infrastructure.app_bus import app_bus_name, app_object_path


class TestNames:
    def test_production_name_and_path(self) -> None:
        assert app_bus_name(False) == "com.dribia.ClockifyLaunchers"
        assert app_object_path(False) == "/com/dribia/ClockifyLaunchers"

    def test_demo_name_and_path(self) -> None:
        assert app_bus_name(True) == "com.dribia.ClockifyLaunchers.Demo"
        assert app_object_path(True) == "/com/dribia/ClockifyLaunchers/Demo"


_SCRIPT_NO_APP = """
from clockify_launchers.infrastructure.app_bus import request_gui_timer_refresh
# No GUI running on this private bus: must return False and never raise
# or auto-start anything.
assert request_gui_timer_refresh(False) is False
assert request_gui_timer_refresh(True) is False
print("APPBUS-OK")
"""

_SCRIPT_ROUND_TRIP = """
import threading
from gi.repository import Gio, GLib
from clockify_launchers.infrastructure.app_bus import (
    REFRESH_TIMER_ACTION,
    request_gui_timer_refresh,
)

app = Gio.Application(
    application_id="com.dribia.ClockifyLaunchers",
    flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
)
hits = []
action = Gio.SimpleAction.new(REFRESH_TIMER_ACTION, None)
action.connect("activate", lambda *_: hits.append(True))
app.add_action(action)
app.register(None)  # own the bus name and export org.freedesktop.Application

# The CLI runs in a separate process; emulate with a thread so the main
# loop can serve the exported action while the sync call blocks.
outcome = []
thread = threading.Thread(target=lambda: outcome.append(request_gui_timer_refresh(False)))
thread.start()

loop = GLib.MainLoop()
GLib.timeout_add(500, lambda: (loop.quit(), False)[1])
loop.run()
thread.join(timeout=5)
assert outcome == [True], outcome
assert hits == [True], hits
print("APPBUS-ROUNDTRIP-OK")
"""


@pytest.mark.skipif(
    shutil.which("dbus-run-session") is None, reason="dbus-run-session not available"
)
class TestOnPrivateBus:
    def _run(self, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["dbus-run-session", "--", sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_no_running_gui_is_a_quiet_no_op(self) -> None:
        result = self._run(_SCRIPT_NO_APP)
        assert result.returncode == 0, result.stderr
        assert "APPBUS-OK" in result.stdout

    def test_round_trip_activates_refresh_action(self) -> None:
        result = self._run(_SCRIPT_ROUND_TRIP)
        assert result.returncode == 0, result.stderr
        assert "APPBUS-ROUNDTRIP-OK" in result.stdout
