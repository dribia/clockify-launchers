# ADR 0008: systemd user oneshot timer, no resident daemon

Status: Accepted

## Context

Periodic reconciliation needs scheduling without a continuously resident
tray process.

## Decision

Ship `clockify-launchers-sync.service` (oneshot, `sync --background`) and
`clockify-launchers-sync.timer`; manage the interval via a user drop-in and
`systemctl --user` (no shell). A runtime file lock prevents overlap.

## Consequences

Zero idle footprint, journal-friendly logging, mode changes map to
enabling/disabling one timer.
