#!/usr/bin/env bash
# bridge/toggle_pane.sh — toggle ui/dev/input panes and pane-border headers.
# Usage: toggle_pane.sh <target> [--persist]
# Targets: ui, dev, input, headers
# Called by cp -u/-d/-i/-h aliases in system.tin.
# With --persist, writes the new state to bridge/startup.conf (used by the in-game popup).

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="$SCRIPT_DIR/startup.conf"
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
        sed -i "s/^${key}=.*/${key}=${val}/" "$CONF"
    else
        echo "${key}=${val}" >> "$CONF"
    fi
}

case "$TARGET" in
    comm)
        if _pane_exists "comm"; then
            _kill_pane "comm"
            bash "$SCRIPT_DIR/apply_layout.sh"
        else
            bash "$SCRIPT_DIR/open_pane.sh" comm
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
            bash "$SCRIPT_DIR/open_pane.sh" status
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
            bash "$SCRIPT_DIR/open_pane.sh" ui
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
            bash "$SCRIPT_DIR/open_pane.sh" dev
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "dev"; then
                _persist_key "show_dev" "1"
            else
                _persist_key "show_dev" "0"
            fi
        fi
        ;;

    input)
        if _pane_exists "input"; then
            _kill_pane "input"
            tmux unbind-key -n MouseUp1Pane
            tmux unbind-key -n MouseDragEnd1Pane
            tmux unbind-key -n DoubleClick1Pane
            tmux unbind-key -n TripleClick1Pane
            tmux select-pane -t mume:cockpit.0
        else
            bash "$SCRIPT_DIR/open_pane.sh" input
        fi
        if [ "$PERSIST" -eq 1 ]; then
            if _pane_exists "input"; then
                _persist_key "show_input" "1"
            else
                _persist_key "show_input" "0"
            fi
        fi
        ;;

    headers)
        STATUS=$(tmux show-option -t mume pane-border-status 2>/dev/null | awk '{print $2}')
        if [ "$STATUS" = "off" ]; then
            tmux set-option -t mume pane-border-status top
            tmux set-option -t mume pane-border-style        fg=colour235
            tmux set-option -t mume pane-active-border-style fg=colour235
        else
            tmux set-option -t mume pane-border-status off
            tmux set-option -t mume pane-border-style        fg=black
            tmux set-option -t mume pane-active-border-style fg=black
        fi
        if [ "$PERSIST" -eq 1 ]; then
            NEW_STATUS=$(tmux show-option -t mume pane-border-status 2>/dev/null | awk '{print $2}')
            if [ "$NEW_STATUS" = "off" ]; then
                _persist_key "show_pane_dividers" "0"
            else
                _persist_key "show_pane_dividers" "1"
            fi
        fi
        ;;

    *)
        echo "toggle_pane.sh: unknown target: $TARGET" >&2
        exit 1
        ;;
esac

exit 0
