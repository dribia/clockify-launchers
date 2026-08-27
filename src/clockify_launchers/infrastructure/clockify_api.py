"""Typed Clockify REST API client.

- API key is sent only in the ``X-Api-Key`` header, never logged.
- GET requests retry conservatively on connection errors, 429, and 5xx.
- POST/PATCH are never blindly retried.
- All responses are validated; additive unknown fields are ignored.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from clockify_launchers import constants
from clockify_launchers.domain.models import Project, Tag, Task, TimeEntry, Workspace

log = logging.getLogger(__name__)

PAGE_SIZE = 200
MAX_PAGES = 50
MAX_GET_RETRIES = 3
CONNECT_TIMEOUT = 10.0
RW_TIMEOUT = 30.0


# -- errors ----------------------------------------------------------------


class ClockifyError(Exception):
    """Base class; message is always safe to show and log."""


class AuthError(ClockifyError): ...


class PermissionError_(ClockifyError): ...


class NotFoundError(ClockifyError): ...


class ValidationFailedError(ClockifyError): ...


class RequiredCustomFieldError(ValidationFailedError): ...


class RateLimitedError(ClockifyError): ...


class OfflineError(ClockifyError): ...


class AmbiguousResultError(ClockifyError):
    """A write may or may not have reached the server."""


class ServerError(ClockifyError): ...


class UnexpectedResponseError(ClockifyError): ...


class PaginationIncompleteError(ClockifyError): ...


# -- URL normalization -----------------------------------------------------


def normalize_base_url(url: str, allow_http: bool = False) -> str:
    """Normalize and validate an API base URL; raises ValueError when unsafe."""
    url = url.strip().rstrip("/")
    if not url:
        raise ValueError("empty URL")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise ValueError(f"unsupported scheme: {parts.scheme!r}")
    if parts.scheme == "http" and not allow_http:
        raise ValueError("HTTPS is required")
    if parts.username or parts.password:
        raise ValueError("embedded credentials are not allowed")
    if parts.query or parts.fragment:
        raise ValueError("query strings and fragments are not allowed")
    if not parts.hostname:
        raise ValueError("missing host")
    path = parts.path.rstrip("/")
    if path not in ("", "/api", "/api/v1"):
        raise ValueError(f"unexpected path: {path!r}")
    if path == "/api/v1":
        path = "/api"
    if not path:
        path = "/api"
    netloc = parts.hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return f"{parts.scheme}://{netloc}{path}"


def region_base_url(region: str | None) -> str:
    """Base URL for a known Clockify region prefix, or the global default."""
    if not region:
        return constants.DEFAULT_API_BASE_URL
    region = region.strip().lower()
    if region not in constants.KNOWN_REGION_PREFIXES:
        raise ValueError(f"unknown region: {region!r}")
    return f"https://{region}.api.clockify.me/api"


def redact(text: str, api_key: str | None) -> str:
    if api_key and api_key in text:
        return text.replace(api_key, "***REDACTED***")
    return text


# -- parsing helpers -------------------------------------------------------


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def format_dt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _req_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise UnexpectedResponseError(f"missing required field {key!r}")
    return value


def _parse_time_entry(data: dict[str, Any]) -> TimeEntry:
    interval = data.get("timeInterval") or {}
    if not isinstance(interval, dict):
        raise UnexpectedResponseError("timeInterval is not an object")
    start = _parse_dt(interval.get("start"))
    if start is None:
        raise UnexpectedResponseError("time entry missing start")
    tag_ids = data.get("tagIds") or []
    if not isinstance(tag_ids, list):
        tag_ids = []
    entry_type = data.get("type")
    return TimeEntry(
        id=_req_str(data, "id"),
        workspace_id=_req_str(data, "workspaceId"),
        project_id=data.get("projectId") or None,
        task_id=data.get("taskId") or None,
        tag_ids=tuple(sorted(str(t) for t in tag_ids)),
        description=str(data.get("description") or ""),
        start=start,
        end=_parse_dt(interval.get("end")),
        is_break=(entry_type == "BREAK"),
    )


# -- client ----------------------------------------------------------------


class ClockifyClientProtocol(Protocol):
    """Read/write surface shared by the real client and test/demo fakes."""

    def close(self) -> None: ...

    def get_current_user(self) -> dict[str, Any]: ...

    def get_workspaces(self) -> list[Workspace]: ...

    def get_projects(self, workspace_id: str, archived: bool = False) -> list[Project]: ...

    def get_project(self, workspace_id: str, project_id: str) -> Project: ...

    def get_tags(self, workspace_id: str) -> list[Tag]: ...

    def get_tasks(self, workspace_id: str, project_id: str) -> list[Task]: ...

    def get_time_entries(
        self, workspace_id: str, user_id: str, start: datetime, end: datetime
    ) -> list[TimeEntry]: ...

    def get_in_progress_entry(self, workspace_id: str, user_id: str) -> TimeEntry | None: ...

    def start_time_entry(
        self,
        workspace_id: str,
        project_id: str,
        start: datetime,
        task_id: str | None = None,
        tag_ids: tuple[str, ...] = (),
        description: str | None = None,
        billable: bool | None = None,
    ) -> TimeEntry: ...

    def stop_current_entry(
        self, workspace_id: str, user_id: str, end: datetime
    ) -> TimeEntry | None: ...


class ClockifyClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self._base_url = normalize_base_url(base_url, allow_http=transport is not None)
        self._api_key = api_key
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=self._base_url + "/v1",
            headers={
                "X-Api-Key": api_key,
                "User-Agent": constants.USER_AGENT,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(RW_TIMEOUT, connect=CONNECT_TIMEOUT),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ClockifyClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level ---------------------------------------------------------

    def _raise_for_status(self, response: httpx.Response) -> None:
        code = response.status_code
        if code < 400:
            return
        body = ""
        try:
            body = redact(response.text[:500], self._api_key)
        except Exception:  # pragma: no cover - defensive
            body = "<unreadable>"
        if code == 401:
            raise AuthError("Clockify rejected the API key.")
        if code == 403:
            raise PermissionError_("Clockify denied permission for this request.")
        if code == 404:
            raise NotFoundError("The requested Clockify resource was not found.")
        if code == 429:
            raise RateLimitedError("Rate limited by Clockify.")
        if code in (400, 409, 422):
            if "custom" in body.lower() and "field" in body.lower():
                raise RequiredCustomFieldError(
                    "Clockify requires a custom field this launcher does not provide."
                )
            raise ValidationFailedError(f"Clockify rejected the request: {body}")
        if code >= 500:
            raise ServerError(f"Clockify server error (HTTP {code}).")
        raise UnexpectedResponseError(f"Unexpected HTTP {code}: {body}")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(MAX_GET_RETRIES + 1):
            if attempt:
                retry_after = 0.0
                if isinstance(last_exc, _RetryableStatus):
                    retry_after = last_exc.retry_after
                delay = max(retry_after, min(8.0, (2.0**attempt) * 0.25)) + random.uniform(0, 0.25)  # noqa: S311
                self._sleep(delay)
            try:
                response = self._client.get(path, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = 0.0
                header = response.headers.get("Retry-After")
                if header and header.isdigit():
                    retry_after = float(header)
                last_exc = _RetryableStatus(response, retry_after)
                continue
            self._raise_for_status(response)
            try:
                return response.json()
            except ValueError as exc:
                raise UnexpectedResponseError("Clockify returned invalid JSON.") from exc
        if isinstance(last_exc, _RetryableStatus):
            self._raise_for_status(last_exc.response)
        raise OfflineError("Could not reach Clockify (network problem or timeout).") from last_exc

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        results: list[Any] = []
        params = dict(params or {})
        params["page-size"] = PAGE_SIZE
        for page in range(1, MAX_PAGES + 1):
            params["page"] = page
            data = self._get(path, params=params)
            if not isinstance(data, list):
                raise UnexpectedResponseError("expected a JSON array")
            results.extend(data)
            if len(data) < PAGE_SIZE:
                return results
        raise PaginationIncompleteError(
            f"more than {MAX_PAGES * PAGE_SIZE} results; refusing incomplete data"
        )

    # -- read operations ----------------------------------------------------

    def get_current_user(self) -> dict[str, Any]:
        data = self._get("/user", params={"include-memberships": "true"})
        if not isinstance(data, dict):
            raise UnexpectedResponseError("user response is not an object")
        _req_str(data, "id")
        return data

    def get_workspaces(self) -> list[Workspace]:
        data = self._get("/workspaces")
        if not isinstance(data, list):
            raise UnexpectedResponseError("workspaces response is not an array")
        return [
            Workspace(id=_req_str(w, "id"), name=str(w.get("name") or w["id"]))
            for w in data
            if isinstance(w, dict)
        ]

    def get_projects(self, workspace_id: str, archived: bool = False) -> list[Project]:
        raw = self._paginate(
            f"/workspaces/{workspace_id}/projects",
            params={"archived": "true" if archived else "false"},
        )
        projects = []
        for p in raw:
            if not isinstance(p, dict):
                continue
            client_name = p.get("clientName") or None
            projects.append(
                Project(
                    id=_req_str(p, "id"),
                    workspace_id=workspace_id,
                    name=str(p.get("name") or p["id"]),
                    color=p.get("color") or None,
                    client_name=client_name,
                    archived=bool(p.get("archived", False)),
                    billable_by_default=bool(p.get("billable", False)),
                )
            )
        return projects

    def get_project(self, workspace_id: str, project_id: str) -> Project:
        p = self._get(f"/workspaces/{workspace_id}/projects/{project_id}")
        if not isinstance(p, dict):
            raise UnexpectedResponseError("project response is not an object")
        return Project(
            id=_req_str(p, "id"),
            workspace_id=workspace_id,
            name=str(p.get("name") or p["id"]),
            color=p.get("color") or None,
            client_name=p.get("clientName") or None,
            archived=bool(p.get("archived", False)),
            billable_by_default=bool(p.get("billable", False)),
        )

    def get_tags(self, workspace_id: str) -> list[Tag]:
        raw = self._paginate(f"/workspaces/{workspace_id}/tags")
        return [
            Tag(
                id=_req_str(t, "id"),
                workspace_id=workspace_id,
                name=str(t.get("name") or t["id"]),
                archived=bool(t.get("archived", False)),
            )
            for t in raw
            if isinstance(t, dict)
        ]

    def get_tasks(self, workspace_id: str, project_id: str) -> list[Task]:
        raw = self._paginate(f"/workspaces/{workspace_id}/projects/{project_id}/tasks")
        return [
            Task(
                id=_req_str(t, "id"),
                project_id=project_id,
                name=str(t.get("name") or t["id"]),
                active=(t.get("status", "ACTIVE") == "ACTIVE"),
            )
            for t in raw
            if isinstance(t, dict)
        ]

    def get_time_entries(
        self, workspace_id: str, user_id: str, start: datetime, end: datetime
    ) -> list[TimeEntry]:
        """Return the user's time entries overlapping ``[start, end]``.

        Clockify interprets the ``start``/``end`` query parameters in the
        user's profile timezone even though the documented format is UTC
        (observed live: with a +02:00 profile, ``end=now`` excluded every
        entry of the last two hours). The request window is therefore
        padded by a full day on each side - larger than any UTC offset -
        and the exact bounds are applied client-side, so the result is
        correct regardless of how the server reads the parameters.
        """
        pad = timedelta(days=1)
        raw = self._paginate(
            f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
            params={"start": format_dt(start - pad), "end": format_dt(end + pad)},
        )
        entries = [_parse_time_entry(e) for e in raw if isinstance(e, dict)]
        return [
            e for e in entries if e.start <= end and (e.end is None or e.end >= start)
        ]

    def get_in_progress_entry(self, workspace_id: str, user_id: str) -> TimeEntry | None:
        data = self._get(
            f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
            params={"in-progress": "true"},
        )
        if not isinstance(data, list):
            raise UnexpectedResponseError("in-progress response is not an array")
        entries = [_parse_time_entry(e) for e in data if isinstance(e, dict)]
        running = [e for e in entries if e.running]
        return running[0] if running else None

    # -- write operations (timer only) --------------------------------------

    def start_time_entry(
        self,
        workspace_id: str,
        project_id: str,
        start: datetime,
        task_id: str | None = None,
        tag_ids: tuple[str, ...] = (),
        description: str | None = None,
        billable: bool | None = None,
    ) -> TimeEntry:
        payload: dict[str, Any] = {"start": format_dt(start), "projectId": project_id}
        if task_id:
            payload["taskId"] = task_id
        if tag_ids:
            payload["tagIds"] = list(tag_ids)
        if description:
            payload["description"] = description
        if billable is not None:
            payload["billable"] = billable
        try:
            response = self._client.post(f"/workspaces/{workspace_id}/time-entries", json=payload)
        except httpx.ConnectError as exc:
            raise OfflineError("Could not reach Clockify to start the timer.") from exc
        except httpx.TimeoutException as exc:
            raise AmbiguousResultError(
                "The start request timed out; the timer may or may not have started."
            ) from exc
        self._raise_for_status(response)
        data = response.json()
        if not isinstance(data, dict):
            raise UnexpectedResponseError("start response is not an object")
        return _parse_time_entry(data)

    def stop_current_entry(
        self, workspace_id: str, user_id: str, end: datetime
    ) -> TimeEntry | None:
        try:
            response = self._client.patch(
                f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
                json={"end": format_dt(end)},
            )
        except httpx.ConnectError as exc:
            raise OfflineError("Could not reach Clockify to stop the timer.") from exc
        except httpx.TimeoutException as exc:
            raise AmbiguousResultError(
                "The stop request timed out; the timer may or may not have stopped."
            ) from exc
        if response.status_code == 404:
            return None  # no running entry: defined no-op
        self._raise_for_status(response)
        data = response.json()
        if not isinstance(data, dict):
            raise UnexpectedResponseError("stop response is not an object")
        return _parse_time_entry(data)


class _RetryableStatus(Exception):
    def __init__(self, response: httpx.Response, retry_after: float) -> None:
        super().__init__(f"retryable HTTP {response.status_code}")
        self.response = response
        self.retry_after = retry_after
