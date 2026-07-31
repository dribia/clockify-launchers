"""Legacy ``clockify-cli in`` launcher import (read-only parsing, never executes)."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from clockify_launchers import constants  # noqa: E402

log = logging.getLogger(__name__)

_SHELL_META = set(";|&<>`$(){}\n")
_PROJECT_FLAGS = {"-p", "--project"}
_TASK_FLAGS = {"-T", "--task"}
_TAG_FLAGS = {"-g", "--tag", "--tags"}
_DESC_FLAGS = {"-d", "--description"}
_WORKSPACE_FLAGS = {"-w", "--workspace"}
_IGNORABLE_FLAGS = {
    "-i",
    "--interactive",
    "--allow-incomplete",
    "--md",
    "--csv",
    "--json",
    "-q",
    "--quiet",
}


class ImportRejected(Exception):
    """The Exec line is unsafe or has an unknown shape."""


@dataclass(frozen=True, slots=True)
class LegacyLauncher:
    path: Path
    name: str
    comment: str
    icon: str | None
    project: str
    task: str | None
    tags: tuple[str, ...]
    description: str | None
    workspace: str | None
    ignored_options: tuple[str, ...]


class ParsedExec(TypedDict):
    """Safely parsed components of a legacy clockify-cli 'in' command."""

    project: str
    task: str | None
    tags: tuple[str, ...]
    description: str | None
    workspace: str | None
    ignored: tuple[str, ...]


def parse_exec_line(exec_line: str) -> ParsedExec:
    """Parse a clockify-cli 'in' Exec command safely. Never executes anything."""
    if any(ch in _SHELL_META for ch in exec_line):
        raise ImportRejected("command contains shell control characters")
    if "$(" in exec_line or "${" in exec_line or "`" in exec_line:
        raise ImportRejected("command contains substitutions")
    try:
        tokens = shlex.split(exec_line, posix=True)
    except ValueError as exc:
        raise ImportRejected(f"malformed quoting: {exc}") from exc
    if not tokens:
        raise ImportRejected("empty command")
    for token in tokens:
        if "=" in token and tokens.index(token) == 0:
            raise ImportRejected("environment assignments are not allowed")
        if token.startswith("@"):
            raise ImportRejected("response files are not allowed")
    executable = Path(tokens[0]).name
    if executable != "clockify-cli":
        raise ImportRejected(f"executable is {executable!r}, expected 'clockify-cli'")
    rest = tokens[1:]

    project: str | None = None
    task: str | None = None
    tags: list[str] = []
    description: str | None = None
    workspace: str | None = None
    ignored: list[str] = []
    subcommand: str | None = None

    index = 0
    while index < len(rest):
        token = rest[index]
        if token in _PROJECT_FLAGS | _TASK_FLAGS | _TAG_FLAGS | _DESC_FLAGS | _WORKSPACE_FLAGS:
            if index + 1 >= len(rest):
                raise ImportRejected(f"flag {token} has no value")
            value = rest[index + 1]
            if token in _PROJECT_FLAGS:
                project = value
            elif token in _TASK_FLAGS:
                task = value
            elif token in _TAG_FLAGS:
                tags.append(value)
            elif token in _DESC_FLAGS:
                description = value
            else:
                workspace = value
            index += 2
            continue
        if token in _IGNORABLE_FLAGS:
            ignored.append(token)
            index += 1
            continue
        if token.startswith("-"):
            raise ImportRejected(f"unknown option: {token}")
        if subcommand is None:
            subcommand = token
            index += 1
            continue
        # Positional arguments after 'in' are not part of the known shape.
        raise ImportRejected(f"unexpected argument: {token}")

    if subcommand != "in":
        raise ImportRejected(f"first command is {subcommand!r}, expected 'in'")
    if not project:
        raise ImportRejected("no project specified")
    return ParsedExec(
        project=project,
        task=task,
        tags=tuple(tags),
        description=description,
        workspace=workspace,
        ignored=tuple(ignored),
    )


def scan_legacy_launchers(applications_dir: Path) -> list[LegacyLauncher]:
    """Find likely legacy launchers; parses only, never rewrites or executes."""
    found: list[LegacyLauncher] = []
    if not applications_dir.is_dir():
        return found
    for path in sorted(applications_dir.glob("*.desktop")):
        if path.name.startswith(constants.DESKTOP_FILE_PREFIX):
            continue
        kf = GLib.KeyFile()
        try:
            kf.load_from_file(str(path), GLib.KeyFileFlags.NONE)
        except GLib.Error:
            continue
        group = "Desktop Entry"
        try:
            exec_line = kf.get_string(group, "Exec")
        except GLib.Error:
            continue
        if "clockify-cli" not in exec_line:
            continue
        try:
            parsed = parse_exec_line(exec_line)
        except ImportRejected as exc:
            log.info("Skipping %s: %s", path.name, exc)
            continue

        def _opt(key: str) -> str:
            try:
                return kf.get_string(group, key)  # noqa: B023
            except GLib.Error:
                return ""

        found.append(
            LegacyLauncher(
                path=path,
                name=_opt("Name") or path.stem,
                comment=_opt("Comment"),
                icon=_opt("Icon") or None,
                project=parsed["project"],
                task=parsed["task"],
                tags=parsed["tags"],
                description=parsed["description"],
                workspace=parsed["workspace"],
                ignored_options=parsed["ignored"],
            )
        )
    return found
