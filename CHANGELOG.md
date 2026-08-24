# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

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
- Top-bar timer indicator (StatusNotifierItem + minimal com.canonical.dbusmenu)
  showing the currently tracked project via the Ubuntu AppIndicators extension,
  with an Open / Stop timer / Quit menu, automatic re-registration across
  screen lock/unlock and shell restarts, and hide-to-indicator on window close
  while the indicator is visible (ADR 0015).
