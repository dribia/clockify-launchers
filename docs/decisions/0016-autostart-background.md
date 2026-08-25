# ADR 0016: Background start at login (autostart)

Date: 2026-08-25

## Status

Accepted

## Context

The top-bar timer indicator (ADR 0015) is owned by the GUI process and only
exists while the application runs. The primary usage pattern, however, is
starting timers from generated Ubuntu launchers without ever opening the
application window. After login, the indicator was therefore absent until the
user explicitly opened the app, so a timer started from a launcher tracked
correctly but was invisible in the top bar.

Two options were considered:

1. Autostart the application hidden at login (indicator only, no window).
2. Make `start --launcher` open or spawn the GUI.

Option 2 violates the CLI contract ("start must not open the full GUI on
success", AGENTS.md section 8), adds GTK startup latency to every launcher
click, and introduces spawn races. A hidden-spawn variant of option 2 is
lazy autostart with more failure modes.

## Decision

- Add an XDG autostart entry (`$XDG_CONFIG_HOME/autostart/
  com.dribia.ClockifyLaunchers.desktop`) running `clockify-launchers gui
  --hidden`. The entry contains only fixed strings, is written atomically,
  and carries the `X-Clockify-Launchers-Managed` marker.
- `gui --hidden` creates the main window without presenting it; only the
  top-bar indicator is published. If the indicator cannot register (no
  StatusNotifierWatcher), the existing reachability check presents the
  window instead of running invisibly.
- The behavior is controlled by a `start_in_background` config flag,
  **enabled by default**. Onboarding shows the switch (on) so the user can
  opt out; Preferences can toggle it later. Toggling installs/removes the
  autostart file immediately.
- The hidden flag is consumed on the first activation only: remote
  activations (second `gui` run, indicator "Open") always present the
  window.

This consciously relaxes the "no continuously resident tray process"
non-goal, which ADR 0015 already relaxed for the window-close case. The
resident process is the ordinary GUI process, idle, user-disableable, and
never required for launchers to function.

## Consequences

- The indicator is available from login; launcher clicks update it through
  the existing `refresh-timer` D-Bus nudge.
- One additional idle process per session when enabled.
- Demo mode never touches the real autostart directory (same guard as
  systemd timer management).
