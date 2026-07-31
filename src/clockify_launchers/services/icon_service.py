"""Icon generation and safe selected-image normalization."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

MAX_ICON_BYTES = 5 * 1024 * 1024

_FALLBACK_COLORS = [
    "#03A9F4",
    "#8BC34A",
    "#FF5722",
    "#9C27B0",
    "#607D8B",
    "#FF9800",
    "#009688",
    "#E91E63",
]


class IconError(Exception): ...


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def text_color_for(background: str) -> str:
    """White or near-black text, whichever gives better contrast."""
    try:
        lum = _relative_luminance(background)
    except (ValueError, IndexError):
        return "#FFFFFF"
    return "#FFFFFF" if lum < 0.45 else "#1A1A1A"


def monogram(name: str) -> str:
    words = [w for w in name.split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def normalize_color(color: str | None, fallback_seed: str = "") -> str:
    if color and len(color.lstrip("#")) == 6:
        try:
            int(color.lstrip("#"), 16)
            return "#" + color.lstrip("#").upper()
        except ValueError:
            pass
    index = int(hashlib.sha256(fallback_seed.encode()).hexdigest(), 16) % len(_FALLBACK_COLORS)
    return _FALLBACK_COLORS[index]


def generate_svg_icon(project_name: str, project_color: str | None) -> str:
    """Accessible SVG tile: project color, contrasting monogram, timer glyph."""
    bg = normalize_color(project_color, fallback_seed=project_name)
    fg = text_color_for(bg)
    text = escape(monogram(project_name))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="{bg}"/>
  <text x="64" y="74" font-family="Cantarell, sans-serif" font-size="52" font-weight="700"
        text-anchor="middle" fill="{fg}">{text}</text>
  <g transform="translate(94,94)">
    <circle r="20" fill="{fg}" opacity="0.9"/>
    <circle r="16" fill="{bg}"/>
    <path d="M 0 -10 L 0 0 L 8 4" stroke="{fg}" stroke-width="3.5" fill="none"
          stroke-linecap="round"/>
  </g>
</svg>
"""


class IconService:
    def __init__(self, icons_dir: Path) -> None:
        self._icons_dir = icons_dir

    def icon_path(self, launcher_id: str, extension: str = "svg") -> Path:
        return self._icons_dir / f"{launcher_id}.{extension}"

    def write_generated(
        self, launcher_id: str, project_name: str, project_color: str | None
    ) -> Path:
        self._icons_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.icon_path(launcher_id)
        path.write_text(generate_svg_icon(project_name, project_color), encoding="utf-8")
        return path

    def import_selected(self, launcher_id: str, source: Path) -> Path:
        """Copy a normalized, validated user-selected image into managed storage."""
        if not source.is_file():
            raise IconError(f"not a file: {source}")
        size = source.stat().st_size
        if size == 0 or size > MAX_ICON_BYTES:
            raise IconError(f"icon file size {size} bytes is out of bounds")
        extension = self._validate_image(source)
        self._icons_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        dest = self.icon_path(launcher_id, extension)
        for stale in self._icons_dir.glob(f"{launcher_id}.*"):
            stale.unlink(missing_ok=True)
        shutil.copyfile(source, dest)
        return dest

    @staticmethod
    def _validate_image(source: Path) -> str:
        header = source.open("rb").read(64)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if header.startswith(b"\xff\xd8\xff"):
            return "jpg"
        stripped = header.lstrip()
        if stripped.startswith(b"<?xml") or stripped.startswith(b"<svg"):
            return "svg"
        raise IconError("unsupported image format (PNG, JPEG, or SVG required)")

    def delete_icon(self, launcher_id: str) -> None:
        for path in self._icons_dir.glob(f"{launcher_id}.*"):
            if not path.is_symlink():
                path.unlink(missing_ok=True)

    def hash_of(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
