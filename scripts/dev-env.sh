#!/bin/bash
# Run a command against an isolated development HOME/XDG environment.
set -euo pipefail
DEV_ROOT="${CLOCKIFY_LAUNCHERS_DEV_ROOT:-$PWD/.dev-home}"
mkdir -p "$DEV_ROOT"
export HOME="$DEV_ROOT"
export XDG_CONFIG_HOME="$DEV_ROOT/.config"
export XDG_STATE_HOME="$DEV_ROOT/.local/state"
export XDG_CACHE_HOME="$DEV_ROOT/.cache"
export XDG_DATA_HOME="$DEV_ROOT/.local/share"
export XDG_RUNTIME_DIR="$DEV_ROOT/runtime"
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"
exec "$@"
