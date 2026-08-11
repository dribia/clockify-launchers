#!/bin/bash
# Run a command under an isolated Xvfb display with a private D-Bus session.
set -euo pipefail
TMP_ROOT="$(mktemp -d /tmp/clockify-launchers-ui.XXXXXX)"
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_STATE_HOME="$HOME/.local/state"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_RUNTIME_DIR="$TMP_ROOT/runtime"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

export LC_ALL=C.UTF-8
export TZ=UTC
export GTK_A11Y=atspi
export GSK_RENDERER=cairo
export GDK_BACKEND=x11
export ADW_DISABLE_PORTAL=1
export GTK_ENABLE_ANIMATIONS=0

exec xvfb-run --auto-servernum --server-args="-screen 0 1280x900x24" \
  dbus-run-session -- bash -c '
    # dogtail refuses to run unless toolkit accessibility is enabled in the session.
    gsettings set org.gnome.desktop.interface toolkit-accessibility true 2>/dev/null || true
    exec "$@"' _ "$@"
