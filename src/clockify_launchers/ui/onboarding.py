"""First-run onboarding flow."""

from __future__ import annotations

import logging
import os

from gi.repository import Adw, Gtk

from clockify_launchers import constants
from clockify_launchers.context import AppContext
from clockify_launchers.domain.models import ManagementMode, Workspace
from clockify_launchers.infrastructure.clockify_api import region_base_url
from clockify_launchers.services.account_service import ValidationResult
from clockify_launchers.ui.workers import run_async

log = logging.getLogger(__name__)

_REGIONS = [
    ("Global (default)", None),
    ("Europe Central (euc1)", "euc1"),
    ("US East (use2)", "use2"),
    ("Europe West (euw2)", "euw2"),
    ("Asia Pacific (apse2)", "apse2"),
]

_MODE_CHOICES = [
    (
        ManagementMode.MANUAL,
        "Manual",
        "You create and delete every launcher yourself. No background sync.",
    ),
    (
        ManagementMode.ASSISTED,
        "Assisted - recommended",
        "New launchers appear automatically from your recent activity. Removals are only suggested, never automatic.",
    ),
    (
        ManagementMode.AUTOPILOT,
        "Autopilot",
        "Adds and also removes stale, unpinned launchers - conservatively, with a restorable history.",
    ),
]


class OnboardingWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, context: AppContext) -> None:
        super().__init__(application=app, title=constants.APP_NAME)
        self.context = context
        self.set_default_size(720, 640)
        self._validation: ValidationResult | None = None
        self._api_key: str = ""
        self._base_url: str = constants.DEFAULT_API_BASE_URL
        self._workspaces: list[Workspace] = []
        self._chosen_workspace: str | None = None
        self._chosen_mode = ManagementMode.ASSISTED

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)
        self.nav = Adw.NavigationView()
        self.toast_overlay.set_child(self.nav)

        self.nav.add(self._welcome_page())
        state = os.environ.get(constants.DEMO_STATE_ENV_VAR, "")
        if context.demo and state.startswith("onboarding-") and state != "onboarding-welcome":
            if state == "onboarding-key":
                self.nav.push(self._connect_page())
            elif state == "onboarding-workspace":
                self._validation = self._demo_validation()
                self._workspaces = list(self._validation.workspaces)
                self.nav.push(self._workspace_page())
            elif state == "onboarding-mode":
                self._validation = self._demo_validation()
                self._workspaces = list(self._validation.workspaces)
                self._chosen_workspace = self._workspaces[0].id
                self.nav.push(self._mode_page())

    @staticmethod
    def _demo_validation() -> ValidationResult:
        from clockify_launchers.demo import fixtures

        return ValidationResult(
            user_id=fixtures.DEMO_USER_ID,
            email=fixtures.DEMO_EMAIL,
            display_name=fixtures.DEMO_NAME,
            default_workspace_id=fixtures.WS_MAIN.id,
            workspaces=tuple(fixtures.WORKSPACES),
        )

    def toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    # -- pages -----------------------------------------------------------------

    def _page(self, tag: str, title: str, content: Gtk.Widget) -> Adw.NavigationPage:
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(content)
        return Adw.NavigationPage(title=title, tag=tag, child=content and toolbar)

    def _welcome_page(self) -> Adw.NavigationPage:
        status = Adw.StatusPage(
            title="Welcome to Clockify Launchers",
            description=(
                "Create Ubuntu application launchers that start Clockify timers with one click. "
                "Your API key stays in the system keyring."
            ),
            icon_name="alarm-symbolic",
            vexpand=True,
        )
        button = Gtk.Button(label="Get started", halign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.add_css_class("pill")
        button.connect("clicked", lambda *_: self.nav.push(self._connect_page()))
        status.set_child(button)
        return self._page("welcome", "Welcome", status)

    def _connect_page(self) -> Adw.NavigationPage:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Connect Clockify",
            description=(
                "The key is stored in your system keyring and never leaves this "
                "machine except to Clockify."
            ),
        )
        self.region_row = Adw.ComboRow(title="API region")
        self.region_row.set_model(Gtk.StringList.new([label for label, _ in _REGIONS]))
        group.add(self.region_row)
        key_help_row = Adw.ActionRow(
            title="Get your API key",
            subtitle="Generate or copy it in Clockify under Profile settings, Advanced",
        )
        open_settings = Gtk.Button(label="Open Clockify settings", valign=Gtk.Align.CENTER)
        open_settings.set_tooltip_text("Opens the Clockify profile settings page in your browser")
        open_settings.connect("clicked", self._on_open_key_settings)
        key_help_row.add_suffix(open_settings)
        key_help_row.set_activatable_widget(open_settings)
        group.add(key_help_row)
        self.key_row = Adw.PasswordEntryRow(title="Clockify API key")
        group.add(self.key_row)
        page.add(group)

        verify_group = Adw.PreferencesGroup()
        self.verify_button = Gtk.Button(label="Verify connection", halign=Gtk.Align.CENTER)
        self.verify_button.add_css_class("suggested-action")
        self.verify_button.add_css_class("pill")
        self.verify_button.connect("clicked", self._on_verify)
        self.verify_status = Gtk.Label(label="", wrap=True, margin_top=12)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        holder.append(self.verify_button)
        holder.append(self.verify_status)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(holder)
        verify_group.add(row)
        page.add(verify_group)
        return self._page("connect", "Connect Clockify", page)

    def _on_open_key_settings(self, _button: Gtk.Button) -> None:
        launcher = Gtk.UriLauncher(uri=constants.API_KEY_SETTINGS_URL)
        launcher.launch(self, None, None)

    def _on_verify(self, _button: Gtk.Button) -> None:
        api_key = self.key_row.get_text().strip()
        if not api_key:
            self.verify_status.set_label("Enter your API key first.")
            return
        region = _REGIONS[self.region_row.get_selected()][1]
        base_url = region_base_url(region)
        self.verify_button.set_sensitive(False)
        self.verify_status.set_label("Verifying...")

        def work() -> ValidationResult:
            if self.context.demo:
                return self._demo_validation()
            return self.context.account_service.validate_key(base_url, api_key)

        def done(result: ValidationResult) -> None:
            self._validation = result
            self._api_key = api_key
            self._base_url = base_url
            self._workspaces = list(result.workspaces)
            self.verify_status.set_label(f"Connected as {result.display_name} ({result.email}).")
            self.verify_button.set_sensitive(True)
            self.nav.push(self._workspace_page())

        def error(exc: Exception) -> None:
            self.verify_button.set_sensitive(True)
            self.verify_status.set_label(f"Could not verify: {exc}")

        run_async(work, done, error)

    def _workspace_page(self) -> Adw.NavigationPage:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Choose workspace")
        self.workspace_row = Adw.ComboRow(title="Workspace")
        names = [ws.name for ws in self._workspaces] or ["(none found)"]
        self.workspace_row.set_model(Gtk.StringList.new(names))
        if self._validation and self._validation.default_workspace_id:
            for index, ws in enumerate(self._workspaces):
                if ws.id == self._validation.default_workspace_id:
                    self.workspace_row.set_selected(index)
                    break
        group.add(self.workspace_row)
        page.add(group)
        next_group = Adw.PreferencesGroup()
        button = Gtk.Button(label="Continue", halign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.add_css_class("pill")

        def on_continue(*_args: object) -> None:
            index = self.workspace_row.get_selected()
            if 0 <= index < len(self._workspaces):
                self._chosen_workspace = self._workspaces[index].id
                self.nav.push(self._mode_page())

        button.connect("clicked", on_continue)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(button)
        next_group.add(row)
        page.add(next_group)
        return self._page("workspace", "Choose workspace", page)

    def _mode_page(self) -> Adw.NavigationPage:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Choose management mode")
        self._mode_checks: list[Gtk.CheckButton] = []
        first: Gtk.CheckButton | None = None
        for mode, title, description in _MODE_CHOICES:
            row = Adw.ActionRow(title=title, subtitle=description)
            check = Gtk.CheckButton()
            if first is None:
                first = check
            else:
                check.set_group(first)
            if mode is ManagementMode.ASSISTED:
                check.set_active(True)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            check.connect("toggled", lambda c, m=mode: self._set_mode(c, m))
            group.add(row)
            self._mode_checks.append(check)
        page.add(group)

        background_group = Adw.PreferencesGroup(
            title="Background",
            description=(
                "Recommended: with this on, timers started from Ubuntu launchers show "
                "the tracked project in the top bar even when this window is closed."
            ),
        )
        self.background_row = Adw.SwitchRow(
            title="Show the timer indicator at login",
            subtitle="Start Clockify Launchers in the background when you log in",
            active=True,
        )
        background_group.add(self.background_row)
        page.add(background_group)

        finish_group = Adw.PreferencesGroup()
        button = Gtk.Button(label="Finish", halign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.add_css_class("pill")
        button.connect("clicked", self._on_finish)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(button)
        finish_group.add(row)
        page.add(finish_group)
        return self._page("mode", "Management mode", page)

    def _set_mode(self, check: Gtk.CheckButton, mode: ManagementMode) -> None:
        if check.get_active():
            self._chosen_mode = mode

    def _on_finish(self, _button: Gtk.Button) -> None:
        if self._validation is None or self._chosen_workspace is None:
            self.toast("Complete the connection steps first.")
            return
        validation = self._validation
        workspace_id = self._chosen_workspace
        mode = self._chosen_mode
        base_url = self._base_url
        api_key = self._api_key or "demo-key"
        start_in_background = self.background_row.get_active()

        def work() -> None:
            self.context.account_service.connect(base_url, api_key, validation, workspace_id)
            config = self.context.config_store.load()
            config.management_mode = mode
            config.onboarding_complete = True
            config.start_in_background = start_in_background
            self.context.config_store.save(config)
            self.context._config_cache = None
            if not self.context.demo:
                from clockify_launchers.infrastructure import autostart

                autostart.apply(self.context.paths, start_in_background)
            if mode is not ManagementMode.MANUAL and not self.context.demo:
                self.context.systemd.reconcile(True, config.policy.sync_interval_minutes)

        def done(_result: object) -> None:
            from clockify_launchers.application import ClockifyLaunchersApp

            app = self.get_application()
            if isinstance(app, ClockifyLaunchersApp):
                app.show_main_window()

        def error(exc: Exception) -> None:
            self.toast(f"Could not finish setup: {exc}")

        run_async(work, done, error)


class ConnectDialog(Adw.Dialog):
    """Change/re-verify the API key from Preferences."""

    def __init__(self, window: Adw.ApplicationWindow, context: AppContext) -> None:
        super().__init__(title="Change API key")
        self.window = window
        self.context = context
        self.set_content_width(480)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Clockify API key",
            description=(
                "The key is stored in your system keyring and never leaves this "
                "machine except to Clockify."
            ),
        )
        key_help_row = Adw.ActionRow(
            title="Get your API key",
            subtitle="Generate or copy it in Clockify under Profile settings, Advanced",
        )
        open_settings = Gtk.Button(label="Open Clockify settings", valign=Gtk.Align.CENTER)
        open_settings.set_tooltip_text("Opens the Clockify profile settings page in your browser")
        open_settings.connect(
            "clicked",
            lambda *_a: Gtk.UriLauncher(uri=constants.API_KEY_SETTINGS_URL).launch(
                self.window, None, None
            ),
        )
        key_help_row.add_suffix(open_settings)
        key_help_row.set_activatable_widget(open_settings)
        group.add(key_help_row)
        self.key_row = Adw.PasswordEntryRow(title="New API key")
        group.add(self.key_row)
        self.status = Gtk.Label(label="", wrap=True)
        button = Gtk.Button(label="Verify and save", halign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.add_css_class("pill")
        button.connect("clicked", self._on_save)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8)
        holder.append(button)
        holder.append(self.status)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(holder)
        group.add(row)
        page.add(group)
        toolbar.set_content(page)
        self.set_child(toolbar)

    def _on_save(self, _button: Gtk.Button) -> None:
        api_key = self.key_row.get_text().strip()
        if not api_key:
            self.status.set_label("Enter the new API key first.")
            return
        config = self.context.config
        base_url = config.api_base_url

        def work() -> ValidationResult:
            if self.context.demo:
                return OnboardingWindow._demo_validation()
            validation = self.context.account_service.validate_key(base_url, api_key)
            self.context.account_service.connect(
                base_url, api_key, validation, config.active_workspace_id or ""
            )
            return validation

        def done(validation: ValidationResult) -> None:
            self.status.set_label(f"Saved key for {validation.email}.")
            self.close()

        run_async(work, done, lambda exc: self.status.set_label(f"Could not verify: {exc}"))
