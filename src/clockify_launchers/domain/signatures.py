"""Signature normalization and target equality.

The automatic candidate signature is (workspace, project, task, sorted tags).
Descriptions are excluded from automatic identity; a manual launcher's fixed
description participates only in running-timer equality.
"""

from __future__ import annotations

from collections.abc import Iterable

from clockify_launchers.domain.models import LauncherTarget, TimeEntry

Signature = tuple[str, str, str | None, tuple[str, ...]]


def normalize_tags(tag_ids: Iterable[object] | None) -> tuple[str, ...]:
    if not tag_ids:
        return ()
    return tuple(sorted({str(t) for t in tag_ids if str(t).strip()}))


def signature_of(target: LauncherTarget) -> Signature:
    return target.signature


def entry_signature(entry: TimeEntry) -> Signature | None:
    """Signature of a time entry, or None when it has no project."""
    if not entry.project_id:
        return None
    return (
        entry.workspace_id,
        entry.project_id,
        entry.task_id or None,
        normalize_tags(entry.tag_ids),
    )


def _norm_description(value: str | None) -> str:
    return (value or "").strip()


def entry_matches_target(entry: TimeEntry, target: LauncherTarget) -> bool:
    """Whether a running entry already tracks the launcher target.

    Task/tags/description absence is normalized; tag order is irrelevant.
    A launcher without a fixed description matches any description.
    """
    if entry.workspace_id != target.workspace_id:
        return False
    if entry.project_id != target.project_id:
        return False
    if (entry.task_id or None) != (target.task_id or None):
        return False
    if normalize_tags(entry.tag_ids) != target.tag_ids:
        return False
    return not (
        target.description is not None
        and _norm_description(entry.description) != _norm_description(target.description)
    )


def entry_matches_signature(entry: TimeEntry, sig: Signature) -> bool:
    return entry_signature(entry) == sig
