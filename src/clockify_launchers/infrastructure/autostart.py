"""XDG autostart entry management.

When "start in background at login" is enabled, an autostart desktop entry
launches the GUI hidden so the top-bar timer indicator is available from
login without opening the window (ADR 0016).

The entry contains only fixed strings (no user-provided text) and is written
atomically. It is owned by this application: install/remove only ever touch
the fixed filename under the user's XDG autostart directory.
"""

from __future__ import annotations

import logging

from clockify_launchers import constants
from clockify_launchers.infrastructure.config_store import atomic_write_text
from clockify_launchers.infrastructure.desktop_entries import EXEC_PATH
from clockify_launchers.infrastructure.xdg_paths import XdgPaths

log = logging.getLogger(__name__)

AUTOSTART_FILENAME = f"{constants.APP_ID}.desktop"

_CONTENT = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={constants.APP_NAME}
Comment=Show the Clockify timer indicator in the top bar
Exec={EXEC_PATH} gui --hidden
TryExec={EXEC_PATH}
Icon={constants.APP_ID}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
X-Clockify-Launchers-Managed=true
"""


def autostart_path(paths: XdgPaths):  # -> Path
    return paths.autostart_dir / AUTOSTART_FILENAME


def is_installed(paths: XdgPaths) -> bool:
    return autostart_path(paths).is_file()


def install(paths: XdgPaths) -> None:
    """Atomically write the autostart entry (idempotent)."""
    atomic_write_text(autostart_path(paths), _CONTENT, mode=0o644)
    log.info("autostart entry installed at %s", autostart_path(paths))


def remove(paths: XdgPaths) -> None:
    """Remove the autostart entry if present (idempotent, no symlink follow)."""
    path = autostart_path(paths)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        log.info("autostart entry removed from %s", path)


def apply(paths: XdgPaths, enabled: bool) -> None:
    if enabled:
        install(paths)
    else:
        remove(paths)
