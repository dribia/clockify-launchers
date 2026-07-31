"""Shared fixtures for integration tests: isolated environment + demo data."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from clockify_launchers.demo import fixtures
from clockify_launchers.demo.backend import demo_paths
from clockify_launchers.domain.models import Account
from clockify_launchers.infrastructure.config_store import ConfigStore
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.infrastructure.secret_store import InMemorySecretStore
from clockify_launchers.infrastructure.xdg_paths import XdgPaths
from clockify_launchers.services.icon_service import IconService
from clockify_launchers.services.launcher_service import LauncherService


@dataclass
class Env:
    paths: XdgPaths
    db: Database
    secrets: InMemorySecretStore
    icon_service: IconService
    launcher_service: LauncherService
    config_store: ConfigStore
    account: Account

    def close(self) -> None:
        self.db.close()


def make_account(db: Database) -> Account:
    account = Account(
        id=fixtures.DEMO_ACCOUNT_ID,
        api_base_url="https://api.clockify.me/api",
        clockify_user_id=fixtures.DEMO_USER_ID,
        email=fixtures.DEMO_EMAIL,
        display_name=fixtures.DEMO_NAME,
        active_workspace_id=fixtures.WS_MAIN.id,
        created_at=fixtures.DEMO_NOW,
        last_validated_at=fixtures.DEMO_NOW,
    )
    db.save_account(account)
    return account


def cache_demo_metadata(db: Database) -> None:
    db.cache_workspaces(list(fixtures.WORKSPACES), fixtures.DEMO_NOW)
    db.cache_projects(list(fixtures.PROJECTS), fixtures.DEMO_NOW)
    db.cache_tags(list(fixtures.TAGS), fixtures.DEMO_NOW)
    db.cache_tasks(list(fixtures.TASKS), fixtures.DEMO_NOW)


@pytest.fixture()
def env(tmp_path) -> Env:
    paths = demo_paths(tmp_path)
    paths.ensure_private_dirs()
    db = Database(paths.state_db)
    secrets = InMemorySecretStore()
    icon_service = IconService(paths.icons_dir)
    launcher_service = LauncherService(db, icon_service, paths.applications_dir)
    config_store = ConfigStore(paths.config_file)
    account = make_account(db)
    cache_demo_metadata(db)
    environment = Env(
        paths=paths,
        db=db,
        secrets=secrets,
        icon_service=icon_service,
        launcher_service=launcher_service,
        config_store=config_store,
        account=account,
    )
    yield environment
    environment.close()
