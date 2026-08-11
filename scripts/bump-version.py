#!/usr/bin/env python3
"""Bump the project version in every location that carries it.

Usage: bump-version.py {major|minor|patch|X.Y.Z}

Updates:
  - pyproject.toml            (version = "...")
  - src/clockify_launchers/constants.py  (VERSION = "...")
  - debian/changelog          (new entry)
  - data/com.dribia.ClockifyLaunchers.metainfo.xml (new <release>)

Prints the new version to stdout.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def current_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("could not find version in pyproject.toml")
    return match.group(1)


def next_version(current: str, request: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", request):
        return request
    major, minor, patch = (int(p) for p in current.split("."))
    if request == "major":
        return f"{major + 1}.0.0"
    if request == "minor":
        return f"{major}.{minor + 1}.0"
    if request == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"invalid version request: {request!r} (use major|minor|patch|X.Y.Z)")


def replace_in_file(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"pattern not found in {path}: {pattern}")
    path.write_text(new_text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    old = current_version()
    new = next_version(old, sys.argv[1])
    if new == old:
        print(f"version unchanged: {old}", file=sys.stderr)
        return 1
    today = datetime.date.today().isoformat()
    now_rfc2822 = datetime.datetime.now(datetime.UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")

    replace_in_file(ROOT / "pyproject.toml", r'^version = "[^"]+"', f'version = "{new}"')
    replace_in_file(
        ROOT / "src/clockify_launchers/constants.py",
        r'^VERSION = "[^"]+"',
        f'VERSION = "{new}"',
    )

    changelog = ROOT / "debian/changelog"
    entry = (
        f"dribia-clockify-launchers ({new}-1) noble; urgency=medium\n\n"
        f"  * Release {new}.\n\n"
        f" -- Dribia <dev@dribia.com>  {now_rfc2822}\n\n"
    )
    changelog.write_text(entry + changelog.read_text(encoding="utf-8"), encoding="utf-8")

    replace_in_file(
        ROOT / "data/com.dribia.ClockifyLaunchers.metainfo.xml",
        r"  <releases>\n",
        (
            "  <releases>\n"
            f'    <release version="{new}" date="{today}">\n'
            "      <description>\n"
            f"        <p>Release {new}.</p>\n"
            "      </description>\n"
            "    </release>\n"
        ),
    )

    print(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
