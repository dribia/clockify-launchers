"""Reconciliation: candidate extraction and plan application.

Read-only with respect to Clockify. Runs under a nonblocking lock; any
uncertainty poisons removals per the no-deletion rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from clockify_launchers.domain.autopilot import (
    CandidateAggregate,
    ReconciliationPlan,
    RunHealth,
    build_plan,
)
from clockify_launchers.domain.models import (
    ActivityEvent,
    Candidate,
    EventSeverity,
    Launcher,
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementMode,
    Suggestion,
    SuggestionType,
    new_id,
    utc_now,
)
from clockify_launchers.domain.policies import PolicySettings, default_name, recency_score
from clockify_launchers.domain.signatures import Signature, entry_signature
from clockify_launchers.infrastructure.clockify_api import (
    AuthError,
    ClockifyClientProtocol,
    ClockifyError,
    OfflineError,
    PaginationIncompleteError,
    RateLimitedError,
    UnexpectedResponseError,
)
from clockify_launchers.infrastructure.database import Database
from clockify_launchers.services.launcher_service import LauncherService

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncResult:
    outcome: str  # success | offline | auth-error | error | skipped
    added: tuple[Launcher, ...] = ()
    removed: tuple[Launcher, ...] = ()
    suggestions_created: int = 0
    # Eligible candidates the automatic-launcher cap left unadded.
    blocked: tuple[Candidate, ...] = ()
    detail: str = ""
    safe_to_remove: bool = True


class SyncService:
    def __init__(
        self,
        db: Database,
        launcher_service: LauncherService,
        client: ClockifyClientProtocol,
        account_id: str,
        user_id: str,
        workspace_id: str,
    ) -> None:
        self._db = db
        self._launchers = launcher_service
        self._client = client
        self._account_id = account_id
        self._user_id = user_id
        self._workspace_id = workspace_id

    # -- candidate extraction ------------------------------------------------

    def extract_candidates(
        self, settings: PolicySettings, now: datetime
    ) -> tuple[list[Candidate], RunHealth]:
        try:
            projects = self._client.get_projects(self._workspace_id)
            tags = self._client.get_tags(self._workspace_id)
            self._db.cache_projects(projects, now)
            self._db.cache_tags(tags, now)
        except AuthError:
            return [], RunHealth(auth_ok=False)
        except RateLimitedError:
            return [], RunHealth(no_rate_limit=False)
        except OfflineError:
            return [], RunHealth(no_timeouts=False)
        except ClockifyError:
            return [], RunHealth(metadata_ok=False)

        start = now - timedelta(days=settings.lookback_days)
        try:
            entries = self._client.get_time_entries(self._workspace_id, self._user_id, start, now)
        except PaginationIncompleteError:
            return [], RunHealth(complete_pagination=False)
        except AuthError:
            return [], RunHealth(auth_ok=False)
        except RateLimitedError:
            return [], RunHealth(no_rate_limit=False)
        except OfflineError:
            return [], RunHealth(no_timeouts=False)
        except UnexpectedResponseError:
            return [], RunHealth(no_parse_errors=False)
        except ClockifyError:
            return [], RunHealth(metadata_ok=False)

        project_map = {p.id: p for p in projects}
        tag_map = {t.id: t for t in tags}
        window_start = now - timedelta(days=settings.min_uses_window_days)

        aggregates: dict[Signature, CandidateAggregate] = {}
        task_ids_needed: set[tuple[str, str]] = set()
        for entry in entries:
            if entry.is_break:
                continue
            sig = entry_signature(entry)
            if sig is None:
                continue
            project = project_map.get(entry.project_id or "")
            if project is None or project.archived:
                continue
            if entry.task_id:
                task_ids_needed.add((entry.project_id or "", entry.task_id))
            agg = aggregates.setdefault(sig, CandidateAggregate())
            if entry.running:
                # Running entries count as recent evidence, not frequency.
                if agg.last_use is None or entry.start > agg.last_use:
                    agg.last_use = entry.start
                    agg.representative_entry_id = entry.id
                continue
            reference = entry.end or entry.start
            agg.use_times.append(reference)
            if reference >= window_start:
                agg.count += 1
            if agg.last_use is None or reference > agg.last_use:
                agg.last_use = reference
                agg.representative_entry_id = entry.id

        # Resolve tasks needed by candidates.
        task_map: dict[str, str] = {}
        task_active: dict[str, bool] = {}
        for project_id in {pid for pid, _ in task_ids_needed}:
            try:
                tasks = self._client.get_tasks(self._workspace_id, project_id)
                self._db.cache_tasks(tasks, now)
                for task in tasks:
                    task_map[task.id] = task.name
                    task_active[task.id] = task.active
            except ClockifyError:
                return [], RunHealth(metadata_ok=False)

        candidates: list[Candidate] = []
        for sig, agg in aggregates.items():
            workspace_id, project_id, task_id, tag_ids = sig
            if agg.last_use is None:
                continue
            project = project_map[project_id]
            reasons: list[str] = []
            if task_id and task_id not in task_map:
                reasons.append("task no longer exists")
            elif task_id and not task_active.get(task_id, False):
                reasons.append("task is not active")
            tag_names = []
            for tag_id in tag_ids:
                tag = tag_map.get(tag_id)
                if tag is None:
                    reasons.append("a tag no longer exists")
                elif tag.archived:
                    reasons.append(f"tag '{tag.name}' is archived")
                else:
                    tag_names.append(tag.name)
            candidates.append(
                Candidate(
                    target=LauncherTarget(
                        workspace_id=workspace_id,
                        project_id=project_id,
                        task_id=task_id,
                        tag_ids=tag_ids,
                    ),
                    count=agg.count,
                    last_use=agg.last_use,
                    score=recency_score(agg.use_times, now, settings.half_life_days),
                    representative_entry_id=agg.representative_entry_id,
                    project_name=project.name,
                    task_name=task_map.get(task_id or ""),
                    tag_names=tuple(tag_names),
                    eligible=not reasons,
                    ineligibility_reasons=tuple(reasons),
                )
            )
        return candidates, RunHealth()

    # -- last-use refresh ------------------------------------------------------

    def refresh_last_use(self, candidates: list[Candidate], launchers: list[Launcher]) -> None:
        by_signature = {c.target.signature: c for c in candidates}
        for launcher in launchers:
            cand = by_signature.get(launcher.target.signature)
            if cand and (
                launcher.last_clockify_use_at is None
                or cand.last_use > launcher.last_clockify_use_at
            ):
                self._db.save_launcher(
                    launcher.with_(last_clockify_use_at=cand.last_use, updated_at=utc_now())
                )

    # -- run ---------------------------------------------------------------------

    def run(
        self, mode: ManagementMode, settings: PolicySettings, now: datetime | None = None
    ) -> SyncResult:
        now = now or utc_now()
        started = now
        settings = settings.validated()

        if mode is ManagementMode.MANUAL:
            result = SyncResult(outcome="skipped", detail="manual mode")
            self._record_run(started, result)
            return result

        # Disk reconciliation first: external modifications poison removals.
        changed = self._launchers.reconcile_disk()
        externally_modified = any(lc.status is LauncherStatus.EXTERNALLY_MODIFIED for lc in changed)

        candidates, health = self.extract_candidates(settings, now)
        if externally_modified:
            health = RunHealth(
                complete_pagination=health.complete_pagination,
                auth_ok=health.auth_ok,
                metadata_ok=health.metadata_ok,
                no_rate_limit=health.no_rate_limit,
                no_timeouts=health.no_timeouts,
                no_parse_errors=health.no_parse_errors,
                db_ok=health.db_ok,
                no_concurrent_actions=False,
            )

        if not health.auth_ok:
            result = SyncResult(
                outcome="auth-error", detail="Clockify rejected the API key", safe_to_remove=False
            )
            self._record_run(started, result)
            return result
        if not health.no_timeouts:
            result = SyncResult(
                outcome="offline", detail="could not reach Clockify", safe_to_remove=False
            )
            self._record_run(started, result)
            return result

        launchers = self._db.list_launchers()
        self.refresh_last_use(candidates, launchers)
        launchers = self._db.list_launchers()
        dismissals = self._db.list_dismissals()

        plan = build_plan(mode, candidates, launchers, dismissals, health, settings, now)
        added = self._apply_additions(plan, settings, now)
        suggestions_created = self._apply_removal_suggestions(plan, now)
        removed = self._apply_removals(plan, now)

        detail = "; ".join(plan.skipped_reasons) if plan.skipped_reasons else ""
        result = SyncResult(
            outcome="success",
            added=tuple(added),
            removed=tuple(removed),
            suggestions_created=suggestions_created,
            blocked=plan.blocked_additions,
            detail=detail,
            safe_to_remove=health.safe_to_remove,
        )
        self._record_run(started, result)
        self._db.compact_events(now)
        self._db.prune_tombstones(now)
        return result

    def _apply_additions(
        self, plan: ReconciliationPlan, settings: PolicySettings, now: datetime
    ) -> list[Launcher]:
        added: list[Launcher] = []
        existing_names = {lc.display_name for lc in self._db.list_launchers()}
        for cand in plan.additions:
            launcher_id_preview = new_id()
            name = default_name(
                cand.project_name,
                cand.task_name,
                cand.tag_names,
                existing_names,
                launcher_id_preview,
            )
            launcher = self._launchers.create(
                account_id=self._account_id,
                target=cand.target,
                display_name=name,
                source=LauncherSource.AUTOMATIC,
                grace_until=now + timedelta(days=settings.grace_days),
                now=now,
            )
            existing_names.add(name)
            evidence = (
                f"Used {cand.count} times in the last {settings.min_uses_window_days} days; "
                f"last on {cand.last_use.date().isoformat()}."
            )
            self._db.record_event(
                ActivityEvent(
                    id=new_id(),
                    event_type="auto-added",
                    severity=EventSeverity.INFO,
                    summary=f"Automatically added launcher '{name}'",
                    details=evidence,
                    launcher_id=launcher.id,
                )
            )
            added.append(launcher)
        return added

    def _apply_removal_suggestions(self, plan: ReconciliationPlan, now: datetime) -> int:
        created = 0
        open_for = {
            s.launcher_id
            for s in self._db.list_suggestions()
            if s.type is SuggestionType.REMOVE and s.launcher_id
        }
        for launcher in plan.removal_suggestions:
            if launcher.id in open_for:
                continue
            days = (now - self._effective_last_use(launcher)).days
            last = (
                launcher.last_clockify_use_at.date().isoformat()
                if launcher.last_clockify_use_at
                else "never"
            )
            suggestion = Suggestion(
                id=new_id(),
                type=SuggestionType.REMOVE,
                launcher_id=launcher.id,
                target=launcher.target,
                explanation=(f"Not used in Clockify or from this launcher for {days} days."),
                evidence=f"Last matching entry: {last}.",
                created_at=now,
            )
            self._db.save_suggestion(suggestion)
            created += 1
        return created

    @staticmethod
    def _effective_last_use(launcher: Launcher) -> datetime:
        from clockify_launchers.domain.policies import effective_last_use

        return effective_last_use(launcher)

    def _apply_removals(self, plan: ReconciliationPlan, now: datetime) -> list[Launcher]:
        removed: list[Launcher] = []
        for launcher in plan.removals:
            days = (now - self._effective_last_use(launcher)).days
            reason = f"Autopilot: not used for {days} days"
            removed.append(self._launchers.delete(launcher, reason=reason))
        return removed

    def _record_run(self, started: datetime, result: SyncResult) -> None:
        self._db.record_sync_run(
            started_at=started,
            finished_at=utc_now(),
            outcome=result.outcome,
            safe_to_remove=result.safe_to_remove,
            detail=result.detail,
        )
