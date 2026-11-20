#!/usr/bin/env bash
# Build an unsigned Debian source package from the committed tree.
# Set PPA_SERIES=noble or resolute for a per-series Launchpad upload.
set -euo pipefail

cd "$(dirname "$0")/.."
command -v git >/dev/null
command -v dpkg-parsechangelog >/dev/null
command -v dpkg-buildpackage >/dev/null
command -v python3 >/dev/null

package=dribia-clockify-launchers
base_version=$(dpkg-parsechangelog -S Version)
upstream_version=${base_version%-*}
if [[ "$upstream_version" == "$base_version" ]]; then
  echo "Expected a Debian revision (for example, 0.5.2-1)" >&2
  exit 1
fi

# Launchpad requires unique versions for each Ubuntu series. The suffix is
# lower than the next Debian revision but greater than the previous upstream
# release (e.g. 0.5.2-1~ppa1~ubuntu24.04.1 > 0.5.1-1).
series=${PPA_SERIES:-}
case "$series" in
  "") version="$base_version" ;;
  noble) version="${base_version}~ppa1~ubuntu24.04.1" ;;
  resolute) version="${base_version}~ppa1~ubuntu26.04.1" ;;
  *) echo "Unsupported PPA_SERIES: $series (supported: noble, resolute)" >&2; exit 1 ;;
esac

# Export committed files only, so uncommitted edits never reach Launchpad.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
source_dir="$package-$upstream_version"
git archive --format=tar --prefix="$source_dir/" HEAD | tar -xf - -C "$work"

if [[ -n "$series" ]]; then
  # Update the changelog IN THE EXPORTED TREE (not in the working directory).
  # Modifying debian/changelog outside the export would be lost by git archive.
  python3 - "$work/$source_dir/debian/changelog" "$base_version" "$version" "$series" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old, new, suite = sys.argv[2:]
text = path.read_text(encoding="utf-8")
first, newline, remaining = text.partition("\n")
prefix = f"dribia-clockify-launchers ({old}) "
if not first.startswith(prefix) or "; urgency=" not in first or not newline:
    raise SystemExit("Unexpected top debian/changelog entry")
urgency = first.split("; urgency=", 1)[1]
path.write_text(
    f"dribia-clockify-launchers ({new}) {suite}; urgency={urgency}\n" + remaining,
    encoding="utf-8",
)
PY
fi

# Keep this orig tarball byte-identical across series; Launchpad rejects
# multiple different .orig.tar.xz files for the same upstream version.
# Debian packaging is excluded from the pristine upstream archive.
epoch=$(git show -s --format=%ct HEAD)
tar --format=gnu --sort=name --mtime="@$epoch" \
  --owner=0 --group=0 --numeric-owner \
  --exclude="$source_dir/debian" \
  -cJf "$work/${package}_${upstream_version}.orig.tar.xz" \
  -C "$work" "$source_dir"

(
  cd "$work/$source_dir"
  dpkg-buildpackage -S -us -uc -sa
)

mkdir -p dist/source
cp "$work/${package}_${upstream_version}.orig.tar.xz" dist/source/
cp "$work/${package}_${version}.debian.tar."* dist/source/
cp "$work/${package}_${version}.dsc" dist/source/
cp "$work/${package}_${version}_source.buildinfo" dist/source/
cp "$work/${package}_${version}_source.changes" dist/source/

echo "Unsigned ${series:-default} source package ${version} written to dist/source/."
echo "Sign its _source.changes file with debsign before uploading to Launchpad."
