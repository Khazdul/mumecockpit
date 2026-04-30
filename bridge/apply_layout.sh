#!/usr/bin/env bash
# bridge/apply_layout.sh — pins the input row and enforces the width floor.
# Right-column pane heights are tmux-managed (freely resizable).
# Called after any right-column operation. Idempotent.

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || exit 0

_pane_index() {
    tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' 2>/dev/null \
        | awk -v t="$1" '$2==t{print $1; exit}'
}

UI_IDX=$(_pane_index ui)
COMM_IDX=$(_pane_index comm)
DEV_IDX=$(_pane_index dev)
STATUS_IDX=$(_pane_index status)
INPUT_IDX=$(_pane_index input)

# Input pin — always 1 row
[ -n "$INPUT_IDX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_IDX" -y 1

# ── Width floor (status open → right column ≥ 29 cols) ───────────────────
if [ -n "$STATUS_IDX" ]; then
    RIGHT_W=$(tmux list-panes -t mume:cockpit \
        -F '#{pane_title} #{pane_width}' \
        | awk '$1=="ui" || $1=="comm" || $1=="dev" || $1=="status" {print $2; exit}')
    if [ -n "$RIGHT_W" ] && [ "$RIGHT_W" -lt 29 ]; then
        COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
        NEW_LEFT=$(( COLS - 29 - 1 ))
        if [ "$NEW_LEFT" -ge 30 ]; then
            tmux resize-pane -t mume:cockpit.0 -x "$NEW_LEFT"
            sed -i "s/^ui_width=.*/ui_width=29/" "$LAYOUT_CONF"
        fi
    fi
fi

exit 0
