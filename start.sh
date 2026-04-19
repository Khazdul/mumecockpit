#!/bin/bash
# start.sh — MUME cockpit entry point.
# Installs dependencies, then launches the startup menu or goes straight to tmux.
#
# Usage:
#   ./start.sh            — show startup menu (default)
#   ./start.sh --no-menu  — skip menu, use current startup.conf
#   ./start.sh -d         — skip menu, force dev pane on (not persisted)
#   ./start.sh -u         — skip menu, force UI pane on (not persisted)

cd "$(dirname "$0")"

# ---------------------------------------------------------------------------
# 1. Install dependencies
# ---------------------------------------------------------------------------
if ! command -v tmux >/dev/null 2>&1; then
    echo "📦 Installing tmux..."
    sudo apt update && sudo apt install -y tmux
fi

if ! command -v lua >/dev/null 2>&1; then
    echo "📦 Installing lua..."
    sudo apt update && sudo apt install -y lua5.4
fi

mkdir -p bridge logs

chmod +x bridge/open_pane.sh
chmod +x bridge/focus_input.sh
chmod +x bridge/launcher.sh
chmod +x bridge/tmux_start.sh

# ---------------------------------------------------------------------------
# 2. Parse flags
# ---------------------------------------------------------------------------
_NO_MENU=0
_OVERRIDE_SHOW_UI=""
_OVERRIDE_SHOW_DEV=""

for arg in "$@"; do
    case "$arg" in
        --no-menu)  _NO_MENU=1 ;;
        -d)         _NO_MENU=1; _OVERRIDE_SHOW_DEV=1 ;;
        -u)         _NO_MENU=1; _OVERRIDE_SHOW_UI=1  ;;
        -du|-ud)    _NO_MENU=1; _OVERRIDE_SHOW_DEV=1; _OVERRIDE_SHOW_UI=1 ;;
    esac
done

# ---------------------------------------------------------------------------
# 3. Dispatch
# ---------------------------------------------------------------------------
if [ "$_NO_MENU" -eq 1 ]; then
    export _OVERRIDE_SHOW_UI _OVERRIDE_SHOW_DEV
    exec bash bridge/tmux_start.sh
else
    exec bash bridge/launcher.sh
fi
