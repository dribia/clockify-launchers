"""Legacy clockify-cli launcher import end-to-end."""

from __future__ import annotations

from pathlib import Path

from clockify_launchers.demo import fixtures
from clockify_launchers.domain.models import (
    LauncherSource,
    LauncherTarget,
    ManagementPolicy,
)
from clockify_launchers.services.import_service import scan_legacy_launchers

LEGACY_CONTENT = """[Desktop Entry]
Version=1.0
Type=Application
Name=Kaito Legacy
Comment=Old Clockify launcher
Icon=clock
Exec=clockify-cli in -p Tank -g Project
Terminal=false
"""


def write_legacy(apps_dir: Path) -> Path:
    path = apps_dir / "kaito-legacy.desktop"
    path.write_text(LEGACY_CONTENT)
    return path


def test_scan_finds_and_parses_legacy_launcher(env):
    path = write_legacy(env.paths.applications_dir)
    found = scan_legacy_launchers(env.paths.applications_dir)
    assert len(found) == 1
    legacy = found[0]
    assert legacy.path == path
    assert legacy.name == "Kaito Legacy"
    assert legacy.comment == "Old Clockify launcher"
    assert legacy.icon == "clock"
    assert legacy.project == "Tank"
    assert legacy.task is None
    assert legacy.tags == ("Project",)
    assert legacy.description is None


def test_scan_ignores_unsafe_and_owned_files(env):
    apps = env.paths.applications_dir
    (apps / "evil.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Evil\nExec=clockify-cli in -p Tank; rm -rf /\n"
    )
    (apps / "unrelated.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Editor\nExec=gedit\n"
    )
    assert scan_legacy_launchers(apps) == []


def test_import_creates_pinned_launcher_and_leaves_original(env):
    path = write_legacy(env.paths.applications_dir)
    original = path.read_text()
    legacy = scan_legacy_launchers(env.paths.applications_dir)[0]

    # Resolve names to demo IDs (the editor/UI does this against cached metadata).
    project = next(p for p in env.db.get_projects(fixtures.WS_MAIN.id) if p.name == legacy.project)
    tag = next(t for t in env.db.get_tags(fixtures.WS_MAIN.id) if t.name == legacy.tags[0])
    target = LauncherTarget(
        workspace_id=fixtures.WS_MAIN.id, project_id=project.id, tag_ids=(tag.id,)
    )
    launcher = env.launcher_service.create(
        account_id=env.account.id,
        target=target,
        display_name=legacy.name,
        comment=legacy.comment,
        source=LauncherSource.IMPORTED,
    )
    assert launcher.source is LauncherSource.IMPORTED
    assert launcher.management_policy is ManagementPolicy.PINNED
    new_path = Path(launcher.desktop_path)
    assert new_path.exists() and new_path != path
    assert "start --launcher" in new_path.read_text()
    # Original legacy file untouched.
    assert path.read_text() == original
