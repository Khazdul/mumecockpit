#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"
LOG="$HOME/MUME/logs/debug.log"

echo "[window_resize] fired at $(date '+%H:%M:%S.%3N')" >> "$LOG"
[ -f "$LOCK" ] && echo "[window_resize] lock exists — exiting" >> "$LOG" && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
echo "[window_resize] COLS=$COLS stored_window_cols=$window_cols" >> "$LOG"

[ "$COLS" = "$window_cols" ] && echo "[window_resize] width unchanged — exiting" >> "$LOG" && exit 0

LEFT_WIDTH=$(( COLS - ui_width - 1 ))
echo "[window_resize] resizing — LEFT_WIDTH=$LEFT_WIDTH" >> "$LOG"

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

sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"
rm -f "$LOCK"
echo "[window_resize] done" >> "$LOG"
