#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

# Skip if this resize was triggered programmatically
[ -f "$LOCK" ] && exit 0

# Only respond to ui or dev pane being dragged
RESIZED_TITLE=$(tmux display-message -p '#{pane_title}')
[[ "$RESIZED_TITLE" != "ui" && "$RESIZED_TITLE" != "dev" ]] && exit 0

COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
RIGHT_WIDTH=$(tmux display-message -p '#{pane_width}')

NEW_RATIO=$(( RIGHT_WIDTH * 100 / COLS ))

# Update persisted ratio
sed -i "s/^ui_ratio=.*/ui_ratio=$NEW_RATIO/" "$LAYOUT_CONF"
