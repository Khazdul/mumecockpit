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
[ -f "$LAYOUT_CONF" ] || printf "ui_width=33\nwindow_cols=0\n" > "$LAYOUT_CONF"
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
# per-pane MIN_HEIGHT sum (plus title rows and input) fits inside ROWS.
TITLE=$([ "$SHOW_DIVIDERS" -eq 1 ] && echo 1 || echo 0)
while [ "${#REQUESTED[@]}" -gt 0 ]; do
    NN=${#REQUESTED[@]}
    MIN_SUM=0
    for p in "${REQUESTED[@]}"; do MIN_SUM=$((MIN_SUM + MIN_HEIGHT[$p])); done
    NEEDED=$((MIN_SUM + NN * TITLE + INPUT_RESERVE))
    [ "$NEEDED" -le "$ROWS" ] && break
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
            echo "[layout] cold start: skipping $dropped (terminal too short: $ROWS rows, needed $NEEDED)" >> logs/debug.log
            break
        fi
    done
    [ -z "$dropped" ] && break
done

# Phase 3 — create panes in visual order, then input.
for pane in "${REQUESTED[@]}"; do
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" "$pane"

    # Equalize current right-column panes so the next split's target
    # stays above tmux's floor and rc_target_can_be_split's gate.
    mapfile -t RC_INDICES < <(
        tmux list-panes -t mume:cockpit -F '#{pane_top} #{pane_index} #{pane_title}' \
        | awk '$3 ~ /^(status|buffs|group|comm|ui|dev)$/' \
        | sort -n \
        | awk '{print $2}'
    )
    N_RC=${#RC_INDICES[@]}
    if [ "$N_RC" -gt 1 ]; then
        SHARE=$(( (ROWS - INPUT_RESERVE) / N_RC ))
        for ((i=0; i<N_RC-1; i++)); do
            tmux resize-pane -t "mume:cockpit.${RC_INDICES[$i]}" -y "$SHARE"
        done
    fi
done

bash "$HOME/MUME/bridge/launcher/open_pane.sh" input

# Phase 2 + final resize pass — pin each surviving pane to its desired
# allocation (linearly scaled when the budget is tight; residual to the
# highest-priority survivor). Replaces the old equalize pass.
bash "$HOME/MUME/bridge/layout/apply_desired_heights.sh"

INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '/^[0-9]+ input$/{print $1}')
tmux select-pane -t mume:cockpit."$INPUT_INDEX"

if [ "$SHOW_DIVIDERS" -eq 1 ]; then
    tmux set-option -t mume pane-border-status top
    tmux set-option -t mume pane-border-style        "fg=black bg=black"
    tmux set-option -t mume pane-active-border-style "fg=black bg=black"
else
    tmux set-option -t mume pane-border-status off
    tmux set-option -t mume pane-border-style        "fg=black bg=black"
    tmux set-option -t mume pane-active-border-style "fg=black bg=black"
fi

touch bridge/runtime/.layout_ready
tmux set-hook -t mume -u client-attached
