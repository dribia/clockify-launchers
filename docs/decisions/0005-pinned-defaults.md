# ADR 0005: Manual and imported launchers are pinned by default

Status: Accepted

## Context

Removal automation must never surprise users about launchers they created
or migrated deliberately.

## Decision

Manually created and imported launchers default to pinned; only automatic
launchers default to managed (unpinned). Restored launchers are pinned
unless restored as managed.

## Consequences

Pinning keeps user-authored launchers outside removal automation while still
allowing metadata refresh and health checks.
