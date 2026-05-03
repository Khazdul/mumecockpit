#!/usr/bin/env bash
# bridge/apply_layout.sh — pins the input row to 1 row.
# Right-column pane heights are tmux-managed (freely resizable).
# Called after any right-column operation. Idempotent.

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || exit 0

_pane_index() {
    tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' 2>/dev/null \
        | awk -v t="$1" '$2==t{print $1; exit}'
}

INPUT_IDX=$(_pane_index input)

# Input pin — always 1 row
[ -n "$INPUT_IDX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_IDX" -y 1

exit 0
