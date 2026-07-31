# ADR 0001: Direct Clockify REST calls, no runtime dependency on clockify-cli

Status: Accepted

## Context

Timers can be started either by shelling out to `clockify-cli` or by calling
the Clockify v1 REST API directly.

## Decision

Use a typed in-process HTTP client (`infrastructure/clockify_api.py`) with
`httpx`. `clockify-cli` is only relevant as a legacy import source.

## Consequences

No shell invocation, centralized redaction and error mapping, no dependency
on an external binary's version or config; we own retry/pagination behavior.
