"""Launchers page: list, search, filters, row actions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, Gtk

from clockify_launchers.domain.models import (
    Launcher,
    LauncherSource,
    LauncherStatus,
)
from clockify_launchers.ui.workers import run_async

if TYPE_CHECKING:
    from clockify_launchers.services.timer_service import StartResult
    from clockify_launchers.ui.main_window import MainWindow

log = logging.getLogger(__name__)

_STATUS_LABEL = {
    LauncherStatus.HEALTHY: ("Healthy", "status-healthy", "emblem-ok-symbolic"),
    LauncherStatus.STALE: ("Stale", "status-warning", "alarm-symbolic"),
    LauncherStatus.TARGET_MISSING: ("Target missing", "status-error", "dialog-warning-symbolic"),
    LauncherStatus.EXTERNALLY_MODIFIED: (
        "Modified outside Clockify Launchers",
        "status-warning",
        "document-edit-symbolic",
    ),
    LauncherStatus.PENDING_REMOVAL: ("Pending removal", "status-warning", "user-trash-symbolic"),
    LauncherStatus.ERROR: ("Needs attention", "status-error", "dialog-error-symbolic"),
}

_SOURCE_LABEL = {
    LauncherSource.MANUAL: "Manual",
    LauncherSource.IMPORTED: "Imported",
    LauncherSource.AUTOMATIC: "Automatic",
}


class LaunchersPage(Gtk.Box):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.context = window.context

        # Search + filters
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_margin_start(12)
        controls.set_margin_end(12)
        controls.set_margin_top(8)
        controls.set_margin_bottom(4)
        self.search = Gtk.SearchEntry(placeholder_text="Search launchers", hexpand=True)
        self.search.set_tooltip_text("Search launchers by name")
        self.search.connect("search-changed", lambda *_: self._render())
        controls.append(self.search)
        self.filter_status = Gtk.DropDown.new_from_strings(
            ["All statuses", "Healthy", "Stale", "Needs attention"]
        )
        self.filter_status.set_tooltip_text("Filter by status")
        self.filter_status.connect("notify::selected", lambda *_: self._render())
        controls.append(self.filter_status)
        self.filter_source = Gtk.DropDown.new_from_strings(
            ["All sources", "Manual", "Imported", "Automatic"]
        )
        self.filter_source.set_tooltip_text("Filter by source")
        self.filter_source.connect("notify::selected", lambda *_: self._render())
        controls.append(self.filter_source)
        self.filter_pin = Gtk.DropDown.new_from_strings(["All", "Pinned", "Managed"])
        self.filter_pin.set_tooltip_text("Filter by pin state")
        self.filter_pin.connect("notify::selected", lambda *_: self._render())
        controls.append(self.filter_pin)
        self.append(controls)

        # List
        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_start(12)
        self.listbox.set_margin_end(12)
        self.listbox.set_margin_top(4)
        self.listbox.set_margin_bottom(12)
        self.listbox.set_valign(Gtk.Align.START)
        self.scroller.set_child(self.listbox)

        self.empty_state = Adw.StatusPage(
            title="No launchers yet",
            description="Create your first launcher to start Clockify timers from the Ubuntu app grid.",
            icon_name="alarm-symbolic",
            vexpand=True,
        )
        create_button = Gtk.Button(label="New launcher", halign=Gtk.Align.CENTER)
        create_button.add_css_class("suggested-action")
        create_button.add_css_class("pill")
        create_button.set_action_name("win.new-launcher")
        self.empty_state.set_child(create_button)

        self.content_stack = Gtk.Stack()
        self.content_stack.add_named(self.scroller, "list")
        self.content_stack.add_named(self.empty_state, "empty")
        self.append(self.content_stack)

    def refresh(self) -> None:
        self._launchers = self.context.db.list_launchers()
        self._render()

    # -- rendering -------------------------------------------------------------

    def _passes_filters(self, launcher: Launcher) -> bool:
        text = self.search.get_text().strip().lower()
        if text and text not in launcher.display_name.lower():
            return False
        status_sel = self.filter_status.get_selected()
        if status_sel == 1 and launcher.status is not LauncherStatus.HEALTHY:
            return False
        if status_sel == 2 and launcher.status is not LauncherStatus.STALE:
            return False
        if status_sel == 3 and launcher.status in (LauncherStatus.HEALTHY, LauncherStatus.STALE):
            return False
        source_sel = self.filter_source.get_selected()
        sources = [None, LauncherSource.MANUAL, LauncherSource.IMPORTED, LauncherSource.AUTOMATIC]
        if source_sel > 0 and launcher.source is not sources[source_sel]:
            return False
        pin_sel = self.filter_pin.get_selected()
        if pin_sel == 1 and not launcher.pinned:
            return False
        return not (pin_sel == 2 and launcher.pinned)

    def _render(self) -> None:
        while child := self.listbox.get_first_child():
            self.listbox.remove(child)
        launchers = [lc for lc in getattr(self, "_launchers", []) if self._passes_filters(lc)]
        if not getattr(self, "_launchers", []):
            self.content_stack.set_visible_child_name("empty")
            return
        self.content_stack.set_visible_child_name("list")
        for launcher in launchers:
            self.listbox.append(self._build_row(launcher))

    def _subtitle_for(self, launcher: Launcher) -> str:
        parts = []
        project = self.context.db.get_project(launcher.target.project_id)
        parts.append(project.name if project else launcher.target.project_id)
        if launcher.target.task_id:
            task = self.context.db.get_task(launcher.target.task_id)
            parts.append(task.name if task else launcher.target.task_id)
        tags = []
        for tag_id in launcher.target.tag_ids:
            tag = self.context.db.get_tag(tag_id)
            tags.append(tag.name if tag else tag_id)
        line = " - ".join(parts)
        if tags:
            line += "  [" + ", ".join(tags) + "]"
        meta = [_SOURCE_LABEL[launcher.source]]
        if launcher.pinned:
            meta.append("Pinned")
        if launcher.last_start_success_at:
            meta.append(f"Last used {launcher.last_start_success_at.date().isoformat()}")
        return line + "\n" + " | ".join(meta)

    def _build_row(self, launcher: Launcher) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(launcher.display_name))
        row.set_subtitle(GLib.markup_escape_text(self._subtitle_for(launcher)))
        row.set_title_lines(1)
        row.set_subtitle_lines(2)

        icon = Gtk.Image()
        if launcher.icon_path and Path(launcher.icon_path).exists():
            icon.set_from_file(launcher.icon_path)
        else:
            icon.set_from_icon_name("alarm-symbolic")
        icon.set_pixel_size(40)
        icon.add_css_class("launcher-icon")
        row.add_prefix(icon)

        label, css, icon_name = _STATUS_LABEL.get(launcher.status, ("", "", "emblem-ok-symbolic"))
        status = Gtk.Image(icon_name=icon_name, tooltip_text=label or "Healthy")
        status.add_css_class(css or "status-healthy")
        status.set_accessible_role(Gtk.AccessibleRole.IMG)
        row.add_suffix(status)

        start = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Start timer")
        start.add_css_class("flat")
        start.set_valign(Gtk.Align.CENTER)
        start.connect("clicked", lambda *_a, lc=launcher: self._start(lc))
        start.update_property([Gtk.AccessibleProperty.LABEL], [f"Start {launcher.display_name}"])
        row.add_suffix(start)

        menu = Gio.Menu()
        menu.append("Edit", None)
        button = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="More actions")
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        button.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"Actions for {launcher.display_name}"]
        )
        button.set_popover(self._build_menu_popover(launcher))
        row.add_suffix(button)
        return row

    def _build_menu_popover(self, launcher: Launcher) -> Gtk.Popover:
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        def add_item(
            label: str, callback: Callable[[Launcher], None], destructive: bool = False
        ) -> None:
            item = Gtk.Button(label=label)
            item.add_css_class("flat")
            if destructive:
                item.add_css_class("destructive-action")
            item.set_halign(Gtk.Align.FILL)
            child = item.get_first_child()
            if child is not None:
                child.set_halign(Gtk.Align.START)
            item.connect("clicked", lambda *_a, cb=callback: (popover.popdown(), cb(launcher)))
            box.append(item)

        add_item("Edit", self._edit)
        add_item("Unpin" if launcher.pinned else "Pin (keep this launcher)", self._toggle_pin)
        if launcher.status is LauncherStatus.EXTERNALLY_MODIFIED:
            add_item("Restore managed version", self._restore_managed)
        add_item("Open file location", self._open_location)
        add_item("Recreate file", self._recreate)
        add_item("Delete", self._delete, destructive=True)
        popover.set_child(box)
        return popover

    # -- row actions -----------------------------------------------------------

    def _start(self, launcher: Launcher) -> None:
        config = self.context.config
        user_id = config.clockify_user_id or ""

        def work() -> StartResult:
            from clockify_launchers.services.timer_service import TimerService

            client = self.window._get_client()
            service = TimerService(
                self.context.db,
                client,
                user_id,
                self.context.paths.timer_action_lock,
            )
            return service.start_launcher(launcher)

        def done(result: StartResult) -> None:
            self.window.toast(result.message)
            self.window._refresh_timer_banner()
            self.refresh()

        run_async(work, done, lambda exc: self.window.toast(f"Could not start: {exc}"))

    def _edit(self, launcher: Launcher) -> None:
        from clockify_launchers.ui.launcher_editor import LauncherEditor

        editor = LauncherEditor(self.window, self.context, launcher=launcher)
        editor.present(self.window)

    def _toggle_pin(self, launcher: Launcher) -> None:
        self.context.launcher_service.set_pinned(launcher, not launcher.pinned)
        self.window.toast(
            f"{'Pinned' if not launcher.pinned else 'Unpinned'} {launcher.display_name}."
        )
        self.refresh()

    def _restore_managed(self, launcher: Launcher) -> None:
        self.context.launcher_service.restore_managed_version(launcher)
        self.window.toast(f"Restored the managed file for {launcher.display_name}.")
        self.refresh()

    def _open_location(self, launcher: Launcher) -> None:
        if not launcher.desktop_path:
            return
        Gio.AppInfo.launch_default_for_uri(f"file://{Path(launcher.desktop_path).parent}", None)

    def _recreate(self, launcher: Launcher) -> None:
        self.context.launcher_service.write_desktop_file(launcher)
        self.window.toast(f"Recreated the desktop file for {launcher.display_name}.")
        self.refresh()

    def _delete(self, launcher: Launcher) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=f"Delete {launcher.display_name}?",
            body="The launcher can be restored from Suggestions for 90 days.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog: Adw.MessageDialog, response: str) -> None:
            if response == "delete":
                self.context.launcher_service.delete(launcher)
                self.window.toast(f"Deleted {launcher.display_name}.")
                self.refresh()
                self.window.suggestions_page.refresh()

        dialog.connect("response", on_response)
        dialog.present()
