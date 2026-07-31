"""AccountService.connect, secret store locking, and config recovery."""

from __future__ import annotations

import pytest

from clockify_launchers.demo import fixtures
from clockify_launchers.infrastructure.config_store import AppConfig
from clockify_launchers.infrastructure.secret_store import SecretUnavailableError
from clockify_launchers.services.account_service import AccountService, ValidationResult

BASE_URL = "https://api.clockify.me/api"


def validation() -> ValidationResult:
    return ValidationResult(
        user_id=fixtures.DEMO_USER_ID,
        email=fixtures.DEMO_EMAIL,
        display_name=fixtures.DEMO_NAME,
        default_workspace_id=fixtures.WS_MAIN.id,
        workspaces=tuple(fixtures.WORKSPACES),
    )


def test_connect_persists_everything(env):
    service = AccountService(env.config_store, env.db, env.secrets)
    account = service.connect(BASE_URL, "secret-key-123", validation(), fixtures.WS_MAIN.id)

    # Key stored only in the secret store, keyed by the account id.
    assert env.secrets.get_api_key(account.id) == "secret-key-123"
    # Config updated.
    config = env.config_store.load()
    assert config.active_account_id == account.id
    assert config.api_base_url == BASE_URL
    assert config.clockify_user_id == fixtures.DEMO_USER_ID
    assert config.email == fixtures.DEMO_EMAIL
    assert config.active_workspace_id == fixtures.WS_MAIN.id
    # The secret never appears in the config file.
    assert "secret-key-123" not in env.paths.config_file.read_text()
    # Account row saved; workspaces cached.
    stored = env.db.get_account(account.id)
    assert stored is not None and stored.email == fixtures.DEMO_EMAIL
    rows = env.db.connection.execute("SELECT id FROM workspaces").fetchall()
    assert {r["id"] for r in rows} == {fixtures.WS_MAIN.id, fixtures.WS_SIDE.id}


def test_connect_with_locked_keyring_changes_nothing(env):
    env.config_store.save(AppConfig())
    before = env.paths.config_file.read_text()
    env.secrets.locked = True
    service = AccountService(env.config_store, env.db, env.secrets)
    with pytest.raises(SecretUnavailableError):
        service.connect(BASE_URL, "secret-key-123", validation(), fixtures.WS_MAIN.id)
    assert env.paths.config_file.read_text() == before
    assert env.config_store.load().active_account_id is None


def test_malformed_config_recovers_with_defaults(env):
    env.paths.config_file.write_text("{ this is not json !!!")
    config = env.config_store.load()
    assert isinstance(config, AppConfig)
    assert config.active_account_id is None
    broken = list(env.paths.config_dir.glob("config.json.broken.*"))
    assert len(broken) == 1
    assert broken[0].read_text() == "{ this is not json !!!"
    # The store keeps working afterwards.
    env.config_store.save(config)
    assert env.config_store.load().schema_version == config.schema_version
