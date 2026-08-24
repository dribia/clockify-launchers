"""Bus-level integration test for the top-bar timer indicator.

Runs the full StatusNotifierItem round trip (register object, register with a
fake StatusNotifierWatcher, read properties, label update) inside a private
D-Bus session so the developer's real session bus and shell are untouched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

_SCRIPT = """
from gi.repository import Gio, GLib

xml = '''<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
</interface></node>'''
conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
registered = []


def call(c, s, p, i, m, params, inv):
    registered.append(params.unpack())
    inv.return_value(None)


node = Gio.DBusNodeInfo.new_for_xml(xml)
conn.register_object("/StatusNotifierWatcher", node.interfaces[0], call, None, None)
Gio.bus_own_name_on_connection(
    conn, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, None, None
)

from clockify_launchers.infrastructure.status_notifier import TimerIndicator

ind = TimerIndicator()
assert ind.publish() is True

out = {}


def got_all(src, res):
    out["all"] = src.call_finish(res).unpack()[0]


def got_label(src, res):
    out["label"] = src.call_finish(res).unpack()[0]


def got_layout(src, res):
    out["layout"] = src.call_finish(res).unpack()


def step1():
    conn.call(
        conn.get_unique_name(), "/StatusNotifierItem",
        "org.freedesktop.DBus.Properties", "GetAll",
        GLib.Variant("(s)", ("org.kde.StatusNotifierItem",)),
        None, Gio.DBusCallFlags.NONE, 2000, None, got_all,
    )
    return False


def step2():
    ind.set_tracking("Tank")
    conn.call(
        conn.get_unique_name(), "/StatusNotifierItem",
        "org.freedesktop.DBus.Properties", "Get",
        GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", "XAyatanaLabel")),
        None, Gio.DBusCallFlags.NONE, 2000, None, got_label,
    )
    conn.call(
        conn.get_unique_name(), "/StatusNotifierItem/Menu",
        "com.canonical.dbusmenu", "GetLayout",
        GLib.Variant("(iias)", (0, -1, [])),
        None, Gio.DBusCallFlags.NONE, 2000, None, got_layout,
    )
    return False


loop = GLib.MainLoop()
GLib.timeout_add(100, step1)
GLib.timeout_add(400, step2)
GLib.timeout_add(1500, lambda: (loop.quit(), False)[1])
loop.run()

assert registered == [(conn.get_unique_name(),)], registered
assert out["all"]["Id"] == "com.dribia.ClockifyLaunchers", out
assert out["all"]["XAyatanaLabel"] == "Not tracking", out
assert out["label"] == "\\u25b6 Tank", out
assert out["all"]["Menu"] == "/StatusNotifierItem/Menu", out
revision, layout = out["layout"]
root_id, root_props, children = layout
assert root_id == 0 and root_props.get("children-display") == "submenu", layout
labels = [child[1].get("label", "") for child in children]
assert any("Open" in lbl for lbl in labels), labels
assert ind.registered is True
ind.unpublish()
assert ind.registered is False
print("INDICATOR-BUS-OK")
"""


@pytest.mark.skipif(
    shutil.which("dbus-run-session") is None, reason="dbus-run-session not available"
)
def test_indicator_full_bus_round_trip() -> None:
    result = subprocess.run(
        ["dbus-run-session", "--", sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "INDICATOR-BUS-OK" in result.stdout
