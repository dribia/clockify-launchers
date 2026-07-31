#!/bin/bash
# Print/install development dependencies.
set -euo pipefail
PKGS="python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1 python3-httpx \
xvfb dbus-x11 xdotool imagemagick python3-dogtail at-spi2-core \
desktop-file-utils appstream lintian debhelper dh-python \
pybuild-plugin-pyproject python3-all python3-setuptools libglib2.0-bin \
devscripts reprepro gnome-keyring"
if [ "${1:-}" = "--install" ]; then
  sudo apt-get install -y $PKGS
else
  echo "Run: sudo apt-get install -y $PKGS"
fi
uv venv --python /usr/bin/python3.12 --system-site-packages .venv
uv pip install -e ".[dev]"
