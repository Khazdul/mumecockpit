#!/bin/bash
TYPE=$1
MUME="$HOME/MUME"
SENTINEL="$HOME/MUME/bridge/.collapsed_panes"

# Bail out silently if the right column is collapsed due to narrow terminal.
# Pane toggles during the narrow state are no-ops; they auto-restore on widen.
[ -f "$SENTINEL" ] && exit 0

# Where focus should return after opening a pane.
# Prefer input pane (user's command line); fall back to pane 0 (MUME).
resolve_focus_target() {
    local idx
    idx=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | awk '$2=="input"{print $1; exit}')
    echo "mume:cockpit.${idx:-0}"
}

# Exit if pane already exists
EXISTING=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep "^$TYPE$")
if [ -n "$EXISTING" ]; then
    exit 0
fi

LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || echo "ui_width=33" > "$LAYOUT_CONF"
grep -q "^ui_height=" "$LAYOUT_CONF"     || echo "ui_height=20"    >> "$LAYOUT_CONF"
grep -q "^comm_height=" "$LAYOUT_CONF"   || echo "comm_height=10"  >> "$LAYOUT_CONF"
grep -q "^status_height=" "$LAYOUT_CONF" || echo "status_height=12" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
LEFT=$(( COLS - ui_width - 1 ))

# Check if any right pane already exists
HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep -E '^(ui|comm|dev|status)$')

# Clamp status_height to minimum 12
STATUS_MIN_HEIGHT=12
STATUS_H_APPLY=$(( status_height > STATUS_MIN_HEIGHT ? status_height : STATUS_MIN_HEIGHT ))

# Geometric helpers: pick right-column panes by vertical position.
_right_pane_at_top() {
    tmux list-panes -t mume:cockpit \
        -F '#{pane_top} #{pane_index} #{pane_title}' \
      | awk '$3=="ui" || $3=="comm" || $3=="dev" || $3=="status"' \
      | sort -n | head -1 | awk '{print $2}'
}
_right_pane_at_bottom() {
    tmux list-panes -t mume:cockpit \
        -F '#{pane_top} #{pane_index} #{pane_title}' \
      | awk '$3=="ui" || $3=="comm" || $3=="dev" || $3=="status"' \
      | sort -rn | head -1 | awk '{print $2}'
}

# Pane commands
STATUS_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/status_pane.py; printf \"\\n[pane kept alive — use cp -c to close]\\n\"; sleep 0.2; done'"
COMM_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/comm_pane.py; printf \"\\n[pane kept alive — use cp -m to close]\\n\"; sleep 0.2; done'"

if [ -n "$HAS_RIGHT" ]; then
    # Right column exists — split vertically inside it using geometric position.
    # Column ordering (top to bottom): ui → comm → status → dev

    case $TYPE in
        ui)
            # ui is always at the top of the right column.
            TOP_IDX=$(_right_pane_at_top)
            NEW_INDEX=$(tmux split-window -v -b -t mume:cockpit.$TOP_IDX -P -F '#{pane_index}' \
                "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $MUME/logs/ui.log; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;

        comm)
            # comm goes below ui, above status.
            UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="ui" {print $1; exit}')
            STATUS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="status" {print $1; exit}')

            if [ -n "$UI_INDEX" ]; then
                # Split below ui
                NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$UI_INDEX -P -F '#{pane_index}' "$COMM_CMD")
            elif [ -n "$STATUS_INDEX" ]; then
                # No ui — split above status
                NEW_INDEX=$(tmux split-window -v -b -t mume:cockpit.$STATUS_INDEX -P -F '#{pane_index}' "$COMM_CMD")
            else
                # Only dev — split above it
                TOP_IDX=$(_right_pane_at_top)
                NEW_INDEX=$(tmux split-window -v -b -t mume:cockpit.$TOP_IDX -P -F '#{pane_index}' "$COMM_CMD")
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "comm"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;

        status)
            # status goes below comm, below ui, above dev.
            COMM_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="comm" {print $1; exit}')
            UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="ui" {print $1; exit}')
            DEV_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="dev" {print $1; exit}')

            if [ -n "$COMM_INDEX" ]; then
                NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$COMM_INDEX -P -F '#{pane_index}' "$STATUS_CMD")
            elif [ -n "$UI_INDEX" ]; then
                NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$UI_INDEX -P -F '#{pane_index}' "$STATUS_CMD")
            elif [ -n "$DEV_INDEX" ]; then
                NEW_INDEX=$(tmux split-window -v -b -t mume:cockpit.$DEV_INDEX -P -F '#{pane_index}' "$STATUS_CMD")
            else
                BOT_IDX=$(_right_pane_at_bottom)
                NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$BOT_IDX -P -F '#{pane_index}' "$STATUS_CMD")
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "status"
            tmux resize-pane -t mume:cockpit.$NEW_INDEX -y "$STATUS_H_APPLY"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;

        dev)
            # dev is always at the bottom.
            BOT_IDX=$(_right_pane_at_bottom)
            NEW_INDEX=$(tmux split-window -v -t mume:cockpit.$BOT_IDX -P -F '#{pane_index}' \
                "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;

        input)
            NEW_INDEX=$(tmux split-window -v -l 1 -t mume:cockpit.0 -P -F '#{pane_index}' \
                "python3 $MUME/bridge/input_pane.py")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "input"
            ;;
    esac
else
    # No right column yet — create horizontal split at window level.
    # -f is required: without it, if the input pane already exists, tmux inserts
    # the new right pane as main's sibling inside the left-column subtree, causing
    # input to span the full window width instead of staying below main only.
    case $TYPE in
        ui)
            NEW_INDEX=$(tmux split-window -h -f -t mume:cockpit.0 -P -F '#{pane_index}' \
                "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $MUME/logs/ui.log; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;
        comm)
            NEW_INDEX=$(tmux split-window -h -f -t mume:cockpit.0 -P -F '#{pane_index}' "$COMM_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "comm"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;
        dev)
            NEW_INDEX=$(tmux split-window -h -f -t mume:cockpit.0 -P -F '#{pane_index}' \
                "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;
        status)
            NEW_INDEX=$(tmux split-window -h -f -t mume:cockpit.0 -P -F '#{pane_index}' "$STATUS_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "status"
            tmux resize-pane -t mume:cockpit.$NEW_INDEX -y "$STATUS_H_APPLY"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/apply_layout.sh"
            ;;
        input)
            NEW_INDEX=$(tmux split-window -v -l 1 -t mume:cockpit.0 -P -F '#{pane_index}' \
                "python3 $MUME/bridge/input_pane.py")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "input"
            ;;
    esac
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT"
fi
