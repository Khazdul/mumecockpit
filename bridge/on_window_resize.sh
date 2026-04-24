#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"
SENTINEL="$HOME/MUME/bridge/.collapsed_panes"

[ -f "$LOCK" ] && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

[ "$COLS" = "$window_cols" ] && exit 0

# Global width-priority constraint:
#   MAIN_MIN  = 30 — main/tt++ pane floor
#   RIGHT_MIN = 33 — right column floor when any right pane is active
MAIN_MIN=30
RIGHT_MIN=33

HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' \
    | grep -E '^(ui|dev|status)$' | head -1)

AVAILABLE_RIGHT=$(( COLS - MAIN_MIN - 1 ))

# --- Collapse / restore logic ---
if [ -n "$HAS_RIGHT" ] && [ "$AVAILABLE_RIGHT" -lt "$RIGHT_MIN" ]; then
    # Terminal too narrow: record open right panes and kill them.
    touch "$LOCK"
    tmux list-panes -t mume:cockpit -F '#{pane_title}' \
        | grep -E '^(ui|dev|status)$' > "$SENTINEL"
    while IFS= read -r pname; do
        PIDX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
            | awk -v n="$pname" '$2==n {print $1; exit}')
        [ -n "$PIDX" ] && tmux kill-pane -t "mume:cockpit.$PIDX"
    done < "$SENTINEL"
    # Re-pin input pane to 1 row
    INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
      -F '#{pane_index} #{pane_title}' \
      | awk '$2=="input" {print $1}')
    [ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1
    sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"
    rm -f "$LOCK"
    exit 0
elif [ -f "$SENTINEL" ] && [ "$AVAILABLE_RIGHT" -ge "$RIGHT_MIN" ]; then
    # Terminal widened back: restore previously-collapsed panes.
    touch "$LOCK"
    RESTORE_PANES=()
    while IFS= read -r pname; do
        RESTORE_PANES+=("$pname")
    done < "$SENTINEL"
    rm -f "$SENTINEL"   # delete before opening so open_pane.sh sentinel check passes
    for pname in "${RESTORE_PANES[@]}"; do
        bash "$HOME/MUME/bridge/open_pane.sh" "$pname"
    done
    rm -f "$LOCK"
    # Fall through to normal layout logic below.
    source "$LAYOUT_CONF"
    HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' \
        | grep -E '^(ui|dev|status)$' | head -1)
fi

# --- Normal layout logic ---
touch "$LOCK"

if [ -n "$HAS_RIGHT" ]; then
    if [ "$AVAILABLE_RIGHT" -ge "$RIGHT_MIN" ]; then
        EFFECTIVE_RIGHT=$(( ui_width > RIGHT_MIN ? ui_width : RIGHT_MIN ))
    else
        EFFECTIVE_RIGHT=$(( AVAILABLE_RIGHT > 0 ? AVAILABLE_RIGHT : 0 ))
    fi
    LEFT_WIDTH=$(( COLS - EFFECTIVE_RIGHT - 1 ))
else
    LEFT_WIDTH=$COLS
fi

if [ -n "$HAS_RIGHT" ]; then
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

# Re-pin input pane to 1 row
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_index} #{pane_title}' \
  | awk '$2=="input" {print $1}')
[ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1

bash "$HOME/MUME/bridge/apply_layout.sh"

sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"
rm -f "$LOCK"
