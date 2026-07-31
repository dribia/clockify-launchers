"""Desktop entry serialization, ownership, and safe-delete tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from clockify_launchers import constants
from clockify_launchers.infrastructure.desktop_entries import (
    DesktopEntryError,
    DesktopEntrySpec,
    check_ownership,
    content_hash,
    desktop_file_name,
    safe_delete_owned,
    sanitize_single_line,
    scan_owned_files,
    serialize_desktop_entry,
    write_desktop_file_atomic,
)

LID = "6d17b662-5ba4-4c39-903b-cc319a633fe7"
LID2 = "11111111-2222-3333-4444-555555555555"


def _spec(**kwargs: object) -> DesktopEntrySpec:
    defaults: dict = {
        "launcher_id": LID,
        "name": "Kaito",
        "comment": "Start Clockify timer: Tank - Project",
        "icon_path": "/tmp/icon.svg",
        "keywords": ("Kaito", "Tank"),
    }
    defaults.update(kwargs)
    return DesktopEntrySpec(**defaults)


def _write_owned(apps_dir: Path, launcher_id: str = LID) -> tuple[Path, str]:
    content = serialize_desktop_entry(_spec(launcher_id=launcher_id))
    path = apps_dir / desktop_file_name(launcher_id)
    h = write_desktop_file_atomic(path, content)
    return path, h


class TestSerialize:
    def test_required_keys(self) -> None:
        data = serialize_desktop_entry(_spec())
        for key in (
            "Type=Application",
            "Name=Kaito",
            "Version=1.0",
            "Terminal=false",
            "StartupNotify=false",
            f"{constants.MANAGED_KEY}=true",
            f"{constants.LAUNCHER_ID_KEY}={LID}",
            "TryExec=/usr/bin/clockify-launchers",
        ):
            assert key in data

    def test_exec_only_fixed_path_and_uuid(self) -> None:
        data = serialize_desktop_entry(_spec(name="evil; rm -rf /"))
        exec_line = next(line for line in data.splitlines() if line.startswith("Exec="))
        assert exec_line == f"Exec=/usr/bin/clockify-launchers start --launcher {LID}"

    def test_control_chars_stripped_from_name(self) -> None:
        data = serialize_desktop_entry(_spec(name="Bad\nName\x01\x7fHere"))
        name_line = next(line for line in data.splitlines() if line.startswith("Name="))
        assert "\x01" not in name_line
        assert name_line == "Name=Bad Name  Here"

    def test_empty_name_falls_back(self) -> None:
        data = serialize_desktop_entry(_spec(name="\n\x00"))
        assert "Name=Clockify launcher" in data

    def test_semicolon_terminated_lists(self) -> None:
        data = serialize_desktop_entry(_spec())
        lines = dict(line.split("=", 1) for line in data.splitlines() if "=" in line)
        assert lines["Categories"].endswith(";")
        assert lines["Categories"] == "Office;Utility;"
        assert lines["Keywords"].endswith(";")
        assert lines["Keywords"].startswith("Clockify;")

    def test_keyword_semicolons_neutralized(self) -> None:
        data = serialize_desktop_entry(_spec(keywords=("a;b",)))
        lines = dict(line.split("=", 1) for line in data.splitlines() if "=" in line)
        assert lines["Keywords"].count("a b") == 1

    def test_invalid_launcher_id_raises(self) -> None:
        for bad in ("short", "x" * 36, "", LID + "0", "../../../etc/passwd0123456789012345"):
            with pytest.raises(DesktopEntryError):
                serialize_desktop_entry(_spec(launcher_id=bad))

    def test_sanitize_single_line(self) -> None:
        assert sanitize_single_line("a\nb\tc") == "a b c"
        assert sanitize_single_line("  spaced  ") == "spaced"


class TestOwnership:
    def test_owned_file(self, tmp_path: Path) -> None:
        path, _ = _write_owned(tmp_path)
        check = check_ownership(path)
        assert check.owned
        assert check.launcher_id == LID

    def test_wrong_filename(self, tmp_path: Path) -> None:
        p = tmp_path / "firefox.desktop"
        p.write_text("[Desktop Entry]\nType=Application\n")
        check = check_ownership(p)
        assert not check.owned
        assert "filename" in check.reason

    def test_main_desktop_file_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / constants.MAIN_DESKTOP_FILE
        p.write_text("[Desktop Entry]\nType=Application\n")
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "main application desktop file"

    def test_missing_marker(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text("[Desktop Entry]\nType=Application\nName=x\n")
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "missing managed marker"

    def test_marker_not_true(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text(f"[Desktop Entry]\nType=Application\n{constants.MANAGED_KEY}=false\n")
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "managed marker is not 'true'"

    def test_missing_id(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text(f"[Desktop Entry]\n{constants.MANAGED_KEY}=true\n")
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "missing launcher id"

    def test_id_mismatch(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text(
            f"[Desktop Entry]\n{constants.MANAGED_KEY}=true\n{constants.LAUNCHER_ID_KEY}={LID2}\n"
        )
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "filename id does not match embedded id"

    def test_invalid_embedded_id(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text(
            f"[Desktop Entry]\n{constants.MANAGED_KEY}=true\n"
            f"{constants.LAUNCHER_ID_KEY}=not-a-uuid\n"
        )
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "invalid launcher id"

    def test_malformed_file(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text("this is not a keyfile at all \x00")
        check = check_ownership(p)
        assert not check.owned
        assert check.reason == "unreadable or malformed desktop entry"


class TestSafeDelete:
    def test_deletes_owned(self, tmp_path: Path) -> None:
        path, h = _write_owned(tmp_path)
        safe_delete_owned(path, h, tmp_path)
        assert not path.exists()

    def test_refuses_modified_hash(self, tmp_path: Path) -> None:
        path, h = _write_owned(tmp_path)
        path.write_text(path.read_text() + "# edited\n")
        with pytest.raises(DesktopEntryError, match="modified externally"):
            safe_delete_owned(path, h, tmp_path)
        assert path.exists()

    def test_refuses_symlink(self, tmp_path: Path) -> None:
        real, h = _write_owned(tmp_path)
        # place symlink in the applications dir itself
        link = tmp_path / desktop_file_name(LID2)
        link.symlink_to(real)
        with pytest.raises(DesktopEntryError, match="symlink"):
            safe_delete_owned(link, h, tmp_path)

    def test_refuses_outside_dir(self, tmp_path: Path) -> None:
        apps = tmp_path / "applications"
        apps.mkdir()
        other = tmp_path / "elsewhere"
        other.mkdir()
        path, h = _write_owned(other)
        with pytest.raises(DesktopEntryError, match="outside applications dir"):
            safe_delete_owned(path, h, apps)
        assert path.exists()

    def test_refuses_unowned(self, tmp_path: Path) -> None:
        p = tmp_path / desktop_file_name(LID)
        p.write_text("[Desktop Entry]\nType=Application\n")
        with pytest.raises(DesktopEntryError, match="not an owned file"):
            safe_delete_owned(p, content_hash(p.read_bytes()), tmp_path)


class TestScanAndWrite:
    def test_scan_owned_files(self, tmp_path: Path) -> None:
        p1, _ = _write_owned(tmp_path, LID)
        p2, _ = _write_owned(tmp_path, LID2)
        (tmp_path / "unrelated.desktop").write_text("[Desktop Entry]\n")
        (tmp_path / desktop_file_name("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")).write_text(
            "[Desktop Entry]\nType=Application\n"
        )  # missing markers -> not owned
        result = scan_owned_files(tmp_path)
        assert result == {LID: p1, LID2: p2}

    def test_scan_missing_dir(self, tmp_path: Path) -> None:
        assert scan_owned_files(tmp_path / "nope") == {}

    def test_atomic_write_returns_hash_and_no_tmp(self, tmp_path: Path) -> None:
        path = tmp_path / desktop_file_name(LID)
        content = serialize_desktop_entry(_spec())
        h = write_desktop_file_atomic(path, content)
        assert h == content_hash(content)
        assert path.read_text() == content
        assert not list(tmp_path.glob(".*.tmp.*"))

    def test_write_refuses_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.write_text("x")
        link = tmp_path / desktop_file_name(LID)
        link.symlink_to(target)
        with pytest.raises(DesktopEntryError, match="symlink"):
            write_desktop_file_atomic(link, "data")
