# ADR 0017: Indicator label resilience (heartbeat with alternating wire label)

Date: 2026-08-27

## Status

Accepted

## Context

Users reported the top-bar label ("Not tracking" / the tracked project)
disappearing, leaving only the icon, while the application side was
demonstrably healthy (item registered, `XAyatanaLabel` property correct on
the bus). Two earlier patches (emit the label on registration; re-emit the
same label on every periodic refresh) reduced but did not eliminate the
problem.

Reading the installed `ubuntu-appindicators@ubuntu.com` extension source
(GNOME Shell 46) explains the full failure chain:

1. **The label property is invisible to property reads.** The extension's
   `interfaces.js` StatusNotifierItem XML does not declare
   `XAyatanaLabel`. GDBus proxies drop undeclared properties from
   `GetAll`, so the extension can only learn the label from the
   `XAyatanaNewLabel` signal payload, never from (re)reading properties.
2. **Value-equal signals are swallowed.** `appIndicator.js`
   `_queuePropertyUpdate` returns early when the signalled value equals the
   extension's cached value, without notifying the widget. Re-emitting an
   unchanged label therefore never reaches the rendering code.
3. **The widget can silently lose its label actor.** The extension's own
   `indicatorStatusIcon.js` re-adds the label bin with the comment
   `// FIXME: why is it suddenly necessary?` - the shell sometimes drops
   the label actor from the indicator box. When that happens while the
   extension's cache still holds the current value, points 1 and 2 mean
   nothing ever re-triggers `_updateLabel`: the label is gone until the
   value genuinely changes. The icon is a separate actor and survives,
   matching the observed symptom exactly.

## Decision

- Keep the registration-time label emit (covers fresh registrations and
  watcher restarts, where the extension state is empty).
- Replace the "re-emit the same label" periodic refresh with a
  **heartbeat that alternates the wire label**: on each periodic refresh
  the label sent over D-Bus toggles a trailing zero-width space (U+200B).
  The value always differs from the extension's cache, so the update
  passes the equality check and forces `_updateLabel`, which re-adds a
  dropped label actor. The suffix is invisible; the top bar text never
  visibly changes.
- The heartbeat emits **only** `XAyatanaNewLabel`. The previous refresh
  also fired `NewToolTip` and menu `LayoutUpdated` every 30 seconds,
  causing needless extension round-trips (`Get` calls, menu layout
  fetches); tooltip/menu signals are now only sent on real label changes.
- The exported `XAyatanaLabel` property and the emitted signal always
  agree (both use the wire label), so any property read the extension may
  do stays consistent. The public `label` accessor used by application
  logic never carries the suffix.

## Consequences

- The top bar self-heals within one refresh tick (30 s) after any
  extension-side label loss, regardless of its cause.
- One invisible character alternates in the exported label value; tests
  compare visible labels via the suffix-free accessor.
- If the upstream extension ever declares `XAyatanaLabel` or removes the
  equality check, the heartbeat remains harmless.
