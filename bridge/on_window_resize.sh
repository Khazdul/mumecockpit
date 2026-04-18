#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

# Window width unchanged — this was a pane drag, not a terminal resize
[ "$COLS" = "$window_cols" ] && exit 0

LEFT_WIDTH=$(( COLS - ui_width - 1 ))

RIGHT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="ui" || $2=="dev" {print $1; exit}')

touch "$LOCK"

if [ -n "$RIGHT_INDEX" ]; then
  tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="input" {print $1}')
[ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1

# Update stored window width
sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"

rm -f "$LOCK"
