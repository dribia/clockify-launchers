"""Automation policy: thresholds, scoring, staleness, naming.

All policy defaults from AGENTS.md live here so preferences and tests share
one source of truth. A fake clock is passed everywhere (``now`` parameters)
so date-sensitive logic never reads wall time implicitly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from clockify_launchers.domain.models import Launcher

# Defaults (see AGENTS.md section 17.1)
DEFAULT_SYNC_INTERVAL_MINUTES = 30
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_HALF_LIFE_DAYS = 21
DEFAULT_RECENT_USE_DAYS = 7
DEFAULT_MIN_USES = 2
DEFAULT_MIN_USES_WINDOW_DAYS = 30
DEFAULT_STALE_DAYS = 45
DEFAULT_GRACE_DAYS = 7
DEFAULT_SNOOZE_DAYS = 30
DEFAULT_MAX_AUTO_LAUNCHERS = 15

# Validation bounds
SYNC_INTERVAL_BOUNDS = (5, 24 * 60)  # minutes
LOOKBACK_BOUNDS = (14, 365)  # days
STALE_BOUNDS = (14, 365)  # days
MAX_AUTO_BOUNDS = (1, 100)


@dataclass(frozen=True, slots=True)
class PolicySettings:
    sync_interval_minutes: int = DEFAULT_SYNC_INTERVAL_MINUTES
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    half_life_days: int = DEFAULT_HALF_LIFE_DAYS
    recent_use_days: int = DEFAULT_RECENT_USE_DAYS
    min_uses: int = DEFAULT_MIN_USES
    min_uses_window_days: int = DEFAULT_MIN_USES_WINDOW_DAYS
    stale_days: int = DEFAULT_STALE_DAYS
    grace_days: int = DEFAULT_GRACE_DAYS
    snooze_days: int = DEFAULT_SNOOZE_DAYS
    max_auto_launchers: int = DEFAULT_MAX_AUTO_LAUNCHERS

    def validated(self) -> PolicySettings:
        def clamp(value: int, bounds: tuple[int, int]) -> int:
            return max(bounds[0], min(bounds[1], value))

        return PolicySettings(
            sync_interval_minutes=clamp(self.sync_interval_minutes, SYNC_INTERVAL_BOUNDS),
            lookback_days=clamp(self.lookback_days, LOOKBACK_BOUNDS),
            half_life_days=max(1, self.half_life_days),
            recent_use_days=max(1, self.recent_use_days),
            min_uses=max(1, self.min_uses),
            min_uses_window_days=max(1, self.min_uses_window_days),
            stale_days=clamp(self.stale_days, STALE_BOUNDS),
            grace_days=max(0, self.grace_days),
            snooze_days=max(1, self.snooze_days),
            max_auto_launchers=clamp(self.max_auto_launchers, MAX_AUTO_BOUNDS),
        )


def recency_score(use_times: list[datetime], now: datetime, half_life_days: int) -> float:
    """score = sum(exp(-age_days / half_life_days)); deterministic."""
    total = 0.0
    for t in use_times:
        age_days = max(0.0, (now - t).total_seconds() / 86400.0)
        total += math.exp(-age_days / float(half_life_days))
    return total


def effective_last_use(launcher: Launcher) -> datetime:
    """Newest of Clockify use, local start success, and grace-protected creation."""
    candidates = [launcher.created_at]
    if launcher.last_clockify_use_at:
        candidates.append(launcher.last_clockify_use_at)
    if launcher.last_start_success_at:
        candidates.append(launcher.last_start_success_at)
    if launcher.auto_add_grace_until:
        candidates.append(launcher.auto_add_grace_until)
    return max(candidates)


def is_stale(launcher: Launcher, now: datetime, settings: PolicySettings) -> bool:
    if launcher.auto_add_grace_until and now < launcher.auto_add_grace_until:
        return False
    return (now - effective_last_use(launcher)) > timedelta(days=settings.stale_days)


def is_snoozed(launcher: Launcher, now: datetime) -> bool:
    return launcher.removal_snoozed_until is not None and now < launcher.removal_snoozed_until


def default_name(
    project_name: str,
    task_name: str | None,
    tag_names: tuple[str, ...],
    existing_names: set[str],
    launcher_id: str,
) -> str:
    """Automatic naming: project [- task], tag qualifier, UUID suffix as last resort."""
    base = f"{project_name} - {task_name}" if task_name else project_name
    if base not in existing_names:
        return base
    if tag_names:
        qualified = f"{base} ({', '.join(tag_names)})"
        if qualified not in existing_names:
            return qualified
        base = qualified
    return f"{base} [{launcher_id[:8]}]"
