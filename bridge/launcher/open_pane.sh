#!/usr/bin/env bash
# bridge/launcher/open_pane.sh — open a single named pane.
# Usage: open_pane.sh <type> [--batch]
#   --batch  Suppress the post-split apply_desired_heights call.
#            Used by cold-start (build_initial_layout.sh) and narrow-
#            restore (on_window_resize.sh) loops, which apply once at
#            the end. Interactive toggles omit --batch so each open
#            settles to algorithmic ALLOC.

MUME="$HOME/MUME"
SENTINEL="$HOME/MUME/bridge/runtime/.collapsed_panes"

TYPE=""
BATCH_MODE=0
for arg in "$@"; do
    case "$arg" in
        --batch) BATCH_MODE=1 ;;
        *) [ -z "$TYPE" ] && TYPE="$arg" ;;
    esac
done

# Bail out silently if the right column is collapsed due to narrow terminal.
# Pane toggles during the narrow state are no-ops; they auto-restore on widen.
[ -f "$SENTINEL" ] && exit 0

# Emit an amber WARN line to the UI pane log. Mirrors the format of
# lua/brain/ui.lua's ui_warn(); no shared shell helper exists yet.
_warn_pane_too_short() {
    local type="$1"
    printf '\033[38;2;255;179;0m⚠ WARN:\033[0m \033[1;97mCannot open %s pane — terminal too short. Close another pane or enlarge the terminal.\033[0m\n' \
        "$type" >> "$HOME/MUME/logs/ui.log"
}

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

# Budget gate — refuse to open if the right column is already full.
# input and unrelated TYPE values are not gated.
source "$HOME/MUME/bridge/layout/right_column_budget.sh"

# Re-check whether TARGET_IDX has enough body to split, redistributing
# the current right column to fair share first if needed. In the typical
# compressed-by-drag case equalize is enough; the gate then passes.
_can_split_after_equalize() {
    local target="$1"
    rc_target_can_be_split "$target" && return 0
    bash "$HOME/MUME/bridge/layout/equalize_right_column.sh"
    rc_target_can_be_split "$target"
}

case "$TYPE" in
    status|buffs|group|comm|ui|dev)
        if ! rc_fits_one_more; then
            echo "[layout] cannot open $TYPE — terminal too short; close another pane first." \
                >> "$HOME/MUME/logs/debug.log"
            _warn_pane_too_short "$TYPE"
            exit 1
        fi
        ;;
esac

LAYOUT_CONF="$HOME/MUME/bridge/runtime/layout.conf"
[ -f "$LAYOUT_CONF" ] || echo "ui_width=33" > "$LAYOUT_CONF"
source "$LAYOUT_CONF"
COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
LEFT=$(( COLS - ui_width - 1 ))

# Check if any right pane already exists
HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep -E '^(ui|comm|dev|status|buffs|group)$')

# Geometric helpers: pick right-column panes by vertical position.
_right_pane_at_top() {
    tmux list-panes -t mume:cockpit \
        -F '#{pane_top} #{pane_index} #{pane_title}' \
      | awk '$3=="ui" || $3=="comm" || $3=="dev" || $3=="status" || $3=="buffs" || $3=="group"' \
      | sort -n | head -1 | awk '{print $2}'
}
_right_pane_at_bottom() {
    tmux list-panes -t mume:cockpit \
        -F '#{pane_top} #{pane_index} #{pane_title}' \
      | awk '$3=="ui" || $3=="comm" || $3=="dev" || $3=="status" || $3=="buffs" || $3=="group"' \
      | sort -rn | head -1 | awk '{print $2}'
}

# Pane background (per-pane tmux style; cells the renderer doesn't paint
# fall through to this bg). Applied to status/buffs/group/comm/ui/dev only —
# game and input panes keep terminal default.
PANE_BG="bg=#0E141C"

# Pane commands
STATUS_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/panes/status_pane.py; printf \"\\n[pane kept alive — use cp -c to close]\\n\"; sleep 0.2; done'"
BUFFS_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/panes/buffs_pane.py; printf \"\\n[pane kept alive — use cp -b to close]\\n\"; sleep 0.2; done'"
COMM_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/panes/comm_pane.py; printf \"\\n[pane kept alive — use cp -m to close]\\n\"; sleep 0.2; done'"
GROUP_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/panes/group_pane.py; printf \"\\n[pane kept alive — use cp -g to close]\\n\"; sleep 0.2; done'"
UI_CMD="bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $MUME/bridge/panes/ui_pane.py; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'"

if [ -n "$HAS_RIGHT" ]; then
    # Right column exists — split vertically inside it using geometric position.
    # Column ordering (top to bottom): status → buffs → group → comm → ui → dev

    case $TYPE in
        status)
            # status is always at the top of the right column.
            TARGET_IDX=$(_right_pane_at_top)
            SPLIT_DIR="-b"
            if ! _can_split_after_equalize "$TARGET_IDX"; then
                echo "[layout] cannot open $TYPE — terminal too short even after equalize; close another pane or enlarge the terminal." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            NEW_INDEX=$(tmux split-window -v $SPLIT_DIR -t mume:cockpit.$TARGET_IDX -P -F '#{pane_index}' "$STATUS_CMD")
            if [ -z "$NEW_INDEX" ]; then
                echo "[layout] split-window failed for $TYPE (target idx=$TARGET_IDX); aborting open." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "status"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;

        buffs)
            # buffs goes below status, above group/comm.
            STATUS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="status" {print $1; exit}')
            GROUP_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="group" {print $1; exit}')
            COMM_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="comm" {print $1; exit}')
            UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="ui" {print $1; exit}')
            DEV_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="dev" {print $1; exit}')

            if [ -n "$STATUS_INDEX" ]; then
                # Split below status (predecessor)
                TARGET_IDX=$STATUS_INDEX; SPLIT_DIR=""
            elif [ -n "$GROUP_INDEX" ]; then
                # No status — split above group (successor)
                TARGET_IDX=$GROUP_INDEX; SPLIT_DIR="-b"
            elif [ -n "$COMM_INDEX" ]; then
                # No status or group — split above comm (successor)
                TARGET_IDX=$COMM_INDEX; SPLIT_DIR="-b"
            elif [ -n "$UI_INDEX" ]; then
                # No status, group, or comm — split above ui (successor)
                TARGET_IDX=$UI_INDEX; SPLIT_DIR="-b"
            elif [ -n "$DEV_INDEX" ]; then
                # No status, group, comm, or ui — split above dev (successor)
                TARGET_IDX=$DEV_INDEX; SPLIT_DIR="-b"
            else
                # Only empty column — go at top
                TARGET_IDX=$(_right_pane_at_top); SPLIT_DIR="-b"
            fi
            if ! _can_split_after_equalize "$TARGET_IDX"; then
                echo "[layout] cannot open $TYPE — terminal too short even after equalize; close another pane or enlarge the terminal." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            NEW_INDEX=$(tmux split-window -v $SPLIT_DIR -t mume:cockpit.$TARGET_IDX -P -F '#{pane_index}' "$BUFFS_CMD")
            if [ -z "$NEW_INDEX" ]; then
                echo "[layout] split-window failed for $TYPE (target idx=$TARGET_IDX); aborting open." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "buffs"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;

        group)
            # group goes below buffs (or status if buffs absent), above comm.
            BUFFS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="buffs" {print $1; exit}')
            STATUS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="status" {print $1; exit}')
            COMM_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="comm" {print $1; exit}')
            UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="ui" {print $1; exit}')
            DEV_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="dev" {print $1; exit}')

            if [ -n "$BUFFS_INDEX" ]; then
                # Split below buffs
                TARGET_IDX=$BUFFS_INDEX; SPLIT_DIR=""
            elif [ -n "$STATUS_INDEX" ]; then
                # No buffs — split below status
                TARGET_IDX=$STATUS_INDEX; SPLIT_DIR=""
            elif [ -n "$COMM_INDEX" ]; then
                # No status or buffs — split above comm
                TARGET_IDX=$COMM_INDEX; SPLIT_DIR="-b"
            elif [ -n "$UI_INDEX" ]; then
                # Split above ui
                TARGET_IDX=$UI_INDEX; SPLIT_DIR="-b"
            elif [ -n "$DEV_INDEX" ]; then
                # Split above dev
                TARGET_IDX=$DEV_INDEX; SPLIT_DIR="-b"
            else
                # Fallback — go at top
                TARGET_IDX=$(_right_pane_at_top); SPLIT_DIR="-b"
            fi
            if ! _can_split_after_equalize "$TARGET_IDX"; then
                echo "[layout] cannot open $TYPE — terminal too short even after equalize; close another pane or enlarge the terminal." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            NEW_INDEX=$(tmux split-window -v $SPLIT_DIR -t mume:cockpit.$TARGET_IDX -P -F '#{pane_index}' "$GROUP_CMD")
            if [ -z "$NEW_INDEX" ]; then
                echo "[layout] split-window failed for $TYPE (target idx=$TARGET_IDX); aborting open." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "group"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;

        comm)
            # comm goes below group (or buffs, or status if those are absent), above ui.
            GROUP_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="group" {print $1; exit}')
            BUFFS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="buffs" {print $1; exit}')
            STATUS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="status" {print $1; exit}')
            UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="ui" {print $1; exit}')
            DEV_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="dev" {print $1; exit}')

            if [ -n "$GROUP_INDEX" ]; then
                # Split below group (predecessor)
                TARGET_IDX=$GROUP_INDEX; SPLIT_DIR=""
            elif [ -n "$BUFFS_INDEX" ]; then
                # Split below buffs (predecessor)
                TARGET_IDX=$BUFFS_INDEX; SPLIT_DIR=""
            elif [ -n "$STATUS_INDEX" ]; then
                # Split below status (predecessor)
                TARGET_IDX=$STATUS_INDEX; SPLIT_DIR=""
            elif [ -n "$UI_INDEX" ]; then
                # No predecessors — split above ui (successor)
                TARGET_IDX=$UI_INDEX; SPLIT_DIR="-b"
            elif [ -n "$DEV_INDEX" ]; then
                # No predecessors or ui — split above dev (successor)
                TARGET_IDX=$DEV_INDEX; SPLIT_DIR="-b"
            else
                # Empty column — go at top
                TARGET_IDX=$(_right_pane_at_top); SPLIT_DIR="-b"
            fi
            if ! _can_split_after_equalize "$TARGET_IDX"; then
                echo "[layout] cannot open $TYPE — terminal too short even after equalize; close another pane or enlarge the terminal." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            NEW_INDEX=$(tmux split-window -v $SPLIT_DIR -t mume:cockpit.$TARGET_IDX -P -F '#{pane_index}' "$COMM_CMD")
            if [ -z "$NEW_INDEX" ]; then
                echo "[layout] split-window failed for $TYPE (target idx=$TARGET_IDX); aborting open." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "comm"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;

        ui)
            # ui goes below comm, above dev.
            COMM_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="comm" {print $1; exit}')
            GROUP_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="group" {print $1; exit}')
            BUFFS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="buffs" {print $1; exit}')
            STATUS_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="status" {print $1; exit}')
            DEV_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
              | awk '$2=="dev" {print $1; exit}')

            if [ -n "$COMM_INDEX" ]; then
                # Split below comm (predecessor)
                TARGET_IDX=$COMM_INDEX; SPLIT_DIR=""
            elif [ -n "$GROUP_INDEX" ]; then
                # Split below group (predecessor)
                TARGET_IDX=$GROUP_INDEX; SPLIT_DIR=""
            elif [ -n "$BUFFS_INDEX" ]; then
                # Split below buffs (predecessor)
                TARGET_IDX=$BUFFS_INDEX; SPLIT_DIR=""
            elif [ -n "$STATUS_INDEX" ]; then
                # Split below status (predecessor)
                TARGET_IDX=$STATUS_INDEX; SPLIT_DIR=""
            elif [ -n "$DEV_INDEX" ]; then
                # No predecessors — split above dev (successor)
                TARGET_IDX=$DEV_INDEX; SPLIT_DIR="-b"
            else
                # Only unreachable edge case — go at bottom
                TARGET_IDX=$(_right_pane_at_bottom); SPLIT_DIR=""
            fi
            if ! _can_split_after_equalize "$TARGET_IDX"; then
                echo "[layout] cannot open $TYPE — terminal too short even after equalize; close another pane or enlarge the terminal." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            NEW_INDEX=$(tmux split-window -v $SPLIT_DIR -t mume:cockpit.$TARGET_IDX -P -F '#{pane_index}' "$UI_CMD")
            if [ -z "$NEW_INDEX" ]; then
                echo "[layout] split-window failed for $TYPE (target idx=$TARGET_IDX); aborting open." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;

        dev)
            # dev is always at the bottom.
            TARGET_IDX=$(_right_pane_at_bottom)
            SPLIT_DIR=""
            if ! _can_split_after_equalize "$TARGET_IDX"; then
                echo "[layout] cannot open $TYPE — terminal too short even after equalize; close another pane or enlarge the terminal." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            NEW_INDEX=$(tmux split-window -v $SPLIT_DIR -t mume:cockpit.$TARGET_IDX -P -F '#{pane_index}' \
                "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'")
            if [ -z "$NEW_INDEX" ]; then
                echo "[layout] split-window failed for $TYPE (target idx=$TARGET_IDX); aborting open." \
                    >> "$HOME/MUME/logs/debug.log"
                _warn_pane_too_short "$TYPE"
                exit 1
            fi
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;

        input)
            NEW_INDEX=$(tmux split-window -v -f -l 1 -t mume:cockpit.0 -P -F '#{pane_index}' \
                "python3 $MUME/bridge/panes/input_pane.py")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "input"
            ;;
    esac
else
    # No right column yet — split horizontally within the top container (main's
    # subtree). Do NOT use -f: with input now a window-level full-width split,
    # -f would span across the input row too, breaking the layout. See ADR 0029.
    case $TYPE in
        status)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' "$STATUS_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "status"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;
        buffs)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' "$BUFFS_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "buffs"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;
        group)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' "$GROUP_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "group"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;
        comm)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' "$COMM_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "comm"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;
        ui)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' "$UI_CMD")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;
        dev)
            NEW_INDEX=$(tmux split-window -h -t mume:cockpit.0 -P -F '#{pane_index}' \
                "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            tmux select-pane -t mume:cockpit.$NEW_INDEX -P "$PANE_BG"
            tmux select-pane -t "$(resolve_focus_target)"
            bash "$MUME/bridge/layout/apply_layout.sh"
            ;;
        input)
            NEW_INDEX=$(tmux split-window -v -f -l 1 -t mume:cockpit.0 -P -F '#{pane_index}' \
                "python3 $MUME/bridge/panes/input_pane.py")
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "input"
            ;;
    esac
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT"
fi

# Settle right-column panes to algorithmic ALLOC after a successful
# split. Suppressed in batch mode — callers (cold-start Phase 3,
# narrow-restore) apply once at the end of their loop.
if [ "$BATCH_MODE" -ne 1 ]; then
    bash "$HOME/MUME/bridge/layout/apply_desired_heights.sh"
fi
