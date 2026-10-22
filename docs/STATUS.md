# Project status

Updated: 2026-10-21

## Completed

- **Phase 0**: repository scaffold, CLI, libadwaita shell, demo backend with 13
  deterministic states, screenshot harness (`make ui-capture`), CI skeleton.
- **Phase 1**: XDG paths, atomic config store, SQLite schema/migrations,
  libsecret adapter + in-memory fake, typed Clockify client with retries,
  redaction, pagination guards; onboarding flow (region, key verify,
  workspace, mode).
- **Phase 2**: domain models and signatures, launcher CRUD, generated SVG
  icons + safe selected-image import, GLib.KeyFile desktop serializer with
  atomic writes and ownership checks, disk reconciliation, external
  modification detection, legacy `clockify-cli in` import (safe parser +
  preview dialog).
- **Phase 3**: `start --launcher` with full stop/switch semantics, ambiguous
  POST read-back reconciliation, partial-switch reporting, notifications,
  current-timer banner, `stop` command.
- **Phase 4**: candidate extraction with recency scoring, Assisted additions
  and removal suggestions, guarded Autopilot removals with tombstones and
  restore, no-deletion-on-uncertainty enforced, systemd user timer management
  with interval drop-ins, sync lock.
- **Phase 5**: all 13 demo states captured at normal + narrow sizes and
  visually reviewed (docs/ui-review.md); 8 AT-SPI smoke flows pass
  (`make ui-test`): launchers list, start via UI, page navigation, editor
  save, accept-add, snooze, remove+restore, onboarding completion.
- **Phase 6**: Debian package builds (`make deb`), lintian passes with
  `--fail-on error` (2 informational warnings), desktop/AppStream validation
  passes, locally signed test APT repository resolves and downloads the
  package by name (`make test-apt-repo`), manpage installed.
- **Top-bar timer indicator** (ADR 0015): a StatusNotifierItem published
  while the app runs shows the currently tracked project (or
  "Not tracking") in Ubuntu's top bar via the default `ubuntu-appindicators`
  extension, with an Open / Stop timer / Quit menu (com.canonical.dbusmenu).
  When the indicator is confirmed visible, closing the window hides to the
  indicator and the app keeps running; Quit exits fully. Without a watcher
  the indicator stays dormant and window close quits as before. Unit tests
  plus a private-bus integration round trip
  (`tests/integration/test_status_notifier_bus.py`).
- **Cap-aware autopilot + self-arming timer** (ADR 0019): reconciliation
  plans removals before additions so a freed automatic slot is reused in
  the same run; cap-blocked candidates are surfaced (sync notes, GUI
  toast, Suggestions "Waiting for a free slot" group) instead of being
  silently dropped. The interval drop-in re-declares the timer anchors
  (systemd's empty `On*Sec=` reset wipes the whole shared spec list, which
  left the timer eventless across reboots), startup reconcile heals legacy
  drop-ins, an unarmed-but-active timer is recorded as a `timer-unarmed`
  activity event, and `doctor` fails on it in Assisted/Autopilot modes.
- **Customizable indicator times**: five per-time toggles (current entry,
  project today/this week, daily/weekly totals) joined with "/" in fixed
  order in the top-bar label; legacy single-toggle configs migrate
  (off = all off, on = entry + daily, the default).

`make verify` passes from a clean checkout: lint, typecheck (ty, 0 errors),
222 unit/contract/integration tests, data validation, UI capture, 8 AT-SPI
tests, and the Debian build.

## Current limitations

- `make smoke-install` requires sudo and has not been executed in CI yet.
- Ubuntu 26.04 has not been exercised (only 24.04 available in the dev
  environment); the CI skeleton targets 24.04.
- Live read-only Clockify tests exist (tests/live) but are opt-in and have
  not been run against a real account yet.
- Custom-field editing is out of scope; the error class is detected and
  surfaced per AGENTS.md 13.6.
- Gettext extraction is prepared (single-language English strings) but no
  translation catalog is generated yet.

## Next concrete tasks

1. Run `make smoke-install` on a machine with sudo (and in CI with a
   container) for 24.04 and 26.04.
2. Run the opt-in live tests once with a real key:
   `CLOCKIFY_LIVE_TESTS=1 CLOCKIFY_API_KEY=... .venv/bin/python -m pytest tests/live -m live`.
3. Add tolerant image-difference baselines for the most stable fixture
   screens.
4. Wire gettext catalog generation.
