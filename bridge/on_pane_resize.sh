#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

# Save ui_width from whichever right pane exists
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="dev" {print $2; exit}')
[ -z "$NEW_WIDTH" ] && exit 0
sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"

# Save ui_height only if both ui and dev are open
HAS_UI=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^ui$')
HAS_DEV=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^dev$')
if [ -n "$HAS_UI" ] && [ -n "$HAS_DEV" ]; then
  NEW_HEIGHT=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_title} #{pane_height}' \
    | awk '$1=="ui" {print $2; exit}')
  [ -n "$NEW_HEIGHT" ] && sed -i "s/^ui_height=.*/ui_height=$NEW_HEIGHT/" "$LAYOUT_CONF"
fi
