#!/usr/bin/env bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

# ── Width persistence ─────────────────────────────────────────────────────
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="comm" || $1=="dev" || $1=="status" || $1=="buffs" {print $2; exit}')
[ -z "$NEW_WIDTH" ] && exit 0

sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"

bash "$HOME/MUME/bridge/apply_layout.sh"
