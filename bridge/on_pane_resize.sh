#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

# Save ui_width from whichever right pane exists
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="dev" || $1=="status" {print $2; exit}')
[ -z "$NEW_WIDTH" ] && exit 0
# Clamp: manual drag cannot persist ui_width below RIGHT_MIN (33)
ORIG_WIDTH=$NEW_WIDTH
[ "$NEW_WIDTH" -lt 33 ] && NEW_WIDTH=33
sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"
if [ "$ORIG_WIDTH" -lt 33 ]; then
    COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
    LEFT=$(( COLS - 33 - 1 ))
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT"
    bash "$HOME/MUME/bridge/apply_layout.sh"
fi

HAS_STATUS=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^status$')
if [ -n "$HAS_STATUS" ]; then
  STATUS_H=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
    | awk '$1=="status" {print $2; exit}')
  source "$LAYOUT_CONF"
  CONFIGURED=${status_height:-12}
  if [ "$STATUS_H" -ne "$CONFIGURED" ]; then
    # User dragged — ignore and snap back. Do NOT persist.
    bash "$HOME/MUME/bridge/apply_layout.sh"
  fi
fi
