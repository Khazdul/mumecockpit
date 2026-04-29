#!/usr/bin/env bash
# Resolve the input pane's current index and focus it.
# Invoked from:
#   - MouseUp1Pane and MouseDragEnd1Pane bindings (bridge/input_pane.py)
#   - pane-mode-changed hook (bridge/tmux_start.sh) on copy-mode exit
# Always exits 0; tmux's run-shell surfaces non-zero exits as warnings
# in the status line, which we never want.
IDX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
    | awk '$2=="input"{print $1; exit}')
[ -n "$IDX" ] && tmux select-pane -t "mume:cockpit.$IDX"
exit 0
