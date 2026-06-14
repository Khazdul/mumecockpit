#!/usr/bin/env bash
# bridge/layout/toggle_pane.sh — toggle the right-column panes on/off.
# Usage: toggle_pane.sh <target> [--persist]
# Targets: ui, dev, comm, status, timers, group
# Called by cp -u/-d/-m/-c/-t/-g aliases in system.tin. Per-pane in-pane
# borders are toggled from the Panes grid (border_<key>), not here.
# With --persist, writes the new state to bridge/runtime/startup.conf (used by the in-game popup).

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF="$BRIDGE_DIR/runtime/startup.conf"

source "$BRIDGE_DIR/lib/conf_io.sh"
TARGET="${1:-}"
PERSIST=0

if [ "${2:-}" = "--persist" ]; then
    PERSIST=1
fi

if [ -z "$TARGET" ]; then
    echo "toggle_pane.sh: missing target" >&2
    exit 1
fi

_pane_exists() {
    tmux list-panes -t mume:cockpit -F '#{pane_title}' 2>/dev/null | grep -q "^${1}$"
}

_kill_pane() {
    local idx
    idx=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' 2>/dev/null \
        | awk "/^[0-9]+ ${1}\$/{print \$1}")
    [ -n "$idx" ] && tmux kill-pane -t "mume:cockpit.$idx"
}

_persist_key() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$CONF" 2>/dev/null; then
        sed_inplace "s/^${key}=.*/${key}=${val}/" "$CONF"
    else
        echo "${key}=${val}" >> "$CONF"
    fi
}

case "$TARGET" in
    timers)
        if _pane_exists "timers"; then
            _kill_pane "timers"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$BRIDGE_DIR/launcher/open_pane.sh" timers
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "timers"; then
                _persist_key "show_timers" "1"
            else
                _persist_key "show_timers" "0"
            fi
        fi
        ;;

    group)
        if _pane_exists "group"; then
            _kill_pane "group"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$BRIDGE_DIR/launcher/open_pane.sh" group
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "group"; then
                _persist_key "show_group" "1"
            else
                _persist_key "show_group" "0"
            fi
        fi
        ;;

    comm)
        if _pane_exists "comm"; then
            _kill_pane "comm"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$BRIDGE_DIR/launcher/open_pane.sh" comm
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "comm"; then
                _persist_key "show_comm" "1"
            else
                _persist_key "show_comm" "0"
            fi
        fi
        ;;

    status)
        if _pane_exists "status"; then
            _kill_pane "status"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$BRIDGE_DIR/launcher/open_pane.sh" status
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "status"; then
                _persist_key "show_status" "1"
            else
                _persist_key "show_status" "0"
            fi
        fi
        ;;

    ui)
        if _pane_exists "ui"; then
            _kill_pane "ui"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$BRIDGE_DIR/launcher/open_pane.sh" ui
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "ui"; then
                _persist_key "show_ui" "1"
            else
                _persist_key "show_ui" "0"
            fi
        fi
        ;;

    dev)
        if _pane_exists "dev"; then
            _kill_pane "dev"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$BRIDGE_DIR/launcher/open_pane.sh" dev
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "dev"; then
                _persist_key "show_dev" "1"
            else
                _persist_key "show_dev" "0"
            fi
        fi
        ;;

    *)
        echo "toggle_pane.sh: unknown target: $TARGET" >&2
        exit 1
        ;;
esac

exit 0
