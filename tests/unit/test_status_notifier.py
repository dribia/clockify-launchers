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
        indicator.unpublish()  # idempotent without publish

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
