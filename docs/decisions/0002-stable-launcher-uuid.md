# ADR 0002: Desktop entries call a stable local launcher UUID

Status: Accepted

## Context

Generated launchers need an `Exec` line that survives backend changes and
never carries secrets or Clockify IDs.

## Decision

`Exec=/usr/bin/clockify-launchers start --launcher <UUID>`; all target data
lives in application state keyed by the UUID.

## Consequences

Credentials stay out of desktop files, local usage can be recorded,
notifications work, and backends can change without rewriting launchers.
