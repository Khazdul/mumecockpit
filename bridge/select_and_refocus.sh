#!/usr/bin/env bash
# Select word or line at click, copy to clipboard, refocus input pane.
# Usage: select_and_refocus.sh {word|line}
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
SEL="${1:-word}"
tmux copy-mode
tmux send-keys -X "select-${SEL}"
tmux send-keys -X copy-pipe-and-cancel
exec bash "$SCRIPT_DIR/focus_input.sh"
