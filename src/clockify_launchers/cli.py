"""Command-line interface (see AGENTS.md section 8)."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from clockify_launchers import constants
from clockify_launchers.context import AppContext, build_context
from clockify_launchers.domain.models import LauncherStatus, ManagementMode
from clockify_launchers.infrastructure.clockify_api import (
    AuthError,
    ClockifyClientProtocol,
    ClockifyError,
)
from clockify_launchers.infrastructure.file_lock import LockBusyError, acquire_lock
from clockify_launchers.infrastructure.secret_store import SecretUnavailableError
from clockify_launchers.services.sync_service import SyncService
from clockify_launchers.services.timer_service import StartOutcome, TimerService

log = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=constants.EXECUTABLE,
        description="Create Ubuntu launchers that start Clockify timers.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {constants.VERSION}")
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command")

    p_gui = sub.add_parser("gui", help="open or focus the application window")
    p_gui.add_argument(
        "--hidden",
        action="store_true",
        help="start in the background (top-bar indicator only, no window)",
    )

    p_start = sub.add_parser("start", help="start or switch the timer for one launcher")
    p_start.add_argument("--launcher", required=True, metavar="UUID")

    sub.add_parser("stop", help="stop the current user's running timer")

    p_sync = sub.add_parser("sync", help="reconcile launchers with Clockify now")
    p_sync.add_argument("--background", action="store_true", help="quiet systemd mode")

    p_doctor = sub.add_parser("doctor", help="diagnose configuration and integration")
    p_doctor.add_argument("--network", action="store_true", help="also test API connectivity")

    p_reset = sub.add_parser("reset", help="reset application data (interactive)")
    p_reset.add_argument("--remove-launchers", action="store_true")
    p_reset.add_argument("--yes", action="store_true", help="skip confirmation")

    p_demo = sub.add_parser("demo", help="open the UI in a deterministic demo state")
    p_demo.add_argument("--state", default="launchers-populated")

    return parser


def _client_for(context: AppContext) -> ClockifyClientProtocol:
    if context.demo:
        from clockify_launchers.demo.backend import FakeClockifyClient

        return FakeClockifyClient()
    return context.account_service.get_client(context.config)


def _notify_gui(context: AppContext) -> None:
    """Best-effort: tell a running GUI to refresh its timer state now."""
    from clockify_launchers.infrastructure.app_bus import request_gui_timer_refresh

    request_gui_timer_refresh(context.demo)


def cmd_start(context: AppContext, launcher_id: str) -> int:
    launcher = context.db.get_launcher(launcher_id)
    notifications = context.notifications()
    if launcher is None or launcher.status is LauncherStatus.REMOVED:
        notifications.timer_failure(
            "This launcher no longer exists. Open Clockify Launchers to review."
        )
        print(f"error: unknown launcher {launcher_id}", file=sys.stderr)
        return constants.EXIT_TARGET_ERROR
    config = context.config
    if not config.clockify_user_id:
        notifications.timer_failure("Clockify Launchers is not configured yet.")
        return constants.EXIT_CONFIG_ERROR
    try:
        client = _client_for(context)
    except SecretUnavailableError:
        notifications.timer_failure("The keyring is locked; could not read the Clockify API key.")
        return constants.EXIT_AUTH_ERROR
    except AuthError:
        notifications.timer_failure("Clockify rejected the stored API key.")
        return constants.EXIT_AUTH_ERROR
    except ClockifyError as exc:
        notifications.timer_failure(str(exc))
        return constants.EXIT_CONFIG_ERROR

    service = TimerService(
        context.db,
        client,
        config.clockify_user_id,
        context.paths.timer_action_lock,
    )
    result = service.start_launcher(launcher)
    _notify_gui(context)
    if result.outcome in (StartOutcome.STARTED, StartOutcome.SWITCHED):
        notifications.timer_success(result.message)
        return constants.EXIT_OK
    if result.outcome is StartOutcome.NOOP:
        notifications.timer_noop(result.message)
        return constants.EXIT_OK
    notifications.timer_failure(result.message)
    print(f"error: {result.message}", file=sys.stderr)
    if result.outcome is StartOutcome.PARTIAL_SWITCH:
        return constants.EXIT_PARTIAL_SWITCH
    return constants.EXIT_API_ERROR


def cmd_stop(context: AppContext) -> int:
    config = context.config
    notifications = context.notifications()
    if not (config.clockify_user_id and config.active_workspace_id):
        notifications.timer_failure("Clockify Launchers is not configured yet.")
        print("error: not configured; run the GUI first", file=sys.stderr)
        return constants.EXIT_CONFIG_ERROR
    try:
        client = _client_for(context)
    except (SecretUnavailableError, ClockifyError) as exc:
        notifications.timer_failure(f"Could not stop the timer: {exc}")
        print(f"error: {exc}", file=sys.stderr)
        return constants.EXIT_AUTH_ERROR
    service = TimerService(
        context.db,
        client,
        config.clockify_user_id,
        context.paths.timer_action_lock,
    )
    result = service.stop_current(config.active_workspace_id)
    _notify_gui(context)
    print(result.message)
    if result.outcome is StartOutcome.FAILED:
        notifications.timer_failure(result.message)
        return constants.EXIT_API_ERROR
    if result.outcome is StartOutcome.NOOP:
        notifications.timer_noop(result.message)
    else:
        notifications.timer_success(result.message)
    return constants.EXIT_OK


def cmd_sync(context: AppContext, background: bool) -> int:
    config = context.config
    if not (config.active_account_id and config.clockify_user_id and config.active_workspace_id):
        if not background:
            print("error: not configured; run the GUI first", file=sys.stderr)
        return constants.EXIT_CONFIG_ERROR
    try:
        with acquire_lock(context.paths.sync_lock):
            try:
                client = _client_for(context)
            except SecretUnavailableError:
                if not background:
                    print("error: keyring locked; sync skipped", file=sys.stderr)
                log.info("credential unavailable; sync skipped without changes")
                return constants.EXIT_AUTH_ERROR if not background else constants.EXIT_OK
            except ClockifyError as exc:
                if not background:
                    print(f"error: {exc}", file=sys.stderr)
                return constants.EXIT_AUTH_ERROR
            service = SyncService(
                context.db,
                context.launcher_service,
                client,
                config.active_account_id,
                config.clockify_user_id,
                config.active_workspace_id,
            )
            result = service.run(config.management_mode, config.policy)
    except LockBusyError:
        if not background:
            print("Another synchronization is already running; skipped.")
        return constants.EXIT_OK

    if not background:
        print(f"Sync finished: {result.outcome}")
        if result.added:
            print(f"  Added: {', '.join(lc.display_name for lc in result.added)}")
        if result.removed:
            print(f"  Removed: {', '.join(lc.display_name for lc in result.removed)}")
        if result.suggestions_created:
            print(f"  New removal suggestions: {result.suggestions_created}")
        if result.blocked:
            waiting = ", ".join(
                f"{c.project_name} - {c.task_name}" if c.task_name else c.project_name
                for c in result.blocked
            )
            print(f"  Waiting for a free automatic slot: {waiting}")
        if result.detail:
            print(f"  Notes: {result.detail}")
    if result.added and background:
        names = ", ".join(lc.display_name for lc in result.added)
        context.notifications().background_summary(f"Added launchers: {names}")
    if result.removed and background:
        names = ", ".join(lc.display_name for lc in result.removed)
        context.notifications().background_summary(f"Removed stale launchers: {names}")
    if result.outcome in ("success", "skipped"):
        return constants.EXIT_OK
    if result.outcome == "auth-error":
        return constants.EXIT_AUTH_ERROR
    return constants.EXIT_API_ERROR


def cmd_doctor(context: AppContext, network: bool) -> int:
    checks: list[tuple[str, bool, str]] = []
    paths = context.paths

    checks.append(("Config directory", paths.config_dir.is_dir(), str(paths.config_dir)))
    checks.append(("State database", paths.state_db.exists(), str(paths.state_db)))
    try:
        context.db.list_launchers()
        checks.append(("Database readable", True, ""))
    except Exception as exc:
        checks.append(("Database readable", False, str(exc)))
    try:
        available = context.secrets.available()
        checks.append(("Secret Service", available, "" if available else "unavailable or locked"))
    except Exception as exc:
        checks.append(("Secret Service", False, str(exc)))

    config = context.config
    configured = bool(config.active_account_id and config.active_workspace_id)
    checks.append(("Account configured", configured, config.email or ""))

    launchers = context.db.list_launchers()
    broken = 0
    for launcher in launchers:
        if launcher.desktop_path:
            from pathlib import Path

            if not Path(launcher.desktop_path).exists():
                broken += 1
    checks.append(
        (
            "Desktop files present",
            broken == 0,
            f"{len(launchers)} launchers, {broken} missing files",
        )
    )
    last = context.db.last_sync_run()
    checks.append(("Last sync", last is not None, f"{last['outcome']}" if last else "never ran"))
    if config.management_mode is ManagementMode.MANUAL:
        checks.append(
            (
                "systemd timer disabled",
                not context.systemd.timer_active(),
                "manual mode expects no sync timer",
            )
        )
    else:
        armed = context.systemd.timer_active() and context.systemd.timer_armed()
        checks.append(
            (
                "systemd timer armed",
                armed,
                "" if armed else "active but never fires; restart the application",
            )
        )

    if network and configured:
        try:
            client = _client_for(context)
            client.get_current_user()
            checks.append(("Clockify API", True, "authenticated"))
        except Exception as exc:
            checks.append(("Clockify API", False, str(exc)))

    failed = False
    # Soft checks never affect the exit code: manual-mode timer state is
    # informational, and a missing sync/account is a setup matter.
    soft_checks = ("Last sync", "Account configured", "systemd timer disabled")
    for name, ok, detail in checks:
        mark = "ok " if ok else "FAIL"
        line = f"[{mark}] {name}"
        if detail:
            line += f" - {detail}"
        print(line)
        if not ok and name not in soft_checks:
            failed = True
    return constants.EXIT_CONFIG_ERROR if failed else constants.EXIT_OK


def cmd_reset(context: AppContext, remove_launchers: bool, yes: bool) -> int:
    launchers = context.db.list_launchers()
    print("Reset will remove:")
    print(f"  - configuration: {context.paths.config_file}")
    print(f"  - state database: {context.paths.state_db}")
    print(f"  - keyring entry for this application")  # noqa: F541
    if remove_launchers:
        print(f"  - {len(launchers)} managed desktop launchers and their icons")
    if not yes:
        answer = input("Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return constants.EXIT_OK
    if remove_launchers:
        for launcher in launchers:
            context.launcher_service.delete(launcher, reason="application reset")
            context.icon_service.delete_icon(launcher.id)
    if context.config.active_account_id:
        try:
            context.secrets.delete_api_key(context.config.active_account_id)
        except SecretUnavailableError:
            print("warning: keyring unavailable; the stored key was not removed", file=sys.stderr)
    context.db.close()
    context.paths.state_db.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        (context.paths.state_db.parent / (context.paths.state_db.name + suffix)).unlink(
            missing_ok=True
        )
    context.paths.config_file.unlink(missing_ok=True)
    print("Reset complete.")
    return constants.EXIT_OK


def cmd_gui(context: AppContext, hidden: bool = False) -> int:
    from clockify_launchers.application import run_app

    return run_app(context, start_hidden=hidden)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))

    command = args.command or "gui"
    if command == "demo":
        os.environ[constants.DEMO_ENV_VAR] = "1"
        os.environ[constants.DEMO_STATE_ENV_VAR] = args.state
        command = "gui"

    context = build_context()
    try:
        if command == "gui":
            return cmd_gui(context, getattr(args, "hidden", False))
        if command == "start":
            return cmd_start(context, args.launcher)
        if command == "stop":
            return cmd_stop(context)
        if command == "sync":
            return cmd_sync(context, args.background)
        if command == "doctor":
            return cmd_doctor(context, args.network)
        if command == "reset":
            return cmd_reset(context, args.remove_launchers, args.yes)
        parser.print_help()
        return constants.EXIT_USAGE
    finally:
        if command != "gui":
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
