# 15. Top-bar timer indicator via StatusNotifierItem

Date: 2026-08-24

## Status

Accepted

## Context

The user wants an Ubuntu top-bar widget that shows the currently tracked
Clockify project (or an idle indicator) while the application is open.
GNOME Shell does not let applications draw in the top bar directly; the
realistic mechanisms are (a) the StatusNotifierItem/AppIndicator D-Bus
protocol, rendered by the `ubuntu-appindicators` shell extension that
Ubuntu ships and enables by default, or (b) a custom GNOME Shell
extension in GJS.

AGENTS.md lists "a continuously resident tray process" as a non-goal.

## Decision

Publish a minimal StatusNotifierItem directly over Gio D-Bus
(`infrastructure/status_notifier.py`), owned by the main-window process
and visible only while the main window exists. No extra daemon, no new
runtime dependency (no libayatana binding; the protocol is small enough
to implement with `Gio.DBusConnection`). The current project is shown
through the Ayatana label extension (`XAyatanaLabel`), which Ubuntu's
extension renders as text next to the icon. Left-click activates
(presents) the main window.

Registration with `org.kde.StatusNotifierWatcher` is asynchronous and
best-effort: when no watcher exists (plain GNOME without the extension,
headless test sessions) the item stays dormant and everything else works
unchanged.

## Consequences

- Works on stock Ubuntu 24.04/26.04 with zero configuration.
- Non-Ubuntu GNOME users without an AppIndicator extension simply do not
  see the indicator; no error surfaces.
- Revision (2026-08-24, owner request): when — and only when — the
  StatusNotifierWatcher has confirmed the item is visible in the top bar,
  closing the main window hides it and the process keeps running in the
  background behind the indicator; the menu gains a Quit entry that fully
  exits. When the indicator is not registered (no watcher: plain GNOME,
  headless, lock-screen edge cases) closing the window quits as before, so
  the app can never become an invisible unreachable background process.
  This consciously amends the "no continuously resident tray process"
  non-goal in AGENTS.md §4.3 for the case where the user has an indicator
  and closes the window; there is still no separate daemon and no
  autostart — the background state only ever begins from an explicit GUI
  launch.
- No menu is exported (`ItemIsMenu=false`) was the original plan, but
  Ubuntu's `ubuntu-appindicators` extension treats the `Menu` property as
  required and drops items whose `Menu` lookup fails with InvalidArgs.
  A minimal `com.canonical.dbusmenu` is therefore exported at
  `/StatusNotifierItem/Menu` with "Open" and "Stop timer" entries; the
  Stop entry is enabled only while a timer is tracked.
- Known quirk (reviewed with the owner, 2026-08-24, decided to keep):
  GNOME Shell's dock "Quit" is implemented as a close request to each
  window - indistinguishable from the window's close button - so with the
  indicator visible it hides to the background instead of exiting, like
  other tray-style applications (Slack, Steam). Actually quitting requires
  the indicator menu's Quit entry. Alternatives (quit-when-idle, a
  preferences toggle) were considered and declined to keep behavior
  predictable.
