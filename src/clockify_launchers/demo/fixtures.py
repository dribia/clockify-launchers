"""Deterministic demo fixtures.

All IDs, names, and timestamps are fixed so screenshots and AT-SPI tests
are reproducible. The reference "now" is 2026-07-01T12:00:00Z.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clockify_launchers.domain.models import (
    Project,
    Tag,
    Task,
    TimeEntry,
    Workspace,
)

DEMO_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

DEMO_USER_ID = "demo-user-0001"
DEMO_EMAIL = "ada@example.com"
DEMO_NAME = "Ada Demo"
DEMO_ACCOUNT_ID = "aaaaaaaa-0000-0000-0000-000000000001"

WS_MAIN = Workspace(id="ws-example", name="Example Workspace")
WS_SIDE = Workspace(id="ws-personal", name="Personal")

WORKSPACES = [WS_MAIN, WS_SIDE]

PROJECTS = [
    Project(
        id="prj-alpha",
        workspace_id=WS_MAIN.id,
        name="Alpha",
        color="#03A9F4",
        client_name="Acme Corp",
    ),
    Project(id="prj-beta", workspace_id=WS_MAIN.id, name="Beta", color="#8BC34A"),
    Project(
        id="prj-longname",
        workspace_id=WS_MAIN.id,
        name="Extremely Long Project Name That Tests Layout Wrapping Behavior In Rows",
        color="#9C27B0",
    ),
    Project(id="prj-ops", workspace_id=WS_MAIN.id, name="Team Operations", color="#FF9800"),
    Project(id="prj-research", workspace_id=WS_MAIN.id, name="Research", color="#009688"),
    Project(id="prj-website", workspace_id=WS_MAIN.id, name="Website", color="#E91E63"),
    Project(id="prj-archived", workspace_id=WS_MAIN.id, name="Old Archive", archived=True),
]

TASKS = [
    Task(id="task-model", project_id="prj-alpha", name="Model training"),
    Task(id="task-etl", project_id="prj-alpha", name="ETL pipeline"),
    Task(id="task-report", project_id="prj-beta", name="Quarterly report"),
    Task(id="task-inactive", project_id="prj-beta", name="Legacy work", active=False),
]

TAGS = [
    Tag(id="tag-project", workspace_id=WS_MAIN.id, name="Project"),
    Tag(id="tag-meeting", workspace_id=WS_MAIN.id, name="Meeting"),
    Tag(id="tag-support", workspace_id=WS_MAIN.id, name="Support"),
    Tag(id="tag-archived", workspace_id=WS_MAIN.id, name="Deprecated", archived=True),
]


def _entry(
    entry_id: str,
    project_id: str,
    days_ago: float,
    duration_hours: float = 1.5,
    task_id: str | None = None,
    tag_ids: tuple[str, ...] = (),
    description: str = "",
) -> TimeEntry:
    start = DEMO_NOW - timedelta(days=days_ago)
    return TimeEntry(
        id=entry_id,
        workspace_id=WS_MAIN.id,
        project_id=project_id,
        task_id=task_id,
        tag_ids=tag_ids,
        description=description,
        start=start,
        end=start + timedelta(hours=duration_hours),
    )


def demo_time_entries() -> list[TimeEntry]:
    """Recent activity supporting add-suggestions and staleness scenarios."""
    entries = []
    # Frequent recent target: Alpha / Model training / Project tag (add candidate)
    for index in range(6):
        entries.append(
            _entry(
                f"te-alpha-{index}",
                "prj-alpha",
                days_ago=1 + index * 3,
                task_id="task-model",
                tag_ids=("tag-project",),
            )
        )
    # Another candidate: Research, no task, meeting tag
    for index in range(3):
        entries.append(
            _entry(
                f"te-res-{index}", "prj-research", days_ago=2 + index * 5, tag_ids=("tag-meeting",)
            )
        )
    # Occasional use, below threshold
    entries.append(_entry("te-web-0", "prj-website", days_ago=40))
    # Entry without project (excluded)
    entries.append(
        TimeEntry(
            id="te-noproj",
            workspace_id=WS_MAIN.id,
            project_id=None,
            task_id=None,
            tag_ids=(),
            description="misc",
            start=DEMO_NOW - timedelta(days=1),
            end=DEMO_NOW - timedelta(days=1) + timedelta(hours=1),
        )
    )
    return entries
