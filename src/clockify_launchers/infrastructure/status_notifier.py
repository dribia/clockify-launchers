"""Top-bar timer indicator via the StatusNotifierItem D-Bus protocol.

Publishes a StatusNotifierItem (the protocol behind Ubuntu's AppIndicator
top-bar icons) while the main window is open. Ubuntu ships the
``ubuntu-appindicators`` GNOME Shell extension by default, which renders
these items in the top bar including the Ayatana label extension used here
to show the currently tracked project.

The extension treats the ``Menu`` property as required and drops items
whose ``Menu`` lookup fails, so a minimal ``com.canonical.dbusmenu``
implementation is exported alongside the item (Open / Stop timer entries).

The indicator is best-effort: when no StatusNotifierWatcher is present
(e.g. headless test sessions, non-Ubuntu GNOME without the extension) the
item stays dormant and the application behaves normally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gi.repository import Gio, GLib

from clockify_launchers import constants

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

OBJECT_PATH = "/StatusNotifierItem"
MENU_PATH = "/StatusNotifierItem/Menu"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_IFACE = "org.kde.StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"

IDLE_LABEL = "Not tracking"

MENU_ITEM_OPEN = 1
MENU_ITEM_STOP = 2
MENU_ITEM_QUIT = 3

_INTROSPECTION_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="XAyatanaLabel" type="s" access="read"/>
    <property name="XAyatanaLabelGuide" type="s" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
    <signal name="XAyatanaNewLabel">
      <arg name="label" type="s"/>
      <arg name="guide" type="s"/>
    </signal>
  </interface>
</node>
"""

_MENU_INTROSPECTION_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{sv})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>
"""


def format_duration_hm(minutes: int) -> str:
    """Format whole minutes as H:MM (e.g. 332 -> "5:32")."""
    minutes = max(0, minutes)
    hours, mins = divmod(minutes, 60)
    return f"{hours:d}:{mins:02d}"


def format_indicator_label(
    project_name: str | None,
    day_minutes: int | None = None,
    entry_minutes: int | None = None,
) -> str:
    """Compute the top-bar label for the current timer state.

    ``None`` project means no timer is running. When ``day_minutes`` is
    given, the label is prefixed with the total tracked today; when
    ``entry_minutes`` is given (only meaningful while tracking), the
    running entry's elapsed time is appended, e.g. ``5:32 Organic (0:05)``.
    Names are flattened to a single line and truncated so the top bar is
    never flooded.
    """
    name = " ".join(project_name.split()) if project_name else ""
    if name:
        max_len = 40
        if len(name) > max_len:
            name = name[: max_len - 1].rstrip() + "\u2026"
        label = f"\u25b6 {name}"
        if entry_minutes is not None:
            label += f" ({format_duration_hm(entry_minutes)})"
    else:
        label = IDLE_LABEL
    if day_minutes is not None:
        label = f"{format_duration_hm(day_minutes)} {label}"
    return label


class TimerIndicator:
    """A minimal StatusNotifierItem showing the current Clockify timer.

    All methods must be called from the GTK main thread.
    """

    def __init__(
        self,
        on_activate: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_lost: Callable[[], None] | None = None,
    ) -> None:
        self._on_activate = on_activate
        self._on_stop = on_stop
        self._on_quit = on_quit
        self._on_lost = on_lost
        self._connection: Gio.DBusConnection | None = None
        self._registration_id: int = 0
        self._menu_registration_id: int = 0
        self._watch_id: int = 0
        self._label = IDLE_LABEL
        self._tracking = False
        self._menu_revision = 1
        self._published = False
        self._registered = False

    # -- state -------------------------------------------------------------

    @property
    def label(self) -> str:
        return self._label

    @property
    def registered(self) -> bool:
        """True once the StatusNotifierWatcher accepted the item.

        Only then is the indicator known to be visible in the top bar, so
        only then is it safe to keep running without a window.
        """
        return self._registered

    def set_tracking(
        self,
        project_name: str | None,
        day_minutes: int | None = None,
        entry_minutes: int | None = None,
    ) -> None:
        """Update the displayed label; ``None`` project means nothing is tracked."""
        new_label = format_indicator_label(project_name, day_minutes, entry_minutes)
        tracking = project_name is not None and bool(" ".join(project_name.split()))
        if new_label == self._label and tracking == self._tracking:
            return
        self._label = new_label
        self._tracking = tracking
        self._emit_label_changed()

    def refresh_label(self) -> None:
        """Re-emit the current label unconditionally.

        The shell extension keeps its own label state and can lose it
        without any observable signal on our side (shell restarts, extension
        reloads). Re-emitting on the periodic refresh makes the top bar
        self-heal within one tick. Safe no-op when unpublished.
        """
        self._emit_label_changed()

    # -- D-Bus lifecycle -----------------------------------------------------

    def publish(self) -> bool:
        """Export the item and menu objects and watch for the watcher.

        Returns True when the local objects were exported. Registration
        with the StatusNotifierWatcher happens whenever that name appears
        on the bus (including after GNOME Shell restarts and screen
        lock/unlock cycles, which restart the watcher).
        """
        if self._published:
            return True
        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            item_node = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
            menu_node = Gio.DBusNodeInfo.new_for_xml(_MENU_INTROSPECTION_XML)
            self._registration_id = connection.register_object(
                OBJECT_PATH,
                item_node.interfaces[0],
                self._on_method_call,
                self._on_get_property,
                None,
            )
            self._menu_registration_id = connection.register_object(
                MENU_PATH,
                menu_node.interfaces[0],
                self._on_menu_method_call,
                self._on_menu_get_property,
                None,
            )
        except GLib.Error as exc:
            log.debug("status notifier unavailable: %s", exc)
            self._cleanup()
            return False
        self._connection = connection
        self._published = True
        self._watch_id = Gio.bus_watch_name_on_connection(
            connection,
            WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            self._on_watcher_vanished,
        )
        return True

    def _on_watcher_appeared(self, connection: Gio.DBusConnection, _name: str, _owner: str) -> None:
        connection.call(
            WATCHER_NAME,
            WATCHER_PATH,
            WATCHER_IFACE,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (connection.get_unique_name(),)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            self._on_watcher_reply,
        )

    def _on_watcher_vanished(self, _connection: Gio.DBusConnection, _name: str) -> None:
        was_registered = self._registered
        self._registered = False
        if was_registered and self._on_lost is not None:
            self._on_lost()

    def _on_watcher_reply(self, source: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
        try:
            source.call_finish(result)
        except GLib.Error as exc:
            # No watcher (extension missing / headless session): stay dormant.
            log.debug("StatusNotifierWatcher not available: %s", exc)
            return
        self._registered = True
        # The shell extension applies the label on XAyatanaNewLabel signals;
        # push the initial state so "Not tracking" shows right after
        # registration instead of only after the first label change.
        self._emit_label_changed()

    def unpublish(self) -> None:
        self._cleanup()
        self._published = False
        self._registered = False

    def _cleanup(self) -> None:
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._connection is not None:
            if self._registration_id:
                self._connection.unregister_object(self._registration_id)
            if self._menu_registration_id:
                self._connection.unregister_object(self._menu_registration_id)
        self._registration_id = 0
        self._menu_registration_id = 0
        self._connection = None

    # -- StatusNotifierItem vtable ---------------------------------------------

    def properties(self) -> dict[str, GLib.Variant]:
        """All exported SNI properties for the current state."""
        return {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", constants.APP_ID),
            "Title": GLib.Variant("s", constants.APP_NAME),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", constants.APP_ID),
            "IconThemePath": GLib.Variant("s", ""),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
            "ToolTip": GLib.Variant(
                "(sa(iiay)ss)", (constants.APP_ID, [], constants.APP_NAME, self._label)
            ),
            "XAyatanaLabel": GLib.Variant("s", self._label),
            "XAyatanaLabelGuide": GLib.Variant("s", ""),
        }

    def _on_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        name: str,
    ) -> GLib.Variant | None:
        return self.properties().get(name)

    def _on_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        method: str,
        _params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method == "Activate" and self._on_activate is not None:
            self._on_activate()
        invocation.return_value(None)

    def _emit_label_changed(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.emit_signal(
                None,
                OBJECT_PATH,
                ITEM_IFACE,
                "XAyatanaNewLabel",
                GLib.Variant("(ss)", (self._label, "")),
            )
            self._connection.emit_signal(None, OBJECT_PATH, ITEM_IFACE, "NewToolTip", None)
            self._menu_revision += 1
            self._connection.emit_signal(
                None,
                MENU_PATH,
                MENU_IFACE,
                "LayoutUpdated",
                GLib.Variant("(ui)", (self._menu_revision, 0)),
            )
        except GLib.Error as exc:  # pragma: no cover - bus gone
            log.debug("could not emit indicator signal: %s", exc)

    # -- com.canonical.dbusmenu vtable -------------------------------------------

    def menu_properties(self) -> dict[str, GLib.Variant]:
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }

    def menu_items(self) -> list[tuple[int, dict[str, GLib.Variant]]]:
        """Menu entries as (id, properties) pairs, reflecting current state."""
        items = [
            (
                MENU_ITEM_OPEN,
                {
                    "label": GLib.Variant("s", f"Open {constants.APP_NAME}"),
                    "enabled": GLib.Variant("b", True),
                    "visible": GLib.Variant("b", True),
                },
            )
        ]
        if self._on_stop is not None:
            items.append(
                (
                    MENU_ITEM_STOP,
                    {
                        "label": GLib.Variant("s", "Stop timer"),
                        "enabled": GLib.Variant("b", self._tracking),
                        "visible": GLib.Variant("b", True),
                    },
                )
            )
        if self._on_quit is not None:
            items.append(
                (
                    MENU_ITEM_QUIT,
                    {
                        "label": GLib.Variant("s", "Quit"),
                        "enabled": GLib.Variant("b", True),
                        "visible": GLib.Variant("b", True),
                    },
                )
            )
        return items

    def _menu_layout(self) -> GLib.Variant:
        # Children of an ``av`` must be single-wrapped variants of
        # ``(ia{sv}av)``; double wrapping breaks the shell's deep_unpack().
        children = [
            GLib.Variant("(ia{sv}av)", (item_id, props, [])) for item_id, props in self.menu_items()
        ]
        root_props = {"children-display": GLib.Variant("s", "submenu")}
        return GLib.Variant(
            "(u(ia{sv}av))",
            (self._menu_revision, (0, root_props, children)),
        )

    def _on_menu_get_property(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        name: str,
    ) -> GLib.Variant | None:
        return self.menu_properties().get(name)

    def _on_menu_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _iface: str,
        method: str,
        params: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method == "GetLayout":
            invocation.return_value(self._menu_layout())
        elif method == "GetGroupProperties":
            ids = set(params.unpack()[0])
            rows = [(i, props) for i, props in self.menu_items() if not ids or i in ids]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (rows,)))
        elif method == "GetProperty":
            item_id, name = params.unpack()
            props = dict(self.menu_items()).get(item_id, {})
            value = props.get(name, GLib.Variant("s", ""))
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event_id, _data, _ts = params.unpack()
            self._dispatch_menu_event(int(item_id), str(event_id))
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event_id, _data, _ts in params.unpack()[0]:
                self._dispatch_menu_event(int(item_id), str(event_id))
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))
        else:  # pragma: no cover - defensive
            invocation.return_value(None)

    def _dispatch_menu_event(self, item_id: int, event_id: str) -> None:
        if event_id != "clicked":
            return
        if item_id == MENU_ITEM_OPEN and self._on_activate is not None:
            self._on_activate()
        elif item_id == MENU_ITEM_STOP and self._on_stop is not None:
            self._on_stop()
        elif item_id == MENU_ITEM_QUIT and self._on_quit is not None:
            self._on_quit()
