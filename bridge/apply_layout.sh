#!/bin/bash
# bridge/apply_layout.sh — single authority for right-column geometry.
# Called after any right-column operation. Idempotent.

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || exit 0
grep -q "^ui_height=" "$LAYOUT_CONF" || echo "ui_height=20" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"

_pane_index() {
    tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' 2>/dev/null \
        | awk -v t="$1" '$2==t{print $1; exit}'
}

UI_IDX=$(_pane_index ui)
DEV_IDX=$(_pane_index dev)
STATUS_IDX=$(_pane_index status)
INPUT_IDX=$(_pane_index input)

# Input pin — always 1 row
[ -n "$INPUT_IDX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_IDX" -y 1

# Nothing to size if no right-column panes
[ -z "$UI_IDX" ] && [ -z "$DEV_IDX" ] && [ -z "$STATUS_IDX" ] && exit 0

# ── Height authority ──────────────────────────────────────────────────────
WIN_H=$(tmux display-message -p -t mume:cockpit '#{window_height}')
AVAIL=$WIN_H

S_HEIGHT=${status_height:-12}
U_HEIGHT=${ui_height:-20}

# Clamp ui_height so dev (when present) keeps at least 3 rows
if [ -n "$DEV_IDX" ]; then
    if [ -n "$STATUS_IDX" ]; then
        U_MAX=$(( AVAIL - S_HEIGHT - 3 ))
    else
        U_MAX=$(( AVAIL - 3 ))
    fi
    [ "$U_MAX" -lt 3 ] && U_MAX=3
    [ "$U_HEIGHT" -gt "$U_MAX" ] && U_HEIGHT=$U_MAX
fi
[ "$U_HEIGHT" -lt 3 ] && U_HEIGHT=3

# Apply top-down: each resize-pane drives the diff into the pane below
[ -n "$UI_IDX" ]     && tmux resize-pane -t "mume:cockpit.$UI_IDX"     -y "$U_HEIGHT"
[ -n "$STATUS_IDX" ] && tmux resize-pane -t "mume:cockpit.$STATUS_IDX" -y "$S_HEIGHT"
# dev receives the residual — no explicit sizing needed

# ── Width floor (status open → right column ≥ 33 cols) ───────────────────
if [ -n "$STATUS_IDX" ]; then
    RIGHT_W=$(tmux list-panes -t mume:cockpit \
        -F '#{pane_title} #{pane_width}' \
        | awk '$1=="ui" || $1=="dev" || $1=="status" {print $2; exit}')
    if [ -n "$RIGHT_W" ] && [ "$RIGHT_W" -lt 33 ]; then
        COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
        NEW_LEFT=$(( COLS - 33 - 1 ))
        if [ "$NEW_LEFT" -ge 30 ]; then
            tmux resize-pane -t mume:cockpit.0 -x "$NEW_LEFT"
            sed -i "s/^ui_width=.*/ui_width=33/" "$LAYOUT_CONF"
        fi
    fi
fi

exit 0
