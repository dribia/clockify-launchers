"""Opt-in, read-only live tests against the real Clockify API.

Skipped unless CLOCKIFY_LIVE_TESTS=1 and CLOCKIFY_API_KEY are set in the
environment. These tests never write to Clockify: they only validate
authentication and list metadata. Write tests are intentionally NOT
implemented; the AGENTS.md contract requires CLOCKIFY_LIVE_WRITE_TESTS and a
dedicated test workspace, which this repository does not configure.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from clockify_launchers import constants
from clockify_launchers.infrastructure.clockify_api import ClockifyClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("CLOCKIFY_LIVE_TESTS") != "1" or not os.environ.get("CLOCKIFY_API_KEY"),
        reason="live tests require CLOCKIFY_LIVE_TESTS=1 and CLOCKIFY_API_KEY",
    ),
]


@pytest.fixture(scope="module")
def client() -> ClockifyClient:
    base = os.environ.get("CLOCKIFY_API_BASE_URL", constants.DEFAULT_API_BASE_URL)
    api_key = os.environ["CLOCKIFY_API_KEY"]
    with ClockifyClient(base, api_key) as c:
        yield c


def test_authenticates_and_returns_user(client: ClockifyClient) -> None:
    user = client.get_current_user()
    assert user["id"]
    assert "email" in user


def test_lists_workspaces(client: ClockifyClient) -> None:
    workspaces = client.get_workspaces()
    assert workspaces, "expected at least one accessible workspace"
    assert all(ws.id and ws.name for ws in workspaces)


def test_lists_projects_tags_and_recent_entries(client: ClockifyClient) -> None:
    user = client.get_current_user()
    workspaces = client.get_workspaces()
    workspace_id = workspaces[0].id
    projects = client.get_projects(workspace_id)
    tags = client.get_tags(workspace_id)
    assert isinstance(projects, list)
    assert isinstance(tags, list)
    now = datetime.now(tz=UTC)
    entries = client.get_time_entries(workspace_id, str(user["id"]), now - timedelta(days=7), now)
    assert isinstance(entries, list)
    # Parsing sanity on whatever real data exists.
    for entry in entries:
        assert entry.id
        assert entry.start.tzinfo is not None


def test_in_progress_entry_parses(client: ClockifyClient) -> None:
    user = client.get_current_user()
    workspaces = client.get_workspaces()
    entry = client.get_in_progress_entry(workspaces[0].id, str(user["id"]))
    assert entry is None or entry.running
