#!/usr/bin/env bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

# ── Width persistence ─────────────────────────────────────────────────────
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="comm" || $1=="dev" || $1=="status" {print $2; exit}')
[ -z "$NEW_WIDTH" ] && exit 0

HAS_STATUS=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^status$')

# Clamp: status pane requires ≥ 33 cols for its field layout
if [ -n "$HAS_STATUS" ] && [ "$NEW_WIDTH" -lt 33 ]; then
    NEW_WIDTH=33
fi
sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"

# ── Height drag detection ─────────────────────────────────────────────────
# Column order: ui (top) → comm → status → dev (bottom)
# Resizable borders: ui↔comm (persists ui_height), comm↔status (persists comm_height).
# status↔dev border: status_height is fixed — snap back via apply_layout.sh.

grep -q "^ui_height="   "$LAYOUT_CONF" || echo "ui_height=20"   >> "$LAYOUT_CONF"
grep -q "^comm_height=" "$LAYOUT_CONF" || echo "comm_height=10" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"

U=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
    | awk '$1=="ui"   {print $2; exit}')
C=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
    | awk '$1=="comm" {print $2; exit}')

if [ -n "$U" ] && [ "$U" -ge 1 ] && [ "$U" -ne "${ui_height:-20}" ]; then
    sed -i "s/^ui_height=.*/ui_height=$U/" "$LAYOUT_CONF"
fi

if [ -n "$C" ] && [ "$C" -ge 1 ] && [ "$C" -ne "${comm_height:-10}" ]; then
    sed -i "s/^comm_height=.*/comm_height=$C/" "$LAYOUT_CONF"
fi

bash "$HOME/MUME/bridge/apply_layout.sh"
