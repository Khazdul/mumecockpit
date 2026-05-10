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
