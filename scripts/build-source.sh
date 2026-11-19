#!/usr/bin/env bash
# Build an unsigned Debian source package suitable for signing and uploading to Launchpad.
set -euo pipefail

cd "$(dirname "$0")/.."
command -v git >/dev/null
command -v dpkg-parsechangelog >/dev/null
command -v dpkg-buildpackage >/dev/null

package=dribia-clockify-launchers
version=$(dpkg-parsechangelog -S Version)
upstream_version=${version%-*}
if [[ "$upstream_version" == "$version" ]]; then
  echo "Expected a Debian revision (for example, 0.5.1-1)" >&2
  exit 1
fi

# Export the committed tree, not the local working directory, so that the
# upstream archive and the source being packaged have matching contents.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
source_dir="$package-$upstream_version"
git archive --format=tar --prefix="$source_dir/" HEAD | tar -xf - -C "$work"

# With 3.0 (quilt), debian/ belongs in the Debian packaging archive rather
# than the pristine upstream orig tarball.
tar -cJf "$work/${package}_${upstream_version}.orig.tar.xz" \
  --exclude="$source_dir/debian" -C "$work" "$source_dir"

(
  cd "$work/$source_dir"
  dpkg-buildpackage -S -us -uc -sa
)

mkdir -p dist/source
cp "$work"/"${package}_"${upstream_version}.orig.tar.xz dist/source/
cp "$work"/"${package}_"${version}.debian.tar.* dist/source/
cp "$work"/"${package}_"${version}.dsc dist/source/
cp "$work"/"${package}_"${version}_source.buildinfo dist/source/
cp "$work"/"${package}_"${version}_source.changes dist/source/
echo "Unsigned source package written to dist/source/; sign before uploading."
