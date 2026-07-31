#!/bin/bash
# Build the Debian package into dist/deb/.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist/deb
mkdir -p dist/deb
dpkg-buildpackage -us -uc -b
mv ../dribia-clockify-launchers_*.deb dist/deb/
mv ../dribia-clockify-launchers_*.buildinfo ../dribia-clockify-launchers_*.changes dist/deb/ 2>/dev/null || true
echo "Built: $(ls dist/deb/*.deb)"
