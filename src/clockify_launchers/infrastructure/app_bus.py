"""Best-effort D-Bus signalling from CLI commands to a running GUI.

Desktop launchers execute ``clockify-launchers start --launcher UUID`` as a
separate short-lived process. When the GUI (and its top-bar indicator) is
running, it would otherwise only notice the timer change on its next poll.
These helpers ask the running application - if any - to refresh immediately
by activating an exported Gio application action.

Everything here is best-effort: when no GUI is running (the common case for
launcher clicks) the call fails fast and is ignored.
"""

from __future__ import annotations

import logging

from gi.repository import Gio, GLib

from clockify_launchers import constants

log = logging.getLogger(__name__)

REFRESH_TIMER_ACTION = "refresh-timer"


def app_bus_name(demo: bool) -> str:
    """The application's D-Bus name (demo instances use a distinct id)."""
    return constants.APP_ID + (".Demo" if demo else "")


def app_object_path(demo: bool) -> str:
    """The GApplication export path derived from the application id."""
    return "/" + app_bus_name(demo).replace(".", "/")


def request_gui_timer_refresh(demo: bool) -> bool:
    """Ask a running GUI instance to refresh its timer state now.

    Returns True when the running application acknowledged the request,
    False when no instance is running or the call failed. Never raises and
    never auto-starts the application.
    """
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        connection.call_sync(
            app_bus_name(demo),
            app_object_path(demo),
            "org.freedesktop.Application",
            "ActivateAction",
            GLib.Variant("(sava{sv})", (REFRESH_TIMER_ACTION, [], {})),
            None,
            Gio.DBusCallFlags.NO_AUTO_START,
            1000,
            None,
        )
    except GLib.Error as exc:
        log.debug("no running GUI to refresh: %s", exc)
        return False
    return True
