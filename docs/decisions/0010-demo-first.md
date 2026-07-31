# ADR 0010: Deterministic demo data and screenshot tooling before substantial UI work

Status: Accepted

## Context

A coding agent must inspect the interface it builds without a live Clockify
account.

## Decision

Build the demo backend (`demo/`), 13 fixture states, and the capture harness
(`scripts/ui-capture.sh`) in Phase 0, before substantial UI development.

## Consequences

Every UI change can be captured, inspected, and regression-checked
deterministically; UI completion claims require visual evidence.
