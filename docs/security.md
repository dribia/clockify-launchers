# Security

These rules override convenience. See AGENTS.md sections 10, 16, and 26 for
the authoritative brief.

## Secret handling

- The Clockify API key is stored only in GNOME Keyring through libsecret
  (`infrastructure/secret_store.py`), using a fixed secret schema with
  nonsecret attributes (`application`, `account_id`, `api_origin`).
- There is **no plaintext fallback**. If Secret Service is unavailable or
  locked, the app explains the problem and preserves existing configuration
  and launchers; background sync records a credential-unavailable result and
  exits without changing anything.
- The key is sent only in the `X-Api-Key` request header
  (`infrastructure/clockify_api.py`). Redaction is centralized so exceptions
  and debug logs cannot expose keys, authorization headers, or raw HTTP
  bodies.
- The key is never written to desktop entries, JSON, SQLite, logs, command
  lines, or process environments of the installed application.

## File ownership and deletion safety

A desktop file is treated as owned only when **all** hold:

- Filename starts with `com.dribia.ClockifyLaunchers.` and ends with `.desktop`.
- It contains `X-Clockify-Launchers-Managed=true`.
- It contains a valid `X-Clockify-Launchers-Id` known to application state.

Deletion additionally requires that the on-disk hash matches the hash last
written by the application. Externally modified owned files are flagged and
never overwritten or deleted automatically. Files are only ever deleted
inside the user's XDG application directory; symlinks are not followed when
replacing or deleting managed files; writes are atomic (temp file, fsync,
`os.replace`).

## No-shell rule

The application never invokes a shell — not for Clockify actions, systemctl
calls, file-manager launches, or parsing. Generated `Exec` lines contain only
the stable executable path and a launcher UUID; user-provided text never
enters `Exec`.

## Import safety

Legacy launcher import (`services/import_service.py`) parses desktop entries
as key files and tokenizes `Exec` with `shlex.split(posix=True)` — it never
executes anything. Only plain `clockify-cli in ...` invocations with known
flags are accepted; shell metacharacters, substitutions, redirects,
environment assignments, and unknown shapes are rejected. Original files are
left untouched until the replacement is validated and atomically installed.

## No deletion on uncertainty

A reconciliation run's `safe_to_remove` flag is cleared by any uncertainty:
missing API key, HTTP failure or rate limiting, incomplete pagination,
response validation failure, database write failure, undeterminable target
state, concurrent launcher action, or an externally modified owned file.
Autopilot removals also require the launcher to be unpinned, unsnoozed,
outside its grace period, stale by threshold, and unused after sync began —
and every removal leaves a restorable tombstone.
