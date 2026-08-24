# AGENTS.md

## 1. Purpose

This repository builds **Clockify Launchers**, a native Ubuntu desktop application for creating, using, and maintaining per-user application launchers that start Clockify timers.

The application is intended to turn a recurring Clockify workflow into a first-class Ubuntu experience:

- The user configures their own Clockify API key.
- The user can create launcher entries from Clockify projects, tasks, and tags.
- The generated entries appear in the Ubuntu/GNOME application launcher.
- Clicking an entry starts or switches the current Clockify timer.
- The application shows all launchers it owns and their health.
- Optional automation keeps the launcher set aligned with the user's recent Clockify activity.

This file is the authoritative product and engineering brief for coding agents. Build the application without waiting for further product clarification unless a missing fact makes secure release or live data access impossible.

## 2. Working name and identifiers

Use these values consistently until the repository owner changes them:

| Concept | Value |
| --- | --- |
| Product name | Clockify Launchers |
| Debian package | `dribia-clockify-launchers` |
| Python distribution | `clockify-launchers` |
| Python package | `clockify_launchers` |
| Executable | `clockify-launchers` |
| Application ID | `com.dribia.ClockifyLaunchers` |
| Main desktop file | `com.dribia.ClockifyLaunchers.desktop` |
| Systemd units | `clockify-launchers-sync.service` and `clockify-launchers-sync.timer` |

Keep identifiers centralized in one module and one packaging metadata file. A rename must not require searching arbitrary source files.

## 3. Product principles

1. **A launcher must be dependable.** Clicking it either starts the intended timer or gives a clear notification explaining why it did not.
2. **Automation must be conservative.** A network error, partial API result, locked keyring, or parse error must never cause launcher deletion.
3. **The API key is a secret.** It must never be stored in a desktop entry, JSON file, SQLite database, log, screenshot, test fixture, command line, or process environment used by the installed application.
4. **Only touch files owned by this application.** Never edit or delete unrelated user desktop entries or icons.
5. **Use native Ubuntu integration.** Follow GTK, libadwaita, XDG, desktop entry, Secret Service, and systemd user-service conventions.
6. **Keep the interface understandable.** The application manages quick-start targets; it is not a replacement for the Clockify web application or a full timesheet editor.
7. **Make every important behavior testable without a live Clockify account.** Demo fixtures and replaceable service interfaces are mandatory.
8. **The agent must inspect the interface it builds.** Automated UI screenshots and AT-SPI tests are part of normal development, not optional release polish.

## 4. Scope

### 4.1 Required MVP capabilities

The first production-ready version must support all of the following:

- First-run onboarding.
- Clockify API key validation and secure storage in GNOME Keyring through libsecret.
- Clockify API region/base URL selection, with the global API as the default.
- Workspace selection.
- Manual launcher creation from active projects, optional task, and zero or more tags.
- Optional fixed time-entry description for a manually created launcher.
- Custom launcher name and icon.
- A list of managed launchers with status, target details, source, pin state, and last use.
- Edit, start, pin/unpin, delete, restore, and open-file-location actions.
- Generated freedesktop `.desktop` files under the user's XDG data directory.
- Direct Clockify REST API integration for starting and switching timers.
- Desktop notifications for timer success, no-op, ambiguous result, and failure.
- Manual, Assisted, and Autopilot management modes.
- Periodic reconciliation through a systemd user timer.
- Addition and removal reasoning visible to the user.
- A deterministic demo mode, automated screenshots, and AT-SPI GUI smoke tests.
- A Debian package that installs and runs on Ubuntu 24.04 LTS and Ubuntu 26.04 LTS.

### 4.2 Strongly recommended migration capability

On first run and from Preferences, scan the user's local application directory for likely legacy launchers whose `Exec` command is a plain `clockify-cli in ...` invocation. Offer a read-only preview and explicit import.

Imported launchers must:

- Keep their name, comment, and icon when safe.
- Parse project, task, and repeated tag arguments without executing anything.
- Become manual, pinned launchers.
- Be rewritten to call this application's stable helper only after explicit confirmation.
- Leave the original file untouched until the replacement has been validated and atomically installed.

Reject import when the command contains shell control operators, substitutions, redirects, environment assignments, or an unknown command shape. Never pass an imported `Exec` line to a shell.

### 4.3 Non-goals for the MVP

Do not expand the initial project into any of the following:

- Full timesheet editing or reporting.
- Project, task, tag, user, or workspace administration in Clockify.
- Team-wide launcher deployment.
- Windows or macOS support.
- Mobile support.
- Multiple simultaneously active Clockify accounts.
- A continuously resident tray process.
- Automatic parsing of arbitrary shell commands.
- A dependency on `clockify-cli` for normal operation.
- Production APT repository credentials or production signing keys in the repository.

The schema and service boundaries should permit multiple accounts later, but the first interface may expose one active account and one active workspace.

## 5. User-facing management modes

Expose exactly three primary modes. Their names and behavior are part of the product contract.

### 5.1 Manual

- No periodic Clockify reconciliation.
- No automatic additions.
- No automatic removal suggestions.
- The user creates, imports, edits, and deletes launchers explicitly.
- The systemd timer is disabled.

### 5.2 Assisted (recommended default)

- Periodically inspect recent Clockify time entries.
- Automatically create high-confidence launchers that do not already exist.
- Never automatically remove a launcher.
- Place stale managed launchers in Suggestions with a concrete explanation.
- Allow Keep, Pin, Snooze, and Remove actions.
- Enable the systemd timer.

### 5.3 Autopilot

- Perform the same high-confidence automatic additions as Assisted mode.
- Automatically remove stale, unpinned, application-managed launchers only after all safety checks and grace periods pass.
- Keep a restorable tombstone and activity record for every removal.
- Never remove manual or imported launchers unless the user has explicitly unpinned them and opted them into automatic management.
- Enable the systemd timer.

### 5.4 Pinning and exclusions

A pinned launcher is outside removal automation. Pinning does not prevent target metadata refresh or health checks.

Defaults:

- Manually created launcher: pinned.
- Imported launcher: pinned.
- Automatically created launcher: unpinned and managed.
- Restored launcher: pinned unless the user explicitly restores it as managed.

Use clear language in the UI. Prefer "Keep this launcher" over implementation terms such as "exclude from garbage collection."

## 6. Target platform and technology

### 6.1 Runtime stack

Use:

- Python 3.12 or newer.
- GTK 4.
- libadwaita, limited to APIs available in libadwaita 1.5.
- PyGObject.
- `httpx` for HTTP.
- Python's standard `sqlite3` module.
- libsecret through `gi.repository.Secret`.
- systemd user services and timers.
- `pytest` for tests.
- `ruff` for linting and formatting.
- `mypy` for type checking.

Target Ubuntu 24.04 LTS as the minimum supported platform and test Ubuntu 26.04 LTS as well. Do not use a newer GTK or libadwaita API unless a runtime feature check provides a working 1.5-compatible fallback.

### 6.2 UI implementation constraints

Use GtkBuilder `.ui` templates compiled into a GResource. Keep CSS and icons in the same resource bundle where appropriate.

Prefer stable libadwaita widgets, including:

- `Adw.ApplicationWindow`
- `Adw.HeaderBar`
- `Adw.ToastOverlay`
- `Adw.ViewStack` and `Adw.ViewSwitcher`
- `Adw.PreferencesPage`, `Adw.PreferencesGroup`, and `Adw.ActionRow`
- `Adw.StatusPage`
- `Adw.MessageDialog`

Do not perform HTTP requests, filesystem scans, desktop database reconciliation, keyring access, or SQLite migrations on the GTK main thread. Keep domain and infrastructure operations synchronous and run them in a bounded worker executor. Marshal completed results back with GLib main-context mechanisms.

### 6.3 Packaging approach

Use a PEP 517 `pyproject.toml` with setuptools and a console-script entry point. Build the Debian package with debhelper 13 and pybuild.

The package must install:

- Python modules.
- `/usr/bin/clockify-launchers`.
- The main application desktop entry.
- AppStream metadata.
- Application icons.
- GResource data.
- Systemd user service and timer units.
- License/copyright metadata appropriate to the repository.

Do not use a dpkg maintainer script to inspect or modify a user's home directory.

## 7. Architecture

Use a layered architecture with dependency injection at service boundaries. GTK code must not contain Clockify request construction, SQL, desktop-entry serialization, or autopilot policy.

Recommended repository layout:

```text
.
+-- AGENTS.md
+-- README.md
+-- CHANGELOG.md
+-- Makefile
+-- pyproject.toml
+-- src/
|   `-- clockify_launchers/
|       +-- __init__.py
|       +-- __main__.py
|       +-- constants.py
|       +-- cli.py
|       +-- application.py
|       +-- actions.py
|       +-- domain/
|       |   +-- models.py
|       |   +-- policies.py
|       |   +-- signatures.py
|       |   +-- autopilot.py
|       |   `-- reconciliation.py
|       +-- services/
|       |   +-- account_service.py
|       |   +-- launcher_service.py
|       |   +-- timer_service.py
|       |   +-- sync_service.py
|       |   +-- import_service.py
|       |   +-- scheduler_service.py
|       |   +-- notification_service.py
|       |   `-- icon_service.py
|       +-- infrastructure/
|       |   +-- clockify_api.py
|       |   +-- database.py
|       |   +-- migrations.py
|       |   +-- secret_store.py
|       |   +-- config_store.py
|       |   +-- xdg_paths.py
|       |   +-- desktop_entries.py
|       |   +-- file_lock.py
|       |   `-- systemd.py
|       +-- ui/
|       |   +-- main_window.py
|       |   +-- onboarding.py
|       |   +-- launchers_page.py
|       |   +-- launcher_editor.py
|       |   +-- suggestions_page.py
|       |   +-- preferences_page.py
|       |   +-- activity_dialog.py
|       |   `-- view_models.py
|       +-- demo/
|       |   +-- backend.py
|       |   +-- fixtures.py
|       |   `-- states.py
|       `-- resources/
|           +-- com.dribia.ClockifyLaunchers.gresource.xml
|           +-- ui/
|           +-- css/
|           `-- icons/
+-- data/
|   +-- com.dribia.ClockifyLaunchers.desktop
|   +-- com.dribia.ClockifyLaunchers.metainfo.xml
|   +-- icons/
|   `-- systemd/
|       +-- clockify-launchers-sync.service
|       `-- clockify-launchers-sync.timer
+-- tests/
|   +-- unit/
|   +-- integration/
|   +-- contract/
|   +-- ui/
|   `-- fixtures/
+-- scripts/
|   +-- bootstrap-dev.sh
|   +-- ui-capture.sh
|   +-- ui-review.py
|   +-- build-deb.sh
|   +-- smoke-install.sh
|   `-- build-test-apt-repo.sh
+-- docs/
|   +-- architecture.md
|   +-- releasing.md
|   +-- security.md
|   +-- ui-review.md
|   +-- STATUS.md
|   `-- decisions/
`-- debian/
    +-- changelog
    +-- control
    +-- copyright
    +-- install
    +-- rules
    +-- source/format
    `-- tests/control
```

Small deviations are acceptable when they simplify implementation, but preserve the separation of domain, service, infrastructure, and UI concerns.

## 8. Command-line contract

The installed executable is both the GUI entry point and the stable target for generated desktop launchers.

Required commands:

```text
clockify-launchers                         # Open or focus the GUI
clockify-launchers gui                     # Explicit GUI command
clockify-launchers start --launcher UUID   # Start/switch timer for one launcher
clockify-launchers stop                    # Stop the current user's timer
clockify-launchers sync                    # Reconcile now; human-readable output
clockify-launchers sync --background       # Quiet systemd mode; journal-friendly
clockify-launchers doctor                  # Diagnose configuration and integration
clockify-launchers reset                   # Interactive reset; safe by default
clockify-launchers demo --state STATE      # Deterministic UI fixture state
clockify-launchers --version
```

Behavioral requirements:

- Return exit code 0 only when the requested outcome succeeded or is a defined no-op.
- Use distinct documented nonzero exit codes for configuration, authentication, API, target, desktop-file, and partial-switch failures.
- Never print the API key or complete HTTP headers.
- `start` must not open the full GUI on success.
- `start` must send a desktop notification unless notifications are disabled.
- `sync --background` must not display modal UI.
- `doctor` must be safe and read-only unless invoked with an explicit repair option.
- Machine-readable `--json` output may be added for `sync` and `doctor`, but human output remains the default.

## 9. XDG paths and file ownership

Resolve paths from the environment at runtime. Never hard-code `/home/<user>` and never use `~` inside a desktop entry.

Use:

```text
Config:       $XDG_CONFIG_HOME/clockify-launchers/config.json
State DB:     $XDG_STATE_HOME/clockify-launchers/state.db
Cache:        $XDG_CACHE_HOME/clockify-launchers/
Runtime lock: $XDG_RUNTIME_DIR/clockify-launchers/sync.lock
Launchers:    $XDG_DATA_HOME/applications/
Icons:        $XDG_DATA_HOME/clockify-launchers/icons/
Timer drop-in:$XDG_CONFIG_HOME/systemd/user/clockify-launchers-sync.timer.d/override.conf
```

Apply XDG defaults when variables are unset:

- `XDG_CONFIG_HOME=$HOME/.config`
- `XDG_STATE_HOME=$HOME/.local/state`
- `XDG_CACHE_HOME=$HOME/.cache`
- `XDG_DATA_HOME=$HOME/.local/share`

Create private directories with mode `0700` where practical. Config and state files should not be world-readable.

An owned launcher must meet all of these conditions:

- Filename begins with `com.dribia.ClockifyLaunchers.` and ends with `.desktop`.
- It contains `X-Clockify-Launchers-Managed=true`.
- It contains a valid `X-Clockify-Launchers-Id` that exists in application state or can be safely recovered.

No deletion is allowed unless all ownership checks pass and the file hash still matches the last hash written by the application. If a user edited an owned file externally, mark it as modified and ask before overwriting or deleting it.

## 10. Secrets and account configuration

### 10.1 API key storage

Store the Clockify API key through libsecret and the desktop Secret Service. Define a fixed secret schema with nonsecret attributes such as:

- `application=com.dribia.ClockifyLaunchers`
- `account_id=<local account UUID>`
- `api_origin=<normalized API origin>`

The keyring label may contain the validated Clockify email address, for example `Clockify API key for person@example.com`.

Do not implement a plaintext fallback. When Secret Service is unavailable or locked, explain the problem and preserve all existing configuration and launchers.

### 10.2 Nonsecret configuration

`config.json` may contain:

- Schema version.
- Active account UUID.
- Clockify API base URL.
- User ID and display email returned after validation.
- Active workspace ID.
- Management mode.
- Sync interval.
- Lookback, stale, grace, and maximum-launcher settings.
- Notification preferences.
- Last successful application version.

Write configuration atomically with a temporary file, `fsync`, and `os.replace`. Validate every loaded value and recover from malformed configuration by preserving the broken file with a timestamped suffix.

### 10.3 Clockify API base URL

Default to the global regular API:

```text
https://api.clockify.me/api
```

Support regional Clockify origins through an onboarding selector and an advanced custom-base option. Known regional host prefixes include `euc1`, `use2`, `euw2`, and `apse2`. Normalize the URL, require HTTPS except in explicit test mode, and reject embedded credentials, query strings, fragments, and unexpected paths.

## 11. Domain model

Use immutable or validation-heavy domain models. IDs received from Clockify are opaque strings.

### 11.1 Account

Minimum fields:

- `id`: local UUID.
- `api_base_url`.
- `clockify_user_id`.
- `email`.
- `display_name`.
- `active_workspace_id`.
- `created_at`.
- `last_validated_at`.

### 11.2 Workspace

- `id`.
- `name`.
- `archived` or active state when available.
- `last_seen_at`.

### 11.3 Launcher target

A launcher target consists of:

- `workspace_id`.
- `project_id`.
- Optional `task_id`.
- A sorted, deduplicated tuple of `tag_ids`.
- Optional fixed `description` for manually created launchers.
- Optional future `custom_fields` payload.

The default automatic candidate signature is:

```text
(workspace_id, project_id, task_id, sorted(tag_ids))
```

Descriptions are deliberately excluded from automatic signatures to avoid creating a launcher for every free-text description. Manually created launchers may include a fixed description.

### 11.4 Launcher

Minimum fields:

- `id`: UUID used by the desktop entry.
- `account_id`.
- Target fields.
- `display_name`.
- `comment`.
- `icon_kind`: generated, selected file, or inherited legacy path.
- `icon_path`.
- `source`: manual, imported, or automatic.
- `management_policy`: pinned or managed.
- `status`: healthy, stale, target-missing, externally-modified, pending-removal, removed, or error.
- `created_at` and `updated_at`.
- `last_invoked_at`.
- `last_start_success_at`.
- `last_clockify_use_at`.
- `auto_add_grace_until`.
- `removal_snoozed_until`.
- `desktop_path`.
- `desktop_hash`.
- `icon_hash`.
- Optional `removed_at` and removal reason.

### 11.5 Candidate and suggestion

A candidate records aggregated recent use for one signature:

- Count in lookback window.
- Last use.
- Weighted recency score.
- Most recent representative entry ID.
- Resolved project, task, and tag names.
- Eligibility and ineligibility reasons.

A suggestion is an auditable proposed state change with:

- Type: add or remove.
- Launcher or target reference.
- Human explanation.
- Evidence summary.
- Created, dismissed, snoozed, accepted, or executed timestamps.

### 11.6 Activity event

Keep a bounded local activity log for user-visible diagnostics:

- Event type.
- Severity.
- Launcher reference when applicable.
- Redacted summary.
- Machine-readable details that contain no secrets.
- Timestamp.

Retain at least 90 days or 2,000 events, whichever is smaller after compaction.

## 12. SQLite requirements

Use SQLite for durable application state and cached Clockify metadata.

Required practices:

- Enable foreign keys.
- Use WAL mode where supported.
- Set a reasonable busy timeout.
- Store UTC timestamps consistently, preferably integer Unix seconds.
- Use explicit transactions for reconciliation.
- Implement ordered schema migrations with a schema-version table.
- Back up the database before a destructive migration.
- Do not store the API key, authorization headers, raw request dumps, or unrestricted time-entry descriptions.
- Index signature fields, status, last-use timestamps, and Clockify IDs.

A reconciliation run must compute its plan before applying filesystem changes. Persist the plan and state changes transactionally where possible, then perform idempotent filesystem actions. If a filesystem action fails, record a recoverable mismatch for the next run rather than corrupting state.

## 13. Clockify API integration

### 13.1 Authentication

Send the API key only in the `X-Api-Key` request header. Centralize redaction so exceptions and debug logs cannot expose it.

Validate credentials with:

```text
GET /v1/user?include-memberships=true
```

Use the result to obtain the Clockify user ID and default/active workspace. Fetch accessible workspaces for the workspace selector.

### 13.2 Required read operations

Implement typed client methods for at least:

- Current user.
- Accessible workspaces.
- Active projects in a workspace.
- Tags in a workspace.
- Active tasks for a project.
- Current user's time entries in a bounded start/end range with pagination.
- Current in-progress time entry.
- Individual project/task/tag refresh when validating a launcher.

Use the official v1 endpoints and treat undocumented response fields as optional.

### 13.3 Required write operations

The application may write to Clockify only for explicit timer actions:

- Start a new time entry with `POST /v1/workspaces/{workspaceId}/time-entries`.
- Stop the current user's running timer with `PATCH /v1/workspaces/{workspaceId}/user/{userId}/time-entries` and an `end` timestamp.

Periodic synchronization is read-only with respect to Clockify.

### 13.4 HTTP behavior

Use conservative defaults:

- Connect timeout: 10 seconds.
- Read/write/pool timeout: 30 seconds.
- User agent containing application name and version.
- Bounded response sizes where practical.
- Pagination with a documented page size and a hard maximum-page guard.
- Respect `Retry-After`.
- Retry safe GET requests on connection failures, HTTP 429, and selected 5xx responses with bounded exponential backoff and jitter.
- Do not blindly retry POST or PATCH requests.

When a POST times out after bytes may have reached the server, immediately query the in-progress entry. If an entry matching the intended target and start time exists within a small tolerance, treat the operation as successful. Otherwise report an ambiguous result rather than issuing a duplicate POST.

### 13.5 API error mapping

Map failures into stable application errors:

- Authentication rejected.
- Permission denied.
- Workspace unavailable.
- Project/task/tag missing or archived.
- Validation failure.
- Required custom field missing.
- Rate limited.
- Offline/timeout.
- Server error.
- Unexpected response.

Show actionable user text while retaining redacted technical detail in the activity log.

### 13.6 Required custom fields

Clockify can reject a new time entry when required custom fields are not supplied. The MVP must:

- Preserve a schema field for optional custom-field values.
- Detect and clearly surface this class of API error.
- Mark the launcher as requiring attention instead of repeatedly retrying.
- Never stop a running timer before validating all locally known target and payload requirements.

Full custom-field editing is a later enhancement unless fixtures or live validation prove it is required for the target workspace. If implemented, use Clockify metadata and support only types that can be validated and serialized safely.

## 14. Timer start and switch semantics

Generated launchers must call this application, not `clockify-cli` directly:

```text
Exec=/usr/bin/clockify-launchers start --launcher <UUID>
```

This indirection is mandatory because it keeps credentials out of desktop files, provides stable behavior, records local usage, allows notifications, and permits backend changes without rewriting every user's launcher command.

Use this sequence for `start`:

1. Acquire a short-lived per-account timer-action lock.
2. Load and validate the launcher and active account.
3. Retrieve the API key from Secret Service.
4. Validate cached target metadata; refresh stale or suspect metadata before altering the current timer.
5. Fetch the current in-progress entry.
6. If it already matches project, task, sorted tags, and fixed description, record a no-op and notify "Already tracking <name>."
7. Generate one timezone-aware UTC timestamp `T`.
8. If another entry is running, stop it at `T`.
9. Start the intended entry at `T`.
10. Reconcile ambiguous network outcomes with a read request.
11. Record `last_invoked_at` and `last_start_success_at` separately.
12. Send a success or failure notification.

Important failure behavior:

- Validate the new target before stopping the old timer.
- If stopping succeeds but starting fails, do not silently restart or modify time entries. Notify prominently that no timer may be running and store a recoverable activity event.
- Do not automatically repeat a non-idempotent request merely because the response was lost.
- A launcher click must never delete, edit, or backfill historical time entries.

Comparison of a running entry to a launcher target must normalize absent task/tag/description values and compare tag sets independent of ordering.

## 15. Desktop entry generation

### 15.1 Production example

A generated entry should resemble:

```ini
[Desktop Entry]
Version=1.0
Type=Application
Name=Kaito
Comment=Start Clockify timer: Tank - Project
Exec=/usr/bin/clockify-launchers start --launcher 6d17b662-5ba4-4c39-903b-cc319a633fe7
TryExec=/usr/bin/clockify-launchers
Icon=/home/example/.local/share/clockify-launchers/icons/6d17b662-5ba4-4c39-903b-cc319a633fe7.svg
Terminal=false
StartupNotify=false
Categories=Office;Utility;
Keywords=Clockify;Time tracking;Dribia;Kaito;Tank;Project;
X-Clockify-Launchers-Managed=true
X-Clockify-Launchers-Id=6d17b662-5ba4-4c39-903b-cc319a633fe7
```

Use an absolute icon path for per-user dynamic icons. The main installed application should use a normal icon-theme name.

### 15.2 File naming

Use:

```text
$XDG_DATA_HOME/applications/com.dribia.ClockifyLaunchers.<UUID>.desktop
```

The filename must remain stable when the user renames the launcher.

### 15.3 Safe serialization

Use GLib key-file facilities or a dedicated desktop-entry serializer with tests. Do not build the file by concatenating untrusted strings.

Requirements:

- Escape desktop-entry values correctly.
- Never put the API key in any field.
- Never put user-provided text into `Exec`.
- Do not invoke a shell.
- Normalize `Categories` and `Keywords` with terminating semicolons.
- Remove newlines and control characters from visible single-line fields.
- Validate the final file with `desktop-file-validate` during tests and builds.
- Write to a temporary file in the same directory, flush and `fsync`, then replace atomically.
- Store the exact written hash in SQLite.

### 15.4 Icons

Default icon behavior:

- Generate an accessible SVG tile using the Clockify project color when available.
- Add a short project monogram with sufficient contrast.
- Include a small consistent timer glyph only when it remains legible.
- Do not rely on remote image URLs at launcher runtime.

When the user chooses an image:

- Accept common raster formats and SVG through GTK's file chooser.
- Enforce a reasonable size limit.
- Decode or validate before copying.
- Copy a normalized managed version into the application's XDG data directory.
- Never continue pointing to a removable or temporary source file unless the user explicitly chooses a legacy-path preservation option.

### 15.5 External modification

At startup and reconciliation:

- Compare the owned file's current hash to the stored hash.
- If different, do not overwrite automatically.
- Show "Modified outside Clockify Launchers."
- Offer: View difference, Adopt safe fields, Restore managed version, or Detach.
- Never auto-remove an externally modified file.

## 16. Legacy launcher import

Scan only the user's XDG application directory by default. Do not recursively scan the whole home directory.

Safe import parser:

1. Parse the desktop entry as a key file.
2. Read, but never execute, `Exec`.
3. Tokenize with `shlex.split(posix=True)`.
4. Require the executable basename to be exactly `clockify-cli`.
5. Require the first non-option command to be `in`.
6. Accept known project, task, tag, description, and workspace flags.
7. Reject shell metacharacters, substitutions, redirections, environment assignments, unknown response files, and malformed quoting.
8. Show the parsed result and any ignored option to the user before import.

Do not attempt to recover the user's API token from `clockify-cli` configuration. The user configures the key in this application.

## 17. Autopilot reconciliation

### 17.1 Default policy settings

Use these defaults and expose them in Preferences with concise explanations:

| Setting | Default |
| --- | --- |
| Sync interval | 30 minutes |
| Activity lookback | 90 days |
| Recency half-life | 21 days |
| Recent-use shortcut | 7 days |
| Minimum uses for automatic addition | 2 uses in 30 days |
| Stale threshold | 45 days |
| New auto-launcher removal grace | 7 days |
| Removal suggestion snooze | 30 days |
| Maximum automatically managed launchers | 15 |

Validate ranges. Suggested bounds:

- Sync interval: 5 minutes to 24 hours.
- Lookback: 14 to 365 days.
- Stale threshold: 14 to 365 days.
- Maximum managed launchers: 1 to 100.

### 17.2 Candidate extraction

For the active user and workspace:

1. Fetch all completed time entries in the lookback range using start/end parameters and complete pagination.
2. Exclude running entries from frequency scoring, but use a matching running entry as recent evidence.
3. Exclude breaks, entries without a project, and entries whose project is unavailable or archived.
4. Resolve task and tag IDs from cached metadata, refreshing when necessary.
5. Build the normalized signature `(workspace, project, task, sorted tags)`.
6. Ignore free-text descriptions for automatic identity.
7. Aggregate count, last-use time, and score per signature.

Use a recency score equivalent to:

```text
score = sum(exp(-age_days / half_life_days))
```

The exact floating-point implementation is less important than deterministic behavior and tests around ordering and thresholds.

### 17.3 Automatic-add eligibility

A candidate is eligible for automatic addition when all of these are true:

- Full time-entry pagination completed successfully.
- The project is active and available.
- Any selected task is active and available.
- All tags are available and not archived.
- No active launcher already has the same signature.
- It was used within the recent-use shortcut window, or it meets the minimum-use threshold.
- It is within the configured maximum after ranking by score.
- It has not been explicitly dismissed within its dismissal cooldown.

Use the most recent matching entry as the representative for target metadata. Do not infer a fixed description.

### 17.4 Automatic naming

Avoid clever or company-specific guesses.

Default naming:

- If a task exists: `<Project> - <Task>`.
- Otherwise: `<Project>`.
- If this is not unique among current launcher names, append a compact tag qualifier.
- If still not unique, append a short stable suffix derived from the launcher UUID.

The subtitle/comment should show the full project, task, and tag combination. The user may rename any launcher without changing its signature.

### 17.5 Staleness

Calculate effective last use as the newest of:

- Last matching Clockify entry.
- Last successful local launcher start.
- Launcher creation time while the new-launcher grace period is active.

A launcher becomes stale only when effective last use exceeds the stale threshold.

### 17.6 Assisted removal suggestions

In Assisted mode, stale launchers become suggestions. Each suggestion must say, for example:

```text
Not used in Clockify or from this launcher for 52 days.
Last matching entry: 2026-05-18.
```

Available actions:

- Remove.
- Keep and pin.
- Snooze for 30 days.
- Dismiss until it next becomes recently used and later stale again.
- View matching activity evidence.

### 17.7 Autopilot removal

An automatic removal is allowed only when all of these are true:

- The run completed every required API page and metadata lookup.
- No authentication, permission, rate-limit, timeout, parse, or partial-data warning occurred.
- The launcher is application-owned and unmodified on disk.
- Its source/policy permits automatic management.
- It is not pinned.
- It is not snoozed.
- It is outside the new-launcher grace period.
- It is stale by the configured threshold.
- The target was not used successfully by a local launcher after sync began.

Before deleting the desktop file, create a tombstone containing enough nonsecret data to restore it. Keep tombstones for at least 90 days.

### 17.8 No-deletion rule on uncertainty

Set a reconciliation run's `safe_to_remove` flag to false for any uncertainty, including:

- API key unavailable.
- HTTP failure or rate limiting.
- Pagination stopped early.
- Response validation failure.
- Database write failure.
- Clock skew concern.
- Metadata cache cannot determine whether a target is active.
- Concurrent launcher action.
- Owned desktop file modified externally.

Automatic additions may also be skipped on partial runs. Prefer doing nothing over creating a misleading launcher set.

## 18. Background scheduling

Use a systemd user oneshot service rather than a resident daemon.

Service concept:

```ini
[Unit]
Description=Synchronize Clockify launchers
After=graphical-session.target

[Service]
Type=oneshot
ExecStart=/usr/bin/clockify-launchers sync --background
```

Timer concept:

```ini
[Unit]
Description=Periodically synchronize Clockify launchers

[Timer]
OnStartupSec=2min
OnUnitActiveSec=30min
AccuracySec=1min
RandomizedDelaySec=30s
Unit=clockify-launchers-sync.service

[Install]
WantedBy=timers.target
```

When the user changes the interval, write a user timer drop-in atomically:

```ini
[Timer]
OnUnitActiveSec=
OnUnitActiveSec=45min
```

Then run, without a shell:

```text
systemctl --user daemon-reload
systemctl --user restart clockify-launchers-sync.timer
```

Mode behavior:

- Manual: disable and stop the timer.
- Assisted/Autopilot: enable and start the timer.

Use a nonblocking file lock in `XDG_RUNTIME_DIR` so GUI sync, timer sync, and manual CLI sync cannot run concurrently. A skipped overlapping run is a normal outcome, not an error.

If the keyring is locked or the user session is not ready, record a credential-unavailable result and exit without changing launchers. Never make a background service pop up an unlock dialog unexpectedly.

## 19. Interface specification

### 19.1 First-run onboarding

Use a short, progressive flow:

1. **Welcome**
   - Explain that the app creates Ubuntu launchers that start Clockify timers.
   - Offer import detection when legacy launchers are found.
2. **Connect Clockify**
   - API-region selector.
   - Password-style API-key entry.
   - "Verify connection" action.
   - Show validated name/email, never echo the key.
3. **Choose workspace**
   - List accessible workspaces.
   - Preselect Clockify's active/default workspace when available.
4. **Choose management mode**
   - Manual.
   - Assisted, visibly recommended.
   - Autopilot, with conservative-removal explanation.
5. **Preview**
   - Show launchers that would be imported or created from recent activity.
   - No destructive changes before Finish.
6. **Finish**
   - Persist configuration.
   - Enable timer when appropriate.
   - Run initial reconciliation.

The user must be able to return to previous steps without losing entered nonsecret choices. Do not persist the API key until validation succeeds and the user completes the connection step.

### 19.2 Main window

Use an `Adw.ApplicationWindow` with an `Adw.ToastOverlay` and a responsive page structure.

Header area:

- Application title.
- Current workspace.
- Management-mode indicator.
- Last successful sync.
- Sync-now action with progress state.
- Primary "New launcher" action.

Primary pages:

#### Launchers

Each row/card shows:

- Icon.
- Display name.
- Project, task, and tags.
- Source: Manual, Imported, or Automatic.
- Pin state.
- Health status.
- Last use.
- Start button.
- Overflow menu for Edit, Pin/Unpin, Open file location, Recreate file, Delete, and Details.

Include search and filters for status, source, and pin state. Provide clear empty, offline, and configuration-error states.

#### Discover

- Search active projects.
- Select one project.
- Optionally select one active task.
- Select zero or more tags.
- Optionally enter a fixed description.
- Edit display name and comment.
- Choose or generate an icon.
- Preview the desktop entry's visible result.
- Detect duplicate signatures before save.

#### Suggestions

- Separate Add and Remove sections when both exist.
- Show the evidence behind each proposal.
- Support batch actions, but require confirmation for batch removal.
- In Assisted mode, automatic additions should still appear in a recent-activity summary with Undo.
- In Autopilot mode, show recently removed tombstones with Restore.

#### Preferences

- Connection health and Change API key.
- API region/base URL.
- Workspace.
- Management mode.
- Sync interval.
- Lookback, stale threshold, grace period, and launcher cap.
- Notification preferences.
- Import legacy launchers.
- Run diagnostics.
- Reset application data.

### 19.3 Current timer visibility

Show a compact current-timer banner when the main application is open:

- Current target and elapsed time.
- Stop action.
- Refresh action.

This is a convenience, not a full time-entry editor. Do not add historical editing to the MVP.

### 19.4 Feedback and errors

- Use toasts for successful local actions and reversible changes.
- Use an `Adw.MessageDialog` for destructive confirmation or failures that require a decision.
- Use inline validation for form errors.
- Do not hide background failures; show a nonblocking status banner and Activity details.
- Avoid showing raw JSON or stack traces in the normal interface.

## 20. Accessibility and keyboard behavior

Every release must be usable without a mouse.

Requirements:

- Every interactive widget has an accessible name and useful role.
- Icon-only buttons have tooltips and accessible labels.
- Logical tab order.
- Visible focus indicators.
- Enter activates the primary action where expected; Escape closes non-destructive dialogs.
- Lists expose row names and states to AT-SPI.
- Status is never communicated only by color.
- Generated project icons meet reasonable contrast requirements.
- Layout remains usable with large text.
- Test high-contrast mode, keyboard navigation, and a narrow window.
- Avoid fixed pixel heights that clip translated or enlarged text.

Prepare strings for gettext from the beginning. English is the initial language; do not block MVP on translations.

## 21. Autonomous UI awareness and visual QA

A coding agent must be able to run the interface with deterministic data, capture it, inspect it, and fix visual problems without a live account.

### 21.1 Demo backend

Provide a service implementation selected by either:

```text
CLOCKIFY_LAUNCHERS_DEMO=1
```

or:

```text
clockify-launchers demo --state <state>
```

The demo backend must never read the real keyring, real application database, real desktop directory, or network. Use temporary HOME and XDG directories.

Required deterministic states:

- `onboarding-welcome`
- `onboarding-key`
- `onboarding-workspace`
- `onboarding-mode`
- `launchers-populated`
- `launchers-empty`
- `launcher-editor`
- `suggestions-add`
- `suggestions-remove`
- `preferences`
- `offline`
- `auth-error`
- `externally-modified`

Fixtures must include:

- Short and very long project names.
- Zero, one, and multiple tags.
- A task-based launcher.
- Manual, imported, and automatic launchers.
- Pinned and unpinned launchers.
- Healthy, stale, missing-target, and externally modified states.
- Enough rows to test scrolling.

### 21.2 Screenshot harness

`make ui-capture` must:

1. Create isolated temporary HOME/XDG directories.
2. Start a private D-Bus session and Xvfb display.
3. Set deterministic locale, timezone, font settings, animation settings, and demo fixtures.
4. Use a software GTK renderer suitable for CI when necessary.
5. Launch each required state at a fixed window size.
6. Wait for an application-created readiness file or D-Bus signal, not only a fixed sleep.
7. Locate the application window by ID/title.
8. Capture the window to `artifacts/ui/<state>.png`.
9. Repeat key screens at a narrow size such as 800x700.
10. Fail when an image is missing, blank, implausibly small, or fully transparent.

Suggested development packages include Xvfb, dbus-x11, xdotool, ImageMagick, and python3-dogtail.

### 21.3 Agent inspection loop

After any change that can affect the UI, the agent must:

1. Run `make ui-capture`.
2. Open every changed screenshot using the environment's image/vision inspection tool.
3. Check for clipping, overlap, poor hierarchy, inconsistent spacing, unreadable contrast, missing icons, accidental empty regions, broken scrolling, and unclear primary actions.
4. Record a short dated assessment in `docs/ui-review.md`.
5. Fix material issues.
6. Re-run the capture and inspect again.

Do not claim UI completion based only on successful widget construction or tests. Visual inspection is required.

### 21.4 AT-SPI automation

`make ui-test` must run deterministic Dogtail/AT-SPI flows that cover at least:

- Complete onboarding with a fake validated account.
- Create a launcher.
- Edit its name and tags.
- Start it through the UI using a fake API backend.
- Pin and unpin it.
- Accept an add suggestion.
- Snooze and then remove a stale suggestion.
- Restore a removed launcher.
- Change management mode and sync interval.
- Navigate primary pages with the keyboard.

Tests must locate controls by accessible identity, not fragile screen coordinates.

### 21.5 Visual baselines

Pixel-perfect baselines may be used for stable fixture screens, but do not make all UI tests brittle. Combine:

- Programmatic checks for window/content existence.
- AT-SPI semantic assertions.
- A small number of tolerant image-difference baselines.
- Mandatory agent visual review.

Preserve screenshots as CI artifacts on failures.

## 22. Test strategy

### 22.1 Unit tests

Cover at least:

- Signature normalization.
- Duplicate detection.
- Recency scoring and deterministic ranking.
- Automatic-add thresholds.
- Staleness, grace, snooze, and pin behavior.
- The no-deletion-on-uncertainty rule.
- Timer target equality.
- Safe desktop serialization and escaping.
- Owned-file detection.
- Legacy `Exec` parsing and rejection cases.
- API URL normalization.
- Config validation and migration.
- SQLite migrations.
- Icon contrast/monogram selection where practical.

Use a fake clock so date-sensitive tests never depend on wall time.

### 22.2 API contract tests

Use `httpx.MockTransport` or an equivalent local transport. Test:

- Authentication.
- Pagination.
- Empty and malformed responses.
- 401, 403, 404, 409, 429, and 5xx mappings.
- `Retry-After` behavior.
- Regional base URLs.
- Start with no running timer.
- Switch from another timer.
- Same-target no-op.
- Stop succeeds and start fails.
- POST response lost but reconciliation finds the new timer.
- POST response lost and outcome remains ambiguous.
- Required custom-field error.

No default test may contact Clockify.

### 22.3 Integration tests

Use temporary XDG directories and replaceable secret storage. Cover:

- First-run setup.
- Launcher create/edit/delete/restore lifecycle.
- Atomic write recovery.
- Externally modified launcher handling.
- Reconciliation from fixture entries.
- SQLite plus filesystem mismatch recovery.
- Systemd drop-in rendering without modifying the developer's real user manager.
- Background sync lock behavior.
- Legacy import preview and conversion.

### 22.4 Live tests

Live tests are opt-in and skipped by default.

Require:

```text
CLOCKIFY_LIVE_TESTS=1
CLOCKIFY_API_KEY=<secret supplied outside the repository>
```

Read-only live tests may validate authentication and list metadata. Any write test additionally requires:

```text
CLOCKIFY_LIVE_WRITE_TESTS=1
```

A live write test must use an explicitly configured test workspace/project and clean up only entries it created. It must never run in CI without protected manual approval.

### 22.5 Packaging tests

The verification pipeline must run:

- Python tests.
- Lint and formatting checks.
- Type checking.
- GResource compilation.
- `desktop-file-validate`.
- AppStream validation.
- Debian package build.
- `lintian`.
- Installation and removal smoke tests in clean Ubuntu 24.04 and 26.04 environments.
- A launch smoke test under Xvfb.

Use an ephemeral HOME during package tests. Verify that package removal does not attempt to delete per-user state.

## 23. Makefile command contract

Create these targets early and keep them working throughout development:

```text
make bootstrap       Install or explain development dependencies
make resources       Compile GTK resources
make run             Run the application against isolated dev data
make demo            Open the populated deterministic demo
make test            Run unit, contract, and integration tests
make lint            Run ruff checks and formatting verification
make format          Apply formatting
make typecheck       Run mypy
make ui-test         Run AT-SPI/Dogtail tests
make ui-capture      Capture all deterministic UI states
make ui-review       Build a contact sheet and print the review checklist
make validate-data   Validate desktop/AppStream/GResource files
make deb             Build the Debian package
make lintian         Run lintian on the package
make smoke-install   Install/test/remove the package in an isolated environment
make test-apt-repo   Build a locally signed test APT repository with an ephemeral key
make verify          Run the full non-live verification suite
make clean
```

Targets must be noninteractive in CI. `make bootstrap` may print commands instead of modifying the host when automatic installation is unsafe.

## 24. Debian and APT requirements

### 24.1 Runtime dependencies

Expect Debian control metadata to include the appropriate package names for:

- Python 3.
- PyGObject.
- GTK 4 introspection.
- libadwaita introspection.
- libsecret introspection.
- `python3-httpx`.

Do not bundle another Python interpreter or GTK stack inside the `.deb`.

### 24.2 Build and test dependencies

Expect packages such as:

- `debhelper-compat (= 13)`.
- `dh-sequence-python3`.
- `pybuild-plugin-pyproject`.
- `python3-all`.
- `python3-setuptools`.
- `libglib2.0-bin`.
- `desktop-file-utils`.
- AppStream validation tools.
- `xvfb`.
- `dbus-x11`.
- `xdotool`.
- `imagemagick`.
- `python3-dogtail`.
- `lintian`.

Confirm exact package names in both supported Ubuntu releases before finalizing `debian/control`.

### 24.3 APT repository readiness

Production repository hosting and signing are deployment decisions, but the source repository must prove that the package is APT-distributable.

Provide a test script that:

1. Builds the `.deb`.
2. Generates an ephemeral test signing key.
3. Creates a minimal signed APT repository with an appropriate tool.
4. Adds that repository to an isolated test environment.
5. Runs `apt update`.
6. Installs `dribia-clockify-launchers` by package name.
7. Runs smoke tests.
8. Removes the ephemeral repository and key material.

Never commit a private signing key.

### 24.4 User-data lifecycle

APT removal cannot safely know which desktop users own generated launchers. Therefore:

- Package uninstall removes only system-installed files.
- The application provides `reset --remove-launchers` and an equivalent Preferences action.
- Reset previews what it will remove.
- Reset touches only application-owned files and state.
- Documentation explains that per-user launchers may remain after uninstall unless reset is run first.

## 25. Logging, notifications, and diagnostics

Use Python logging with structured context, but keep default logs concise.

Mandatory redaction:

- API keys.
- Authorization headers.
- Keyring values.
- Full raw HTTP bodies when they may contain private descriptions.
- Home-directory paths in exported diagnostics when not necessary.

`doctor` should check:

- Supported Python/GTK/libadwaita versions.
- XDG directory permissions.
- SQLite readability and migrations.
- Secret Service availability without revealing the secret.
- Account/workspace configuration consistency.
- API connectivity only with explicit permission or a `--network` flag.
- Owned desktop files and their hashes.
- Icon existence.
- Desktop-file validation.
- Systemd user timer state.
- Last sync result.

Provide an "Export diagnostics" function that creates a redacted text or JSON bundle after preview. Never include the API key or unrestricted time-entry data.

Notification defaults:

- Timer start/switch success: enabled.
- Same-target no-op: enabled but low urgency.
- Timer failure or ambiguous state: enabled and prominent.
- Background additions: summarized, not one notification per launcher.
- Assisted removal suggestions: optional summary.
- Autopilot removals: summary with an action to open the app when supported.
- Routine successful sync with no change: no notification.

## 26. Security and destructive-action rules

These rules override convenience:

- Never execute a desktop entry's `Exec` while importing or inspecting it.
- Never invoke a shell for Clockify actions, systemctl calls, file-manager calls, or parsing.
- Never follow symlinks when replacing or deleting managed desktop/icon files.
- Verify parent directories and use safe open/replace patterns.
- Never delete a desktop file outside the XDG user application directory.
- Never delete a file lacking both application ownership markers.
- Never remove a launcher after a partial reconciliation.
- Never store secrets in environment variables in the installed application.
- Never send telemetry unless a future, explicit, opt-in design is approved.
- Never send project, tag, task, or description data anywhere except the configured Clockify API.
- Never modify historical Clockify entries as part of sync or launcher maintenance.
- Never log a complete Clockify response by default.

Treat project, task, tag, and description names as potentially sensitive user data.

## 27. Development sequence

Work in vertical, testable increments. Keep `docs/STATUS.md` updated with completed behavior, current limitations, and the next concrete task.

### Phase 0: Scaffold and autonomous feedback loop

Deliver:

- Repository structure.
- `pyproject.toml`.
- CLI skeleton.
- Main libadwaita window.
- Demo backend and deterministic fixtures.
- `make run`, `make demo`, `make lint`, `make test`, `make ui-capture`.
- First screenshots inspected and recorded.
- CI skeleton.

Do this first. The visual feedback loop must exist before building substantial UI.

### Phase 1: Configuration, secrets, and Clockify read client

Deliver:

- XDG path service.
- Atomic config store.
- SQLite schema and migrations.
- libsecret adapter and test fake.
- Typed Clockify client.
- API-key validation.
- Workspace/project/tag/task/time-entry fixture and contract tests.
- Onboarding connection and workspace pages.

### Phase 2: Manual launcher lifecycle

Deliver:

- Domain models and signature normalization.
- Launcher editor.
- Icon generation and file selection.
- Safe desktop serializer.
- Create, edit, list, pin, delete, and restore.
- Disk reconciliation and external-modification detection.
- Legacy launcher discovery/import if feasible in this phase.

### Phase 3: Timer actions

Deliver:

- Stable `start --launcher` command.
- Stop and switch semantics.
- Ambiguous-request reconciliation.
- Notifications.
- Current timer banner.
- Complete mocked failure-path tests.

### Phase 4: Assisted mode and autopilot

Deliver:

- Candidate extraction and score policy.
- Additions.
- Removal suggestions.
- Full guarded removal.
- Tombstones and restore.
- Systemd user timer management.
- Sync status and activity views.

### Phase 5: UX hardening

Deliver:

- All deterministic UI states.
- Keyboard navigation.
- AT-SPI tests.
- Narrow and large-text layouts.
- Offline/auth/error recovery.
- Visual review fixes.
- Gettext-ready strings.

### Phase 6: Debian and APT verification

Deliver:

- Complete `debian/` metadata.
- Desktop and AppStream validation.
- `.deb` builds for supported Ubuntu releases.
- Lintian cleanup.
- Install/remove smoke tests.
- Locally signed test APT repository flow.
- Release documentation without embedded production secrets.

Do not postpone testing, demo fixtures, or screenshot inspection until Phase 5. Each phase must extend them.

## 28. Definition of done for the first release

The MVP is done only when all of these are true:

- A fresh install opens a polished onboarding flow.
- A valid API key is verified and stored only in Secret Service.
- The user can select a workspace.
- The user can create a launcher from project, optional task, and tags.
- The generated desktop file passes validation and appears in the Ubuntu/GNOME application search.
- Clicking the generated launcher starts or switches the intended Clockify timer.
- Clicking an already-running target is a clear no-op.
- Failures produce actionable notifications and do not expose secrets.
- The main window lists owned launchers and accurately reconciles disk state.
- Manual, Assisted, and Autopilot modes behave as specified.
- Pinning always prevents automatic removal.
- API/network/keyring/partial-sync failures never trigger removal.
- Automatic removals are restorable.
- The systemd user timer follows mode and interval preferences.
- The application has deterministic demo states.
- UI screenshots have been captured and visually inspected at normal and narrow sizes.
- AT-SPI smoke flows pass.
- The `.deb` installs on Ubuntu 24.04 and 26.04.
- A locally signed test APT repository can install the package by name.
- `make verify` passes from a clean checkout.
- Security and release documentation are current.

## 29. Agent autonomy rules

### 29.0 Git workflow (agreed with the repository owner, 2026-08-24)

- **Code changes go through pull requests to `main`, never direct commits.**
  This includes source, tests, packaging, CI, and skills.
- Trivial documentation-only changes (docs/, CHANGELOG.md typo or wording
  fixes, STATUS.md updates) may be committed directly to `main`.
- The agent opens the PR, waits for CI to pass, then **asks the owner for
  approval before merging**. The owner may review in GitHub or approve
  verbally in-session.
- Merge method for regular PRs: **squash**.
- Exception: the automated release flow keeps its own mechanics (bump PR,
  release.yml, deploy.yml) as described in `docs/releasing.md` and the
  `release-clockify-launchers` skill; the bump PR may also be squash-merged since
  `release.yml` matches on the PR title in the commit message.

### 29.1 Decisions the agent should make without asking

Use the defaults in this document for:

- Working name and identifiers.
- Assisted as the recommended default.
- Direct REST API rather than `clockify-cli`.
- GTK/libadwaita architecture.
- SQLite and XDG layout.
- Autopilot thresholds.
- Safe UI wording and layout details.
- Test fixture content.
- Internal module organization.
- Refactors needed to keep boundaries testable.

When a choice has meaningful tradeoffs, create a concise ADR in `docs/decisions/` and proceed with the safer, simpler option.

### 29.2 Situations that justify asking the repository owner

Ask only when blocked by one of these:

- The final public product name or trademark policy is required for release.
- The repository license cannot be inferred and packaging requires final legal text.
- Production APT hosting or signing infrastructure must be selected.
- A real Clockify workspace requires behavior that cannot be discovered safely with read-only access or fixtures.
- A destructive live test is proposed.
- A requested behavior conflicts with secret handling, user-data safety, or this file's no-deletion rules.

Continue all unblocked work while documenting the question.

### 29.3 Completion evidence

For every material feature, leave evidence in the repository:

- Tests.
- Demo fixture or UI state when applicable.
- Screenshot after UI changes.
- Updated `docs/STATUS.md`.
- ADR for significant design decisions.
- Clear commit-sized changes.

Do not mark work complete merely because code was written.

### 29.4 No hidden shortcuts

Do not:

- Replace the native UI with Electron, a browser wrapper, or a local web server.
- Put the API key in a command-line flag.
- Generate launchers that call an unstable development path.
- Mock core behavior in production code.
- Disable tests to make CI green.
- Ignore visual defects because headless tests pass.
- Auto-delete unrecognized files.
- Assume a single hard-coded user, home path, workspace, project, tag, or Dribia-specific ID.

## 30. Initial implementation backlog

Start with these tickets in order. Split them further as needed, but do not reorder away the early visual/test harness.

1. Scaffold package, CLI, logging, constants, Makefile, and CI.
2. Create libadwaita shell window with demo state injection.
3. Implement isolated XDG development environment.
4. Implement screenshot harness and inspect first screenshots.
5. Add domain IDs, signatures, account, launcher, candidate, and suggestion models.
6. Add SQLite schema, migrations, repositories, and fake clock.
7. Add libsecret interface, production adapter, and in-memory test fake.
8. Add Clockify API client, response validation, pagination, redaction, and mock transport tests.
9. Build onboarding connection and workspace flow.
10. Build project/task/tag caches and manual launcher editor.
11. Build icon generation and safe selected-image normalization.
12. Build desktop-entry serializer, validation, atomic writer, and disk reconciliation.
13. Build launcher list, CRUD, pinning, delete/restore, and status states.
14. Implement legacy `clockify-cli in` import preview and safe conversion.
15. Implement timer start/stop/switch command and mocked edge cases.
16. Add notifications and current-timer banner.
17. Implement candidate extraction, scoring, thresholds, and duplicate prevention.
18. Implement Assisted additions and removal suggestions.
19. Implement guarded Autopilot removals, tombstones, and activity history.
20. Implement systemd timer enable/disable/interval management.
21. Complete Preferences, diagnostics, and reset flow.
22. Complete AT-SPI tests, large-text checks, narrow screenshots, and visual fixes.
23. Add Debian packaging, validators, Lintian, and smoke install.
24. Add locally signed APT repository test and release documentation.

## 31. Acceptance examples

### 31.1 Manual launcher

Given:

- Project `Tank`.
- Tag `Project`.
- Display name `Kaito`.
- The user chooses a local icon.

When the user saves, the application creates one owned `.desktop` file whose `Exec` contains only the stable launcher UUID. The API key and Clockify IDs are stored in protected application state, not in `Exec`. Clicking `Kaito` starts the matching Clockify timer and shows a success notification.

### 31.2 Assisted addition

Given a signature appears three times in the last 30 days and has no launcher, a complete successful sync creates an automatic unpinned launcher. The activity view explains the evidence. The user may Undo, rename, or pin it.

### 31.3 Assisted removal proposal

Given an automatic launcher has not been used in Clockify or locally for 52 days, Assisted mode creates a removal suggestion but leaves the desktop file intact. Pin dismisses the suggestion permanently unless unpinned.

### 31.4 Autopilot safe removal

Given the same stale launcher in Autopilot mode, and a complete error-free sync, and an unchanged owned file, the application removes the desktop file, preserves a 90-day tombstone, and records the reason. Restore recreates it with the same target and display settings.

### 31.5 Offline sync

Given the network is offline, sync records an offline result, changes no launcher files, creates no stale-removal decisions, and keeps the previous successful-sync timestamp visible.

### 31.6 Externally edited file

Given the user manually edits an owned desktop file after the app created it, reconciliation marks it externally modified and neither overwrites nor deletes it. The UI offers a safe resolution.

### 31.7 Ambiguous timer start

Given the POST request times out after transmission, the application reads the current in-progress entry. If the intended target exists with the expected start time, it reports success. Otherwise it reports that the result is uncertain and does not send another POST automatically.

## 32. Reference specifications

Use primary documentation while implementing:

- Clockify API documentation: `https://docs.clockify.me/`
- PyGObject: `https://pygobject.gnome.org/`
- GTK 4: `https://docs.gtk.org/gtk4/`
- libadwaita: `https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/`
- Desktop Entry Specification: `https://specifications.freedesktop.org/desktop-entry-spec/latest/`
- XDG Base Directory Specification: `https://specifications.freedesktop.org/basedir-spec/latest/`
- systemd timer documentation: `https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html`
- Debian Python packaging and debhelper documentation for the target Ubuntu releases.

Pin behavior to tested API responses rather than examples alone. The Clockify client must be resilient to additive fields and explicit about missing required fields.

## 33. Current assumptions to preserve in ADRs

Record these as initial ADRs rather than repeatedly reopening them:

1. Use direct Clockify REST calls; no runtime dependency on `clockify-cli`.
2. Generated desktop entries call a stable local launcher UUID.
3. Use Assisted mode as the recommended default.
4. Automatic signature identity is project plus optional task plus exact tag set; descriptions are manual-only.
5. Manual and imported launchers are pinned by default.
6. No automatic deletion after any incomplete or uncertain sync.
7. Use GNOME Keyring/libsecret with no plaintext fallback.
8. Use a systemd user oneshot timer, not a resident daemon.
9. Target Ubuntu 24.04 LTS and 26.04 LTS.
10. Build deterministic demo data and screenshot tooling before substantial UI work.
11. Keep required Clockify custom-field editing outside the core MVP unless the target workspace proves it necessary; errors must still be handled correctly.
12. Production APT hosting and signing are external release decisions; local signed-repository verification is required in the codebase.

These assumptions are intentionally conservative and give the coding agent enough authority to begin implementation immediately.
