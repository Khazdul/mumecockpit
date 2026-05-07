#!/usr/bin/env bash
# Resolve the input pane's current index and focus it.
# Invoked from:
#   - MouseUp1Pane and MouseDragEnd1Pane bindings (bridge/panes/input_pane.py)
#   - pane-mode-changed hook (bridge/launcher/tmux_start.sh) on copy-mode exit
# Always exits 0; tmux's run-shell surfaces non-zero exits as warnings
# in the status line, which we never want.

if [ "${1}" = "--sweep" ]; then
    # Cancel copy-mode on every non-input pane currently in it.
    # copy-pipe-and-cancel: with a selection copies via OSC 52 and exits;
    # without a selection just exits. Safe to call either way.
    while IFS=' ' read -r idx title in_mode; do
        if [ "$in_mode" = "1" ] && [ "$title" != "input" ]; then
            tmux send-keys -t "mume:cockpit.$idx" -X copy-pipe-and-cancel
        fi
    done < <(tmux list-panes -t mume:cockpit \
        -F '#{pane_index} #{pane_title} #{pane_in_mode}')
fi

IDX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
    | awk '$2=="input"{print $1; exit}')
[ -n "$IDX" ] && tmux select-pane -t "mume:cockpit.$IDX"
exit 0
