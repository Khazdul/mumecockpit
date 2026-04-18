#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

# Break loop — skip if we triggered this resize ourselves
[ -f "$LOCK" ] && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

RIGHT_WIDTH=$(( COLS * ui_ratio / 100 ))
[ $RIGHT_WIDTH -lt 33 ] && RIGHT_WIDTH=33
LEFT_WIDTH=$(( COLS - RIGHT_WIDTH - 1 ))

# Find right pane (ui or dev, topmost)
RIGHT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="ui" || $2=="dev" {print $1; exit}')

touch "$LOCK"

if [ -n "$RIGHT_INDEX" ]; then
  tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

# Always re-pin input pane to 1 row
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="input" {print $1}')
[ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1

rm -f "$LOCK"
