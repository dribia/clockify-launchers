# ADR 0006: No automatic deletion after an incomplete or uncertain sync

Status: Accepted

## Context

Network errors, partial API results, locked keyrings, or parse errors could
otherwise cascade into launcher deletion.

## Decision

Every reconciliation run carries a `safe_to_remove` flag that any
uncertainty clears; Autopilot removals additionally require pin/snooze/grace
and staleness checks to pass and always leave tombstones.

## Consequences

Removal is conservative and restorable; the failure mode of a bad sync is
"nothing changed," never data loss.
