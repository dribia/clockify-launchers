"""Legacy launcher import preview dialog."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from clockify_launchers.context import AppContext
from clockify_launchers.domain.models import LauncherSource, LauncherTarget
from clockify_launchers.services.import_service import LegacyLauncher

if TYPE_CHECKING:
    from clockify_launchers.ui.main_window import MainWindow

log = logging.getLogger(__name__)


class ImportDialog(Adw.Dialog):
    def __init__(
        self, window: MainWindow, context: AppContext, found: list[LegacyLauncher]
    ) -> None:
        super().__init__(title="Import legacy launchers")
        self.window = window
        self.context = context
        self.found = found
        self.set_content_width(600)
        self.set_content_height(520)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Detected launchers",
            description=(
                "These call clockify-cli directly. Importing creates a new managed launcher; "
                "the original file is left untouched."
            ),
        )
        self.checks: list[tuple[LegacyLauncher, Gtk.CheckButton]] = []
        for legacy in found:
            subtitle = f"Project: {legacy.project}"
            if legacy.task:
                subtitle += f", Task: {legacy.task}"
            if legacy.tags:
                subtitle += f", Tags: {', '.join(legacy.tags)}"
            if legacy.description:
                subtitle += f", Description: {legacy.description}"
            if legacy.ignored_options:
                subtitle += f"  (ignored options: {', '.join(legacy.ignored_options)})"
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(legacy.name),
                subtitle=GLib.markup_escape_text(subtitle),
            )
            check = Gtk.CheckButton(active=True)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            group.add(row)
            self.checks.append((legacy, check))
        page.add(group)

        action_group = Adw.PreferencesGroup()
        button = Gtk.Button(label="Import selected", halign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.add_css_class("pill")
        button.connect("clicked", self._on_import)
        row = Adw.PreferencesRow(activatable=False)
        row.set_child(button)
        action_group.add(row)
        page.add(action_group)
        toolbar.set_content(page)
        self.set_child(toolbar)

    def _resolve_target(self, legacy: LegacyLauncher) -> LauncherTarget | None:
        """Resolve legacy names to cached Clockify IDs; None when unresolvable."""
        workspace_id = self.context.config.active_workspace_id or ""
        project = next(
            (
                p
                for p in self.context.db.get_projects(workspace_id)
                if p.name.lower() == legacy.project.lower() or p.id == legacy.project
            ),
            None,
        )
        if project is None:
            return None
        task_id = None
        if legacy.task:
            task = next(
                (
                    t
                    for t in self.context.db.get_tasks(project.id)
                    if t.name.lower() == legacy.task.lower() or t.id == legacy.task
                ),
                None,
            )
            if task is None:
                return None
            task_id = task.id
        tag_ids = []
        all_tags = self.context.db.get_tags(workspace_id)
        for tag_name in legacy.tags:
            tag = next(
                (t for t in all_tags if t.name.lower() == tag_name.lower() or t.id == tag_name),
                None,
            )
            if tag is None:
                return None
            tag_ids.append(tag.id)
        return LauncherTarget(
            workspace_id=workspace_id,
            project_id=project.id,
            task_id=task_id,
            tag_ids=tuple(tag_ids),
            description=legacy.description,
        )

    def _on_import(self, _button: Gtk.Button) -> None:
        imported = 0
        skipped: list[str] = []
        for legacy, check in self.checks:
            if not check.get_active():
                continue
            target = self._resolve_target(legacy)
            if target is None:
                skipped.append(legacy.name)
                continue
            if self.context.launcher_service.duplicate_of(target) is not None:
                skipped.append(f"{legacy.name} (duplicate)")
                continue
            self.context.launcher_service.create(
                account_id=self.context.config.active_account_id or "",
                target=target,
                display_name=legacy.name,
                comment=legacy.comment,
                source=LauncherSource.IMPORTED,
            )
            imported += 1
        message = f"Imported {imported} launcher{'s' if imported != 1 else ''}."
        if skipped:
            message += f" Skipped: {', '.join(skipped)}."
        self.window.toast(message)
        self.window.refresh_all()
        self.close()
