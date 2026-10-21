# ADR 0019: Interval drop-ins must re-declare timer anchors

Date: 2026-10-20

## Status

Accepted

## Context

ADR 0018 made the sync timer self-rearming (`OnStartupSec` +
`OnActiveSec` + `OnUnitActiveSec`) and the shipped 0.4.3 unit carries
those anchors. Nevertheless an Autopilot user's machine was observed with
the ADR 0018 failure signature again: timer `active (elapsed)`,
`NextElapseUSecMonotonic = infinity`, and **zero service activations for
~26 days across three reboots** - background sync only ever ran at app
startup or on manual clicks.

Reproduction with scratch user timers on the affected machine
(Ubuntu 24.04, systemd 255) isolated the cause:

- Scratch timer with the shipped `[Timer]` section and **no drop-in**:
  all three `On*Sec` specs armed (`SubState=waiting`, finite next
  elapse).
- The same scratch timer **plus the app's interval drop-in**
  (`OnUnitActiveSec=` reset line followed by `OnUnitActiveSec=45min`):
  only the single `OnUnitActiveSec` spec remained, `next_elapse=0`,
  `SubState=elapsed` - the exact dead state on the user's machine.

Root cause: systemd parses every `On*Sec` timer directive into **one
shared spec list**. An empty assignment (`OnUnitActiveSec=`) - the
documented way to reset one list setting - resets that *shared* list,
silently discarding every `On*Sec` spec parsed so far from the shipped
unit, including the ADR 0018 re-arm anchors. The single re-added
`OnUnitActiveSec` can never elapse until the service activates, which
never happens after a reboot because the anchors that would fire it are
gone. `doctor` missed it because it only checked `is-active`.

## Decision

1. **The interval drop-in re-declares the anchors.**
   `write_interval_dropin` now renders:
   `OnUnitActiveSec=` (reset), then `OnStartupSec=2min`,
   `OnActiveSec={interval}min`, `OnUnitActiveSec={interval}min`.
   The final spec set is therefore always the shipped anchors plus the
   user's interval, whatever systemd's reset semantics.
2. **The anchor value lives in `constants.TIMER_ON_STARTUP_MINUTES`**,
   and a test cross-checks the shipped unit file, the drop-in output, and
   the constants so they cannot drift apart.
3. **Startup reconcile heals existing installs**: it rewrites the drop-in
   at every app start (as before), so the first launch of a fixed build
   replaces any broken legacy drop-in, then daemon-reload + restart
   re-arms the timer.
4. **The application records a `timer-unarmed` activity event** when the
   timer is active but has no armed elapse after reconcile, so the state
   is visible instead of silent.
5. **`doctor` detects the dead timer**: a new
   `SystemdManager.timer_armed()` reads
   `NextElapseUSecRealtime`/`NextElapseUSecMonotonic`; in
   Assisted/Autopilot modes an active-but-unarmed timer is a hard doctor
   failure (exit code). In Manual mode the check merely verifies the
   timer is disabled and stays informational.

## Consequences

- `OnActiveSec` now follows the user's interval (it matched the shipped
  30min default before), so a restart guarantees a sync within one
  configured interval.
- A future systemd that scopes the reset to the named directive only
  would leave duplicate identical specs; systemd coalesces simultaneous
  elapses, so this is harmless.
- Interval drop-ins are rewritten by the app at every startup, so
  upgraded anchor definitions always take effect without manual cleanup.
