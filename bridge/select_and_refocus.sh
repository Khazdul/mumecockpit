#!/usr/bin/env bash
# Finalize a mouse selection and refocus the input pane.
# Usage: select_and_refocus.sh {drag|word|line}
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
MODE="${1:-drag}"
case "$MODE" in
    drag)
        tmux send-keys -X copy-pipe-and-cancel
        ;;
    word|line)
        tmux copy-mode \; \
             send-keys -X "select-${MODE}" \; \
             send-keys -X copy-pipe-and-cancel
        ;;
    *)
        echo "select_and_refocus.sh: unknown mode: $MODE" >&2
        exit 1
        ;;
esac
exec bash "$SCRIPT_DIR/focus_input.sh"
