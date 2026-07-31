"""Account validation and API-key handling."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from clockify_launchers.domain.models import Account, Workspace, new_id, utc_now
from clockify_launchers.infrastructure.clockify_api import (
    ClockifyClient,
    ClockifyError,
    normalize_base_url,
)
from clockify_launchers.infrastructure.config_store import AppConfig, ConfigStore
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.infrastructure.secret_store import SecretStore

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    user_id: str
    email: str
    display_name: str
    default_workspace_id: str | None
    workspaces: tuple[Workspace, ...]


class AccountService:
    def __init__(
        self,
        config_store: ConfigStore,
        db: Database,
        secret_store: SecretStore,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config_store = config_store
        self._db = db
        self._secrets = secret_store
        self._transport = transport

    def validate_key(self, base_url: str, api_key: str) -> ValidationResult:
        """Validate an API key without persisting anything."""
        base = normalize_base_url(base_url, allow_http=self._transport is not None)
        with ClockifyClient(base, api_key, transport=self._transport) as client:
            user = client.get_current_user()
            workspaces = client.get_workspaces()
        return ValidationResult(
            user_id=str(user["id"]),
            email=str(user.get("email") or ""),
            display_name=str(user.get("name") or user.get("email") or "Clockify user"),
            default_workspace_id=(user.get("activeWorkspace") or user.get("defaultWorkspace"))
            or None,
            workspaces=tuple(workspaces),
        )

    def connect(
        self,
        base_url: str,
        api_key: str,
        validation: ValidationResult,
        workspace_id: str,
    ) -> Account:
        """Persist a validated account: key to keyring, metadata to config/db."""
        base = normalize_base_url(base_url, allow_http=self._transport is not None)
        config = self._config_store.load()
        account_id = config.active_account_id or new_id()
        origin = base.split("/api")[0]
        # Store the secret first: if the keyring fails, nothing else changes.
        self._secrets.store_api_key(account_id, origin, validation.email, api_key)
        now = utc_now()
        account = Account(
            id=account_id,
            api_base_url=base,
            clockify_user_id=validation.user_id,
            email=validation.email,
            display_name=validation.display_name,
            active_workspace_id=workspace_id,
            created_at=now,
            last_validated_at=now,
        )
        self._db.save_account(account)
        self._db.cache_workspaces(list(validation.workspaces), now)
        config.active_account_id = account_id
        config.api_base_url = base
        config.clockify_user_id = validation.user_id
        config.email = validation.email
        config.active_workspace_id = workspace_id
        self._config_store.save(config)
        return account

    def get_client(self, config: AppConfig | None = None) -> ClockifyClient:
        """Build an authenticated client for the active account.

        Raises ClockifyError subclasses or SecretUnavailableError.
        """
        config = config or self._config_store.load()
        if not config.active_account_id:
            raise ClockifyError("No Clockify account is configured yet.")
        api_key = self._secrets.get_api_key(config.active_account_id)
        if not api_key:
            raise ClockifyError("The Clockify API key is not available in the keyring.")
        return ClockifyClient(config.api_base_url, api_key, transport=self._transport)
