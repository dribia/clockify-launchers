"""Legacy import parsing, icon service, and launcher JSON roundtrip tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from clockify_launchers import constants
from clockify_launchers.domain.models import (
    IconKind,
    Launcher,
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementPolicy,
)
from clockify_launchers.services.icon_service import (
    IconError,
    IconService,
    generate_svg_icon,
    monogram,
    normalize_color,
    text_color_for,
)
from clockify_launchers.services.import_service import (
    ImportRejected,
    parse_exec_line,
    scan_legacy_launchers,
)
from clockify_launchers.services.launcher_service import launcher_from_json, launcher_to_json

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
LID = "6d17b662-5ba4-4c39-903b-cc319a633fe7"


class TestParseExecLine:
    def test_full_command_with_repeated_tags(self) -> None:
        parsed = parse_exec_line(
            "/usr/bin/clockify-cli in -p Tank -T Deploy --tag one --tag two -d 'Some work' -w wsx"
        )
        assert parsed["project"] == "Tank"
        assert parsed["task"] == "Deploy"
        assert parsed["tags"] == ("one", "two")
        assert parsed["description"] == "Some work"
        assert parsed["workspace"] == "wsx"
        assert parsed["ignored"] == ()

    def test_ignorable_flags_reported(self) -> None:
        parsed = parse_exec_line("clockify-cli in -p Tank -i --md")
        assert parsed["ignored"] == ("-i", "--md")

    def test_bare_executable_name(self) -> None:
        parsed = parse_exec_line("clockify-cli in --project Tank")
        assert parsed["project"] == "Tank"

    @pytest.mark.parametrize(
        "line",
        [
            "clockify-cli in -p Tank; rm -rf /",
            "clockify-cli in -p Tank | cat",
            "clockify-cli in -p Tank && evil",
            "clockify-cli in -p Tank > /tmp/out",
            "clockify-cli in -p `whoami`",
            "clockify-cli in -p $(id)",
            "clockify-cli in -p ${HOME}",
        ],
    )
    def test_rejects_shell_meta_and_substitutions(self, line: str) -> None:
        with pytest.raises(ImportRejected):
            parse_exec_line(line)

    def test_rejects_env_assignment(self) -> None:
        with pytest.raises(ImportRejected, match="environment assignments"):
            parse_exec_line("FOO=bar clockify-cli in -p Tank")

    def test_rejects_unknown_flag(self) -> None:
        with pytest.raises(ImportRejected, match="unknown option"):
            parse_exec_line("clockify-cli in -p Tank --frobnicate")

    def test_rejects_wrong_executable(self) -> None:
        with pytest.raises(ImportRejected, match="executable"):
            parse_exec_line("/usr/bin/other-cli in -p Tank")

    def test_rejects_wrong_subcommand(self) -> None:
        with pytest.raises(ImportRejected, match="expected 'in'"):
            parse_exec_line("clockify-cli out -p Tank")

    def test_rejects_missing_project(self) -> None:
        with pytest.raises(ImportRejected, match="no project"):
            parse_exec_line("clockify-cli in")

    def test_rejects_flag_without_value(self) -> None:
        with pytest.raises(ImportRejected, match="has no value"):
            parse_exec_line("clockify-cli in -p")

    def test_rejects_response_file(self) -> None:
        with pytest.raises(ImportRejected, match="response files"):
            parse_exec_line("clockify-cli in -p Tank @args.txt")

    def test_rejects_extra_positional(self) -> None:
        with pytest.raises(ImportRejected, match="unexpected argument"):
            parse_exec_line("clockify-cli in extra -p Tank")

    def test_rejects_malformed_quoting(self) -> None:
        with pytest.raises(ImportRejected, match="malformed quoting"):
            parse_exec_line("clockify-cli in -p 'unterminated")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ImportRejected):
            parse_exec_line("   ")


class TestScanLegacyLaunchers:
    def _desktop(self, path: Path, name: str, exec_line: str) -> None:
        path.write_text(f"[Desktop Entry]\nType=Application\nName={name}\nExec={exec_line}\n")

    def test_finds_legacy(self, tmp_path: Path) -> None:
        self._desktop(tmp_path / "kaito.desktop", "Kaito", "clockify-cli in -p Tank -g Project")
        found = scan_legacy_launchers(tmp_path)
        assert len(found) == 1
        lc = found[0]
        assert lc.name == "Kaito"
        assert lc.project == "Tank"
        assert lc.tags == ("Project",)

    def test_skips_managed_prefix(self, tmp_path: Path) -> None:
        self._desktop(
            tmp_path / f"{constants.DESKTOP_FILE_PREFIX}{LID}.desktop",
            "Owned",
            "clockify-cli in -p Tank",
        )
        assert scan_legacy_launchers(tmp_path) == []

    def test_skips_non_clockify(self, tmp_path: Path) -> None:
        self._desktop(tmp_path / "firefox.desktop", "Firefox", "firefox %u")
        assert scan_legacy_launchers(tmp_path) == []

    def test_skips_rejected_exec(self, tmp_path: Path) -> None:
        self._desktop(tmp_path / "bad.desktop", "Bad", "clockify-cli out -p Tank")
        assert scan_legacy_launchers(tmp_path) == []

    def test_missing_dir(self, tmp_path: Path) -> None:
        assert scan_legacy_launchers(tmp_path / "nope") == []


class TestIconService:
    def test_generated_svg_contains_monogram_and_color(self) -> None:
        svg = generate_svg_icon("Tank Project", "#03A9F4")
        assert "TP" in svg
        assert "#03A9F4" in svg
        assert svg.startswith("<svg")

    def test_text_color_contrast(self) -> None:
        assert text_color_for("#000000") == "#FFFFFF"
        assert text_color_for("#1A1A2E") == "#FFFFFF"
        assert text_color_for("#FFFFFF") == "#1A1A1A"
        assert text_color_for("#FFEE58") == "#1A1A1A"
        assert text_color_for("garbage") == "#FFFFFF"

    def test_monogram_edge_cases(self) -> None:
        assert monogram("Tank") == "TA"
        assert monogram("Tank Project") == "TP"
        assert monogram("a b c") == "AB"
        assert monogram("") == "?"
        assert monogram("   ") == "?"
        assert monogram("x") == "X"

    def test_normalize_color(self) -> None:
        assert normalize_color("#03a9f4") == "#03A9F4"
        assert normalize_color("03A9F4") == "#03A9F4"
        fallback = normalize_color(None, fallback_seed="seed")
        assert fallback == normalize_color("zzz", fallback_seed="seed")
        assert fallback.startswith("#")

    def test_write_generated(self, tmp_path: Path) -> None:
        svc = IconService(tmp_path / "icons")
        path = svc.write_generated(LID, "Tank", "#03A9F4")
        assert path == tmp_path / "icons" / f"{LID}.svg"
        assert "#03A9F4" in path.read_text()

    def test_import_selected_png(self, tmp_path: Path) -> None:
        src = tmp_path / "icon.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        svc = IconService(tmp_path / "icons")
        dest = svc.import_selected(LID, src)
        assert dest.suffix == ".png"
        assert dest.read_bytes() == src.read_bytes()

    def test_import_selected_jpg_and_svg(self, tmp_path: Path) -> None:
        svc = IconService(tmp_path / "icons")
        jpg = tmp_path / "a.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
        assert svc.import_selected(LID, jpg).suffix == ".jpg"
        svg = tmp_path / "b.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        assert svc.import_selected(LID, svg).suffix == ".svg"
        # stale .jpg removed when a new format is imported
        assert not (tmp_path / "icons" / f"{LID}.jpg").exists()

    def test_import_rejects_garbage(self, tmp_path: Path) -> None:
        src = tmp_path / "junk.png"
        src.write_bytes(b"not an image at all")
        svc = IconService(tmp_path / "icons")
        with pytest.raises(IconError, match="unsupported image format"):
            svc.import_selected(LID, src)

    def test_import_rejects_empty_and_oversized(self, tmp_path: Path) -> None:
        svc = IconService(tmp_path / "icons")
        empty = tmp_path / "empty.png"
        empty.write_bytes(b"")
        with pytest.raises(IconError, match="out of bounds"):
            svc.import_selected(LID, empty)
        from clockify_launchers.services.icon_service import MAX_ICON_BYTES

        big = tmp_path / "big.png"
        big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_ICON_BYTES)
        with pytest.raises(IconError, match="out of bounds"):
            svc.import_selected(LID, big)

    def test_import_rejects_missing_file(self, tmp_path: Path) -> None:
        svc = IconService(tmp_path / "icons")
        with pytest.raises(IconError, match="not a file"):
            svc.import_selected(LID, tmp_path / "missing.png")


class TestLauncherJsonRoundtrip:
    def test_roundtrip_all_fields(self) -> None:
        lc = Launcher(
            id=LID,
            account_id="acc1",
            target=LauncherTarget(
                workspace_id="ws1",
                project_id="p1",
                task_id="t1",
                tag_ids=("b", "a"),
                description="desc",
            ),
            display_name="Kaito",
            comment="c",
            icon_kind=IconKind.SELECTED,
            icon_path="/tmp/i.png",
            source=LauncherSource.AUTOMATIC,
            management_policy=ManagementPolicy.MANAGED,
            status=LauncherStatus.STALE,
            created_at=NOW - timedelta(days=10),
            updated_at=NOW,
            last_invoked_at=NOW - timedelta(days=1),
            last_start_success_at=NOW - timedelta(days=2),
            last_clockify_use_at=NOW - timedelta(days=3),
            auto_add_grace_until=NOW + timedelta(days=1),
            removal_snoozed_until=None,
            desktop_path="/tmp/x.desktop",
            desktop_hash="h1",
            icon_hash="h2",
            removed_at=None,
            removal_reason=None,
        )
        assert launcher_from_json(launcher_to_json(lc)) == lc

    def test_roundtrip_minimal(self) -> None:
        lc = Launcher(
            id=LID,
            account_id="acc1",
            target=LauncherTarget(workspace_id="ws1", project_id="p1"),
            display_name="Min",
            created_at=NOW,
            updated_at=NOW,
        )
        restored = launcher_from_json(launcher_to_json(lc))
        assert restored == lc
        assert restored.target.tag_ids == ()
        assert restored.created_at.tzinfo is not None
