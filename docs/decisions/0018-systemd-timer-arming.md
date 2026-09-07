# ADR 0018: Robust systemd timer arming for the background sync

Date: 2026-09-07

## Status

Accepted

## Context

Autopilot/Assisted users reported that automatic additions only appeared
after a manual sync. Diagnosis on an affected machine (session up for 9
days):

- The sync timer was "active (elapsed)" with `NextElapseUSecMonotonic =
  infinity` and no `LastTrigger` - **zero armed events**: it would never
  fire again in the session, and the systemd service had not run once
  since boot.
- The shipped timer anchored everything on two events:
  `OnStartupSec=2min` (relative to when the *user manager* started - a
  one-shot, consumed early in the boot) and `OnUnitActiveSec=30min`
  (only armed **after the service has actually activated in the current
  manager instance**).
- The service had `After=graphical-session.target`, which can stall the
  boot-time trigger indefinitely (ordering not yet satisfied), consuming
  the only anchor without activating the service - the
  `OnUnitActiveSec` chain is then stillborn.
- Restarting the timer mid-session (Preferences mode/interval changes
  do) re-arms neither event: `OnStartupSec` is manager-relative and long
  past, `OnUnitActiveSec` has no base. The timer is permanently
  eventless while reporting "active".
- Manual activation of the service revived the chain (next elapse
  correctly armed at +30 min), proving the mechanism.

## Decision

1. **Timer**: add `OnActiveSec=30min` alongside `OnStartupSec=2min` and
   `OnUnitActiveSec=30min`. `OnActiveSec` is relative to the timer's own
   activation, so every enable/restart guarantees a sync within one
   interval even when the `OnUnitActiveSec` chain is broken; the chain
   then continues normally (earliest armed event wins, so the anchor
   never delays syncs).
2. **Service**: drop `After=graphical-session.target`. The sync command
   already handles an unlocked-session/locked-keyring environment by
   recording the result and changing nothing (AGENTS.md section 18), so
   the ordering buys nothing and risks consuming the boot trigger.
3. **Reconcile at startup**: the GUI now converges the timer with the
   management mode at every launch (daemon-reload picks up upgraded
   shipped units, then enable + restart re-arms `OnActiveSec`), next to
   the existing autostart reconcile. A dead or stale timer therefore
   self-heals at the latest on the next app start (which, with login
   autostart, is every login). Preferences mode changes use the same
   one-shot reconcile instead of separate enable + interval calls.
4. AGENTS.md section 18 is updated to match (no session ordering; the
   timer concept shows the `OnActiveSec` anchor).

## Consequences

- A session can no longer end up with an eventless timer: every restart
  re-arms, every app start re-arms, and the service chain anchors itself
  on the first successful activation.
- The first sync after boot may run before the keyring is unlocked; it
  exits silently per the existing background rules and the next anchor
  (chain or `OnActiveSec`) retries.
- `daemon-reload` + `restart` at app startup is idempotent and does not
  delay the next sync (earliest event wins).
