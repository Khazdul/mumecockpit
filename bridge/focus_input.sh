#!/bin/bash
# Resolve the input pane's current index and focus it.
# Used by the MouseUp1Pane binding registered from input_pane.py.
IDX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
    | awk '$2=="input"{print $1; exit}')
[ -n "$IDX" ] && tmux select-pane -t "mume:cockpit.$IDX"
