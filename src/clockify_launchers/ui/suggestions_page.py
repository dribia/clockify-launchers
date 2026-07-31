"""Suggestions page: add/remove proposals, tombstones, recent activity."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk

from clockify_launchers.domain.models import (
    Suggestion,
    SuggestionState,
    SuggestionType,
    Tombstone,
    utc_now,
)
from clockify_launchers.services.launcher_service import launcher_from_json

if TYPE_CHECKING:
    from clockify_launchers.ui.main_window import MainWindow

log = logging.getLogger(__name__)


class SuggestionsPage(Gtk.ScrolledWindow):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(vexpand=True)
        self.window = window
        self.context = window.context
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.box.set_margin_start(12)
        self.box.set_margin_end(12)
        self.box.set_margin_top(12)
        self.box.set_margin_bottom(12)
        self.set_child(self.box)

    def refresh(self) -> None:
        while child := self.box.get_first_child():
            self.box.remove(child)
        suggestions = self.context.db.list_suggestions(SuggestionState.OPEN)
        adds = [s for s in suggestions if s.type is SuggestionType.ADD]
        removes = [s for s in suggestions if s.type is SuggestionType.REMOVE]
        tombstones = self.context.db.list_tombstones()

        if not adds and not removes and not tombstones:
            status = Adw.StatusPage(
                title="Nothing to review",
                description="Suggestions from Clockify activity will appear here.",
                icon_name="starred-symbolic",
                vexpand=True,
            )
            self.box.append(status)
            return

        if adds:
            group = Adw.PreferencesGroup(title="Suggested additions")
            for suggestion in adds:
                group.add(self._add_row(suggestion))
            self.box.append(group)
        if removes:
            group = Adw.PreferencesGroup(title="Suggested removals")
            for suggestion in removes:
                group.add(self._remove_row(suggestion))
            self.box.append(group)
        if tombstones:
            group = Adw.PreferencesGroup(title="Recently removed")
            for tomb in tombstones:
                group.add(self._tombstone_row(tomb))
            self.box.append(group)

    # -- rows --------------------------------------------------------------

    def _target_label(self, suggestion: Suggestion) -> str:
        target = suggestion.target
        if target is None:
            return ""
        parts = []
        project = self.context.db.get_project(target.project_id)
        parts.append(project.name if project else target.project_id)
        if target.task_id:
            task = self.context.db.get_task(target.task_id)
            parts.append(task.name if task else target.task_id)
        tags = [
            (tag.name if (tag := self.context.db.get_tag(t)) is not None else t)
            for t in target.tag_ids
        ]
        label = " - ".join(parts)
        if tags:
            label += "  [" + ", ".join(tags) + "]"
        return label

    def _add_row(self, suggestion: Suggestion) -> Adw.ActionRow:
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(self._target_label(suggestion)),
            subtitle=GLib.markup_escape_text(f"{suggestion.explanation} {suggestion.evidence}"),
        )
        accept = Gtk.Button(label="Add launcher", valign=Gtk.Align.CENTER)
        accept.add_css_class("suggested-action")
        accept.connect("clicked", lambda *_a: self._accept_add(suggestion))
        row.add_suffix(accept)
        dismiss = Gtk.Button(label="Dismiss", valign=Gtk.Align.CENTER)
        dismiss.connect("clicked", lambda *_a: self._dismiss(suggestion))
        row.add_suffix(dismiss)
        return row

    def _remove_row(self, suggestion: Suggestion) -> Adw.ActionRow:
        launcher = self.context.db.get_launcher(suggestion.launcher_id or "")
        title = launcher.display_name if launcher else self._target_label(suggestion)
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(title),
            subtitle=GLib.markup_escape_text(f"{suggestion.explanation} {suggestion.evidence}"),
        )
        remove = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER)
        remove.add_css_class("destructive-action")
        remove.connect("clicked", lambda *_a: self._confirm_remove(suggestion))
        row.add_suffix(remove)
        keep = Gtk.Button(label="Keep and pin", valign=Gtk.Align.CENTER)
        keep.connect("clicked", lambda *_a: self._keep_pin(suggestion))
        row.add_suffix(keep)
        snooze = Gtk.Button(label="Snooze 30 days", valign=Gtk.Align.CENTER)
        snooze.connect("clicked", lambda *_a: self._snooze(suggestion))
        row.add_suffix(snooze)
        return row

    def _tombstone_row(self, tomb: Tombstone) -> Adw.ActionRow:
        launcher = launcher_from_json(tomb.launcher_json)
        row = Adw.ActionRow(
            title=GLib.markup_escape_text(launcher.display_name),
            subtitle=GLib.markup_escape_text(
                f"Removed {tomb.removed_at.date().isoformat()}: {tomb.reason}"
            ),
        )
        restore = Gtk.Button(label="Restore", valign=Gtk.Align.CENTER)
        restore.connect("clicked", lambda *_a: self._restore(tomb.launcher_id))
        row.add_suffix(restore)
        return row

    # -- actions -------------------------------------------------------------

    def _accept_add(self, suggestion: Suggestion) -> None:
        if suggestion.target is None:
            return
        now = utc_now()
        project = self.context.db.get_project(suggestion.target.project_id)
        name = project.name if project else "Clockify launcher"
        if suggestion.target.task_id:
            task = self.context.db.get_task(suggestion.target.task_id)
            if task:
                name = f"{name} - {task.name}"
        from clockify_launchers.domain.models import LauncherSource

        launcher = self.context.launcher_service.create(
            account_id=self.context.config.active_account_id or "",
            target=suggestion.target,
            display_name=name,
            source=LauncherSource.AUTOMATIC,
            now=now,
        )
        self.context.db.save_suggestion(
            Suggestion(
                id=suggestion.id,
                type=suggestion.type,
                launcher_id=launcher.id,
                target=suggestion.target,
                explanation=suggestion.explanation,
                evidence=suggestion.evidence,
                state=SuggestionState.EXECUTED,
                created_at=suggestion.created_at,
                accepted_at=now,
                executed_at=now,
            )
        )
        self.window.toast(f"Added {launcher.display_name}.")
        self.window.refresh_all()

    def _dismiss(self, suggestion: Suggestion) -> None:
        now = utc_now()
        if suggestion.target is not None:
            self.context.db.record_dismissal(suggestion.target, now)
        self.context.db.save_suggestion(
            Suggestion(
                id=suggestion.id,
                type=suggestion.type,
                launcher_id=suggestion.launcher_id,
                target=suggestion.target,
                explanation=suggestion.explanation,
                evidence=suggestion.evidence,
                state=SuggestionState.DISMISSED,
                created_at=suggestion.created_at,
                dismissed_at=now,
            )
        )
        self.window.toast("Suggestion dismissed.")
        self.refresh()

    def _confirm_remove(self, suggestion: Suggestion) -> None:
        launcher = self.context.db.get_launcher(suggestion.launcher_id or "")
        if launcher is None:
            self._dismiss(suggestion)
            return
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading=f"Remove {launcher.display_name}?",
            body=f"{suggestion.explanation} It can be restored for 90 days.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog: object, response: str) -> None:
            if response != "remove":
                return
            now = utc_now()
            self.context.launcher_service.delete(launcher, reason=suggestion.explanation)
            self.context.db.save_suggestion(
                Suggestion(
                    id=suggestion.id,
                    type=suggestion.type,
                    launcher_id=suggestion.launcher_id,
                    target=suggestion.target,
                    explanation=suggestion.explanation,
                    evidence=suggestion.evidence,
                    state=SuggestionState.EXECUTED,
                    created_at=suggestion.created_at,
                    accepted_at=now,
                    executed_at=now,
                )
            )
            self.window.toast(f"Removed {launcher.display_name}.")
            self.window.refresh_all()

        dialog.connect("response", on_response)
        dialog.present()

    def _keep_pin(self, suggestion: Suggestion) -> None:
        launcher = self.context.db.get_launcher(suggestion.launcher_id or "")
        if launcher is not None:
            self.context.launcher_service.set_pinned(launcher, True)
        self._dismiss(suggestion)
        self.window.refresh_all()

    def _snooze(self, suggestion: Suggestion) -> None:
        launcher = self.context.db.get_launcher(suggestion.launcher_id or "")
        now = utc_now()
        snooze_days = self.context.config.policy.snooze_days
        if launcher is not None:
            self.context.launcher_service.snooze(launcher, now + timedelta(days=snooze_days))
        self.context.db.save_suggestion(
            Suggestion(
                id=suggestion.id,
                type=suggestion.type,
                launcher_id=suggestion.launcher_id,
                target=suggestion.target,
                explanation=suggestion.explanation,
                evidence=suggestion.evidence,
                state=SuggestionState.SNOOZED,
                created_at=suggestion.created_at,
                snoozed_until=now + timedelta(days=snooze_days),
            )
        )
        self.window.toast(f"Snoozed for {snooze_days} days.")
        self.refresh()

    def _restore(self, launcher_id: str) -> None:
        launcher = self.context.launcher_service.restore(launcher_id)
        if launcher is not None:
            self.window.toast(f"Restored {launcher.display_name}.")
        self.window.refresh_all()
