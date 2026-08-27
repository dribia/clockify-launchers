"""Contract tests for the Clockify API client (AGENTS.md sections 13, 22.2).

All HTTP is served by httpx.MockTransport; no test contacts the network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from clockify_launchers.infrastructure.clockify_api import (
    MAX_GET_RETRIES,
    MAX_PAGES,
    PAGE_SIZE,
    AmbiguousResultError,
    AuthError,
    ClockifyClient,
    NotFoundError,
    OfflineError,
    PaginationIncompleteError,
    PermissionError_,
    RateLimitedError,
    RequiredCustomFieldError,
    ServerError,
    UnexpectedResponseError,
)

BASE = "http://testserver/api"
KEY = "test-api-key"


def make_client(handler, base_url: str = BASE, sleep=None):
    recorded: list[float] = []
    if sleep is None:
        sleep = recorded.append
    client = ClockifyClient(
        base_url,
        KEY,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )
    return client, recorded


def json_response(data, status_code: int = 200, headers=None) -> httpx.Response:
    return httpx.Response(status_code, json=data, headers=headers)


# -- get_current_user and error mapping -------------------------------------


def test_get_current_user_success_parses_and_sends_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response({"id": "user-1", "email": "a@b.c", "name": "A", "extra": 1})

    client, _ = make_client(handler)
    user = client.get_current_user()
    assert user["id"] == "user-1"
    assert user["email"] == "a@b.c"
    req = seen[0]
    assert req.url.path == "/api/v1/user"
    assert req.url.params["include-memberships"] == "true"
    assert req.headers["X-Api-Key"] == KEY


@pytest.mark.parametrize(
    ("status", "exc"),
    [(401, AuthError), (403, PermissionError_), (404, NotFoundError)],
)
def test_get_status_error_mapping(status, exc):
    client, _ = make_client(lambda request: json_response({"message": "no"}, status))
    with pytest.raises(exc):
        client.get_current_user()


def test_429_retried_respecting_retry_after_then_rate_limited():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return json_response({"message": "slow down"}, 429, headers={"Retry-After": "3"})

    client, sleeps = make_client(handler)
    with pytest.raises(RateLimitedError):
        client.get_current_user()
    assert len(calls) == MAX_GET_RETRIES + 1
    assert len(sleeps) == MAX_GET_RETRIES
    # every backoff delay must honor the Retry-After header value
    assert all(delay >= 3.0 for delay in sleeps)


def test_500_retried_then_server_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return json_response({"message": "boom"}, 500)

    client, sleeps = make_client(handler)
    with pytest.raises(ServerError):
        client.get_current_user()
    assert len(calls) == MAX_GET_RETRIES + 1
    assert len(sleeps) == MAX_GET_RETRIES


def test_malformed_json_raises_unexpected_response():
    client, _ = make_client(
        lambda request: httpx.Response(
            200, content=b"not-json{", headers={"Content-Type": "application/json"}
        )
    )
    with pytest.raises(UnexpectedResponseError):
        client.get_current_user()


def test_connect_error_maps_to_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, sleeps = make_client(handler)
    with pytest.raises(OfflineError):
        client.get_current_user()
    assert len(sleeps) == MAX_GET_RETRIES


# -- pagination ---------------------------------------------------------------


def _entry(i: int) -> dict:
    return {
        "id": f"te-{i}",
        "workspaceId": "ws1",
        "projectId": "p1",
        "tagIds": [],
        "description": "",
        "timeInterval": {"start": "2026-07-01T10:00:00Z", "end": "2026-07-01T11:00:00Z"},
    }


def test_get_time_entries_paginates_and_sends_page_params():
    seen_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen_params.append(params)
        page = int(params["page"])
        if page == 1:
            return json_response([_entry(i) for i in range(PAGE_SIZE)])
        return json_response([_entry(PAGE_SIZE), _entry(PAGE_SIZE + 1)])

    client, _ = make_client(handler)
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 7, 31, tzinfo=UTC)
    entries = client.get_time_entries("ws1", "user-1", start, end)
    assert len(entries) == PAGE_SIZE + 2
    assert [p["page"] for p in seen_params] == ["1", "2"]
    assert all(p["page-size"] == str(PAGE_SIZE) for p in seen_params)
    # The request window is padded by one day on each side because Clockify
    # interprets the parameters in the user's profile timezone; exact bounds
    # are applied client-side.
    assert seen_params[0]["start"] == "2026-05-31T00:00:00Z"
    assert seen_params[0]["end"] == "2026-08-01T00:00:00Z"


def test_get_time_entries_filters_to_overlap_client_side():
    payload = [
        {  # ends before the window: dropped
            "id": "before",
            "workspaceId": "ws1",
            "projectId": "p1",
            "timeInterval": {"start": "2026-05-30T08:00:00Z", "end": "2026-05-31T09:00:00Z"},
        },
        {  # straddles the window start: kept
            "id": "straddle",
            "workspaceId": "ws1",
            "projectId": "p1",
            "timeInterval": {"start": "2026-05-31T23:00:00Z", "end": "2026-06-01T01:00:00Z"},
        },
        {  # inside: kept
            "id": "inside",
            "workspaceId": "ws1",
            "projectId": "p1",
            "timeInterval": {"start": "2026-06-10T10:00:00Z", "end": "2026-06-10T11:00:00Z"},
        },
        {  # running, started inside the window: kept
            "id": "running",
            "workspaceId": "ws1",
            "projectId": "p1",
            "timeInterval": {"start": "2026-06-15T10:00:00Z", "end": None},
        },
        {  # starts after the window end: dropped
            "id": "after",
            "workspaceId": "ws1",
            "projectId": "p1",
            "timeInterval": {"start": "2026-07-02T10:00:00Z", "end": "2026-07-02T11:00:00Z"},
        },
    ]
    client, _ = make_client(lambda request: json_response(payload))
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 7, 1, tzinfo=UTC)
    entries = client.get_time_entries("ws1", "user-1", start, end)
    assert [e.id for e in entries] == ["straddle", "inside", "running"]


def test_pagination_max_pages_guard():
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([_entry(i) for i in range(PAGE_SIZE)])

    client, _ = make_client(handler)
    start = datetime(2026, 6, 1, tzinfo=UTC)
    with pytest.raises(PaginationIncompleteError):
        client.get_time_entries("ws1", "user-1", start, start)


def test_get_time_entries_empty_list_ok():
    client, _ = make_client(lambda request: json_response([]))
    start = datetime(2026, 6, 1, tzinfo=UTC)
    assert client.get_time_entries("ws1", "user-1", start, start) == []


def test_pagination_stops_after_expected_pages_max_guard_boundary():
    # exactly MAX_PAGES full pages -> guard fires (cannot prove completeness)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return json_response([{"id": f"t-{len(calls)}-{i}", "name": "x"} for i in range(PAGE_SIZE)])

    client, _ = make_client(handler)
    with pytest.raises(PaginationIncompleteError):
        client.get_tags("ws1")
    assert len(calls) == MAX_PAGES


# -- metadata parsing ---------------------------------------------------------


def test_get_projects_parses_archived_flag_and_fields():
    payload = [
        {
            "id": "p1",
            "name": "Tank",
            "color": "#03A9F4",
            "clientName": "Dribia",
            "archived": False,
            "billable": True,
        },
        {"id": "p2", "name": "Old", "archived": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workspaces/ws1/projects"
        assert request.url.params["archived"] == "false"
        return json_response(payload)

    client, _ = make_client(handler)
    projects = client.get_projects("ws1")
    assert [p.id for p in projects] == ["p1", "p2"]
    assert projects[0].name == "Tank"
    assert projects[0].color == "#03A9F4"
    assert projects[0].client_name == "Dribia"
    assert projects[0].archived is False
    assert projects[0].billable_by_default is True
    assert projects[1].archived is True
    assert projects[1].billable_by_default is False
    assert all(p.workspace_id == "ws1" for p in projects)


def test_get_tags_parses_archived_flag():
    payload = [
        {"id": "t1", "name": "Project", "archived": False},
        {"id": "t2", "name": "Gone", "archived": True},
    ]
    client, _ = make_client(lambda request: json_response(payload))
    tags = client.get_tags("ws1")
    assert [(t.id, t.name, t.archived) for t in tags] == [
        ("t1", "Project", False),
        ("t2", "Gone", True),
    ]


def test_get_tasks_status_active_and_done():
    payload = [
        {"id": "k1", "name": "Build", "status": "ACTIVE"},
        {"id": "k2", "name": "Ship", "status": "DONE"},
        {"id": "k3", "name": "NoStatus"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workspaces/ws1/projects/p1/tasks"
        return json_response(payload)

    client, _ = make_client(handler)
    tasks = client.get_tasks("ws1", "p1")
    assert [(t.id, t.active) for t in tasks] == [("k1", True), ("k2", False), ("k3", True)]
    assert all(t.project_id == "p1" for t in tasks)


# -- in-progress entry ---------------------------------------------------------


def test_get_in_progress_entry_returns_running_entry():
    payload = [
        {
            "id": "te-run",
            "workspaceId": "ws1",
            "projectId": "p1",
            "taskId": "k1",
            "tagIds": ["t2", "t1"],
            "description": "work",
            "timeInterval": {"start": "2026-07-31T09:00:00Z", "end": None},
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["in-progress"] == "true"
        return json_response(payload)

    client, _ = make_client(handler)
    entry = client.get_in_progress_entry("ws1", "user-1")
    assert entry is not None
    assert entry.id == "te-run"
    assert entry.running is True
    assert entry.tag_ids == ("t1", "t2")  # sorted


def test_get_in_progress_entry_none_when_empty_or_completed():
    client, _ = make_client(lambda request: json_response([]))
    assert client.get_in_progress_entry("ws1", "user-1") is None

    client, _ = make_client(lambda request: json_response([_entry(1)]))  # completed entry
    assert client.get_in_progress_entry("ws1", "user-1") is None


# -- start_time_entry ------------------------------------------------------------


def _started_payload(payload: dict) -> dict:
    return {
        "id": "te-new",
        "workspaceId": "ws1",
        "projectId": payload["projectId"],
        "taskId": payload.get("taskId"),
        "tagIds": payload.get("tagIds", []),
        "description": payload.get("description", ""),
        "timeInterval": {"start": payload["start"], "end": None},
    }


def test_start_time_entry_payload_contents():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/workspaces/ws1/time-entries"
        payload = json.loads(request.content)
        seen.append(payload)
        return json_response(_started_payload(payload), 201)

    client, _ = make_client(handler)
    start = datetime(2026, 7, 31, 12, 34, 56, 789000, tzinfo=UTC)
    entry = client.start_time_entry(
        "ws1", "p1", start, task_id="k1", tag_ids=("t1", "t2"), description="fix", billable=True
    )
    payload = seen[0]
    assert payload == {
        "start": "2026-07-31T12:34:56Z",
        "projectId": "p1",
        "taskId": "k1",
        "tagIds": ["t1", "t2"],
        "description": "fix",
        "billable": True,
    }
    assert entry.id == "te-new"
    assert entry.running is True


def test_start_time_entry_omits_optional_fields():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        return json_response(_started_payload(payload), 201)

    client, _ = make_client(handler)
    client.start_time_entry("ws1", "p1", datetime(2026, 7, 31, tzinfo=UTC))
    assert set(seen[0]) == {"start", "projectId"}


def test_start_time_entry_sends_explicit_billable_false():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        return json_response(_started_payload(payload), 201)

    client, _ = make_client(handler)
    client.start_time_entry("ws1", "p1", datetime(2026, 7, 31, tzinfo=UTC), billable=False)
    assert seen[0]["billable"] is False


def test_start_time_entry_timeout_is_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client, _ = make_client(handler)
    with pytest.raises(AmbiguousResultError):
        client.start_time_entry("ws1", "p1", datetime(2026, 7, 31, tzinfo=UTC))


def test_start_time_entry_connect_error_is_offline():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(handler)
    with pytest.raises(OfflineError):
        client.start_time_entry("ws1", "p1", datetime(2026, 7, 31, tzinfo=UTC))


def test_start_time_entry_required_custom_field_error():
    body = {"message": "A required custom field 'Location' is missing.", "code": 4030}
    client, _ = make_client(lambda request: json_response(body, 400))
    with pytest.raises(RequiredCustomFieldError):
        client.start_time_entry("ws1", "p1", datetime(2026, 7, 31, tzinfo=UTC))


def test_start_time_entry_post_not_retried_on_5xx():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return json_response({"message": "boom"}, 500)

    client, sleeps = make_client(handler)
    with pytest.raises(ServerError):
        client.start_time_entry("ws1", "p1", datetime(2026, 7, 31, tzinfo=UTC))
    assert len(calls) == 1
    assert sleeps == []


# -- stop_current_entry ------------------------------------------------------------


def test_stop_current_entry_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/v1/workspaces/ws1/user/user-1/time-entries"
        payload = json.loads(request.content)
        assert payload == {"end": "2026-07-31T13:00:00Z"}
        return json_response(
            {
                "id": "te-old",
                "workspaceId": "ws1",
                "projectId": "p1",
                "tagIds": [],
                "timeInterval": {"start": "2026-07-31T12:00:00Z", "end": payload["end"]},
            }
        )

    client, _ = make_client(handler)
    entry = client.stop_current_entry("ws1", "user-1", datetime(2026, 7, 31, 13, tzinfo=UTC))
    assert entry is not None
    assert entry.id == "te-old"
    assert entry.running is False


def test_stop_current_entry_404_is_noop_none():
    client, _ = make_client(lambda request: json_response({"message": "nothing running"}, 404))
    assert client.stop_current_entry("ws1", "user-1", datetime(2026, 7, 31, tzinfo=UTC)) is None


# -- regional base URLs ------------------------------------------------------------


def test_regional_base_url_builds_correct_request_urls():
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return json_response({"id": "user-1"})

    client, _ = make_client(handler, base_url="https://euc1.api.clockify.me/api")
    client.get_current_user()
    url = seen[0]
    assert url.scheme == "https"
    assert url.host == "euc1.api.clockify.me"
    assert url.path == "/api/v1/user"
