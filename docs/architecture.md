# Architecture

Clockify Launchers is a layered Python application. GTK code contains no
Clockify request construction, SQL, desktop-entry serialization, or autopilot
policy — those live in lower layers and are injected at service boundaries.

## Layers

```text
src/clockify_launchers/
├── domain/           Pure logic: models, signatures, policies, autopilot rules
├── services/         Use cases: account, launcher, timer, sync, import,
│                     icon, notification
├── infrastructure/   Adapters: Clockify HTTP client, SQLite, migrations,
│                     libsecret, config store, XDG paths, desktop entries,
│                     file locks, systemd
├── ui/               GTK4/libadwaita widgets and pages (built programmatically,
│                     see ADR 0013), plus workers.py
├── demo/             Deterministic fixture backend and states (no network,
│                     keyring, or real user data)
├── cli.py            Argument parsing and command handlers with exit codes
├── application.py    Adw.Application, window wiring, embedded CSS
├── context.py        Composition root
└── constants.py      All product identifiers and defaults
```

## Composition root (`context.py`)

`context.py` builds the whole service graph (`AppContext`) for both CLI and
GUI entry points: it resolves XDG paths, opens the config store and SQLite
database, selects the secret store (`LibsecretStore` in production,
`InMemorySecretStore` in demo/tests), and constructs the services. Demo mode
(`CLOCKIFY_LAUNCHERS_DEMO=1`) swaps in the demo backend and isolated
temporary directories. Nothing else in the codebase constructs infrastructure
objects directly.

## Threading model (`ui/workers.py`)

Domain, service, and infrastructure code is synchronous. The UI never runs
HTTP, filesystem scans, keyring access, or SQLite work on the GTK main
thread; instead it calls `run_async(work, on_done, on_error)`, which submits
`work` to a bounded `ThreadPoolExecutor` (4 workers) and marshals the result
or exception back onto the GTK main loop with `GLib.idle_add`.

## Data flow: `start --launcher UUID`

Handled by `cli.cmd_start` → `TimerService.start_launcher`:

1. Acquire the per-account timer-action lock (`file_lock`).
2. Load and validate the launcher and active account; fetch the API key from
   the secret store.
3. Validate/refresh cached target metadata before touching the running timer.
4. Fetch the current in-progress entry; if it matches the target (normalized
   task/tags/description comparison), record a no-op and notify.
5. Generate one UTC timestamp `T`; stop any running entry at `T`, then start
   the new entry at `T`.
6. On an ambiguous POST outcome, probe the running entry to reconcile
   (`_reconcile_ambiguous_start`); never blindly re-POST.
7. Record `last_invoked_at` / `last_start_success_at`, log an activity event,
   and send a notification. Exit codes map outcomes (7 = old timer stopped
   but new start failed).

## Data flow: `sync`

Handled by `cli.cmd_sync` → `SyncService.run`:

1. Acquire the nonblocking sync lock in `XDG_RUNTIME_DIR`; a skipped
   overlapping run is a normal outcome.
2. Fetch completed time entries in the lookback window (full pagination) and
   cached project/task/tag metadata; extract normalized candidates
   (`extract_candidates`) with recency scores.
3. Compute a `ReconciliationPlan` before any filesystem change; any
   uncertainty (auth, pagination, parse, keyring, external modification)
   clears `safe_to_remove`.
4. Apply automatic additions (Assisted/Autopilot), removal suggestions
   (Assisted), and guarded removals with tombstones (Autopilot only).
5. Record the run in `sync_runs` and activity events.

Sync is read-only with respect to Clockify.

## XDG paths

Resolved at runtime by `infrastructure/xdg_paths.py`; never hard-coded.

| Purpose | Path |
| --- | --- |
| Config | `$XDG_CONFIG_HOME/clockify-launchers/config.json` |
| State DB | `$XDG_STATE_HOME/clockify-launchers/state.db` |
| Cache | `$XDG_CACHE_HOME/clockify-launchers/` |
| Sync lock | `$XDG_RUNTIME_DIR/clockify-launchers/sync.lock` |
| Timer-action lock | `$XDG_RUNTIME_DIR/clockify-launchers/` |
| Launchers | `$XDG_DATA_HOME/applications/` |
| Icons | `$XDG_DATA_HOME/clockify-launchers/icons/` |
| Timer drop-in | `$XDG_CONFIG_HOME/systemd/user/clockify-launchers-sync.timer.d/override.conf` |

Private directories are created with mode `0700`.

## Database tables

SQLite (`infrastructure/database.py`, ordered migrations in
`migrations.py`, WAL mode, foreign keys, UTC timestamps):

| Table | Contents |
| --- | --- |
| `accounts` | Local account UUID, API base URL, Clockify user ID, email, workspace |
| `workspaces` | Cached workspace metadata |
| `projects`, `tasks`, `tags` | Cached Clockify target metadata |
| `launchers` | Launcher targets, name/icon, source, policy, status, hashes, timestamps |
| `suggestions` | Auditable add/remove proposals with evidence |
| `dismissals` | Dismissed candidate signatures with cooldowns |
| `activity_events` | Bounded redacted activity log |
| `tombstones` | Restorable records of removed launchers (kept ≥ 90 days) |
| `sync_runs` | Reconciliation run results and safety flags |
| `schema_version` | Migration bookkeeping |

No API keys, authorization headers, or raw HTTP dumps are ever stored.
