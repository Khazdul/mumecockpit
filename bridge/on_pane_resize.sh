#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

# Skip if this resize was triggered programmatically
[ -f "$LOCK" ] && exit 0

# Find current width of ui or dev pane
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="dev" {print $2; exit}')

# No right pane open — nothing to save
[ -z "$NEW_WIDTH" ] && exit 0

sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"
