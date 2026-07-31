"""API key storage through the desktop Secret Service (libsecret).

There is no plaintext fallback. When Secret Service is unavailable or
locked, ``SecretUnavailableError`` is raised and callers must preserve all
existing configuration.
"""

from __future__ import annotations

import logging
from typing import Protocol

from clockify_launchers import constants

log = logging.getLogger(__name__)


class SecretUnavailableError(Exception):
    """Secret Service is unavailable or the keyring is locked."""


class SecretStore(Protocol):
    def store_api_key(self, account_id: str, api_origin: str, email: str, api_key: str) -> None: ...
    def get_api_key(self, account_id: str) -> str | None: ...
    def delete_api_key(self, account_id: str) -> None: ...
    def available(self) -> bool: ...


class InMemorySecretStore:
    """Test/demo fake; never used in the installed production path."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self.locked = False

    def store_api_key(self, account_id: str, api_origin: str, email: str, api_key: str) -> None:
        if self.locked:
            raise SecretUnavailableError("keyring locked")
        self._secrets[account_id] = api_key

    def get_api_key(self, account_id: str) -> str | None:
        if self.locked:
            raise SecretUnavailableError("keyring locked")
        return self._secrets.get(account_id)

    def delete_api_key(self, account_id: str) -> None:
        if self.locked:
            raise SecretUnavailableError("keyring locked")
        self._secrets.pop(account_id, None)

    def available(self) -> bool:
        return not self.locked


class LibsecretStore:
    """Production adapter over gi.repository.Secret."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        self._secret = Secret
        self._schema = Secret.Schema.new(
            constants.SECRET_SCHEMA_NAME,
            Secret.SchemaFlags.NONE,
            {
                constants.SECRET_ATTR_APPLICATION: Secret.SchemaAttributeType.STRING,
                constants.SECRET_ATTR_ACCOUNT_ID: Secret.SchemaAttributeType.STRING,
                constants.SECRET_ATTR_API_ORIGIN: Secret.SchemaAttributeType.STRING,
            },
        )

    def _attrs(self, account_id: str, api_origin: str | None = None) -> dict[str, str]:
        attrs = {
            constants.SECRET_ATTR_APPLICATION: constants.APP_ID,
            constants.SECRET_ATTR_ACCOUNT_ID: account_id,
        }
        if api_origin is not None:
            attrs[constants.SECRET_ATTR_API_ORIGIN] = api_origin
        return attrs

    def store_api_key(self, account_id: str, api_origin: str, email: str, api_key: str) -> None:
        from gi.repository import GLib

        label = f"Clockify API key for {email}"
        try:
            ok = self._secret.password_store_sync(
                self._schema,
                self._attrs(account_id, api_origin),
                self._secret.COLLECTION_DEFAULT,
                label,
                api_key,
                None,
            )
        except GLib.Error as exc:
            raise SecretUnavailableError(str(exc)) from exc
        if not ok:
            raise SecretUnavailableError("Secret Service rejected the store request")

    def get_api_key(self, account_id: str) -> str | None:
        from gi.repository import GLib

        try:
            return self._secret.password_lookup_sync(self._schema, self._attrs(account_id), None)
        except GLib.Error as exc:
            raise SecretUnavailableError(str(exc)) from exc

    def delete_api_key(self, account_id: str) -> None:
        from gi.repository import GLib

        try:
            self._secret.password_clear_sync(self._schema, self._attrs(account_id), None)
        except GLib.Error as exc:
            raise SecretUnavailableError(str(exc)) from exc

    def available(self) -> bool:
        from gi.repository import GLib

        try:
            service = self._secret.Service.get_sync(self._secret.ServiceFlags.NONE, None)
            return service is not None
        except GLib.Error:
            return False
