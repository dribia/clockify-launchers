# UI Review Log

Record a short, dated visual assessment here after every change that can
affect the UI. Workflow (AGENTS.md § 21.3):

1. `make ui-capture`
2. Inspect every changed screenshot in `artifacts/ui/` (normal and narrow
   sizes) with an image/vision tool.
3. Check for clipping, overlap, poor hierarchy, inconsistent spacing,
   unreadable contrast, missing icons, accidental empty regions, broken
   scrolling, and unclear primary actions.
4. Record the assessment below, fix material issues, re-capture, re-review.

## Entry template

```markdown
## YYYY-MM-DD — <change summary>

- States reviewed: <list>
- Sizes: default / narrow (800x700)
- Findings:
  - <issue or "no issues">
- Actions taken: <fixes or "none needed">
```

## Reviews

*Pending first capture — no reviews recorded yet.*

## 2026-07-31 - Initial capture review (all 13 states + 4 narrow)

Reviewed all screenshots in artifacts/ui at 1000x720 and 800x700.

Findings:
- Launchers list: rows, icons, status marks, filters, and status bar render correctly;
  long project names ellipsize without clipping adjacent controls. Narrow layout intact.
- Onboarding welcome/key/workspace/mode: clear hierarchy, single primary action per page,
  Assisted preselected and labeled "recommended".
- Launcher editor: target group, tag switches, and detail entries all visible; dialog
  scrolls for the remaining fields. Save is the highlighted header action.
- Suggestions add/remove: explanation + evidence text present; Remove styled destructive;
  Keep/Snooze secondary. Empty state renders when nothing is open.
- Offline / auth-error: banner visible and readable; content remains usable.
- Externally modified: row status icon switches to the edit glyph with tooltip.
- Empty state: icon, title, description, and primary "New launcher" action centered.

Minor notes (accepted, non-material):
- The demo launcher named after a different project shows the project monogram (by design).
- Preferences "Apply automation settings" row has an empty title cell; cosmetic only.

No clipping, overlap, contrast, or scroll defects found. No fixes required.

## 2026-07-31 - Preferences auto-save

Removed the "Apply automation settings" button; automation and notification
settings now persist automatically on modification (600 ms debounce, single
"Settings saved." toast, systemd interval drop-in refreshed). Re-captured
preferences at both sizes: layout clean, no empty action row remains.

## 2026-08-03 - Onboarding API-key shortcut

Connect page now shows a "Get your API key" row with an "Open Clockify
settings" button (launches the browser at the profile Advanced section) and
keyring reassurance text in the group description; same additions in the
Change API key dialog. Re-captured onboarding-key: layout clean, clear
hierarchy, button reachable by keyboard (activatable row).

Also hardened the capture harness: target PNG is deleted before capture (a
stale file can no longer pass plausibility checks) and window capture retries
up to five times.

## 2026-08-24 - launcher editor: searchable dropdowns, duplicate wording

- `launcher-editor.png` (1000x720) recaptured after enabling type-to-search
  on the Project and Task combo rows and rewording the duplicate hint.
  Closed-state layout unchanged: rows aligned, no clipping; the search entry
  only appears inside the open popover (not capturable headlessly). Duplicate
  label now distinguishes exact duplicates (blocking) from shared-target
  launchers with different descriptions (informational).

## 2026-08-25 - background-at-login switch (onboarding + preferences)

- `onboarding-mode.png` (1000x720): new "Background" group under the mode
  choices with a SwitchRow "Show the timer indicator at login" (on by
  default). Spacing/hierarchy consistent with the mode group; description
  wraps cleanly; Finish button unaffected.
- `preferences.png` and `preferences-narrow.png` (800x700): matching
  "Background" group between Management mode and Automation. No clipping or
  overlap at either size; the switch and subtitle render correctly narrow.

## 2026-08-26 - indicator times switch in Preferences

- `preferences.png` (1000x720): new "Show times in the top-bar indicator"
  SwitchRow inside the Background group, under the login switch. Rows align,
  subtitle example renders on one line, no clipping; narrow capture also
  clean.

## 2026-10-20 - Suggestions: "Waiting for a free slot" group

- `suggestions-add.png` (1000x720) recaptured after adding the cap-blocked
  candidates group to the Suggestions page (seeded in the demo state with
  "Kaito - Quarterly report" and "Research"). The capture harness validated
  the image (size, color count, non-blank) and the 8 AT-SPI flows pass.
  NOTE: the coding agent could not visually inspect the PNG this round
  (no image input available); the owner should glance at the new group's
  spacing/wording before release - rows are ActionRows like the adjacent
  groups, so the main risk is subtitle wrap length.
