#!/usr/bin/env bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"
SENTINEL="$HOME/MUME/bridge/.collapsed_panes"

[ -f "$LOCK" ] && exit 0

source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')

if [ "$COLS" = "$window_cols" ]; then
    # Height-only resize: re-pin input and reapply layout, skip column logic.
    INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
      -F '#{pane_index} #{pane_title}' \
      | awk '$2=="input" {print $1}')
    [ -n "$INPUT_INDEX" ] && tmux resize-pane -t "mume:cockpit.$INPUT_INDEX" -y 1
    bash "$HOME/MUME/bridge/layout/apply_layout.sh"
    exit 0
fi

# Global width-priority constraint:
#   MAIN_MIN    = 30 — main/tt++ pane floor (always)
#   RIGHT_FLOOR = ui_width (sole authority — see ADR 0038)
MAIN_MIN=30
RIGHT_FLOOR=$ui_width

HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' \
    | grep -E '^(ui|comm|dev|status|buffs)$' | head -1)

AVAILABLE_RIGHT=$(( COLS - MAIN_MIN - 1 ))

# --- Collapse / restore logic ---
if [ -n "$HAS_RIGHT" ] && [ "$AVAILABLE_RIGHT" -lt "$RIGHT_FLOOR" ]; then
    # Terminal too narrow: record open right panes and kill them.
    touch "$LOCK"
    tmux list-panes -t mume:cockpit -F '#{pane_title}' \
        | grep -E '^(ui|comm|dev|status|buffs)$' > "$SENTINEL"
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
elif [ -f "$SENTINEL" ]; then
    # Panes are collapsed — restore floor is always ui_width (ADR 0038).
    RESTORE_FLOOR=$ui_width
    if [ "$AVAILABLE_RIGHT" -ge "$RESTORE_FLOOR" ]; then
        # Terminal widened back: restore previously-collapsed panes.
        touch "$LOCK"
        RESTORE_PANES=()
        while IFS= read -r pname; do
            RESTORE_PANES+=("$pname")
        done < "$SENTINEL"
        rm -f "$SENTINEL"   # delete before opening so open_pane.sh sentinel check passes
        for pname in "${RESTORE_PANES[@]}"; do
            bash "$HOME/MUME/bridge/launcher/open_pane.sh" "$pname"
        done
        rm -f "$LOCK"
        # Fall through to normal layout logic below.
        source "$LAYOUT_CONF"
        RIGHT_FLOOR=$ui_width
        HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' \
            | grep -E '^(ui|comm|dev|status|buffs)$' | head -1)
    fi
fi

# --- Normal layout logic ---
touch "$LOCK"

if [ -n "$HAS_RIGHT" ]; then
    if [ "$AVAILABLE_RIGHT" -ge "$RIGHT_FLOOR" ]; then
        EFFECTIVE_RIGHT=$(( ui_width > RIGHT_FLOOR ? ui_width : RIGHT_FLOOR ))
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

bash "$HOME/MUME/bridge/layout/apply_layout.sh"

sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"
rm -f "$LOCK"
