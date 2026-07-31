"""Composition root: builds the service graph for CLI and GUI entry points."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from clockify_launchers import constants
from clockify_launchers.infrastructure.config_store import AppConfig, ConfigStore
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.infrastructure.secret_store import (
    InMemorySecretStore,
    LibsecretStore,
    SecretStore,
)
from clockify_launchers.infrastructure.systemd import SystemdManager
from clockify_launchers.infrastructure.xdg_paths import XdgPaths, resolve_paths
from clockify_launchers.services.account_service import AccountService
from clockify_launchers.services.icon_service import IconService
from clockify_launchers.services.launcher_service import LauncherService
from clockify_launchers.services.notification_service import (
    GioNotifier,
    NotificationService,
    Notifier,
    NullNotifier,
)

log = logging.getLogger(__name__)


def is_demo_mode() -> bool:
    return os.environ.get(constants.DEMO_ENV_VAR, "") == "1"


@dataclass(slots=True)
class AppContext:
    paths: XdgPaths
    config_store: ConfigStore
    db: Database
    secrets: SecretStore
    icon_service: IconService
    launcher_service: LauncherService
    account_service: AccountService
    systemd: SystemdManager
    notifier: Notifier
    demo: bool = False
    _config_cache: AppConfig | None = field(default=None, repr=False)

    @property
    def config(self) -> AppConfig:
        if self._config_cache is None:
            self._config_cache = self.config_store.load()
        return self._config_cache

    def save_config(self, config: AppConfig) -> None:
        self.config_store.save(config)
        self._config_cache = config

    def notifications(self) -> NotificationService:
        return NotificationService(self.notifier, self.config.notifications)

    def close(self) -> None:
        self.db.close()


def build_context(
    exec_path: str | None = None,
    with_notifications: bool = True,
) -> AppContext:
    if is_demo_mode():
        from clockify_launchers.demo.backend import build_demo_context

        state = os.environ.get(constants.DEMO_STATE_ENV_VAR, "launchers-populated")
        return build_demo_context(state)

    paths = resolve_paths()
    paths.ensure_private_dirs()
    config_store = ConfigStore(paths.config_file)
    db = Database(paths.state_db)
    secrets: SecretStore
    try:
        secrets = LibsecretStore()
    except Exception as exc:
        log.warning("libsecret unavailable: %s", exc)
        secrets = InMemorySecretStore()
    icon_service = IconService(paths.icons_dir)
    launcher_service = LauncherService(
        db, icon_service, paths.applications_dir, exec_path=exec_path
    )
    account_service = AccountService(config_store, db, secrets)
    systemd = SystemdManager(paths.systemd_user_dir)
    notifier: Notifier = GioNotifier() if with_notifications else NullNotifier()
    return AppContext(
        paths=paths,
        config_store=config_store,
        db=db,
        secrets=secrets,
        icon_service=icon_service,
        launcher_service=launcher_service,
        account_service=account_service,
        systemd=systemd,
        notifier=notifier,
    )
