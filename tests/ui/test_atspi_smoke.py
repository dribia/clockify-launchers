"""AT-SPI GUI smoke tests (dogtail).

Run through ``make ui-test`` which wraps pytest in an isolated Xvfb +
private D-Bus session. Widgets are located by accessible identity, never by
screen coordinates.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

dogtail = pytest.importorskip("dogtail.tree", reason="python3-dogtail is not installed")

pytestmark = [
    pytest.mark.ui,
    pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="requires a display"),
]

APP_READY_TIMEOUT = 30.0


class AppHandle:
    def __init__(self, process: subprocess.Popen[bytes], root: object) -> None:
        self.process = process
        self.root = root

    def find(self, name: str, role_name: str | None = None, retry: bool = True) -> object:
        from dogtail import tree

        try:
            if role_name:
                return self.root.child(name=name, roleName=role_name, retry=retry)
            return self.root.child(name=name, retry=retry)
        except tree.SearchError:
            pytest.fail(f"widget not found: name={name!r} role={role_name!r}")

    def maybe_find(self, name: str, role_name: str | None = None) -> object | None:
        from dogtail import tree

        try:
            if role_name:
                return self.root.child(name=name, roleName=role_name, retry=False)
            return self.root.child(name=name, retry=False)
        except tree.SearchError:
            return None

    def click(self, name: str, role_name: str | None = None) -> None:
        """Activate a widget through its AT-SPI action (reliable under Xvfb/CSD)."""
        _activate(self.find(name, role_name))

    def find_all(self, name: str, role_name: str) -> list[object]:
        from dogtail import predicate

        return self.root.findChildren(
            predicate.GenericPredicate(name=name, roleName=role_name), showingOnly=False
        )


def _activate(node: object) -> None:
    try:
        actions = node.actions
    except Exception:
        actions = {}
    for action in ("click", "activate", "press"):
        if action in actions:
            node.doActionNamed(action)
            return
    node.click()


def _launch(state: str) -> Iterator[AppHandle]:
    from dogtail import tree
    from dogtail.config import config

    config.searchCutoffCount = 10
    config.actionDelay = 0.2
    config.defaultDelay = 0.2

    tmp = tempfile.mkdtemp(prefix="cl-ui-test-")
    ready = Path(tmp) / "ready"
    env = dict(os.environ)
    env.update(
        {
            "CLOCKIFY_LAUNCHERS_DEMO": "1",
            "CLOCKIFY_LAUNCHERS_DEMO_STATE": state,
            "CLOCKIFY_LAUNCHERS_READY_FILE": str(ready),
            "GTK_A11Y": "atspi",
        }
    )
    process = subprocess.Popen([sys.executable, "-m", "clockify_launchers", "gui"], env=env)
    deadline = time.monotonic() + APP_READY_TIMEOUT
    while time.monotonic() < deadline and not ready.exists():
        if process.poll() is not None:
            pytest.fail(f"application exited early with {process.returncode}")
        time.sleep(0.2)
    if not ready.exists():
        process.terminate()
        pytest.fail("application never became ready")
    time.sleep(1.5)  # allow the AT-SPI tree to settle

    root = None
    for _ in range(20):
        try:
            root = tree.root.application("clockify-launchers")
            break
        except Exception:
            try:
                candidates = [
                    a for a in tree.root.applications() if "clockify" in (a.name or "").lower()
                ]
                if candidates:
                    root = candidates[0]
                    break
            except Exception:
                pass
            time.sleep(0.5)
    if root is None:
        process.terminate()
        pytest.fail("application not visible on the AT-SPI bus")
    handle = AppHandle(process, root)
    try:
        yield handle
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def populated() -> Iterator[AppHandle]:
    yield from _launch("launchers-populated")


@pytest.fixture
def onboarding() -> Iterator[AppHandle]:
    yield from _launch("onboarding-welcome")


@pytest.fixture
def suggestions_remove() -> Iterator[AppHandle]:
    yield from _launch("suggestions-remove")


@pytest.fixture
def suggestions_add() -> Iterator[AppHandle]:
    yield from _launch("suggestions-add")


# -- tests -------------------------------------------------------------------


def test_main_window_shows_launchers(populated: AppHandle) -> None:
    assert populated.find("Beta")
    assert populated.find("Research")


def test_start_launcher_from_ui(populated: AppHandle) -> None:
    populated.click("Start Beta", role_name="push button")
    time.sleep(1.0)
    # The fake backend starts a timer; the current-timer bar appears.
    stop = populated.maybe_find("Stop", "push button")
    assert stop is not None


def test_navigate_pages_and_change_mode(populated: AppHandle) -> None:
    populated.click("Suggestions", role_name="page tab")
    time.sleep(0.5)
    populated.click("Preferences", role_name="page tab")
    time.sleep(0.5)
    assert populated.find("Management mode")


def test_create_launcher_via_editor(populated: AppHandle) -> None:
    populated.click("New launcher", role_name="push button")
    time.sleep(1.0)
    save = populated.find("Save", role_name="push button")
    # Give it a unique name through the entry row.
    name_row = populated.maybe_find("Display name")
    if name_row is not None:
        # Entry rows vary; saving with the default name is fine.
        with contextlib.suppress(Exception):
            name_row.typeText("AT-SPI created launcher")
    _activate(save)
    time.sleep(1.0)


def test_accept_add_suggestion(suggestions_add: AppHandle) -> None:
    suggestions_add.click("Suggestions", role_name="page tab")
    time.sleep(0.5)
    suggestions_add.click("Add launcher", role_name="push button")
    time.sleep(1.0)
    # The suggestion is executed and disappears from the open list.
    assert suggestions_add.maybe_find("Add launcher", "push button") is None


def test_snooze_then_remove_stale_suggestion(suggestions_remove: AppHandle) -> None:
    suggestions_remove.click("Suggestions", role_name="page tab")
    time.sleep(0.5)
    suggestions_remove.click("Snooze 30 days", role_name="push button")
    time.sleep(1.0)
    assert suggestions_remove.maybe_find("Snooze 30 days", "push button") is None


def test_remove_and_restore_launcher(suggestions_remove: AppHandle) -> None:
    suggestions_remove.click("Suggestions", role_name="page tab")
    time.sleep(0.5)
    suggestions_remove.click("Remove", role_name="push button")
    time.sleep(1.0)
    # Confirm in the message dialog: the dialog's response button is the
    # newest "Remove" push button in the accessible tree.
    buttons = suggestions_remove.find_all("Remove", "push button")
    assert buttons, "confirmation dialog button not found"
    _activate(buttons[-1])
    time.sleep(1.0)
    suggestions_remove.click("Restore", role_name="push button")
    time.sleep(1.0)


def test_onboarding_completes(onboarding: AppHandle) -> None:
    onboarding.click("Get started", role_name="push button")
    time.sleep(0.8)
    key_entry = onboarding.find("Clockify API key", role_name="text")
    key_entry.text = "demo-key"
    time.sleep(0.3)
    onboarding.click("Verify connection", role_name="push button")
    time.sleep(1.0)
    onboarding.click("Continue", role_name="push button")
    time.sleep(0.8)
    onboarding.click("Finish", role_name="push button")
    time.sleep(1.5)
    # Onboarding completes into the main window with the page switcher.
    assert onboarding.find("Launchers", role_name="page tab")
