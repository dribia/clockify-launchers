"""GTK application entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

if TYPE_CHECKING:
    from gi.repository import Gdk

from clockify_launchers import constants  # noqa: E402
from clockify_launchers.context import AppContext  # noqa: E402

log = logging.getLogger(__name__)

_CSS = """
.status-healthy { color: @success_color; }
.status-warning { color: @warning_color; }
.status-error { color: @error_color; }
.launcher-icon { border-radius: 8px; }
.timer-banner {
  background: alpha(@accent_bg_color, 0.12);
  border-radius: 10px;
  padding: 6px 12px;
}
"""


class ClockifyLaunchersApp(Adw.Application):
    def __init__(self, context: AppContext) -> None:
        GLib.set_prgname(constants.EXECUTABLE)
        GLib.set_application_name(constants.APP_NAME)
        super().__init__(
            application_id=constants.APP_ID + (".Demo" if context.demo else ""),
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.context = context
        self._window: Adw.ApplicationWindow | None = None
        self.connect("activate", self._on_activate)

        # Exported app action: lets the short-lived `start`/`stop` CLI
        # processes (desktop launchers) tell a running GUI to refresh the
        # timer banner and top-bar indicator immediately.
        from clockify_launchers.infrastructure.app_bus import REFRESH_TIMER_ACTION

        refresh_action = Gio.SimpleAction.new(REFRESH_TIMER_ACTION, None)
        refresh_action.connect("activate", self._on_refresh_timer_action)
        self.add_action(refresh_action)

    def _on_refresh_timer_action(self, _action: Gio.SimpleAction, _param: object) -> None:
        from clockify_launchers.ui.main_window import MainWindow

        if isinstance(self._window, MainWindow):
            self._window.refresh_timer_now()

    def _on_activate(self, _app: Adw.Application) -> None:
        if self._window is not None:
            self._window.present()
            from clockify_launchers.ui.main_window import MainWindow

            if isinstance(self._window, MainWindow):
                self._window.refresh_timer_now()
            return
        provider = Gtk.CssProvider()
        provider.load_from_string(_CSS)
        display = self._get_display()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        from clockify_launchers.ui.main_window import MainWindow
        from clockify_launchers.ui.onboarding import OnboardingWindow

        if self.context.config.onboarding_complete:
            self._window = MainWindow(self, self.context)
        else:
            self._window = OnboardingWindow(self, self.context)
        size = os.environ.get("CLOCKIFY_LAUNCHERS_WINDOW_SIZE", "")
        if "x" in size:
            try:
                width, height = (int(v) for v in size.split("x", 1))
                self._window.set_default_size(width, height)
            except ValueError:
                pass
        self._window.present()
        GLib.idle_add(self._write_ready_file)

    @staticmethod
    def _get_display() -> Gdk.Display | None:
        from gi.repository import Gdk

        return Gdk.Display.get_default()

    def _write_ready_file(self) -> bool:
        """Readiness marker for the screenshot harness."""
        ready = os.environ.get("CLOCKIFY_LAUNCHERS_READY_FILE")
        if ready:
            try:
                Path(ready).write_text("ready\n", encoding="utf-8")
            except OSError as exc:
                log.warning("could not write ready file: %s", exc)
        return False

    def show_main_window(self) -> None:
        from clockify_launchers.ui.main_window import MainWindow

        old = self._window
        self._window = MainWindow(self, self.context)
        self._window.present()
        if old is not None:
            old.destroy()


def run_app(context: AppContext) -> int:
    app = ClockifyLaunchersApp(context)
    return app.run(None)
