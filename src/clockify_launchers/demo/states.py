"""Deterministic demo states for screenshots and AT-SPI tests."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from clockify_launchers.demo import fixtures
from clockify_launchers.domain.models import (
    Account,
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementMode,
    Suggestion,
    SuggestionType,
    new_id,
)

if TYPE_CHECKING:
    from clockify_launchers.context import AppContext

DEMO_STATES = (
    "onboarding-welcome",
    "onboarding-key",
    "onboarding-workspace",
    "onboarding-mode",
    "launchers-populated",
    "launchers-empty",
    "launcher-editor",
    "suggestions-add",
    "suggestions-remove",
    "preferences",
    "offline",
    "auth-error",
    "externally-modified",
)


def _connect_demo_account(context: AppContext) -> None:
    now = fixtures.DEMO_NOW
    account = Account(
        id=fixtures.DEMO_ACCOUNT_ID,
        api_base_url="https://api.clockify.me/api",
        clockify_user_id=fixtures.DEMO_USER_ID,
        email=fixtures.DEMO_EMAIL,
        display_name=fixtures.DEMO_NAME,
        active_workspace_id=fixtures.WS_MAIN.id,
        created_at=now,
        last_validated_at=now,
    )
    context.db.save_account(account)
    context.db.cache_workspaces(list(fixtures.WORKSPACES), now)
    context.db.cache_projects(list(fixtures.PROJECTS), now)
    context.db.cache_tasks(list(fixtures.TASKS), now)
    context.db.cache_tags(list(fixtures.TAGS), now)
    context.secrets.store_api_key(account.id, "https://api.clockify.me", account.email, "demo-key")
    config = context.config
    config.active_account_id = account.id
    config.clockify_user_id = account.clockify_user_id
    config.email = account.email
    config.active_workspace_id = account.active_workspace_id
    config.management_mode = ManagementMode.ASSISTED
    config.onboarding_complete = True
    context.save_config(config)


def _populate_launchers(context: AppContext) -> None:
    now = fixtures.DEMO_NOW
    ls = context.launcher_service
    # Manual, pinned, healthy, with task and tag
    tank = ls.create(
        account_id=fixtures.DEMO_ACCOUNT_ID,
        target=LauncherTarget(
            workspace_id=fixtures.WS_MAIN.id,
            project_id="prj-tank",
            task_id="task-model",
            tag_ids=("tag-project",),
        ),
        display_name="Kaito",
        source=LauncherSource.MANUAL,
        now=now,
    )
    context.db.save_launcher(
        tank.with_(
            last_clockify_use_at=now - timedelta(days=1),
            last_start_success_at=now - timedelta(days=1),
        )
    )
    # Imported, pinned, with fixed description
    ls.create(
        account_id=fixtures.DEMO_ACCOUNT_ID,
        target=LauncherTarget(
            workspace_id=fixtures.WS_MAIN.id,
            project_id="prj-ops",
            description="Weekly planning",
        ),
        display_name="Ops planning",
        source=LauncherSource.IMPORTED,
        now=now,
    )
    # Automatic, unpinned, healthy
    research = ls.create(
        account_id=fixtures.DEMO_ACCOUNT_ID,
        target=LauncherTarget(
            workspace_id=fixtures.WS_MAIN.id,
            project_id="prj-research",
            tag_ids=("tag-meeting",),
        ),
        display_name="Research",
        source=LauncherSource.AUTOMATIC,
        now=now - timedelta(days=20),
    )
    context.db.save_launcher(research.with_(last_clockify_use_at=now - timedelta(days=2)))
    # Automatic, unpinned, stale
    stale = ls.create(
        account_id=fixtures.DEMO_ACCOUNT_ID,
        target=LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id="prj-website"),
        display_name="Website",
        source=LauncherSource.AUTOMATIC,
        now=now - timedelta(days=120),
    )
    context.db.save_launcher(
        stale.with_(
            status=LauncherStatus.STALE,
            last_clockify_use_at=now - timedelta(days=70),
            created_at=now - timedelta(days=120),
        )
    )
    # Very long name, no tags, target missing
    longname = ls.create(
        account_id=fixtures.DEMO_ACCOUNT_ID,
        target=LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id="prj-longname"),
        display_name="Extremely Long Project Name That Tests Layout Wrapping Behavior In Rows",
        source=LauncherSource.MANUAL,
        now=now,
    )
    context.db.save_launcher(longname.with_(status=LauncherStatus.TARGET_MISSING))
    # Several more rows to exercise scrolling
    for index in range(6):
        ls.create(
            account_id=fixtures.DEMO_ACCOUNT_ID,
            target=LauncherTarget(
                workspace_id=fixtures.WS_MAIN.id,
                project_id="prj-kaito",
                tag_ids=("tag-support",),
                description=f"Batch item {index + 1}",
            ),
            display_name=f"Support rotation {index + 1}",
            source=LauncherSource.MANUAL,
            now=now,
        )


def _add_suggestions(context: AppContext) -> None:
    now = fixtures.DEMO_NOW
    context.db.save_suggestion(
        Suggestion(
            id=new_id(),
            type=SuggestionType.ADD,
            launcher_id=None,
            target=LauncherTarget(
                workspace_id=fixtures.WS_MAIN.id,
                project_id="prj-tank",
                task_id="task-etl",
                tag_ids=("tag-project",),
            ),
            explanation="Used 5 times in the last 30 days.",
            evidence="Last matching entry: 2026-06-29.",
            created_at=now,
        )
    )


def _remove_suggestions(context: AppContext) -> None:
    now = fixtures.DEMO_NOW
    stale = next(
        (lc for lc in context.db.list_launchers() if lc.status is LauncherStatus.STALE),
        None,
    )
    if stale is not None:
        context.db.save_suggestion(
            Suggestion(
                id=new_id(),
                type=SuggestionType.REMOVE,
                launcher_id=stale.id,
                target=stale.target,
                explanation="Not used in Clockify or from this launcher for 70 days.",
                evidence="Last matching entry: 2026-04-22.",
                created_at=now,
            )
        )


def apply_state(context: AppContext, state: str) -> None:
    if state not in DEMO_STATES:
        raise ValueError(f"unknown demo state: {state!r} (choose from {', '.join(DEMO_STATES)})")

    if state.startswith("onboarding"):
        # Onboarding states start unconfigured; the UI decides the page from state.
        return

    _connect_demo_account(context)

    if state == "launchers-empty":
        return
    if state in ("launchers-populated", "launcher-editor", "preferences", "offline", "auth-error"):
        _populate_launchers(context)
        return
    if state == "suggestions-add":
        _populate_launchers(context)
        _add_suggestions(context)
        return
    if state == "suggestions-remove":
        _populate_launchers(context)
        _remove_suggestions(context)
        return
    if state == "externally-modified":
        _populate_launchers(context)
        launchers = context.db.list_launchers()
        victim = launchers[0]
        if victim.desktop_path:
            from pathlib import Path

            path = Path(victim.desktop_path)
            path.write_text(path.read_text() + "\n# edited by hand\n", encoding="utf-8")
            context.launcher_service.reconcile_disk()
