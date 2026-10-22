"""Tests for the top-bar StatusNotifierItem indicator."""

from __future__ import annotations

from clockify_launchers import constants
from clockify_launchers.infrastructure.status_notifier import (
    IDLE_LABEL,
    TimerIndicator,
    format_indicator_label,
)


class TestFormatIndicatorLabel:
    def test_none_means_idle(self) -> None:
        assert format_indicator_label(None) == IDLE_LABEL

    def test_empty_and_whitespace_mean_idle(self) -> None:
        assert format_indicator_label("") == IDLE_LABEL
        assert format_indicator_label("   ") == IDLE_LABEL

    def test_project_name_is_prefixed(self) -> None:
        assert format_indicator_label("Tank") == "\u25b6 Tank"

    def test_newlines_and_runs_of_spaces_are_flattened(self) -> None:
        assert format_indicator_label("Tank\n  Project\t X") == "\u25b6 Tank Project X"

    def test_long_names_are_truncated_with_ellipsis(self) -> None:
        label = format_indicator_label("P" * 100)
        assert len(label) <= 2 + 40  # marker + space + max name length
        assert label.endswith("\u2026")

    def test_short_names_are_not_truncated(self) -> None:
        assert format_indicator_label("A" * 40) == "\u25b6 " + "A" * 40

    def test_day_total_appended_to_idle_label(self) -> None:
        assert format_indicator_label(None, (331,)) == f"{IDLE_LABEL} (5:31)"
        assert format_indicator_label(None, (0,)) == f"{IDLE_LABEL} (0:00)"

    def test_tracking_with_two_times(self) -> None:
        assert format_indicator_label("Agenda", (32, 331)) == "\u25b6 Agenda (0:32 / 5:31)"

    def test_single_time(self) -> None:
        assert format_indicator_label("Tank", (61,)) == "\u25b6 Tank (1:01)"

    def test_many_times_keep_configured_order(self) -> None:
        assert (
            format_indicator_label("Tank", (5, 65, 125, 185, 245))
            == "\u25b6 Tank (0:05 / 1:05 / 2:05 / 3:05 / 4:05)"
        )

    def test_none_times_render_as_placeholder(self) -> None:
        """Unavailable times keep their position so the pattern is stable."""
        assert format_indicator_label(None, (None, 331)) == f"{IDLE_LABEL} (- / 5:31)"
        assert (
            format_indicator_label(None, (None, None, None, 331, 2404))
            == f"{IDLE_LABEL} (- / - / - / 5:31 / 40:04)"
        )

    def test_negative_minutes_clamped(self) -> None:
        from clockify_launchers.infrastructure.status_notifier import format_duration_hm

        assert format_duration_hm(-5) == "0:00"

    def test_times_omitted_when_empty(self) -> None:
        assert format_indicator_label("Tank") == "\u25b6 Tank"
        assert format_indicator_label(None) == IDLE_LABEL


class TestComputeIndicatorTimes:
    """The five configurable indicator times, with a fake clock."""

    from datetime import UTC, datetime, timedelta

    NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)  # a Wednesday
    DAY_START = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    WEEK_START = datetime(2026, 6, 29, 0, 0, tzinfo=UTC)  # Monday

    @staticmethod
    def _entry(entry_id: str, project: str | None, start, end):
        from clockify_launchers.domain.models import TimeEntry

        return TimeEntry(
            id=entry_id,
            workspace_id="ws",
            project_id=project,
            task_id=None,
            tag_ids=(),
            description="",
            start=start,
            end=end,
        )

    def _fixture(self):
        from datetime import timedelta

        running = self._entry("run", "p1", self.NOW - timedelta(minutes=30), None)
        entries = [
            # Today, same project: 60 min.
            self._entry(
                "a", "p1", self.DAY_START + timedelta(hours=9), self.DAY_START + timedelta(hours=10)
            ),
            # Today, other project: 30 min.
            self._entry(
                "b",
                "p2",
                self.DAY_START + timedelta(hours=10),
                self.DAY_START + timedelta(hours=10, minutes=30),
            ),
            # Earlier this week, same project: 120 min.
            self._entry(
                "c",
                "p1",
                self.WEEK_START + timedelta(hours=9),
                self.WEEK_START + timedelta(hours=11),
            ),
            # Before this week: never counted.
            self._entry(
                "d",
                "p1",
                self.WEEK_START - timedelta(hours=5),
                self.WEEK_START - timedelta(hours=3),
            ),
            # The running entry as returned inside the list (end=None): skipped.
            running,
        ]
        return entries, running

    def test_all_enabled_order_and_values(self) -> None:
        from clockify_launchers.infrastructure.config_store import IndicatorPrefs
        from clockify_launchers.infrastructure.status_notifier import compute_indicator_times

        prefs = IndicatorPrefs(
            entry_time=True,
            project_day_total=True,
            project_week_total=True,
            day_total=True,
            week_total=True,
        )
        entries, running = self._fixture()
        times = compute_indicator_times(
            prefs, entries, running, self.NOW, self.DAY_START, self.WEEK_START
        )
        # entry 30; project day 60+30; project week 60+120+30;
        # day 60+30+30; week 60+30+120+30.
        assert times == (30, 90, 210, 120, 240)

    def test_idle_placeholds_entry_and_project_times(self) -> None:
        from clockify_launchers.infrastructure.config_store import IndicatorPrefs
        from clockify_launchers.infrastructure.status_notifier import compute_indicator_times

        prefs = IndicatorPrefs(
            entry_time=True,
            project_day_total=True,
            project_week_total=True,
            day_total=True,
            week_total=True,
        )
        entries, _running = self._fixture()
        entries = [e for e in entries if e.end is not None]
        times = compute_indicator_times(
            prefs, entries, None, self.NOW, self.DAY_START, self.WEEK_START
        )
        assert times == (None, None, None, 90, 210)  # placeholders keep positions

    def test_all_disabled_yields_no_times(self) -> None:
        from clockify_launchers.infrastructure.config_store import IndicatorPrefs
        from clockify_launchers.infrastructure.status_notifier import compute_indicator_times

        prefs = IndicatorPrefs(
            entry_time=False,
            project_day_total=False,
            project_week_total=False,
            day_total=False,
            week_total=False,
        )
        entries, running = self._fixture()
        times = compute_indicator_times(
            prefs, entries, running, self.NOW, self.DAY_START, self.WEEK_START
        )
        assert times == ()
        assert not prefs.needs_entries

    def test_defaults_match_previous_behavior(self) -> None:
        """Default prefs: entry time + daily total (the pre-feature label)."""
        from clockify_launchers.infrastructure.config_store import IndicatorPrefs
        from clockify_launchers.infrastructure.status_notifier import (
            compute_indicator_times,
            format_indicator_label,
        )

        entries, running = self._fixture()
        times = compute_indicator_times(
            IndicatorPrefs(), entries, running, self.NOW, self.DAY_START, self.WEEK_START
        )
        assert format_indicator_label("Agenda", times) == "\u25b6 Agenda (0:30 / 2:00)"

    def test_running_entry_without_project_placeholds_project_totals(self) -> None:
        from datetime import timedelta

        from clockify_launchers.infrastructure.config_store import IndicatorPrefs
        from clockify_launchers.infrastructure.status_notifier import compute_indicator_times

        running = self._entry("run", None, self.NOW - timedelta(minutes=10), None)
        prefs = IndicatorPrefs(
            entry_time=True, project_day_total=True, project_week_total=True, day_total=False
        )
        times = compute_indicator_times(
            prefs, [], running, self.NOW, self.DAY_START, self.WEEK_START
        )
        assert times == (10, None, None)

    def test_entries_clipped_to_window_start(self) -> None:
        from datetime import timedelta

        from clockify_launchers.infrastructure.config_store import IndicatorPrefs
        from clockify_launchers.infrastructure.status_notifier import compute_indicator_times

        # Overnight entry: only the part after local midnight counts today.
        overnight = self._entry(
            "n", "p1", self.DAY_START - timedelta(hours=1), self.DAY_START + timedelta(minutes=45)
        )
        prefs = IndicatorPrefs(entry_time=False, day_total=True)
        times = compute_indicator_times(
            prefs, [overnight], None, self.NOW, self.DAY_START, self.WEEK_START
        )
        assert times == (45,)


class TestTimerIndicator:
    def test_initial_state_is_idle(self) -> None:
        indicator = TimerIndicator()
        assert indicator.label == IDLE_LABEL

    def test_set_tracking_updates_label(self) -> None:
        indicator = TimerIndicator()
        indicator.set_tracking("Tank")
        assert indicator.label == "\u25b6 Tank"
        indicator.set_tracking(None)
        assert indicator.label == IDLE_LABEL

    def test_set_tracking_without_bus_is_safe(self) -> None:
        indicator = TimerIndicator()
        indicator.set_tracking("Tank")  # not published: must not raise
        indicator.refresh_label()  # heartbeat re-emit: safe unpublished
        indicator.unpublish()  # idempotent without publish

    def test_refresh_label_alternates_invisible_heartbeat(self) -> None:
        """The wire label must differ on consecutive heartbeats.

        The shell extension drops value-equal label updates before they
        reach the widget (ADR 0017), so the periodic refresh alternates a
        zero-width suffix. The visible label is unchanged.
        """
        indicator = TimerIndicator()
        indicator.set_tracking("Tank")
        base = indicator.properties()["XAyatanaLabel"].get_string()
        indicator.refresh_label()
        first = indicator.properties()["XAyatanaLabel"].get_string()
        indicator.refresh_label()
        second = indicator.properties()["XAyatanaLabel"].get_string()
        assert first != base
        assert second == base
        assert first.replace("\u200b", "") == base
        # The public label (used by app logic) never carries the suffix.
        assert indicator.label == "\u25b6 Tank"

    def test_properties_shape(self) -> None:
        indicator = TimerIndicator()
        indicator.set_tracking("Tank")
        props = indicator.properties()
        assert props["Id"].get_string() == constants.APP_ID
        assert props["Title"].get_string() == constants.APP_NAME
        assert props["Status"].get_string() == "Active"
        assert props["Category"].get_string() == "ApplicationStatus"
        assert props["IconName"].get_string() == constants.APP_ID
        assert props["ItemIsMenu"].get_boolean() is False
        assert props["XAyatanaLabel"].get_string() == "\u25b6 Tank"
        # ToolTip carries the same label as its description field.
        assert props["ToolTip"].unpack()[3] == "\u25b6 Tank"

    def test_property_set_is_closed(self) -> None:
        indicator = TimerIndicator()
        indicator.set_tracking("Tank")
        # Properties expose only constants and the label.
        names = set(indicator.properties())
        assert names == {
            "Category",
            "Id",
            "Title",
            "Status",
            "IconName",
            "IconThemePath",
            "ItemIsMenu",
            "Menu",
            "ToolTip",
            "XAyatanaLabel",
            "XAyatanaLabelGuide",
        }

    def test_menu_property_points_at_exported_menu(self) -> None:
        indicator = TimerIndicator()
        assert indicator.properties()["Menu"].get_string() == "/StatusNotifierItem/Menu"


class TestIndicatorMenu:
    def test_menu_without_stop_callback_has_only_open(self) -> None:
        indicator = TimerIndicator()
        ids = [item_id for item_id, _ in indicator.menu_items()]
        assert ids == [1]

    def test_stop_item_enabled_follows_tracking_state(self) -> None:
        indicator = TimerIndicator(on_stop=lambda: None)
        items = dict(indicator.menu_items())
        assert items[2]["enabled"].get_boolean() is False
        indicator.set_tracking("Tank")
        items = dict(indicator.menu_items())
        assert items[2]["enabled"].get_boolean() is True
        indicator.set_tracking(None)
        items = dict(indicator.menu_items())
        assert items[2]["enabled"].get_boolean() is False

    def test_menu_click_dispatch(self) -> None:
        opened: list[bool] = []
        stopped: list[bool] = []
        quits: list[bool] = []
        indicator = TimerIndicator(
            on_activate=lambda: opened.append(True),
            on_stop=lambda: stopped.append(True),
            on_quit=lambda: quits.append(True),
        )
        indicator._dispatch_menu_event(1, "clicked")
        indicator._dispatch_menu_event(2, "clicked")
        indicator._dispatch_menu_event(3, "clicked")
        indicator._dispatch_menu_event(2, "hovered")
        assert opened == [True]
        assert stopped == [True]
        assert quits == [True]

    def test_quit_item_present_only_with_callback(self) -> None:
        assert [i for i, _ in TimerIndicator().menu_items()] == [1]
        with_quit = TimerIndicator(on_quit=lambda: None)
        assert [i for i, _ in with_quit.menu_items()] == [1, 3]

    def test_not_registered_until_watcher_confirms(self) -> None:
        indicator = TimerIndicator()
        assert indicator.registered is False
        indicator.unpublish()
        assert indicator.registered is False

    def test_menu_properties_shape(self) -> None:
        indicator = TimerIndicator()
        props = indicator.menu_properties()
        assert props["Version"].get_uint32() >= 2
        assert props["Status"].get_string() == "normal"
