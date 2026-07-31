"""Signature normalization and target equality tests."""

from __future__ import annotations

from datetime import UTC, datetime

from clockify_launchers.domain.models import LauncherTarget, TimeEntry
from clockify_launchers.domain.signatures import (
    entry_matches_signature,
    entry_matches_target,
    entry_signature,
    normalize_tags,
    signature_of,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _entry(**kwargs: object) -> TimeEntry:
    defaults: dict = {
        "id": "e1",
        "workspace_id": "ws1",
        "project_id": "p1",
        "task_id": None,
        "tag_ids": (),
        "description": "",
        "start": NOW,
        "end": None,
    }
    defaults.update(kwargs)
    return TimeEntry(**defaults)


class TestNormalization:
    def test_tags_sorted_and_deduped(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", tag_ids=("b", "a", "b", "c", "a"))
        assert t.tag_ids == ("a", "b", "c")

    def test_normalize_tags_function(self) -> None:
        assert normalize_tags(["b", "a", "a", " "]) == ("a", "b")
        assert normalize_tags(None) == ()
        assert normalize_tags(()) == ()

    def test_description_excluded_from_signature(self) -> None:
        t1 = LauncherTarget(workspace_id="ws1", project_id="p1", description="one")
        t2 = LauncherTarget(workspace_id="ws1", project_id="p1", description="two")
        assert signature_of(t1) == signature_of(t2)
        assert t1.signature == ("ws1", "p1", None, ())

    def test_empty_description_becomes_none(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", description="   ")
        assert t.description is None
        t2 = LauncherTarget(workspace_id="ws1", project_id="p1", description="")
        assert t2.description is None

    def test_entry_signature_none_without_project(self) -> None:
        assert entry_signature(_entry(project_id=None)) is None

    def test_entry_signature_normalizes(self) -> None:
        e = _entry(tag_ids=("z", "a", "z"), task_id="")
        assert entry_signature(e) == ("ws1", "p1", None, ("a", "z"))


class TestEntryMatchesTarget:
    def test_exact_match(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", task_id="t1", tag_ids=("a", "b"))
        e = _entry(task_id="t1", tag_ids=("b", "a"))
        assert entry_matches_target(e, t)

    def test_tag_order_irrelevant(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", tag_ids=("x", "y"))
        assert entry_matches_target(_entry(tag_ids=("y", "x")), t)

    def test_workspace_project_mismatch(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1")
        assert not entry_matches_target(_entry(workspace_id="ws2"), t)
        assert not entry_matches_target(_entry(project_id="p2"), t)

    def test_task_absence_normalized(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", task_id=None)
        assert entry_matches_target(_entry(task_id=""), t)
        assert not entry_matches_target(_entry(task_id="t1"), t)

    def test_no_description_matches_any(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1")
        assert entry_matches_target(_entry(description="anything at all"), t)
        assert entry_matches_target(_entry(description=""), t)

    def test_fixed_description_requires_match(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", description="fixed")
        assert entry_matches_target(_entry(description="fixed"), t)
        assert entry_matches_target(_entry(description="  fixed  "), t)
        assert not entry_matches_target(_entry(description="other"), t)
        assert not entry_matches_target(_entry(description=""), t)

    def test_tag_set_mismatch(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", tag_ids=("a",))
        assert not entry_matches_target(_entry(tag_ids=("a", "b")), t)
        assert not entry_matches_target(_entry(tag_ids=()), t)

    def test_entry_matches_signature(self) -> None:
        t = LauncherTarget(workspace_id="ws1", project_id="p1", tag_ids=("a",))
        assert entry_matches_signature(_entry(tag_ids=("a",)), signature_of(t))
        assert not entry_matches_signature(_entry(tag_ids=()), signature_of(t))
