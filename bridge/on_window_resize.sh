#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

[ "$COLS" = "$window_cols" ] && exit 0

# Global width-priority constraint:
#   MAIN_MIN  = 30 — main/tt++ pane floor
#   RIGHT_MIN = 33 — right column floor when any right pane is active
MAIN_MIN=30
RIGHT_MIN=33

HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' \
    | grep -E '^(ui|dev|status)$' | head -1)

if [ -n "$HAS_RIGHT" ]; then
    AVAILABLE_RIGHT=$(( COLS - MAIN_MIN - 1 ))
    if [ "$AVAILABLE_RIGHT" -ge "$RIGHT_MIN" ]; then
        EFFECTIVE_RIGHT=$(( ui_width > RIGHT_MIN ? ui_width : RIGHT_MIN ))
    else
        EFFECTIVE_RIGHT=$(( AVAILABLE_RIGHT > 0 ? AVAILABLE_RIGHT : 0 ))
    fi
    LEFT_WIDTH=$(( COLS - EFFECTIVE_RIGHT - 1 ))
else
    LEFT_WIDTH=$COLS
fi

touch "$LOCK"

if [ -n "$HAS_RIGHT" ]; then
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

# Re-pin input pane to 1 row
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="input" {print $1}')
[ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1

# Enforce ui/dev height ratio if both panes are open
HAS_UI=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^ui$')
HAS_DEV=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^dev$')
if [ -n "$HAS_UI" ] && [ -n "$HAS_DEV" ]; then
    UI_H=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
        | awk '$1=="ui" {print $2; exit}')
    DEV_H=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
        | awk '$1=="dev" {print $2; exit}')
    TOTAL=$(( UI_H + DEV_H + 1 ))
    NEW_UI_H=$(( TOTAL * ui_height_ratio / 100 ))
    UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | awk '$2=="ui" {print $1; exit}')
    [ -n "$UI_INDEX" ] && tmux resize-pane -t "mume:cockpit.$UI_INDEX" -y "$NEW_UI_H"
fi

# Restore status pane to its configured height when present
HAS_STATUS=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^status$')
if [ -n "$HAS_STATUS" ]; then
    STATUS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | awk '$2=="status" {print $1; exit}')
    [ -n "$STATUS_INDEX" ] && tmux resize-pane -t "mume:cockpit.$STATUS_INDEX" -y "${status_height:-14}"
fi

sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"
rm -f "$LOCK"
