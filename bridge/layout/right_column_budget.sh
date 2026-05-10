#!/usr/bin/env bash
# bridge/layout/right_column_budget.sh — shared right-column budget helpers.
# Sourced by build_initial_layout.sh (cold-start skip) and open_pane.sh
# (runtime open gate). Dependency-free; tmux session is hardcoded
# `mume:cockpit` as everywhere else.

MIN_PER_PANE=3
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
