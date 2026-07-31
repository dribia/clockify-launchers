"""Ordered SQLite schema migrations."""

from __future__ import annotations

import sqlite3

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE accounts (
        id TEXT PRIMARY KEY,
        api_base_url TEXT NOT NULL,
        clockify_user_id TEXT NOT NULL,
        email TEXT NOT NULL,
        display_name TEXT NOT NULL,
        active_workspace_id TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        last_validated_at INTEGER NOT NULL
    );

    CREATE TABLE workspaces (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0,
        last_seen_at INTEGER
    );

    CREATE TABLE projects (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        color TEXT,
        client_name TEXT,
        archived INTEGER NOT NULL DEFAULT 0,
        last_seen_at INTEGER
    );
    CREATE INDEX idx_projects_workspace ON projects(workspace_id);

    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        name TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        last_seen_at INTEGER
    );
    CREATE INDEX idx_tasks_project ON tasks(project_id);

    CREATE TABLE tags (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        archived INTEGER NOT NULL DEFAULT 0,
        last_seen_at INTEGER
    );
    CREATE INDEX idx_tags_workspace ON tags(workspace_id);

    CREATE TABLE launchers (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        workspace_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        task_id TEXT,
        tag_ids TEXT NOT NULL DEFAULT '[]',
        description TEXT,
        display_name TEXT NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        icon_kind TEXT NOT NULL DEFAULT 'generated',
        icon_path TEXT,
        source TEXT NOT NULL,
        management_policy TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_invoked_at INTEGER,
        last_start_success_at INTEGER,
        last_clockify_use_at INTEGER,
        auto_add_grace_until INTEGER,
        removal_snoozed_until INTEGER,
        desktop_path TEXT,
        desktop_hash TEXT,
        icon_hash TEXT,
        removed_at INTEGER,
        removal_reason TEXT
    );
    CREATE INDEX idx_launchers_signature
        ON launchers(workspace_id, project_id, task_id, tag_ids);
    CREATE INDEX idx_launchers_status ON launchers(status);
    CREATE INDEX idx_launchers_last_use ON launchers(last_clockify_use_at);

    CREATE TABLE suggestions (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        launcher_id TEXT,
        workspace_id TEXT,
        project_id TEXT,
        task_id TEXT,
        tag_ids TEXT,
        explanation TEXT NOT NULL,
        evidence TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'open',
        created_at INTEGER NOT NULL,
        dismissed_at INTEGER,
        snoozed_until INTEGER,
        accepted_at INTEGER,
        executed_at INTEGER
    );
    CREATE INDEX idx_suggestions_state ON suggestions(state);

    CREATE TABLE dismissals (
        workspace_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        task_id TEXT,
        tag_ids TEXT NOT NULL,
        dismissed_at INTEGER NOT NULL,
        cooldown_days INTEGER NOT NULL DEFAULT 30,
        PRIMARY KEY (workspace_id, project_id, task_id, tag_ids)
    );

    CREATE TABLE activity_events (
        id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '',
        launcher_id TEXT,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX idx_activity_created ON activity_events(created_at);

    CREATE TABLE tombstones (
        launcher_id TEXT PRIMARY KEY,
        removed_at INTEGER NOT NULL,
        reason TEXT NOT NULL,
        launcher_json TEXT NOT NULL
    );

    CREATE TABLE sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER NOT NULL,
        finished_at INTEGER,
        outcome TEXT,
        safe_to_remove INTEGER,
        detail TEXT
    );
    """,
]


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the resulting schema version."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row[0] if row else 0
    for index, script in enumerate(MIGRATIONS, start=1):
        if index <= current:
            continue
        with conn:
            conn.executescript(script)
            if conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]:
                conn.execute("UPDATE schema_version SET version = ?", (index,))
            else:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (index,))
    return len(MIGRATIONS)
