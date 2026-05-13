#!/usr/bin/env bash
# bridge/layout/right_column_budget.sh — shared right-column budget helpers.
# Sourced by build_initial_layout.sh (cold-start skip) and open_pane.sh
# (runtime open gate). Dependency-free; tmux session is hardcoded
# `mume:cockpit` as everywhere else.

# Per-pane content-row floor (excludes title row).
declare -A MIN_HEIGHT=(
    [status]=2
    [buffs]=1
    [group]=1
    [comm]=1
    [ui]=1
    [dev]=1
)

# Shipped default content-row preferences (excludes title row). Used both as
# the seed for layout.conf desired_<pane> migration and as the reset target
# for `cp -reset-heights`.
declare -A DEFAULT_DESIRED=(
    [status]=6
    [buffs]=5
    [group]=5
    [comm]=10
    [ui]=5
    [dev]=5
)

# Drop order: lowest priority first. Reversed yields PRIORITY_ORDER —
# the highest-priority surviving pane absorbs residual rows.
DROP_ORDER=(dev group buffs comm status ui)
PRIORITY_ORDER=(ui status comm buffs group dev)

# Deprecated: kept one release for the rc_max_panes / rc_fits_one_more
# runtime-open gate in open_pane.sh, which is not changed in this PR.
# Remove after open_pane.sh switches to MIN_HEIGHT-aware sizing.
MIN_PER_PANE=2
TITLE_OVERHEAD=1
INPUT_RESERVE=1

rc_count() {
    tmux list-panes -t mume:cockpit -F '#{pane_title}' 2>/dev/null \
        | grep -cE '^(status|buffs|group|comm|ui|dev)$'
}

rc_window_height() {
    tmux display-message -p -t mume:cockpit '#{window_height}' 2>/dev/null
}

rc_max_panes() {
    local h
    h=$(rc_window_height)
    [ -z "$h" ] && { echo 0; return; }
    echo $(( (h - INPUT_RESERVE) / (MIN_PER_PANE + TITLE_OVERHEAD) ))
}

rc_fits_one_more() {
    local n max
    n=$(rc_count)
    max=$(rc_max_panes)
    [ $((n + 1)) -le "$max" ]
}

# True if the given target pane has enough body height to be split such
# that both halves can satisfy MIN_PER_PANE. tmux #{pane_height} reports
# body rows excluding the title row.
#
# Math: target.body must accommodate two MIN content rows plus one row
# that becomes the new pane's title row.
#   target.body >= 2 * MIN_PER_PANE + 1
rc_target_can_be_split() {
    local idx=$1
    [ -z "$idx" ] && return 1
    local h
    h=$(tmux display-message -p -t "mume:cockpit.$idx" '#{pane_height}' 2>/dev/null)
    [ -z "$h" ] && return 1
    [ "$h" -ge $(( 2 * MIN_PER_PANE + 1 )) ]
}
