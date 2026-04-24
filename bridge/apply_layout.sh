#!/bin/bash
# bridge/apply_layout.sh — apply layout.conf heights to tmux.
# Called after any right-column operation. Idempotent. The only
# authoritative height is status_height; ui and dev share the rest.

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || exit 0
source "$LAYOUT_CONF"

# Status pane — authoritative height
STATUS_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' 2>/dev/null \
    | awk '$2=="status" {print $1; exit}')
if [ -n "$STATUS_INDEX" ]; then
    tmux resize-pane -t "mume:cockpit.$STATUS_INDEX" -y "${status_height:-12}"
fi

# Input pane — always 1 row
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' 2>/dev/null \
    | awk '$2=="input" {print $1; exit}')
[ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1

exit 0
