#!/usr/bin/env bash
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
if [[ "$OSTYPE" == linux* ]]; then
    if ! command -v tmux >/dev/null 2>&1; then
        echo "📦 Installing tmux..."
        sudo apt update && sudo apt install -y tmux
    fi
    if ! command -v lua >/dev/null 2>&1; then
        echo "📦 Installing lua..."
        sudo apt update && sudo apt install -y lua5.4
    fi
fi

# --- Lua runtime resolution (macOS) -----------------------------------
# Prepend brew's lua@5.4 keg to PATH so `lua` resolves to 5.4, not
# whatever brew's rolling `lua` formula currently ships.
# Linux is unaffected: apt package `lua5.4` already pins by name.
if [[ "$OSTYPE" == darwin* ]]; then
    lua_prefix=$(brew --prefix lua@5.4 2>/dev/null)
    if [ -n "$lua_prefix" ] && [ -x "$lua_prefix/bin/lua" ]; then
        export PATH="$lua_prefix/bin:$PATH"
    fi
fi

# --- Lua version pre-flight check -------------------------------------
# Fail fast with a clear error if `lua` is not 5.4.x. Catches future
# upstream changes (lua@5.4 removed from brew, apt switching to 5.5,
# user's PATH overriding ours) before the cockpit silently misbehaves.
if ! command -v lua >/dev/null 2>&1; then
    echo "Error: lua not found on PATH." >&2
    echo "macOS: brew install lua@5.4" >&2
    echo "Linux: apt-get install lua5.4" >&2
    exit 1
fi
lua_version=$(lua -v 2>&1 | awk '{print $2}')
lua_major=${lua_version%.*}
if [ "$lua_major" != "5.4" ]; then
    echo "Error: cockpit requires Lua 5.4.x, found Lua $lua_version" >&2
    echo "  which lua: $(command -v lua)" >&2
    echo "macOS: brew install lua@5.4 (and re-run start.sh; PATH will pick it up)" >&2
    echo "Linux: apt-get install lua5.4" >&2
    exit 1
fi

mkdir -p bridge/runtime logs

# Seed default.tin from the blank-profile template on fresh installs.
# Idempotent: runs only when default.tin is missing.
if [ ! -f ttpp/profiles/default.tin ] && [ -f bridge/launcher/templates/blank_profile.tin ]; then
    mkdir -p ttpp/profiles
    cp bridge/launcher/templates/blank_profile.tin ttpp/profiles/default.tin
fi

chmod +x bridge/launcher/open_pane.sh
chmod +x bridge/layout/focus_input.sh
chmod +x bridge/launcher.sh
chmod +x bridge/tmux_start.sh
chmod +x bridge/launcher/launcher.sh
chmod +x bridge/launcher/tmux_start.sh
chmod +x bridge/launcher/build_initial_layout.sh
chmod +x bridge/launcher/wait_for_layout.sh
chmod +x bridge/launcher/ingame_menu.sh

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
    exec bash bridge/launcher/tmux_start.sh
fi

exec bash bridge/launcher/launcher.sh
