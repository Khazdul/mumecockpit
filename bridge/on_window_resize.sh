#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

[ "$COLS" = "$window_cols" ] && exit 0

LEFT_WIDTH=$(( COLS - ui_width - 1 ))

RIGHT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="ui" || $2=="dev" {print $1; exit}')

touch "$LOCK"

if [ -n "$RIGHT_INDEX" ]; then
  tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

# Re-pin input pane to 1 row
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="input" {print $1}')
[ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1

# Enforce ui_height if both ui and dev are open
HAS_UI=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^ui$')
HAS_DEV=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^dev$')
if [ -n "$HAS_UI" ] && [ -n "$HAS_DEV" ] && [ "$ui_height" -gt 0 ]; then
  UI_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '$2=="ui" {print $1; exit}')
  [ -n "$UI_INDEX" ] && tmux resize-pane -t "mume:cockpit.$UI_INDEX" -y "$ui_height"
fi

sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"
rm -f "$LOCK"
