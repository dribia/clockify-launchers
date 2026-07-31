# ADR 0007: GNOME Keyring/libsecret with no plaintext fallback

Status: Accepted

## Context

The API key is a secret and must survive across sessions without ever being
written to plaintext storage.

## Decision

Store the key only via libsecret with a fixed schema
(`com.dribia.ClockifyLaunchers.ApiKey`). When Secret Service is unavailable
or locked, explain and preserve state — never fall back to a file.

## Consequences

Background sync degrades gracefully to a credential-unavailable no-op;
secrets never appear in config, DB, logs, or desktop files.
