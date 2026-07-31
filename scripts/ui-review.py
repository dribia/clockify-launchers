#!/usr/bin/env python3
"""Build a contact sheet from UI captures and print the review checklist."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKLIST = """
UI review checklist (record findings in docs/ui-review.md):
  1. Clipped or truncated text?
  2. Overlapping widgets?
  3. Clear visual hierarchy and primary action per screen?
  4. Consistent spacing/margins?
  5. Sufficient contrast for text and status indicators?
  6. Icons present and legible?
  7. Accidental empty regions?
  8. Scrolling works where content overflows?
  9. Narrow layout usable?
"""


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/ui")
    images = sorted(out_dir.glob("*.png"))
    images = [i for i in images if i.name != "contact-sheet.png"]
    if not images:
        print(f"No screenshots found in {out_dir}; run 'make ui-capture' first.")
        return 1
    sheet = out_dir / "contact-sheet.png"
    cmd = [
        "montage",
        "-label",
        "%f",
        *[str(i) for i in images],
        "-tile",
        "3x",
        "-geometry",
        "420x300+8+8",
        str(sheet),
    ]
    subprocess.run(cmd, check=True)  # noqa: S603 - fixed argv
    print(f"Contact sheet: {sheet}")
    print(CHECKLIST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
