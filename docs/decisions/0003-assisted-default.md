# ADR 0003: Assisted mode is the recommended default

Status: Accepted

## Context

Three management modes exist: Manual, Assisted, Autopilot.

## Decision

Assisted is the recommended default: automatic high-confidence additions,
never automatic removals — stale launchers become suggestions.

## Consequences

Users get automation value without deletion risk; Autopilot remains an
explicit opt-in with extra safeguards.
