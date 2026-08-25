"""Domain models.

Models are immutable dataclasses; identifiers received from Clockify are
opaque strings. All timestamps are timezone-aware UTC datetimes.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class ManagementMode(enum.StrEnum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTOPILOT = "autopilot"


class LauncherSource(enum.StrEnum):
    MANUAL = "manual"
    IMPORTED = "imported"
    AUTOMATIC = "automatic"


class ManagementPolicy(enum.StrEnum):
    PINNED = "pinned"
    MANAGED = "managed"


class LauncherStatus(enum.StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    TARGET_MISSING = "target-missing"
    EXTERNALLY_MODIFIED = "externally-modified"
    PENDING_REMOVAL = "pending-removal"
    REMOVED = "removed"
    ERROR = "error"


class IconKind(enum.StrEnum):
    GENERATED = "generated"
    SELECTED = "selected"
    LEGACY = "legacy"


class SuggestionType(enum.StrEnum):
    ADD = "add"
    REMOVE = "remove"


class SuggestionState(enum.StrEnum):
    OPEN = "open"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    ACCEPTED = "accepted"
    EXECUTED = "executed"


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    api_base_url: str
    clockify_user_id: str
    email: str
    display_name: str
    active_workspace_id: str
    created_at: datetime
    last_validated_at: datetime


@dataclass(frozen=True, slots=True)
class Workspace:
    id: str
    name: str
    archived: bool = False
    last_seen_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    workspace_id: str
    name: str
    color: str | None = None
    client_name: str | None = None
    archived: bool = False
    billable_by_default: bool = False


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    project_id: str
    name: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class Tag:
    id: str
    workspace_id: str
    name: str
    archived: bool = False


@dataclass(frozen=True, slots=True)
class LauncherTarget:
    """The Clockify target a launcher starts."""

    workspace_id: str
    project_id: str
    task_id: str | None = None
    tag_ids: tuple[str, ...] = ()
    description: str | None = None

    def __post_init__(self) -> None:
        normalized = tuple(sorted(set(self.tag_ids)))
        object.__setattr__(self, "tag_ids", normalized)
        if self.description is not None and not self.description.strip():
            object.__setattr__(self, "description", None)

    @property
    def signature(self) -> tuple[str, str, str | None, tuple[str, ...]]:
        """Automatic identity: description is deliberately excluded."""
        return (self.workspace_id, self.project_id, self.task_id, self.tag_ids)


@dataclass(frozen=True, slots=True)
class Launcher:
    id: str
    account_id: str
    target: LauncherTarget
    display_name: str
    comment: str = ""
    icon_kind: IconKind = IconKind.GENERATED
    icon_path: str | None = None
    source: LauncherSource = LauncherSource.MANUAL
    management_policy: ManagementPolicy = ManagementPolicy.PINNED
    status: LauncherStatus = LauncherStatus.HEALTHY
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_invoked_at: datetime | None = None
    last_start_success_at: datetime | None = None
    last_clockify_use_at: datetime | None = None
    auto_add_grace_until: datetime | None = None
    removal_snoozed_until: datetime | None = None
    desktop_path: str | None = None
    desktop_hash: str | None = None
    icon_hash: str | None = None
    removed_at: datetime | None = None
    removal_reason: str | None = None

    @property
    def pinned(self) -> bool:
        return self.management_policy is ManagementPolicy.PINNED

    def with_(self, **changes: object) -> Launcher:
        return replace(self, **changes)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Candidate:
    """Aggregated recent use for one automatic signature."""

    target: LauncherTarget
    count: int
    last_use: datetime
    score: float
    representative_entry_id: str
    project_name: str
    task_name: str | None = None
    tag_names: tuple[str, ...] = ()
    eligible: bool = True
    ineligibility_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Suggestion:
    id: str
    type: SuggestionType
    launcher_id: str | None
    target: LauncherTarget | None
    explanation: str
    evidence: str
    state: SuggestionState = SuggestionState.OPEN
    created_at: datetime = field(default_factory=utc_now)
    dismissed_at: datetime | None = None
    snoozed_until: datetime | None = None
    accepted_at: datetime | None = None
    executed_at: datetime | None = None


class EventSeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    id: str
    event_type: str
    severity: EventSeverity
    summary: str
    details: str = ""
    launcher_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class TimeEntry:
    """A Clockify time entry, reduced to what the application needs."""

    id: str
    workspace_id: str
    project_id: str | None
    task_id: str | None
    tag_ids: tuple[str, ...]
    description: str
    start: datetime
    end: datetime | None
    is_break: bool = False

    @property
    def running(self) -> bool:
        return self.end is None


@dataclass(frozen=True, slots=True)
class Tombstone:
    """Restorable record of an automatically removed launcher."""

    launcher_id: str
    removed_at: datetime
    reason: str
    launcher_json: str
