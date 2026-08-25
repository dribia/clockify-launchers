"""Tests for the XDG autostart entry management (ADR 0016)."""

from __future__ import annotations

from pathlib import Path

from clockify_launchers import constants
from clockify_launchers.infrastructure import autostart
from clockify_launchers.infrastructure.config_store import AppConfig
from clockify_launchers.infrastructure.xdg_paths import resolve_paths


def _paths(tmp_path: Path):
    return resolve_paths(
        {
            "HOME": str(tmp_path),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_RUNTIME_DIR": str(tmp_path / "run"),
        }
    )


def test_autostart_path_under_config_autostart(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    expected = tmp_path / "config" / "autostart" / f"{constants.APP_ID}.desktop"
    assert autostart.autostart_path(paths) == expected


def test_install_creates_valid_entry(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    assert not autostart.is_installed(paths)
    autostart.install(paths)
    assert autostart.is_installed(paths)
    content = autostart.autostart_path(paths).read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert f"Exec=/usr/bin/{constants.EXECUTABLE} gui --hidden" in content
    assert "NoDisplay=true" in content
    assert "X-Clockify-Launchers-Managed=true" in content
    # Never any secrets or user text.
    assert "api" not in content.lower().replace("application", "")


def test_install_is_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    autostart.install(paths)
    autostart.install(paths)
    assert autostart.is_installed(paths)


def test_remove_is_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    autostart.remove(paths)  # nothing installed: no error
    autostart.install(paths)
    autostart.remove(paths)
    assert not autostart.is_installed(paths)
    autostart.remove(paths)


def test_apply_toggles(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    autostart.apply(paths, True)
    assert autostart.is_installed(paths)
    autostart.apply(paths, False)
    assert not autostart.is_installed(paths)


def test_config_start_in_background_defaults_true() -> None:
    assert AppConfig().start_in_background is True
    # Older configs without the key default to enabled.
    assert AppConfig.from_dict({}).start_in_background is True
    assert AppConfig.from_dict({"start_in_background": False}).start_in_background is False


def test_config_start_in_background_roundtrip(tmp_path: Path) -> None:
    import json

    cfg = AppConfig()
    cfg.start_in_background = False
    data = json.loads(cfg.to_json())
    assert data["start_in_background"] is False
    assert AppConfig.from_dict(data).start_in_background is False
