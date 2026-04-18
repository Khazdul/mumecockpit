#!/bin/bash
TYPE=$1
MUME="$HOME/MUME"

# Exit if pane already exists
EXISTING=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep "^$TYPE$")
if [ -n "$EXISTING" ]; then
    exit 0
fi

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || echo "ui_width=33" > "$LAYOUT_CONF"
source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
LEFT=$(( COLS - ui_width - 1 ))

# Check if any right pane already exists
HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep -E '^(ui|dev)$')

if [ -n "$HAS_RIGHT" ]; then
    # Right column exists — split vertically inside it
    RIGHT_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | grep -E ' (ui|dev)$' | cut -d' ' -f1 | head -1)

    case $TYPE in
        ui)
            # ui always on top — split then swap
            NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$RIGHT_INDEX -P -F '#{pane_index}' \
                "tail -f $MUME/logs/ui.log")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux swap-pane -s mume:cockpit.$NEW_INDEX -t mume:cockpit.$RIGHT_INDEX
            tmux select-pane -t mume:cockpit.0
            ;;
        dev)
            # dev always on bottom — split normally
            NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$RIGHT_INDEX -P -F '#{pane_index}' \
                "tail -f $MUME/logs/debug.log")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            tmux select-pane -t mume:cockpit.0
            # Restore saved ui_height if it fits
            source "$LAYOUT_CONF"
            if [ "${ui_height:-0}" -gt 0 ]; then
              UI_INDEX=$(tmux list-panes -t mume:cockpit \
                -F '#{pane_index} #{pane_title}' \
                | awk '$2=="ui" {print $1; exit}')
              [ -n "$UI_INDEX" ] && tmux resize-pane -t "mume:cockpit.$UI_INDEX" -y "$ui_height"
            fi
            ;;
        input)
            NEW_INDEX=$(tmux split-window -v -l 1 -t mume:cockpit.0 -P -F '#{pane_index}' \
                "python3 $MUME/bridge/input_pane.py")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "input"
            ;;
    esac
else
    # No right column yet — create horizontal split from pane 0
    case $TYPE in
        ui)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' \
                "tail -f $MUME/logs/ui.log")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux select-pane -t mume:cockpit.0
            ;;
        dev)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' \
                "tail -f $MUME/logs/debug.log")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            tmux select-pane -t mume:cockpit.0
            # Restore saved ui_height if it fits
            source "$LAYOUT_CONF"
            if [ "${ui_height:-0}" -gt 0 ]; then
              UI_INDEX=$(tmux list-panes -t mume:cockpit \
                -F '#{pane_index} #{pane_title}' \
                | awk '$2=="ui" {print $1; exit}')
              [ -n "$UI_INDEX" ] && tmux resize-pane -t "mume:cockpit.$UI_INDEX" -y "$ui_height"
            fi
            ;;
        input)
            NEW_INDEX=$(tmux split-window -v -l 1 -t mume:cockpit.0 -P -F '#{pane_index}' \
                "python3 $MUME/bridge/input_pane.py")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "input"
            ;;
    esac
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT"
fi