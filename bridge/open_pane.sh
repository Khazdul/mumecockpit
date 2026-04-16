#!/bin/bash
TYPE=$1
MUME="$HOME/MUME"

# Exit if pane already exists
EXISTING=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep "^$TYPE$")
if [ -n "$EXISTING" ]; then
    exit 0
fi

COLS=$(tmux display-message -p '#{window_width}')
RIGHT_WIDTH=33
LEFT=$(( COLS - RIGHT_WIDTH - 1 ))

# Check if any right pane already exists
HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep -E '^(ui|dev)$')

if [ -n "$HAS_RIGHT" ]; then
    # Right column exists — split vertically inside it
    RIGHT_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | grep -E ' (ui|dev)$' | cut -d' ' -f1 | head -1)

    case $TYPE in
        ui)
            # ui always on top — split then swap
            tmux split-window -v -t mume:cockpit.$RIGHT_INDEX \
                "tail -f $MUME/logs/ui.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux swap-pane -s mume:cockpit.$NEW_INDEX -t mume:cockpit.$RIGHT_INDEX
            ;;
        dev)
            # dev always on bottom — split normally
            tmux split-window -v -t mume:cockpit.$RIGHT_INDEX \
                "tail -f $MUME/logs/debug.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            ;;
    esac
else
    # No right column yet — create horizontal split from pane 0
    case $TYPE in
        ui)
            tmux split-window -h -t mume:cockpit.0 \
                "tail -f $MUME/logs/ui.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            ;;
        dev)
            tmux split-window -h -t mume:cockpit.0 \
                "tail -f $MUME/logs/debug.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            ;;
    esac
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT"
fi

tmux select-pane -t mume:cockpit.0