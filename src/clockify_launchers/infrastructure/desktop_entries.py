"""Safe desktop entry serialization, ownership checks, and atomic writes.

Uses GLib.KeyFile for serialization so escaping is always correct. Managed
files carry two ownership markers and their exact written hash is stored in
SQLite; deletion requires all checks to pass.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from clockify_launchers import constants  # noqa: E402

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

EXEC_PATH = f"/usr/bin/{constants.EXECUTABLE}"


class DesktopEntryError(Exception): ...


def sanitize_single_line(value: str) -> str:
    """Remove newlines and control characters from visible single-line fields."""
    return _CONTROL_CHARS.sub(" ", value).strip()


def _semicolon_list(values: list[str]) -> str:
    cleaned = [sanitize_single_line(v).replace(";", " ").strip() for v in values]
    cleaned = [v for v in cleaned if v]
    return ";".join(cleaned) + ";" if cleaned else ""


@dataclass(frozen=True, slots=True)
class DesktopEntrySpec:
    launcher_id: str
    name: str
    comment: str
    icon_path: str | None
    keywords: tuple[str, ...] = ()
    exec_path: str = EXEC_PATH


def desktop_file_name(launcher_id: str) -> str:
    return f"{constants.DESKTOP_FILE_PREFIX}{launcher_id}{constants.DESKTOP_FILE_SUFFIX}"


def serialize_desktop_entry(spec: DesktopEntrySpec) -> str:
    """Serialize a managed desktop entry via GLib.KeyFile (no string building)."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", spec.launcher_id):
        raise DesktopEntryError(f"invalid launcher id: {spec.launcher_id!r}")
    kf = GLib.KeyFile()
    group = "Desktop Entry"
    kf.set_string(group, "Version", "1.0")
    kf.set_string(group, "Type", "Application")
    kf.set_string(group, "Name", sanitize_single_line(spec.name) or "Clockify launcher")
    if spec.comment:
        kf.set_string(group, "Comment", sanitize_single_line(spec.comment))
    # Exec never contains user-provided text: only the fixed path and the UUID.
    kf.set_string(group, "Exec", f"{spec.exec_path} start --launcher {spec.launcher_id}")
    kf.set_string(group, "TryExec", spec.exec_path)
    if spec.icon_path:
        kf.set_string(group, "Icon", spec.icon_path)
    kf.set_boolean(group, "Terminal", False)
    kf.set_boolean(group, "StartupNotify", False)
    kf.set_string(group, "Categories", "Office;Utility;")
    keywords = _semicolon_list(["Clockify", "Time tracking", *spec.keywords])
    if keywords:
        kf.set_string(group, "Keywords", keywords)
    kf.set_string(group, constants.MANAGED_KEY, "true")
    kf.set_string(group, constants.LAUNCHER_ID_KEY, spec.launcher_id)
    data, _length = kf.to_data()
    return data


def content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def write_desktop_file_atomic(path: Path, content: str) -> str:
    """Atomically write; refuses to follow symlinks. Returns the content hash."""
    if path.is_symlink():
        raise DesktopEntryError(f"refusing to write through symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return content_hash(content)


@dataclass(frozen=True, slots=True)
class OwnershipCheck:
    owned: bool
    launcher_id: str | None
    reason: str


def check_ownership(path: Path) -> OwnershipCheck:
    """A file is owned iff filename pattern, managed marker, and id all check out."""
    name = path.name
    if not (
        name.startswith(constants.DESKTOP_FILE_PREFIX)
        and name.endswith(constants.DESKTOP_FILE_SUFFIX)
    ):
        return OwnershipCheck(False, None, "filename does not match the managed pattern")
    if name == constants.MAIN_DESKTOP_FILE:
        return OwnershipCheck(False, None, "main application desktop file")
    kf = GLib.KeyFile()
    try:
        kf.load_from_file(str(path), GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return OwnershipCheck(False, None, "unreadable or malformed desktop entry")
    group = "Desktop Entry"
    try:
        managed = kf.get_string(group, constants.MANAGED_KEY)
    except GLib.Error:
        return OwnershipCheck(False, None, "missing managed marker")
    if managed != "true":
        return OwnershipCheck(False, None, "managed marker is not 'true'")
    try:
        launcher_id = kf.get_string(group, constants.LAUNCHER_ID_KEY)
    except GLib.Error:
        return OwnershipCheck(False, None, "missing launcher id")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", launcher_id):
        return OwnershipCheck(False, None, "invalid launcher id")
    embedded = name[len(constants.DESKTOP_FILE_PREFIX) : -len(constants.DESKTOP_FILE_SUFFIX)]
    if embedded != launcher_id:
        return OwnershipCheck(False, launcher_id, "filename id does not match embedded id")
    return OwnershipCheck(True, launcher_id, "")


def safe_delete_owned(path: Path, expected_hash: str, applications_dir: Path) -> None:
    """Delete an owned desktop file only when every safety check passes."""
    resolved_parent = path.parent.resolve()
    if resolved_parent != applications_dir.resolve():
        raise DesktopEntryError(f"refusing to delete outside applications dir: {path}")
    if path.is_symlink():
        raise DesktopEntryError(f"refusing to delete a symlink: {path}")
    check = check_ownership(path)
    if not check.owned:
        raise DesktopEntryError(f"not an owned file ({check.reason}): {path}")
    current = content_hash(path.read_bytes())
    if current != expected_hash:
        raise DesktopEntryError(f"file was modified externally; refusing to delete: {path}")
    path.unlink()


def scan_owned_files(applications_dir: Path) -> dict[str, Path]:
    """Map launcher id -> path for every owned desktop file on disk."""
    result: dict[str, Path] = {}
    if not applications_dir.is_dir():
        return result
    for path in sorted(applications_dir.glob(f"{constants.DESKTOP_FILE_PREFIX}*.desktop")):
        check = check_ownership(path)
        if check.owned and check.launcher_id:
            result[check.launcher_id] = path
    return result
