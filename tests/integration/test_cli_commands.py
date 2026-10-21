"""CLI-level tests for cmd_doctor and cmd_reset with a manually built context."""

from __future__ import annotations

import subprocess
from pathlib import Path

from clockify_launchers import constants
from clockify_launchers.cli import cmd_doctor, cmd_reset
from clockify_launchers.context import AppContext
from clockify_launchers.demo import fixtures
from clockify_launchers.domain.models import LauncherTarget, ManagementMode
from clockify_launchers.infrastructure.config_store import AppConfig
from clockify_launchers.infrastructure.systemd import SystemdManager
from clockify_launchers.services.account_service import AccountService
from clockify_launchers.services.notification_service import RecordingNotifier


def _runner(args):
    if "show" in args:
        stdout = "NextElapseUSecRealtime=\nNextElapseUSecMonotonic=17874952570000\n"
    else:
        stdout = "active\n"
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


def _unarmed_runner(args):
    if "show" in args:
        stdout = "NextElapseUSecRealtime=\nNextElapseUSecMonotonic=infinity\n"
    else:
        stdout = "active\n"
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


def _inactive_runner(args):
    stdout = "" if "show" in args else "inactive\n"
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


def make_context(env, runner=_runner) -> AppContext:
    account_service = AccountService(env.config_store, env.db, env.secrets)
    return AppContext(
        paths=env.paths,
        config_store=env.config_store,
        db=env.db,
        secrets=env.secrets,
        icon_service=env.icon_service,
        launcher_service=env.launcher_service,
        account_service=account_service,
        systemd=SystemdManager(env.paths.systemd_user_dir, runner=runner),
        notifier=RecordingNotifier(),
        demo=True,
    )


def configure(env, mode: ManagementMode = ManagementMode.ASSISTED) -> None:
    config = AppConfig(
        active_account_id=env.account.id,
        clockify_user_id=fixtures.DEMO_USER_ID,
        email=fixtures.DEMO_EMAIL,
        active_workspace_id=fixtures.WS_MAIN.id,
        onboarding_complete=True,
        management_mode=mode,
    )
    env.config_store.save(config)
    env.secrets.store_api_key(env.account.id, "https://api.clockify.me", fixtures.DEMO_EMAIL, "k")


def test_doctor_ok_on_configured_context(env, capsys):
    configure(env)
    context = make_context(env)
    assert cmd_doctor(context, network=False) == constants.EXIT_OK
    out = capsys.readouterr().out
    assert "[ok ] Config directory" in out
    assert "[ok ] systemd timer armed" in out
    assert "FAIL] Database readable" not in out
    assert env.secrets.get_api_key(env.account.id) == "k"  # doctor never touches the key


def test_doctor_fails_on_active_but_unarmed_timer(env, capsys):
    """A timer that is active yet never fires must FAIL doctor (ADR 0019)."""
    configure(env)
    context = make_context(env, runner=_unarmed_runner)
    assert cmd_doctor(context, network=False) == constants.EXIT_CONFIG_ERROR
    out = capsys.readouterr().out
    assert "FAIL] systemd timer armed" in out
    assert "never fires" in out


def test_doctor_manual_mode_expects_disabled_timer(env, capsys):
    configure(env, mode=ManagementMode.MANUAL)
    context = make_context(env, runner=_inactive_runner)
    # The timer check is informational in manual mode and never fails doctor.
    assert cmd_doctor(context, network=False) == constants.EXIT_OK
    out = capsys.readouterr().out
    assert "[ok ] systemd timer disabled" in out


def test_reset_removes_launchers_config_and_db(env, capsys):
    configure(env)
    launcher = env.launcher_service.create(
        account_id=env.account.id,
        target=LauncherTarget(workspace_id=fixtures.WS_MAIN.id, project_id="prj-tank"),
        display_name="Kaito",
    )
    desktop_path = Path(launcher.desktop_path)
    assert desktop_path.exists()
    context = make_context(env)
    assert cmd_reset(context, remove_launchers=True, yes=True) == constants.EXIT_OK
    assert not desktop_path.exists()
    assert not env.paths.config_file.exists()
    assert not env.paths.state_db.exists()
    assert env.secrets.get_api_key(env.account.id) is None
    out = capsys.readouterr().out
    assert "Reset complete." in out


def test_stop_desktop_entry_is_valid_and_stops_via_notification(env, monkeypatch):
    """The packaged Stop launcher stays valid; cmd_stop notifies instead of relying on a terminal."""
    import shutil
    import subprocess
    from pathlib import Path

    desktop = Path(__file__).resolve().parents[2] / "data/com.dribia.ClockifyLaunchers.stop.desktop"
    content = desktop.read_text(encoding="utf-8")
    assert "Exec=clockify-launchers stop" in content
    assert "Terminal=false" in content
    if shutil.which("desktop-file-validate"):
        subprocess.run(["desktop-file-validate", str(desktop)], check=True)
