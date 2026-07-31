"""Preferences page."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from clockify_launchers.domain.models import ManagementMode

if TYPE_CHECKING:
    from clockify_launchers.ui.main_window import MainWindow

log = logging.getLogger(__name__)

_MODES = [ManagementMode.MANUAL, ManagementMode.ASSISTED, ManagementMode.AUTOPILOT]
_MODE_LABELS = ["Manual", "Assisted (recommended)", "Autopilot"]


class PreferencesPage(Adw.PreferencesPage):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.window = window
        self.context = window.context
        config = self.context.config

        # Connection
        connection = Adw.PreferencesGroup(title="Clockify connection")
        account_row = Adw.ActionRow(
            title="Account",
            subtitle=config.email or "Not connected",
        )
        change_key = Gtk.Button(label="Change API key", valign=Gtk.Align.CENTER)
        change_key.connect("clicked", self._on_change_key)
        account_row.add_suffix(change_key)
        connection.add(account_row)
        url_row = Adw.ActionRow(title="API base URL", subtitle=config.api_base_url)
        connection.add(url_row)
        self.add(connection)

        # Management
        management = Adw.PreferencesGroup(
            title="Management mode",
            description="Assisted adds high-confidence launchers and only suggests removals.",
        )
        self.mode_row = Adw.ComboRow(title="Mode")
        self.mode_row.set_model(Gtk.StringList.new(_MODE_LABELS))
        self.mode_row.set_selected(_MODES.index(config.management_mode))
        self.mode_row.connect("notify::selected", self._on_mode_changed)
        management.add(self.mode_row)
        self.add(management)

        # Automation settings
        automation = Adw.PreferencesGroup(title="Automation")
        self.interval_row = self._spin_row(
            automation, "Sync interval (minutes)", config.policy.sync_interval_minutes, 5, 1440
        )
        self.lookback_row = self._spin_row(
            automation, "Activity lookback (days)", config.policy.lookback_days, 14, 365
        )
        self.stale_row = self._spin_row(
            automation, "Stale threshold (days)", config.policy.stale_days, 14, 365
        )
        self.grace_row = self._spin_row(
            automation, "New-launcher grace period (days)", config.policy.grace_days, 0, 60
        )
        self.max_row = self._spin_row(
            automation, "Maximum automatic launchers", config.policy.max_auto_launchers, 1, 100
        )
        apply_button = Gtk.Button(label="Apply automation settings", halign=Gtk.Align.END)
        apply_button.add_css_class("suggested-action")
        apply_button.connect("clicked", self._on_apply_policy)
        apply_row = Adw.ActionRow(title="")
        apply_row.add_suffix(apply_button)
        automation.add(apply_row)
        self.add(automation)

        # Notifications
        notifications = Adw.PreferencesGroup(title="Notifications")
        self.notif_success = self._switch_row(
            notifications, "Timer started or switched", config.notifications.timer_success
        )
        self.notif_failure = self._switch_row(
            notifications, "Timer failures", config.notifications.timer_failure
        )
        self.notif_additions = self._switch_row(
            notifications, "Background additions summary", config.notifications.background_additions
        )
        self.add(notifications)

        # Maintenance
        maintenance = Adw.PreferencesGroup(title="Maintenance")
        import_row = Adw.ActionRow(
            title="Import legacy launchers",
            subtitle="Find launchers that call clockify-cli directly",
        )
        import_button = Gtk.Button(label="Scan", valign=Gtk.Align.CENTER)
        import_button.connect("clicked", self._on_import)
        import_row.add_suffix(import_button)
        maintenance.add(import_row)
        diag_row = Adw.ActionRow(title="Diagnostics", subtitle="Run configuration checks")
        diag_button = Gtk.Button(label="Run doctor", valign=Gtk.Align.CENTER)
        diag_button.connect("clicked", self._on_doctor)
        diag_row.add_suffix(diag_button)
        maintenance.add(diag_row)
        reset_row = Adw.ActionRow(
            title="Reset application data",
            subtitle="Removes configuration, state, and optionally launchers",
        )
        reset_button = Gtk.Button(label="Reset...", valign=Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect("clicked", self._on_reset)
        reset_row.add_suffix(reset_button)
        maintenance.add(reset_row)
        self.add(maintenance)

    def refresh(self) -> None:  # symmetry with other pages
        pass

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _spin_row(
        group: Adw.PreferencesGroup, title: str, value: int, low: int, high: int
    ) -> Adw.SpinRow:
        row = Adw.SpinRow.new_with_range(low, high, 1)
        row.set_title(title)
        row.set_value(value)
        group.add(row)
        return row

    @staticmethod
    def _switch_row(group: Adw.PreferencesGroup, title: str, active: bool) -> Adw.SwitchRow:
        row = Adw.SwitchRow(title=title, active=active)
        group.add(row)
        return row

    # -- handlers ----------------------------------------------------------------

    def _on_mode_changed(self, *_args: object) -> None:
        mode = _MODES[self.mode_row.get_selected()]
        config = self.context.config
        if mode is config.management_mode:
            return
        config.management_mode = mode
        self.context.save_config(config)
        if mode is ManagementMode.MANUAL:
            self.context.systemd.disable_timer()
        else:
            self.context.systemd.enable_timer()
            self.context.systemd.apply_interval(config.policy.sync_interval_minutes)
        self.window.toast(f"Management mode set to {mode.value.capitalize()}.")
        self.window._update_status_bar()

    def _on_apply_policy(self, _button: Gtk.Button) -> None:
        config = self.context.config
        config.policy = replace(
            config.policy,
            sync_interval_minutes=int(self.interval_row.get_value()),
            lookback_days=int(self.lookback_row.get_value()),
            stale_days=int(self.stale_row.get_value()),
            grace_days=int(self.grace_row.get_value()),
            max_auto_launchers=int(self.max_row.get_value()),
        ).validated()
        config.notifications.timer_success = self.notif_success.get_active()
        config.notifications.timer_failure = self.notif_failure.get_active()
        config.notifications.background_additions = self.notif_additions.get_active()
        self.context.save_config(config)
        if config.management_mode is not ManagementMode.MANUAL:
            self.context.systemd.apply_interval(config.policy.sync_interval_minutes)
        self.window.toast("Settings saved.")

    def _on_change_key(self, _button: Gtk.Button) -> None:
        from clockify_launchers.ui.onboarding import ConnectDialog

        dialog = ConnectDialog(self.window, self.context)
        dialog.present(self.window)

    def _on_import(self, _button: Gtk.Button) -> None:
        from clockify_launchers.services.import_service import scan_legacy_launchers

        found = scan_legacy_launchers(self.context.paths.applications_dir)
        if not found:
            self.window.toast("No legacy clockify-cli launchers were found.")
            return
        from clockify_launchers.ui.import_dialog import ImportDialog

        dialog = ImportDialog(self.window, self.context, found)
        dialog.present(self.window)

    def _on_doctor(self, _button: Gtk.Button) -> None:
        import contextlib
        import io

        from clockify_launchers.cli import cmd_doctor

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cmd_doctor(self.context, network=False)
        dialog = Adw.MessageDialog(
            transient_for=self.window, heading="Diagnostics", body=buffer.getvalue()
        )
        dialog.add_response("close", "Close")
        dialog.present()

    def _on_reset(self, _button: Gtk.Button) -> None:
        launchers = self.context.db.list_launchers()
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading="Reset application data?",
            body=(
                "This removes the configuration, local state, and the keyring entry. "
                f"Optionally also remove the {len(launchers)} managed launchers."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("keep", "Reset, keep launchers")
        dialog.add_response("all", "Reset and remove launchers")
        dialog.set_response_appearance("all", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog: object, response: str) -> None:
            if response == "cancel":
                return
            from clockify_launchers.cli import cmd_reset

            cmd_reset(self.context, remove_launchers=(response == "all"), yes=True)
            self.window.toast("Application data was reset. Restart the application.")

        dialog.connect("response", on_response)
        dialog.present()
