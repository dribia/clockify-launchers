"""Launcher lifecycle, external modification, and disk reconciliation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from clockify_launchers.demo import fixtures
from clockify_launchers.domain.models import (
    LauncherSource,
    LauncherStatus,
    LauncherTarget,
    ManagementPolicy,
)


def tank_target() -> LauncherTarget:
    return LauncherTarget(
        workspace_id=fixtures.WS_MAIN.id,
        project_id="prj-tank",
        task_id="task-model",
        tag_ids=("tag-project",),
    )


def test_create_writes_valid_desktop_file(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    path = Path(launcher.desktop_path)
    assert path.exists()
    assert path.parent == env.paths.applications_dir
    assert launcher.desktop_hash
    content = path.read_text()
    assert f"start --launcher {launcher.id}" in content
    assert "X-Clockify-Launchers-Managed=true" in content
    # Manual launchers are pinned by default.
    assert launcher.management_policy is ManagementPolicy.PINNED
    if shutil.which("desktop-file-validate"):
        result = subprocess.run(
            ["desktop-file-validate", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    else:  # pragma: no cover
        pytest.skip("desktop-file-validate not installed")


def test_edit_rename_keeps_filename_stable(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    original_path = Path(launcher.desktop_path)
    updated = env.launcher_service.update(launcher, display_name="Renamed Kaito")
    assert updated.display_name == "Renamed Kaito"
    assert Path(updated.desktop_path) == original_path
    assert original_path.exists()
    assert "Name=Renamed Kaito" in original_path.read_text()


def test_pin_unpin(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    unpinned = env.launcher_service.set_pinned(launcher, False)
    assert unpinned.management_policy is ManagementPolicy.MANAGED
    assert env.db.get_launcher(launcher.id).management_policy is ManagementPolicy.MANAGED
    pinned = env.launcher_service.set_pinned(unpinned, True)
    assert pinned.pinned
    assert env.db.get_launcher(launcher.id).pinned


def test_delete_and_restore(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    path = Path(launcher.desktop_path)
    removed = env.launcher_service.delete(launcher)
    assert not path.exists()
    assert removed.status is LauncherStatus.REMOVED
    assert env.db.get_tombstone(launcher.id) is not None
    assert env.db.get_launcher(launcher.id).status is LauncherStatus.REMOVED

    restored = env.launcher_service.restore(launcher.id)
    assert restored is not None
    assert restored.id == launcher.id
    assert restored.target == launcher.target
    assert restored.display_name == "Kaito"
    assert restored.management_policy is ManagementPolicy.PINNED
    assert Path(restored.desktop_path).exists()
    assert env.db.get_tombstone(launcher.id) is None


def test_external_modification_flow(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    path = Path(launcher.desktop_path)
    path.write_text(path.read_text() + "\n# user edit\n")

    changed = env.launcher_service.reconcile_disk()
    assert any(
        lc.id == launcher.id and lc.status is LauncherStatus.EXTERNALLY_MODIFIED for lc in changed
    )
    modified = env.db.get_launcher(launcher.id)
    assert modified.status is LauncherStatus.EXTERNALLY_MODIFIED

    # Delete refuses to remove the file (hash mismatch) but marks state removed.
    removed = env.launcher_service.delete(modified)
    assert path.exists()
    assert removed.status is LauncherStatus.REMOVED

    # Restore state and rewrite the managed version instead.
    assert env.launcher_service.restore(launcher.id) is not None
    path.write_text(path.read_text() + "\n# user edit again\n")
    env.launcher_service.reconcile_disk()
    modified = env.db.get_launcher(launcher.id)
    assert modified.status is LauncherStatus.EXTERNALLY_MODIFIED

    rewritten = env.launcher_service.restore_managed_version(modified)
    assert rewritten.status is LauncherStatus.HEALTHY
    changed = env.launcher_service.reconcile_disk()
    assert env.db.get_launcher(launcher.id).status is LauncherStatus.HEALTHY
    assert "# user edit" not in Path(rewritten.desktop_path).read_text()


def test_reconcile_recreates_missing_file(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    path = Path(launcher.desktop_path)
    path.unlink()
    changed = env.launcher_service.reconcile_disk()
    assert any(lc.id == launcher.id for lc in changed)
    assert path.exists()


def test_duplicate_signature_detection(env):
    env.launcher_service.create(
        account_id=env.account.id, target=tank_target(), display_name="Kaito"
    )
    dup = env.launcher_service.duplicate_of(tank_target())
    assert dup is not None
    other = LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id="prj-website")
    assert env.launcher_service.duplicate_of(other) is None


def test_imported_launcher_pinned_by_default(env):
    launcher = env.launcher_service.create(
        account_id=env.account.id,
        target=tank_target(),
        display_name="Legacy Kaito",
        source=LauncherSource.IMPORTED,
    )
    assert launcher.source is LauncherSource.IMPORTED
    assert launcher.management_policy is ManagementPolicy.PINNED


def test_desktop_keywords_include_client_name(env):
    """GNOME shell search must find launchers by the project's client name."""
    from pathlib import Path

    from clockify_launchers.domain.models import LauncherTarget

    launcher = env.launcher_service.create(
        account_id=env.account.id,
        target=LauncherTarget(workspace_id="ws-dribia", project_id="prj-tank"),
        display_name="Tank work",
    )
    content = Path(launcher.desktop_path).read_text(encoding="utf-8")
    keywords_line = next(line for line in content.splitlines() if line.startswith("Keywords="))
    assert "Tank" in keywords_line
    assert "Acme Corp" in keywords_line
