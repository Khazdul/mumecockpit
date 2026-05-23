#!/usr/bin/env bash
# bridge/launcher/build_initial_layout.sh — builds the cockpit pane layout post-attach.
# Fired by a one-shot client-attached hook registered in tmux_start.sh.
# Reads true terminal dimensions from tmux (authoritative post-attach) rather than
# stty size (unreliable pre-attach on terminals that haven't synced PTY size).

cd "$HOME/MUME"

# Idempotency guard: re-attach must not rebuild a live layout.
PANE_COUNT=$(tmux list-panes -t mume:cockpit 2>/dev/null | wc -l)
[ "$PANE_COUNT" -gt 1 ] && exit 0

source bridge/runtime/startup.conf 2>/dev/null || true

SHOW_UI="${show_ui:-1}"
SHOW_DEV="${show_dev:-0}"
SHOW_STATUS="${show_status:-0}"
SHOW_BUFFS="${show_buffs:-0}"
SHOW_GROUP="${show_group:-1}"
SHOW_COMM="${show_comm:-0}"
SHOW_DIVIDERS="${show_pane_dividers:-1}"

LAYOUT_CONF="bridge/runtime/layout.conf"
# detect_terminal_bg.sh may have created layout.conf with only terminal_bg=
# already populated; seed the remaining keys without clobbering existing ones.
[ -f "$LAYOUT_CONF" ] || : > "$LAYOUT_CONF"
grep -q "^ui_width="    "$LAYOUT_CONF" || echo "ui_width=33"    >> "$LAYOUT_CONF"
grep -q "^window_cols=" "$LAYOUT_CONF" || echo "window_cols=0" >> "$LAYOUT_CONF"

source bridge/layout/right_column_budget.sh

# Migration: append any missing desired_<pane> key with the shipped default.
# Same pattern as the window_cols migration above. Once persisted, drags on
# vertical right-column borders will update these in place.
for p in status buffs group comm ui dev; do
    grep -q "^desired_${p}=" "$LAYOUT_CONF" \
        || echo "desired_${p}=${DEFAULT_DESIRED[$p]}" >> "$LAYOUT_CONF"
done

source "$LAYOUT_CONF"

# Dimension source: prefer launcher-provided env vars (pre-attach build,
# detached session has no authoritative window size yet); fall back to
# tmux display-message in the post-attach hook path.
if [ -n "${LAUNCHER_COLS:-}" ] && [ -n "${LAUNCHER_ROWS:-}" ]; then
    COLS="$LAUNCHER_COLS"
    ROWS="$LAUNCHER_ROWS"
else
    COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
    ROWS=$(tmux display-message -p -t mume:cockpit '#{window_height}')
fi
sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"

REQUESTED=()
[ "$SHOW_STATUS" -eq 1 ] && REQUESTED+=(status)
[ "$SHOW_BUFFS"  -eq 1 ] && REQUESTED+=(buffs)
[ "$SHOW_GROUP"  -eq 1 ] && REQUESTED+=(group)
[ "$SHOW_COMM"   -eq 1 ] && REQUESTED+=(comm)
[ "$SHOW_UI"     -eq 1 ] && REQUESTED+=(ui)
[ "$SHOW_DEV"    -eq 1 ] && REQUESTED+=(dev)

# Phase 1 — survivor selection: drop lowest-priority panes until the
# per-pane MIN_HEIGHT sum fits inside the right-column body budget
# (rc_available_rows accounts for the top header, inter-pane borders,
# and the input area).
while [ "${#REQUESTED[@]}" -gt 0 ]; do
    NN=${#REQUESTED[@]}
    MIN_SUM=0
    for p in "${REQUESTED[@]}"; do MIN_SUM=$((MIN_SUM + MIN_HEIGHT[$p])); done
    AVAILABLE=$(rc_available_rows "$NN")
    [ "$MIN_SUM" -le "$AVAILABLE" ] && break
    dropped=""
    for victim in "${DROP_ORDER[@]}"; do
        new=()
        for p in "${REQUESTED[@]}"; do
            if [ -z "$dropped" ] && [ "$p" = "$victim" ]; then
                dropped="$victim"
                continue
            fi
            new+=("$p")
        done
        if [ -n "$dropped" ]; then
            REQUESTED=("${new[@]}")
            echo "[layout] cold start: skipping $dropped (terminal too short: need $MIN_SUM body rows, have $AVAILABLE of $ROWS)" >> logs/debug.log
            break
        fi
    done
    [ -z "$dropped" ] && break
done

# Phase 3 — create panes in visual order, then input. --batch
# suppresses the per-call apply_desired_heights inside open_pane.sh;
# the final pass below settles the geometry once.
for pane in "${REQUESTED[@]}"; do
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" "$pane" --batch
    bash "$HOME/MUME/bridge/layout/equalize_right_column.sh"
done

bash "$HOME/MUME/bridge/launcher/open_pane.sh" input --batch

# pane-border-status must be set BEFORE apply_desired_heights so the
# final resize pass operates against tmux's final divider state.
# Setting it after causes a 1-row drift at the top pane when
# SHOW_DIVIDERS=1 (tmux reserves the top header row by stealing from
# whichever pane is topmost AFTER the resize already settled).
if [ "$SHOW_DIVIDERS" -eq 1 ]; then
    tmux set-option -t mume pane-border-status top
else
    tmux set-option -t mume pane-border-status off
fi
bash "$HOME/MUME/bridge/layout/apply_border_style.sh"

# Phase 2 + final resize pass — pin each surviving pane to its desired
# allocation (linearly scaled when the budget is tight; residual to the
# highest-priority survivor). Replaces the old equalize pass.
bash "$HOME/MUME/bridge/layout/apply_desired_heights.sh"

INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '/^[0-9]+ input$/{print $1}')
tmux select-pane -t mume:cockpit."$INPUT_INDEX"

touch bridge/runtime/.layout_ready
tmux set-hook -t mume -u client-attached
