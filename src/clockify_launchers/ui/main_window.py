"""Main application window."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk, Pango

from clockify_launchers import constants
from clockify_launchers.context import AppContext
from clockify_launchers.domain.models import Candidate, TimeEntry
from clockify_launchers.infrastructure.clockify_api import (
    AuthError,
    ClockifyClientProtocol,
    OfflineError,
)
from clockify_launchers.infrastructure.secret_store import SecretUnavailableError
from clockify_launchers.infrastructure.status_notifier import TimerIndicator
from clockify_launchers.services.sync_service import SyncResult, SyncService
from clockify_launchers.ui.launchers_page import LaunchersPage
from clockify_launchers.ui.preferences_page import PreferencesPage
from clockify_launchers.ui.suggestions_page import SuggestionsPage
from clockify_launchers.ui.workers import run_async

if TYPE_CHECKING:
    from clockify_launchers.services.timer_service import StartResult

log = logging.getLogger(__name__)


def _screen_is_locked() -> bool:
    """Best-effort GNOME screensaver query (worker thread)."""
    from gi.repository import Gio

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync(
            "org.gnome.ScreenSaver",
            "/org/gnome/ScreenSaver",
            "org.gnome.ScreenSaver",
            "GetActive",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            2000,
            None,
        )
        return bool(result.unpack()[0])
    except Exception:
        return False


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, context: AppContext) -> None:
        super().__init__(application=app, title=constants.APP_NAME)
        self.context = context
        self.set_default_size(1000, 720)
        self.set_size_request(360, 400)
        # Eligible candidates the automatic-launcher cap left unadded in the
        # last sync; rendered on the Suggestions page until the next sync.
        self.blocked_candidates: list[Candidate] = []
        if context.demo and os.environ.get(constants.DEMO_STATE_ENV_VAR, "") == "suggestions-add":
            self._seed_demo_blocked_candidates()

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        root = Adw.ToolbarView()
        self.toast_overlay.set_child(root)

        # Header
        header = Adw.HeaderBar()
        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        new_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New launcher")
        new_button.update_property([Gtk.AccessibleProperty.LABEL], ["New launcher"])
        new_button.set_action_name("win.new-launcher")
        header.pack_start(new_button)

        self.sync_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Sync now")
        self.sync_button.set_action_name("win.sync-now")
        header.pack_end(self.sync_button)
        self.sync_spinner = Gtk.Spinner()
        header.pack_end(self.sync_spinner)
        root.add_top_bar(header)

        # Status banner (offline / auth errors / sync info)
        self.banner = Adw.Banner(revealed=False)
        root.add_top_bar(self.banner)

        # Current-timer banner
        self.timer_bar = self._build_timer_bar()
        root.add_top_bar(self.timer_bar)

        # Pages
        self.launchers_page = LaunchersPage(self)
        self.suggestions_page = SuggestionsPage(self)
        self.preferences_page = PreferencesPage(self)
        page = self.view_stack.add_titled(self.launchers_page, "launchers", "Launchers")
        page.set_icon_name("view-list-symbolic")
        page = self.view_stack.add_titled(self.suggestions_page, "suggestions", "Suggestions")
        page.set_icon_name("starred-symbolic")
        page = self.view_stack.add_titled(self.preferences_page, "preferences", "Preferences")
        page.set_icon_name("preferences-system-symbolic")
        root.set_content(self.view_stack)

        # Bottom bar with workspace / mode / last-sync info
        root.add_bottom_bar(self._build_status_bar())

        self._install_actions()
        self._apply_demo_state()
        self.refresh_all()

        # Top-bar indicator. While it is visible in the top bar, closing the
        # window hides to the indicator instead of quitting (ADR 0015).
        self.indicator = TimerIndicator(
            on_activate=self._present_and_refresh,
            on_stop=lambda: self._on_stop_timer(None),
            on_quit=self._quit_app,
            on_lost=self._on_indicator_lost,
        )
        self.indicator.publish()
        self.connect("close-request", self._on_close_request)

        GLib.timeout_add_seconds(30, self._refresh_timer_banner_tick)
        # Refresh the current-timer state every time the window is shown,
        # including the initial presentation and re-shows from the
        # top-bar indicator after running hidden in the background.
        self.connect("map", lambda *_: self.refresh_timer_now())

    # -- construction helpers ------------------------------------------------

    def _seed_demo_blocked_candidates(self) -> None:
        """Deterministic cap-blocked rows for the suggestions-add demo state."""
        from datetime import timedelta

        from clockify_launchers.demo import fixtures
        from clockify_launchers.domain.models import LauncherTarget

        now = fixtures.DEMO_NOW
        self.blocked_candidates = [
            Candidate(
                target=LauncherTarget(
                    workspace_id=fixtures.WS_MAIN.id,
                    project_id="prj-kaito",
                    task_id="task-report",
                ),
                count=3,
                last_use=now - timedelta(days=2),
                score=2.7,
                representative_entry_id="te-demo-blocked-1",
                project_name="Kaito",
                task_name="Quarterly report",
            ),
            Candidate(
                target=LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id="prj-research"),
                count=2,
                last_use=now - timedelta(days=5),
                score=1.9,
                representative_entry_id="te-demo-blocked-2",
                project_name="Research",
            ),
        ]

    def _build_timer_bar(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, visible=False)
        box.add_css_class("timer-banner")
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        self.timer_label = Gtk.Label(
            label="", xalign=0.0, hexpand=True, ellipsize=Pango.EllipsizeMode.END
        )
        self.timer_label.set_tooltip_text("Current Clockify timer")
        box.append(self.timer_label)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh timer")
        refresh.add_css_class("flat")
        refresh.connect("clicked", lambda *_: self._refresh_timer_banner())
        box.append(refresh)
        stop = Gtk.Button(label="Stop", tooltip_text="Stop the running timer")
        stop.add_css_class("destructive-action")
        stop.connect("clicked", self._on_stop_timer)
        box.append(stop)
        return box

    def _build_status_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)
        config = self.context.config
        workspace_name = config.active_workspace_id or "no workspace"
        ws = self.context.db.connection.execute(
            "SELECT name FROM workspaces WHERE id = ?", (config.active_workspace_id or "",)
        ).fetchone()
        if ws:
            workspace_name = ws["name"]
        self.workspace_label = Gtk.Label(label=f"Workspace: {workspace_name}")
        self.workspace_label.add_css_class("dim-label")
        self.mode_label = Gtk.Label(label=f"Mode: {config.management_mode.value.capitalize()}")
        self.mode_label.add_css_class("dim-label")
        self.last_sync_label = Gtk.Label(label="Last sync: never", hexpand=True, xalign=1.0)
        self.last_sync_label.add_css_class("dim-label")
        bar.append(self.workspace_label)
        bar.append(self.mode_label)
        bar.append(self.last_sync_label)
        return bar

    def _install_actions(self) -> None:
        from gi.repository import Gio

        for name, callback in (
            ("new-launcher", self._on_new_launcher),
            ("sync-now", self._on_sync_now),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _apply_demo_state(self) -> None:
        state = os.environ.get(constants.DEMO_STATE_ENV_VAR, "")
        if not self.context.demo:
            return
        if state.startswith("suggestions"):
            self.view_stack.set_visible_child_name("suggestions")
        elif state == "preferences":
            self.view_stack.set_visible_child_name("preferences")
        elif state == "offline":
            self.show_banner(
                "Clockify is unreachable. Launchers still work when you are back online."
            )
        elif state == "auth-error":
            self.show_banner("Clockify rejected the API key. Update it in Preferences.")
        elif state == "launcher-editor":
            GLib.idle_add(self._open_editor_idle)

    def _open_editor_idle(self) -> bool:
        self._on_new_launcher(None, None)
        return False

    # -- shared behaviors ------------------------------------------------------

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if self.indicator.registered:
            # Keep running in the background; the indicator stays in the
            # top bar and its menu offers Open / Stop / Quit.
            self.set_visible(False)
            return True
        self.indicator.unpublish()
        return False

    def _present_and_refresh(self) -> None:
        was_visible = self.get_visible()
        self.present()
        if was_visible:
            # "map" does not fire when the window was already visible.
            self.refresh_timer_now()

    def run_in_background(self) -> None:
        """Background (autostart) start: keep the window hidden.

        The window stays alive so the top-bar indicator works from login.
        If the indicator cannot register, the existing reachability check
        presents the window instead of staying invisibly hidden.
        """
        GLib.timeout_add_seconds(10, self._check_indicator_reachable)

    def _quit_app(self) -> None:
        self.indicator.unpublish()
        app = self.get_application()
        if app is not None:
            app.quit()

    def _on_indicator_lost(self) -> None:
        """The top-bar watcher vanished while we may be running hidden.

        Screen lock/unlock restarts the watcher, so give it a grace period
        (and skip re-checks while the screen is locked) before re-presenting
        the window. Never stay hidden without a reachable indicator.
        """
        GLib.timeout_add_seconds(10, self._check_indicator_reachable)

    def _check_indicator_reachable(self) -> bool:
        if self.indicator.registered or self.get_visible():
            return False

        def done(locked: bool) -> None:
            if locked:
                # Watcher is expected to return on unlock; check again later.
                GLib.timeout_add_seconds(10, self._check_indicator_reachable)
            elif not self.indicator.registered and not self.get_visible():
                self.present()

        run_async(_screen_is_locked, done, lambda _exc: done(False))
        return False

    def toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def show_banner(self, message: str) -> None:
        self.banner.set_title(message)
        self.banner.set_revealed(True)

    def hide_banner(self) -> None:
        self.banner.set_revealed(False)

    def refresh_all(self) -> None:
        self.launchers_page.refresh()
        self.suggestions_page.refresh()
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        config = self.context.config
        self.mode_label.set_label(f"Mode: {config.management_mode.value.capitalize()}")
        last = self.context.db.last_successful_sync()
        if last:
            self.last_sync_label.set_label(f"Last sync: {last.strftime('%Y-%m-%d %H:%M')} UTC")
        else:
            self.last_sync_label.set_label("Last sync: never")

    # -- actions -----------------------------------------------------------------

    def _on_new_launcher(self, _action: object, _param: object) -> None:
        from clockify_launchers.ui.launcher_editor import LauncherEditor

        editor = LauncherEditor(self, self.context)
        editor.present(self)

    def _on_sync_now(self, _action: object, _param: object) -> None:
        config = self.context.config
        if not (
            config.active_account_id and config.clockify_user_id and config.active_workspace_id
        ):
            self.toast("Connect a Clockify account first.")
            return
        self.sync_button.set_sensitive(False)
        self.sync_spinner.start()
        account_id = config.active_account_id or ""
        user_id = config.clockify_user_id or ""
        workspace_id = config.active_workspace_id or ""

        def work() -> SyncResult:
            client = self._get_client()
            service = SyncService(
                self.context.db,
                self.context.launcher_service,
                client,
                account_id,
                user_id,
                workspace_id,
            )
            return service.run(config.management_mode, config.policy)

        def done(result: SyncResult) -> None:
            self.sync_button.set_sensitive(True)
            self.sync_spinner.stop()
            outcome = result.outcome
            if outcome == "success":
                self.hide_banner()
                self.blocked_candidates = list(result.blocked)
                parts = ["Sync finished"]
                if result.added:
                    parts.append(f"{len(result.added)} added")
                if result.removed:
                    parts.append(f"{len(result.removed)} removed")
                if result.suggestions_created:
                    parts.append(f"{result.suggestions_created} suggestions")
                if result.blocked:
                    parts.append(f"{len(result.blocked)} waiting for a free slot")
                self.toast(", ".join(parts) + ".")
            elif outcome == "offline":
                self.show_banner("Clockify is unreachable. Nothing was changed.")
            elif outcome == "auth-error":
                self.show_banner("Clockify rejected the API key. Update it in Preferences.")
            else:
                self.toast(f"Sync: {outcome}")
            self.refresh_all()

        def error(exc: Exception) -> None:
            self.sync_button.set_sensitive(True)
            self.sync_spinner.stop()
            if isinstance(exc, OfflineError):
                self.show_banner("Clockify is unreachable. Nothing was changed.")
            elif isinstance(exc, AuthError | SecretUnavailableError):
                self.show_banner("Could not read the API key or Clockify rejected it.")
            else:
                self.toast(f"Sync failed: {exc}")

        run_async(work, done, error)

    def _get_client(self) -> ClockifyClientProtocol:
        if self.context.demo:
            from clockify_launchers.demo.backend import FakeClockifyClient

            client = getattr(self, "_demo_client", None)
            if client is None:
                state = os.environ.get(constants.DEMO_STATE_ENV_VAR, "")
                client = FakeClockifyClient(
                    offline=(state == "offline"), auth_error=(state == "auth-error")
                )
                self._demo_client = client
            return client
        return self.context.account_service.get_client(self.context.config)

    # -- timer banner ---------------------------------------------------------------

    def refresh_timer_now(self) -> None:
        """Public entry point: re-query Clockify for the current timer.

        Called on window show, on app re-activation, and remotely (via the
        exported ``refresh-timer`` app action) by `start`/`stop` CLI runs so
        the banner and top-bar indicator update immediately.
        """
        self._refresh_timer_banner()

    def _refresh_timer_banner_tick(self) -> bool:
        self._refresh_timer_banner()
        return True

    def _refresh_timer_banner(self) -> None:
        config = self.context.config
        if not (config.clockify_user_id and config.active_workspace_id):
            return
        user_id = config.clockify_user_id
        workspace_id = config.active_workspace_id
        prefs = config.indicator

        from datetime import UTC, datetime, timedelta

        from clockify_launchers.infrastructure.status_notifier import compute_indicator_times

        def work() -> tuple[TimeEntry | None, tuple[int, ...]]:
            client = self._get_client()
            entry = client.get_in_progress_entry(workspace_id, user_id)
            now = datetime.now(tz=UTC)
            # Local midnight and local Monday midnight anchor the totals.
            day_start = (
                datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            week_start = day_start - timedelta(days=day_start.weekday())
            entries: list[TimeEntry] = []
            if prefs.needs_entries:
                fetch_start = week_start if prefs.needs_week else day_start
                entries = client.get_time_entries(workspace_id, user_id, fetch_start, now)
            times = compute_indicator_times(prefs, entries, entry, now, day_start, week_start)
            return entry, times

        def done(result: tuple[TimeEntry | None, tuple[int, ...]]) -> None:
            entry, times = result
            if entry is None:
                self.timer_bar.set_visible(False)
                self.indicator.set_tracking(None, times)
                self.indicator.refresh_label()
                return
            project = self.context.db.get_project(entry.project_id or "")
            name = project.name if project else (entry.description or "timer")
            elapsed = datetime.now(tz=UTC) - entry.start
            minutes = int(elapsed.total_seconds() // 60)
            hours, mins = divmod(minutes, 60)
            self.timer_label.set_label(f"Tracking {name} - {hours:d}:{mins:02d} elapsed")
            self.timer_bar.set_visible(True)
            self.indicator.set_tracking(name, times)
            self.indicator.refresh_label()

        def error(_exc: Exception) -> None:
            self.timer_bar.set_visible(False)
            self.indicator.set_tracking(None)

        run_async(work, done, error)

    def _on_stop_timer(self, _button: Gtk.Button | None) -> None:
        config = self.context.config
        user_id = config.clockify_user_id or ""
        workspace_id = config.active_workspace_id or ""

        def work() -> StartResult:
            from clockify_launchers.services.timer_service import TimerService

            client = self._get_client()
            service = TimerService(
                self.context.db,
                client,
                user_id,
                self.context.paths.timer_action_lock,
            )
            return service.stop_current(workspace_id)

        def done(result: StartResult) -> None:
            self.toast(result.message)
            self._refresh_timer_banner()

        run_async(work, done, lambda exc: self.toast(f"Could not stop the timer: {exc}"))
