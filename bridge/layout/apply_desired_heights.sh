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
    | awk '$2 ~ /^(status|timers|group|comm|ui|dev)$/' \
    | sort -n \
    | awk '{print $2}')

[ "${#REQUESTED[@]}" -eq 0 ] && exit 0

# Map pane title → tmux index for the targeted resize pass.
declare -A PIDX
while IFS=$'\t' read -r idx title; do
    case "$title" in
        status|timers|group|comm|ui|dev)
            PIDX[$title]=$idx
            ;;
    esac
done < <(tmux list-panes -t mume:cockpit \
    -F '#{pane_index}	#{pane_title}' 2>/dev/null)

# AVAILABLE is computed from window height minus right-column overhead
# (inter-pane borders, input area) — the same formula used by
# build_initial_layout.sh so cold start and cp -reset-heights agree.
# In-pane border rows are reserved per framed pane (frame_extra) and
# carved out of the content budget below, then added back to the pinned
# tmux height so content height is preserved.
AVAILABLE=$(rc_available_rows "${#REQUESTED[@]}")

# Per-pane in-pane border reservation, and the content budget after
# carving out every framed pane's reservation.
declare -A FRAME_EXTRA
FRAME_SUM=0
for p in "${REQUESTED[@]}"; do
    FRAME_EXTRA[$p]=$(rc_frame_extra "$p")
    FRAME_SUM=$((FRAME_SUM + FRAME_EXTRA[$p]))
done
CONTENT_AVAILABLE=$((AVAILABLE - FRAME_SUM))
[ "$CONTENT_AVAILABLE" -lt 0 ] && CONTENT_AVAILABLE=0

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

# Allocate a set of panes against a content budget, writing ALLOC[p] for
# each pane in the set. Two-branch rule: if the set's desired-sum fits the
# budget every pane gets its DESIRED; otherwise each is scaled linearly
# between its MIN_HEIGHT and DESIRED. The residual (from integer division or
# a surplus budget) drops into the highest-priority pane within the set per
# PRIORITY_ORDER. Reads DESIRED/MIN_HEIGHT/PRIORITY_ORDER from the outer
# scope; only ALLOC is mutated.
# Args: $1 = budget, $2.. = pane names.
allocate_set() {
    local budget=$1; shift
    local -a set=("$@")
    [ "${#set[@]}" -eq 0 ] && return

    local p
    local -A in_set=()
    local min_sum=0 desired_sum=0
    for p in "${set[@]}"; do
        in_set[$p]=1
        min_sum=$((min_sum + MIN_HEIGHT[$p]))
        desired_sum=$((desired_sum + DESIRED[$p]))
    done

    if [ "$desired_sum" -le "$budget" ]; then
        for p in "${set[@]}"; do ALLOC[$p]=${DESIRED[$p]}; done
    else
        local num=$((budget - min_sum))
        local den=$((desired_sum - min_sum))
        [ "$num" -lt 0 ] && num=0
        [ "$den" -le 0 ] && den=1
        for p in "${set[@]}"; do
            ALLOC[$p]=$(( MIN_HEIGHT[$p] + (DESIRED[$p] - MIN_HEIGHT[$p]) * num / den ))
        done
    fi

    # Drop residual content rows into the highest-priority pane in the set.
    local sum=0
    for p in "${set[@]}"; do sum=$((sum + ALLOC[$p])); done
    local residual=$((budget - sum))
    if [ "$residual" -ne 0 ]; then
        for p in "${PRIORITY_ORDER[@]}"; do
            if [ -n "${in_set[$p]+x}" ]; then
                ALLOC[$p]=$((ALLOC[$p] + residual))
                break
            fi
        done
    fi
}

# Phase 2 — allocate content rows between MIN and DESIRED against the
# content budget (border reservations excluded). The status pane is reserved
# first when present: its desired height is set aside before the remaining
# panes scale against what is left, so a tight budget squeezes the others
# rather than the character pane. When the status pane is absent (dropped by
# Phase 1 survivor selection) or is the only requested pane, every pane is
# allocated in a single pass — geometry identical to the unprotected rule.
declare -A ALLOC
STATUS_IN=0
OTHERS=()
for p in "${REQUESTED[@]}"; do
    if [ "$p" = status ]; then
        STATUS_IN=1
    else
        OTHERS+=("$p")
    fi
done

if [ "$STATUS_IN" -eq 1 ] && [ "${#OTHERS[@]}" -gt 0 ]; then
    OTHERS_MIN_SUM=0
    for p in "${OTHERS[@]}"; do
        OTHERS_MIN_SUM=$((OTHERS_MIN_SUM + MIN_HEIGHT[$p]))
    done

    # Reserve status at its desired height, clamped so the other panes always
    # keep at least their mins. Phase 1 guarantees the surviving mins fit, so
    # the upper clamp only bites on an absurdly short terminal.
    STATUS_ALLOC=${DESIRED[status]}
    UPPER=$((CONTENT_AVAILABLE - OTHERS_MIN_SUM))
    [ "$STATUS_ALLOC" -gt "$UPPER" ] && STATUS_ALLOC=$UPPER
    [ "$STATUS_ALLOC" -lt "${MIN_HEIGHT[status]}" ] && STATUS_ALLOC=${MIN_HEIGHT[status]}

    allocate_set "$((CONTENT_AVAILABLE - STATUS_ALLOC))" "${OTHERS[@]}"
    ALLOC[status]=$STATUS_ALLOC
else
    allocate_set "$CONTENT_AVAILABLE" "${REQUESTED[@]}"
fi

# Final resize pass — pin each pane to its content allocation plus its
# in-pane border reservation.
for p in "${REQUESTED[@]}"; do
    [ -n "${PIDX[$p]}" ] \
        && tmux resize-pane -t "mume:cockpit.${PIDX[$p]}" \
               -y "$(( ALLOC[$p] + FRAME_EXTRA[$p] ))"
done

exit 0
