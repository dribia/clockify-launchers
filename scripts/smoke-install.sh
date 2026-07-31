#!/bin/bash
# Install the built .deb, smoke-test it with an ephemeral HOME, and remove it.
# Requires sudo for dpkg; state checks use a throwaway HOME.
set -euo pipefail
cd "$(dirname "$0")/.."
DEB=$(ls dist/deb/dribia-clockify-launchers_*.deb 2>/dev/null | head -1)
[ -n "$DEB" ] || { echo "Build the package first: make deb"; exit 1; }

sudo dpkg -i "$DEB" || sudo apt-get install -f -y

TMP_HOME=$(mktemp -d)
trap 'rm -rf "$TMP_HOME"' EXIT
export HOME="$TMP_HOME"
export XDG_CONFIG_HOME="$TMP_HOME/.config"
export XDG_STATE_HOME="$TMP_HOME/.local/state"
export XDG_DATA_HOME="$TMP_HOME/.local/share"
export XDG_CACHE_HOME="$TMP_HOME/.cache"
export XDG_RUNTIME_DIR="$TMP_HOME/runtime"
mkdir -p "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"

clockify-launchers --version
clockify-launchers doctor || true   # unconfigured is expected; must not crash
desktop-file-validate /usr/share/applications/com.dribia.ClockifyLaunchers.desktop
test -f /usr/lib/systemd/user/clockify-launchers-sync.timer

# GUI launch smoke test under Xvfb when available.
if command -v xvfb-run >/dev/null; then
  CLOCKIFY_LAUNCHERS_DEMO=1 CLOCKIFY_LAUNCHERS_READY_FILE="$TMP_HOME/ready" \
    xvfb-run --auto-servernum dbus-run-session -- bash -c '
      clockify-launchers gui & PID=$!
      for i in $(seq 1 100); do [ -f "'"$TMP_HOME"'/ready" ] && break; sleep 0.2; done
      kill $PID 2>/dev/null || true
      [ -f "'"$TMP_HOME"'/ready" ]'
  echo "GUI smoke test passed"
fi

# Simulate per-user state, then verify package removal leaves it alone.
mkdir -p "$XDG_STATE_HOME/clockify-launchers"
echo marker > "$XDG_STATE_HOME/clockify-launchers/marker"
sudo dpkg -r dribia-clockify-launchers
test -f "$XDG_STATE_HOME/clockify-launchers/marker" || { echo "FAIL: user state removed"; exit 1; }
echo "smoke-install: all checks passed"
