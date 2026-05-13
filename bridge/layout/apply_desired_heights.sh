#!/usr/bin/env bash
# bridge/layout/apply_desired_heights.sh — Phase 2 + targeted resize pass.
# Reads the live right-column pane list from tmux, computes per-pane
# allocation from desired_<pane> values in layout.conf (clamped against
# MIN_HEIGHT), drops the residual into the highest-priority surviving
# pane, and pins each pane via `tmux resize-pane -y`.
#
# Called by build_initial_layout.sh (cold start, post-create) and by
# `cp -reset-heights` (soft re-apply after rewriting layout.conf).
# Idempotent — re-running with the same inputs yields the same geometry.

cd "$HOME/MUME" 2>/dev/null

source "$HOME/MUME/bridge/runtime/startup.conf" 2>/dev/null || true
LAYOUT_CONF="$HOME/MUME/bridge/runtime/layout.conf"
[ -f "$LAYOUT_CONF" ] && source "$LAYOUT_CONF"
source "$HOME/MUME/bridge/layout/right_column_budget.sh"

# Right-column panes in visual order (top to bottom).
REQUESTED=()
while IFS= read -r p; do
    REQUESTED+=("$p")
done < <(tmux list-panes -t mume:cockpit \
    -F '#{pane_top} #{pane_title}' 2>/dev/null \
    | awk '$2 ~ /^(status|buffs|group|comm|ui|dev)$/' \
    | sort -n \
    | awk '{print $2}')

[ "${#REQUESTED[@]}" -eq 0 ] && exit 0

# Map pane title → tmux index for the targeted resize pass.
declare -A PIDX
while IFS=$'\t' read -r idx title; do
    case "$title" in
        status|buffs|group|comm|ui|dev)
            PIDX[$title]=$idx
            ;;
    esac
done < <(tmux list-panes -t mume:cockpit \
    -F '#{pane_index}	#{pane_title}' 2>/dev/null)

# AVAILABLE is computed from window height minus right-column overhead
# (top header, inter-pane borders, input area) — the same formula used
# by build_initial_layout.sh so cold start and cp -reset-heights agree.
AVAILABLE=$(rc_available_rows "${#REQUESTED[@]}")

# Resolve DESIRED, clamping below to MIN_HEIGHT so a stale/edited value
# can never force a pane below its content floor.
declare -A DESIRED
MIN_SUM=0
DESIRED_SUM=0
for p in "${REQUESTED[@]}"; do
    var="desired_${p}"
    v=${!var:-${DEFAULT_DESIRED[$p]}}
    [ "$v" -lt "${MIN_HEIGHT[$p]}" ] && v=${MIN_HEIGHT[$p]}
    DESIRED[$p]=$v
    MIN_SUM=$((MIN_SUM + MIN_HEIGHT[$p]))
    DESIRED_SUM=$((DESIRED_SUM + v))
done

# Phase 2 — allocate between MIN and DESIRED.
declare -A ALLOC
if [ "$DESIRED_SUM" -le "$AVAILABLE" ]; then
    for p in "${REQUESTED[@]}"; do ALLOC[$p]=${DESIRED[$p]}; done
else
    NUM=$((AVAILABLE - MIN_SUM))
    DEN=$((DESIRED_SUM - MIN_SUM))
    [ "$NUM" -lt 0 ] && NUM=0
    [ "$DEN" -le 0 ] && DEN=1
    for p in "${REQUESTED[@]}"; do
        ALLOC[$p]=$(( MIN_HEIGHT[$p] + (DESIRED[$p] - MIN_HEIGHT[$p]) * NUM / DEN ))
    done
fi

# Drop residual rows into the highest-priority surviving pane.
SUM=0
for p in "${REQUESTED[@]}"; do SUM=$((SUM + ALLOC[$p])); done
RESIDUAL=$((AVAILABLE - SUM))
if [ "$RESIDUAL" -ne 0 ]; then
    for p in "${PRIORITY_ORDER[@]}"; do
        if [ -n "${ALLOC[$p]+x}" ]; then
            ALLOC[$p]=$((ALLOC[$p] + RESIDUAL))
            break
        fi
    done
fi

# Final resize pass — pin each pane to its allocation.
for p in "${REQUESTED[@]}"; do
    [ -n "${PIDX[$p]}" ] && tmux resize-pane -t "mume:cockpit.${PIDX[$p]}" -y "${ALLOC[$p]}"
done

exit 0
