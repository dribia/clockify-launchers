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
