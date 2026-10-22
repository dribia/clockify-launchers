# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Customizable times in the top-bar indicator: five individual toggles
  (current entry time, project total today, project total this week, daily
  total, weekly total) replace the single "Show times" switch. Enabled
  times are joined with "/" in that fixed order, without labels, e.g.
  `Organic (0:05 / 5:32)`; all-off hides times entirely (the old toggle
  off). Weeks start on Monday, local time. Existing configs migrate:
  the old switch off becomes all-off, on becomes the previous
  entry-time + daily-total pair (also the default).

### Fixed

- Automatic additions are no longer silently blocked by a full
  automatic-launcher cap: a sync run now plans removals first, so a slot
  freed by a stale-launcher removal is usable by additions in the same
  run (previously the freed slot waited for a next sync that might never
  come). When eligible candidates remain unadded because the cap is full,
  the sync records the reason, the GUI toast and `clockify-launchers sync`
  report it, and the Suggestions page lists the waiting candidates under
  "Waiting for a free slot".
- The background sync timer no longer dies after a reboot: the interval
  drop-in written by the app used an empty `OnUnitActiveSec=` reset,
  which in systemd clears the shared spec list of ALL `On*Sec` directives
  - wiping the ADR 0018 re-arm anchors from the shipped unit and leaving
  the timer permanently eventless ("active" but never firing) until the
  app was started. The drop-in now re-declares the anchors alongside the
  custom interval, startup reconcile rewrites (and thereby heals) legacy
  broken drop-ins, the app records a `timer-unarmed` activity event if
  the timer is active but not armed, and `doctor` fails on an
  active-but-unarmed timer in Assisted/Autopilot modes instead of
  reporting it healthy (ADR 0019).

## [0.4.3] - 2026-09-07

### Fixed

- Background sync (Assisted/Autopilot) no longer silently stops running:
  the systemd timer could become permanently eventless ("active" but with
  no next elapse) when its boot-time trigger was consumed without the
  service activating - automatic additions then only appeared after
  manual syncs or app restarts. The timer now carries an `OnActiveSec`
  anchor so every enable/restart re-arms it within one interval, the
  service no longer orders after `graphical-session.target` (a stalled
  ordering could consume the boot trigger), and the app reconciles the
  timer (reload, enable, restart) at every startup (ADR 0018).

## [0.4.2] - 2026-08-27

### Fixed

- The indicator's day total no longer reads 0:00 when time was tracked.
  Clockify interprets the time-entry query's `start`/`end` parameters in
  the user's profile timezone (despite the documented UTC format), which
  silently excluded up to a UTC-offset's worth of recent entries - the
  whole day for the indicator, and the most recent hours from sync's
  activity lookback. Time-entry queries now pad the requested window by a
  day on each side and apply the exact bounds client-side, making results
  correct regardless of the server's timezone interpretation.

## [0.4.1] - 2026-08-27

### Changed

- Indicator label layout: times now render inside one trailing
  parenthesis - while tracking `▶ Agenda (0:32 / 5:31)` (running entry /
  total today), when idle `Not tracking (5:31)` - instead of prefixing
  the day total.

### Fixed

- The top-bar indicator label no longer disappears permanently. The GNOME
  Shell appindicator extension drops value-equal label updates and can
  silently lose its label actor, so the plain periodic re-emit added in
  0.4.0 never reached the widget. The periodic refresh now alternates an
  invisible zero-width suffix in the emitted label ("heartbeat"), which
  always passes the extension's equality check and forces a re-render,
  self-healing the top bar within one 30-second tick (ADR 0017). The
  refresh also no longer fires tooltip/menu signals every tick.

## [0.4.0] - 2026-08-26

### Added

- The top-bar indicator can show tracked times: the total tracked today
  and the running entry's elapsed time, e.g. `5:32 Organic (0:05)`.
  Enabled by default; a switch in Preferences (Background group) turns it
  off.

### Fixed

- The top-bar indicator label ("Not tracking" / the tracked project) now
  appears immediately after the indicator registers. Previously the label
  was only pushed on the first change, so a freshly started app showed
  only the icon.
- The indicator label also self-heals: it is re-emitted on registration
  (covering screen lock/unlock and GNOME Shell restarts, which previously
  could leave only the icon in the top bar) and unconditionally on every
  periodic refresh.

### Fixed

- The "start in background at login" preference now takes effect on
  existing installations: the GUI reconciles the autostart entry with the
  configured preference at startup, so upgrades that enabled the default
  (or an externally removed entry) no longer require toggling the switch
  in Preferences.

## [0.3.0] - 2026-08-25

### Fixed

- Started time entries now respect the Clockify project's "billable by
  default" setting. Previously the `billable` flag was omitted from the
  start request, so the Clockify API defaulted every entry to
  non-billable regardless of the project configuration.

### Added

- Background start at login (enabled by default, ADR 0016): an XDG
  autostart entry launches `clockify-launchers gui --hidden`, so the
  top-bar timer indicator is available from login even when timers are
  only ever started from Ubuntu launchers. Onboarding offers the switch
  (on by default) and Preferences can toggle it later; disabling removes
  the autostart entry immediately.
- New `gui --hidden` flag: starts the application in the background
  (indicator only). If the top-bar indicator cannot register, the window
  presents itself instead of running invisibly.
- Launcher editor: the Project and Task dropdowns support type-to-search,
  making workspaces with many projects manageable.
- Multiple launchers per target: launchers sharing the same project, task,
  and tags may now coexist as long as their fixed descriptions differ; only
  a full target+description match is blocked as a duplicate. The editor
  shows an informational hint (instead of a hard block) when another
  launcher shares the target. Automatic (sync) additions still deduplicate
  by signature and never create such variants.

## [0.2.1] - 2026-08-24

### Fixed

- The current-timer state (banner and top-bar indicator) now refreshes
  immediately when the window is opened, re-presented from the background
  indicator, or re-activated - not only on the 30-second poll.
- `clockify-launchers start`/`stop` (what desktop launchers execute) now ping
  a running GUI over D-Bus so the top-bar indicator updates instantly after
  using a launcher instead of waiting for the next poll.
- Stop timer: a lost/timed-out stop response is now reconciled by reading back
  the in-progress entry (success if the timer stopped, explicit ambiguous
  result otherwise) instead of always reporting a failure, mirroring the
  existing ambiguous-start handling (AGENTS.md 13.4).

## [0.2.0] - 2026-08-24

### Added

- Top-bar timer indicator (StatusNotifierItem + minimal com.canonical.dbusmenu)
  showing the currently tracked project via the Ubuntu AppIndicators extension,
  with an Open / Stop timer / Quit menu, automatic re-registration across
  screen lock/unlock and shell restarts, and hide-to-indicator on window close
  while the indicator is visible (ADR 0015).

## [0.1.0] - 2026-08-11

### Added

- First-run onboarding: API region selection, API key validation, workspace
  selection, and management-mode choice.
- Secure API key storage in GNOME Keyring via libsecret (no plaintext fallback).
- Manual launcher creation from project, optional task, tags, and optional
  fixed description, with custom name and generated or selected icon.
- Generated freedesktop `.desktop` entries under `$XDG_DATA_HOME/applications`
  with ownership markers and atomic writes.
- `clockify-launchers start --launcher UUID` timer start/switch with same-target
  no-op detection, ambiguous-outcome reconciliation, and desktop notifications.
- `stop`, `sync` (with `--background`), `doctor`, `reset`, `demo`, and `gui`
  CLI commands with documented exit codes.
- Manual, Assisted, and Autopilot management modes; pinning, suggestions,
  snooze, tombstones, and restore.
- Read-only periodic reconciliation via systemd user service and timer, with
  interval drop-in management and a runtime file lock.
- Legacy `clockify-cli in` launcher import with safe read-only parsing.
- SQLite state store with ordered migrations, activity log, and sync run records.
- Deterministic demo backend with 13 UI states and a screenshot capture harness.
- Debian packaging metadata (`debian/`), Makefile verification pipeline,
  and locally signed test APT repository script.
