#!/usr/bin/env bash
# bridge/apply_layout.sh — single authority for right-column geometry.
# Column order (top to bottom): ui → comm → status → dev
# Called after any right-column operation. Idempotent.

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || exit 0
grep -q "^ui_height="     "$LAYOUT_CONF" || echo "ui_height=20"    >> "$LAYOUT_CONF"
grep -q "^comm_height="   "$LAYOUT_CONF" || echo "comm_height=10"  >> "$LAYOUT_CONF"
grep -q "^status_height=" "$LAYOUT_CONF" || echo "status_height=12" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"

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

# Nothing to size if no right-column panes
[ -z "$UI_IDX" ] && [ -z "$COMM_IDX" ] && [ -z "$DEV_IDX" ] && [ -z "$STATUS_IDX" ] && exit 0

# ── Height authority ──────────────────────────────────────────────────────
WIN_H=$(tmux display-message -p -t mume:cockpit '#{window_height}')

S_HEIGHT=${status_height:-12}
C_HEIGHT=${comm_height:-10}
U_HEIGHT=${ui_height:-20}

# Count borders needed between panes (one per pane boundary)
BORDERS=0
ACTIVE_COUNT=0
[ -n "$UI_IDX" ]     && { ACTIVE_COUNT=$(( ACTIVE_COUNT + 1 )); }
[ -n "$COMM_IDX" ]   && { ACTIVE_COUNT=$(( ACTIVE_COUNT + 1 )); }
[ -n "$STATUS_IDX" ] && { ACTIVE_COUNT=$(( ACTIVE_COUNT + 1 )); }
[ -n "$DEV_IDX" ]    && { ACTIVE_COUNT=$(( ACTIVE_COUNT + 1 )); }
[ "$ACTIVE_COUNT" -gt 1 ] && BORDERS=$(( ACTIVE_COUNT - 1 ))

# Available height for all right panes minus borders
AVAIL=$(( WIN_H - BORDERS ))

# Clamp S_HEIGHT (status is fixed-height in phase 1)
[ "$S_HEIGHT" -lt 1 ] && S_HEIGHT=1

# Clamp C_HEIGHT so ui + status + dev each keep at least 1 row
C_MAX=$AVAIL
[ -n "$STATUS_IDX" ] && C_MAX=$(( C_MAX - S_HEIGHT ))
[ -n "$UI_IDX" ]     && C_MAX=$(( C_MAX - 1 ))         # ui gets at least 1
[ -n "$DEV_IDX" ]    && C_MAX=$(( C_MAX - 1 ))         # dev gets at least 1
[ "$C_MAX" -lt 1 ]   && C_MAX=1
[ -n "$COMM_IDX" ] && [ "$C_HEIGHT" -gt "$C_MAX" ] && C_HEIGHT=$C_MAX
[ "$C_HEIGHT" -lt 1 ] && C_HEIGHT=1

# Clamp U_HEIGHT so comm + status + dev each keep at least 1 row
U_MAX=$AVAIL
[ -n "$STATUS_IDX" ] && U_MAX=$(( U_MAX - S_HEIGHT ))
[ -n "$COMM_IDX" ]   && U_MAX=$(( U_MAX - C_HEIGHT ))
[ -n "$DEV_IDX" ]    && U_MAX=$(( U_MAX - 1 ))         # dev gets at least 1
[ "$U_MAX" -lt 1 ]   && U_MAX=1
[ -n "$UI_IDX" ] && [ "$U_HEIGHT" -gt "$U_MAX" ] && U_HEIGHT=$U_MAX
[ "$U_HEIGHT" -lt 1 ] && U_HEIGHT=1

# Apply heights in order: ui → comm → status; dev receives the residual.
# Applying from top down means tmux moves each pane's bottom border,
# squeezing panes below rather than above.
[ -n "$UI_IDX" ]     && tmux resize-pane -t "mume:cockpit.$UI_IDX"     -y "$U_HEIGHT"
[ -n "$COMM_IDX" ]   && tmux resize-pane -t "mume:cockpit.$COMM_IDX"   -y "$C_HEIGHT"
[ -n "$STATUS_IDX" ] && tmux resize-pane -t "mume:cockpit.$STATUS_IDX" -y "$S_HEIGHT"
# dev receives the residual — no explicit sizing needed

# ── Width floor (status open → right column ≥ 33 cols) ───────────────────
if [ -n "$STATUS_IDX" ]; then
    RIGHT_W=$(tmux list-panes -t mume:cockpit \
        -F '#{pane_title} #{pane_width}' \
        | awk '$1=="ui" || $1=="comm" || $1=="dev" || $1=="status" {print $2; exit}')
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
