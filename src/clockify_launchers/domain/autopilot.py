"""Autopilot / Assisted decision engine.

Pure functions: given inputs (candidates, launchers, run health, settings,
clock), compute a plan. No I/O here; the sync service applies plans.

The no-deletion-on-uncertainty rule: any uncertainty flag on the run forces
``safe_to_remove = False`` and removals are not proposed or executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from clockify_launchers.domain.models import (
    Candidate,
    Launcher,
    LauncherSource,
    LauncherStatus,
    ManagementMode,
)
from clockify_launchers.domain.policies import PolicySettings, is_snoozed, is_stale
from clockify_launchers.domain.signatures import Signature, signature_of


@dataclass(frozen=True, slots=True)
class RunHealth:
    """Health of a reconciliation run; any flag poisons removals."""

    complete_pagination: bool = True
    auth_ok: bool = True
    metadata_ok: bool = True
    no_rate_limit: bool = True
    no_timeouts: bool = True
    no_parse_errors: bool = True
    db_ok: bool = True
    no_concurrent_actions: bool = True

    @property
    def safe_to_remove(self) -> bool:
        return all(
            (
                self.complete_pagination,
                self.auth_ok,
                self.metadata_ok,
                self.no_rate_limit,
                self.no_timeouts,
                self.no_parse_errors,
                self.db_ok,
                self.no_concurrent_actions,
            )
        )

    @property
    def safe_to_add(self) -> bool:
        # Additions require a complete, healthy read too.
        return self.safe_to_remove

    def problems(self) -> tuple[str, ...]:
        labels = {
            "complete_pagination": "time-entry pagination incomplete",
            "auth_ok": "authentication problem",
            "metadata_ok": "project/task/tag metadata unavailable",
            "no_rate_limit": "rate limited by Clockify",
            "no_timeouts": "network timeout",
            "no_parse_errors": "response validation failure",
            "db_ok": "local database problem",
            "no_concurrent_actions": "concurrent launcher action",
        }
        return tuple(label for attr, label in labels.items() if not getattr(self, attr))


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    additions: tuple[Candidate, ...] = ()
    removal_suggestions: tuple[Launcher, ...] = ()
    removals: tuple[Launcher, ...] = ()
    skipped_reasons: tuple[str, ...] = ()
    safe_to_remove: bool = True


@dataclass(frozen=True, slots=True)
class DismissalRecord:
    """A previously dismissed add-signature with cooldown."""

    signature: Signature
    dismissed_at: datetime
    cooldown_days: int = 30

    def active(self, now: datetime) -> bool:
        return now < self.dismissed_at + timedelta(days=self.cooldown_days)


def eligible_additions(
    candidates: list[Candidate],
    launchers: list[Launcher],
    dismissals: list[DismissalRecord],
    settings: PolicySettings,
    now: datetime,
) -> list[Candidate]:
    """Filter and rank candidates eligible for automatic addition."""
    active_signatures = {
        signature_of(lc.target) for lc in launchers if lc.status is not LauncherStatus.REMOVED
    }
    active_dismissals = {d.signature for d in dismissals if d.active(now)}
    auto_count = sum(
        1
        for lc in launchers
        if lc.source is LauncherSource.AUTOMATIC and lc.status is not LauncherStatus.REMOVED
    )
    budget = max(0, settings.max_auto_launchers - auto_count)

    picked: list[Candidate] = []
    ranked = sorted(
        candidates, key=lambda c: (-c.score, -c.last_use.timestamp(), c.target.signature)
    )
    for cand in ranked:
        if len(picked) >= budget:
            break
        if not cand.eligible:
            continue
        sig = signature_of(cand.target)
        if sig in active_signatures or sig in active_dismissals:
            continue
        recent = (now - cand.last_use) <= timedelta(days=settings.recent_use_days)
        window_ok = cand.count >= settings.min_uses
        if not (recent or window_ok):
            continue
        picked.append(cand)
    return picked


def removable(launcher: Launcher, now: datetime, settings: PolicySettings) -> tuple[bool, str]:
    """Whether an individual launcher passes every autopilot removal guard."""
    if launcher.status is LauncherStatus.REMOVED:
        return False, "already removed"
    if launcher.pinned:
        return False, "pinned"
    if launcher.source is not LauncherSource.AUTOMATIC:
        return False, "not automatically managed"
    if launcher.status is LauncherStatus.EXTERNALLY_MODIFIED:
        return False, "modified outside the application"
    if is_snoozed(launcher, now):
        return False, "removal snoozed"
    if launcher.auto_add_grace_until and now < launcher.auto_add_grace_until:
        return False, "within new-launcher grace period"
    if not is_stale(launcher, now, settings):
        return False, "not stale"
    return True, ""


def build_plan(
    mode: ManagementMode,
    candidates: list[Candidate],
    launchers: list[Launcher],
    dismissals: list[DismissalRecord],
    health: RunHealth,
    settings: PolicySettings,
    now: datetime,
) -> ReconciliationPlan:
    settings = settings.validated()
    if mode is ManagementMode.MANUAL:
        return ReconciliationPlan(skipped_reasons=("manual mode: no automation",))

    skipped: list[str] = []
    additions: tuple[Candidate, ...] = ()
    if health.safe_to_add:
        additions = tuple(eligible_additions(candidates, launchers, dismissals, settings, now))
    else:
        skipped.append("additions skipped: " + "; ".join(health.problems()))

    stale_unpinned = [
        lc
        for lc in launchers
        if removable(lc, now, settings)[0]
        or (
            lc.status is not LauncherStatus.REMOVED
            and not lc.pinned
            and lc.source is LauncherSource.AUTOMATIC
            and is_stale(lc, now, settings)
            and not is_snoozed(lc, now)
        )
    ]

    if not health.safe_to_remove:
        skipped.append("removals skipped: " + "; ".join(health.problems()))
        return ReconciliationPlan(
            additions=additions, skipped_reasons=tuple(skipped), safe_to_remove=False
        )

    if mode is ManagementMode.ASSISTED:
        return ReconciliationPlan(
            additions=additions,
            removal_suggestions=tuple(stale_unpinned),
            skipped_reasons=tuple(skipped),
        )

    removals = tuple(lc for lc in stale_unpinned if removable(lc, now, settings)[0])
    return ReconciliationPlan(
        additions=additions, removals=removals, skipped_reasons=tuple(skipped)
    )


@dataclass(slots=True)
class CandidateAggregate:
    """Mutable aggregation helper used during candidate extraction."""

    count: int = 0
    last_use: datetime | None = None
    use_times: list[datetime] = field(default_factory=list)
    representative_entry_id: str = ""
