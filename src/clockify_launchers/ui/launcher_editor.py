"""Launcher editor dialog (create and edit)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from gi.repository import Adw, Gtk

from clockify_launchers.context import AppContext
from clockify_launchers.domain.models import Launcher, LauncherTarget, Project, Task
from clockify_launchers.ui.workers import run_async

if TYPE_CHECKING:
    from clockify_launchers.ui.main_window import MainWindow

log = logging.getLogger(__name__)


class LauncherEditor(Adw.Dialog):
    def __init__(
        self, window: MainWindow, context: AppContext, launcher: Launcher | None = None
    ) -> None:
        super().__init__(title="Edit launcher" if launcher else "New launcher")
        self.window = window
        self.context = context
        self.launcher = launcher
        self.set_content_width(560)
        self.set_content_height(680)
        self._icon_source: Path | None = None

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.save_button = Gtk.Button(label="Save")
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", self._on_save)
        header.pack_end(self.save_button)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Clockify target")

        self.projects = self.context.db.get_projects(self.context.config.active_workspace_id or "")
        self.projects = [p for p in self.projects if not p.archived]
        project_names = [p.name for p in self.projects] or ["(no projects cached)"]
        self.project_row = Adw.ComboRow(title="Project", subtitle="Required")
        self.project_row.set_model(Gtk.StringList.new(project_names))
        # Type-to-search inside the popover; essential with many projects.
        self.project_row.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
        )
        self.project_row.set_enable_search(True)
        self.project_row.connect("notify::selected", self._on_project_changed)
        group.add(self.project_row)

        self.task_row = Adw.ComboRow(title="Task", subtitle="Optional")
        self.task_row.set_model(Gtk.StringList.new(["No task"]))
        self.task_row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.task_row.set_enable_search(True)
        self.task_row.connect("notify::selected", lambda *_: self._check_duplicate())
        group.add(self.task_row)

        self.tags_group = Adw.PreferencesGroup(title="Tags")
        self.tag_rows: list[tuple[str, Adw.SwitchRow]] = []
        for tag in self.context.db.get_tags(self.context.config.active_workspace_id or ""):
            if tag.archived:
                continue
            row = Adw.SwitchRow(title=tag.name)
            row.connect("notify::active", lambda *_: self._check_duplicate())
            self.tags_group.add(row)
            self.tag_rows.append((tag.id, row))

        details = Adw.PreferencesGroup(title="Launcher details")
        self.name_row = Adw.EntryRow(title="Display name")
        details.add(self.name_row)
        self.comment_row = Adw.EntryRow(title="Comment (optional)")
        details.add(self.comment_row)
        self.description_row = Adw.EntryRow(title="Fixed time-entry description (optional)")
        self.description_row.connect("notify::text", lambda *_: self._check_duplicate())
        details.add(self.description_row)

        icon_row = Adw.ActionRow(
            title="Icon", subtitle="A tile with the project color is generated automatically"
        )
        self.icon_button = Gtk.Button(label="Choose image", valign=Gtk.Align.CENTER)
        self.icon_button.connect("clicked", self._on_choose_icon)
        icon_row.add_suffix(self.icon_button)
        details.add(icon_row)

        self.duplicate_label = Gtk.Label(label="", xalign=0.0, wrap=True, visible=False)
        self.duplicate_label.add_css_class("status-warning")

        page.add(group)
        page.add(self.tags_group)
        page.add(details)
        dup_group = Adw.PreferencesGroup()
        dup_row = Adw.PreferencesRow(activatable=False)
        dup_row.set_child(self.duplicate_label)
        dup_group.add(dup_row)
        page.add(dup_group)
        toolbar.set_content(page)
        self.set_child(toolbar)

        self._tasks_for_selected: list[Task] = []
        if launcher is not None:
            self._prefill(launcher)
        else:
            self._on_project_changed(None, None)

    # -- helpers ------------------------------------------------------------

    def _selected_project(self) -> Project | None:
        index = self.project_row.get_selected()
        if 0 <= index < len(self.projects):
            return self.projects[index]
        return None

    def _on_project_changed(self, _row: object, _pspec: object) -> None:
        project = self._selected_project()
        names = ["No task"]
        self._tasks_for_selected = []
        if project is not None:
            tasks = [t for t in self.context.db.get_tasks(project.id) if t.active]
            self._tasks_for_selected = tasks
            names += [t.name for t in tasks]
        self.task_row.set_model(Gtk.StringList.new(names))
        self.task_row.set_selected(0)
        self._check_duplicate()

    def _current_target(self) -> LauncherTarget | None:
        project = self._selected_project()
        if project is None:
            return None
        task_index = self.task_row.get_selected()
        task_id = None
        if task_index > 0 and task_index - 1 < len(self._tasks_for_selected):
            task_id = self._tasks_for_selected[task_index - 1].id
        tag_ids = tuple(tag_id for tag_id, row in self.tag_rows if row.get_active())
        description = self.description_row.get_text().strip() or None
        return LauncherTarget(
            workspace_id=self.context.config.active_workspace_id or "",
            project_id=project.id,
            task_id=task_id,
            tag_ids=tag_ids,
            description=description,
        )

    def _check_duplicate(self) -> None:
        target = self._current_target()
        if target is None:
            return
        exact = self.context.launcher_service.duplicate_of(target)
        if exact is not None and (self.launcher is None or exact.id != self.launcher.id):
            self.duplicate_label.set_label(
                f"A launcher with this target and description already exists: {exact.display_name}"
            )
            self.duplicate_label.set_visible(True)
            return
        same = self.context.launcher_service.same_target_of(target)
        if same is not None and (self.launcher is None or same.id != self.launcher.id):
            self.duplicate_label.set_label(
                f"'{same.display_name}' shares this target. That is fine as long as "
                "the fixed descriptions differ."
            )
            self.duplicate_label.set_visible(True)
        else:
            self.duplicate_label.set_visible(False)

    def _prefill(self, launcher: Launcher) -> None:
        for index, project in enumerate(self.projects):
            if project.id == launcher.target.project_id:
                self.project_row.set_selected(index)
                break
        self._on_project_changed(None, None)
        if launcher.target.task_id:
            for index, task in enumerate(self._tasks_for_selected):
                if task.id == launcher.target.task_id:
                    self.task_row.set_selected(index + 1)
                    break
        for tag_id, row in self.tag_rows:
            row.set_active(tag_id in launcher.target.tag_ids)
        self.name_row.set_text(launcher.display_name)
        self.comment_row.set_text(launcher.comment)
        if launcher.target.description:
            self.description_row.set_text(launcher.target.description)

    def _on_choose_icon(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Choose launcher icon")
        filter_images = Gtk.FileFilter()
        filter_images.set_name("Images")
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.svg"):
            filter_images.add_pattern(pattern)
        from gi.repository import Gio

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filter_images)
        dialog.set_filters(filters)

        def on_done(dlg: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                file = dlg.open_finish(result)
            except Exception:
                return
            path = file.get_path() if file is not None else None
            if path:
                self._icon_source = Path(path)
                self.icon_button.set_label(self._icon_source.name)

        dialog.open(self.window, None, on_done)

    def _on_save(self, _button: Gtk.Button) -> None:
        target = self._current_target()
        if target is None:
            self.window.toast("Select a project first.")
            return
        name = self.name_row.get_text().strip()
        if not name:
            project = self._selected_project()
            name = project.name if project else "Clockify launcher"
        comment = self.comment_row.get_text().strip()
        duplicate = self.context.launcher_service.duplicate_of(target)
        if duplicate is not None and (self.launcher is None or duplicate.id != self.launcher.id):
            self._check_duplicate()
            self.window.toast("A launcher with this target and description already exists.")
            return

        def work() -> Launcher:
            if self.launcher is None:
                return self.context.launcher_service.create(
                    account_id=self.context.config.active_account_id or "",
                    target=target,
                    display_name=name,
                    comment=comment,
                    icon_source=self._icon_source,
                )
            return self.context.launcher_service.update(
                self.launcher,
                display_name=name,
                comment=comment,
                target=target,
                icon_source=self._icon_source,
            )

        def done(launcher: Launcher) -> None:
            self.window.toast(f"Saved {launcher.display_name}.")
            self.window.refresh_all()
            self.close()

        def error(exc: Exception) -> None:
            self.save_button.set_sensitive(True)
            self.window.toast(f"Could not save: {exc}")

        self.save_button.set_sensitive(False)
        run_async(work, done, error)
