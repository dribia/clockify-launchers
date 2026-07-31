"""Desktop notifications through Gio (works from both CLI and GUI)."""

from __future__ import annotations

import logging
from typing import Protocol

from clockify_launchers import constants
from clockify_launchers.infrastructure.config_store import NotificationPrefs

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, title: str, body: str, urgent: bool = False) -> None: ...


class NullNotifier:
    def notify(self, title: str, body: str, urgent: bool = False) -> None:
        log.info("notification suppressed: %s - %s", title, body)


class RecordingNotifier:
    """Test fake."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bool]] = []

    def notify(self, title: str, body: str, urgent: bool = False) -> None:
        self.sent.append((title, body, urgent))


class GioNotifier:
    """Sends notifications via a transient Gio.Application registration."""

    def notify(self, title: str, body: str, urgent: bool = False) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            app = Gio.Application.get_default()
            owns_app = app is None
            if owns_app:
                app = Gio.Application.new(
                    constants.APP_ID + ".Notify", Gio.ApplicationFlags.NON_UNIQUE
                )
                app.register(None)
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            if urgent:
                notification.set_priority(Gio.NotificationPriority.URGENT)
            app.send_notification(None, notification)
        except Exception as exc:
            log.warning("could not send notification: %s", exc)


class NotificationService:
    def __init__(self, notifier: Notifier, prefs: NotificationPrefs) -> None:
        self._notifier = notifier
        self._prefs = prefs

    def timer_success(self, message: str) -> None:
        if self._prefs.timer_success:
            self._notifier.notify(constants.APP_NAME, message)

    def timer_noop(self, message: str) -> None:
        if self._prefs.timer_noop:
            self._notifier.notify(constants.APP_NAME, message)

    def timer_failure(self, message: str) -> None:
        if self._prefs.timer_failure:
            self._notifier.notify(constants.APP_NAME, message, urgent=True)

    def background_summary(self, message: str) -> None:
        if self._prefs.background_additions:
            self._notifier.notify(constants.APP_NAME, message)
