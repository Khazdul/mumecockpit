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
SHOW_GROUP="${show_group:-0}"
SHOW_COMM="${show_comm:-0}"
SHOW_DIVIDERS="${show_pane_dividers:-1}"

LAYOUT_CONF="bridge/runtime/layout.conf"
[ -f "$LAYOUT_CONF" ] || printf "ui_width=33\nwindow_cols=0\n" > "$LAYOUT_CONF"
grep -q "^window_cols=" "$LAYOUT_CONF" || echo "window_cols=0" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"

COLS=$(tmux display-message -p -t mume:cockpit '#{window_width}')
sed -i "s/^window_cols=.*/window_cols=$COLS/" "$LAYOUT_CONF"

# Pre-flight: compute the right-column budget, build the requested pane list
# in visual order, then drop the lowest-priority survivors until they fit.
# Skipped panes stay enabled in startup.conf — a wider terminal next start
# gets them back without manual reconfiguration.
ROWS=$(tmux display-message -p -t mume:cockpit '#{window_height}')
source bridge/layout/right_column_budget.sh
MAX=$(rc_max_panes)

REQUESTED=()
[ "$SHOW_STATUS" -eq 1 ] && REQUESTED+=(status)
[ "$SHOW_BUFFS"  -eq 1 ] && REQUESTED+=(buffs)
[ "$SHOW_GROUP"  -eq 1 ] && REQUESTED+=(group)
[ "$SHOW_COMM"   -eq 1 ] && REQUESTED+=(comm)
[ "$SHOW_UI"     -eq 1 ] && REQUESTED+=(ui)
[ "$SHOW_DEV"    -eq 1 ] && REQUESTED+=(dev)

# Drop order: lowest priority first. ui is kept last.
DROP_ORDER=(dev group buffs comm status ui)
while [ "${#REQUESTED[@]}" -gt "$MAX" ]; do
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
            echo "[layout] cold start: skipping $dropped (terminal too short: $ROWS rows)" >> logs/debug.log
            break
        fi
    done
    [ -z "$dropped" ] && break
done

for pane in "${REQUESTED[@]}"; do
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" "$pane"
done

bash "$HOME/MUME/bridge/launcher/open_pane.sh" input

# Equalize pass — runs once at cold start; never on resizes or drags (ADR 0030).
mapfile -t RC_INDICES < <(
    tmux list-panes -t mume:cockpit -F '#{pane_top} #{pane_index} #{pane_title}' \
    | awk '$3 ~ /^(status|buffs|group|comm|ui|dev)$/' \
    | sort -n \
    | awk '{print $2}'
)
N=${#RC_INDICES[@]}
if [ "$N" -gt 1 ]; then
    BUDGET=$(( ROWS - INPUT_RESERVE - N ))
    SHARE=$(( BUDGET / N ))
    for ((i=0; i<N-1; i++)); do
        tmux resize-pane -t "mume:cockpit.${RC_INDICES[$i]}" -y "$SHARE"
    done
fi

INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '/^[0-9]+ input$/{print $1}')
tmux select-pane -t mume:cockpit."$INPUT_INDEX"

if [ "$SHOW_DIVIDERS" -eq 1 ]; then
    tmux set-option -t mume pane-border-status top
    tmux set-option -t mume pane-border-style "fg=colour235"
    tmux set-option -t mume pane-active-border-style "fg=colour235"
else
    tmux set-option -t mume pane-border-status off
    tmux set-option -t mume pane-border-style "fg=black"
    tmux set-option -t mume pane-active-border-style "fg=black"
fi

touch bridge/runtime/.layout_ready
tmux set-hook -t mume -u client-attached
