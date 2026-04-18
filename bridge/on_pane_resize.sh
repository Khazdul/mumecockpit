#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"
LOG="$HOME/MUME/logs/debug.log"

echo "[pane_resize] fired at $(date '+%H:%M:%S')" >> "$LOG"

[ -f "$LOCK" ] && echo "[pane_resize] lock exists — exiting" >> "$LOG" && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

echo "[pane_resize] COLS=$COLS stored_window_cols=$window_cols stored_ui_width=$ui_width" >> "$LOG"

[ "$COLS" != "$window_cols" ] && echo "[pane_resize] window width changed — exiting" >> "$LOG" && exit 0

HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep -E '^(ui|dev)$')
[ -z "$HAS_RIGHT" ] && echo "[pane_resize] no right pane — exiting" >> "$LOG" && exit 0

PANE_LIST=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_width}')
echo "[pane_resize] pane list: $PANE_LIST" >> "$LOG"

MAIN_WIDTH=$(echo "$PANE_LIST" | awk '$1=="MUME" {print $2; exit}')
echo "[pane_resize] MAIN_WIDTH=$MAIN_WIDTH" >> "$LOG"

[ -z "$MAIN_WIDTH" ] && echo "[pane_resize] MUME pane not found — exiting" >> "$LOG" && exit 0

NEW_WIDTH=$(( COLS - MAIN_WIDTH - 1 ))
echo "[pane_resize] saving NEW_WIDTH=$NEW_WIDTH" >> "$LOG"

sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"
