#!/bin/bash
# Capture deterministic UI screenshots for every demo state.
# Usage: scripts/ui-capture.sh STATE [STATE...]
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
OUT_DIR="artifacts/ui"
mkdir -p "$OUT_DIR"

NARROW_STATES="launchers-populated onboarding-welcome preferences suggestions-remove"

capture_one() {
  local state="$1" width="$2" height="$3" suffix="$4"
  local tmp_root ready pid
  tmp_root="$(mktemp -d /tmp/clockify-launchers-cap.XXXXXX)"
  ready="$tmp_root/ready"
  (
    export HOME="$tmp_root/home"
    export XDG_CONFIG_HOME="$HOME/.config"
    export XDG_STATE_HOME="$HOME/.local/state"
    export XDG_CACHE_HOME="$HOME/.cache"
    export XDG_DATA_HOME="$HOME/.local/share"
    export XDG_RUNTIME_DIR="$tmp_root/runtime"
    mkdir -p "$HOME" "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"
    export LC_ALL=C.UTF-8 TZ=UTC
    export GSK_RENDERER=cairo GDK_BACKEND=x11 GTK_ENABLE_ANIMATIONS=0 ADW_DISABLE_PORTAL=1
    export CLOCKIFY_LAUNCHERS_DEMO=1
    export CLOCKIFY_LAUNCHERS_DEMO_STATE="$state"
    export CLOCKIFY_LAUNCHERS_READY_FILE="$ready"
    export CLOCKIFY_LAUNCHERS_WINDOW_SIZE="${width}x${height}"
    xvfb-run --auto-servernum --server-args="-screen 0 1400x1000x24" \
      dbus-run-session -- bash -c '
        set -e
        '"$PYTHON"' -m clockify_launchers gui &
        APP_PID=$!
        for i in $(seq 1 100); do
          [ -f "'"$ready"'" ] && break
          sleep 0.2
        done
        [ -f "'"$ready"'" ] || { echo "app never became ready"; kill $APP_PID; exit 1; }
        sleep 1.5
        WIN_ID=$(xdotool search --sync --onlyvisible --class clockify | head -1 || true)
        if [ -z "$WIN_ID" ]; then WIN_ID=$(xdotool search --onlyvisible "" | tail -1); fi
        import -window "$WIN_ID" "'"$OUT_DIR/$state$suffix.png"'"
        kill $APP_PID 2>/dev/null || true
      '
  )
  rm -rf "$tmp_root"
  # Plausibility checks: exists, not tiny, not blank.
  local file="$OUT_DIR/$state$suffix.png"
  if [ ! -s "$file" ]; then echo "FAIL: $file missing or empty"; return 1; fi
  local size colors
  size=$(identify -format "%w %h" "$file")
  read -r w h <<<"$size"
  if [ "$w" -lt 300 ] || [ "$h" -lt 300 ]; then echo "FAIL: $file implausibly small ($size)"; return 1; fi
  colors=$(identify -format "%k" "$file")
  if [ "$colors" -lt 8 ]; then echo "FAIL: $file appears blank ($colors colors)"; return 1; fi
  echo "ok: $file (${size}, ${colors} colors)"
}

FAILED=0
for state in "$@"; do
  capture_one "$state" 1000 720 "" || FAILED=1
done
for state in $NARROW_STATES; do
  case " $* " in
    *" $state "*) capture_one "$state" 800 700 "-narrow" || FAILED=1 ;;
  esac
done
exit $FAILED
