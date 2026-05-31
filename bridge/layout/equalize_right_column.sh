#!/usr/bin/env bash
# bridge/layout/equalize_right_column.sh — distribute current right-column
# panes to equal fair-share heights using the same budget formula as
# rc_available_rows (PR A.3). Called between split-window invocations
# during cold-start Phase 3 and narrow-restore so the next split's
# target stays above tmux's pane floor and rc_target_can_be_split's
# gate.
#
# Final algorithmic geometry should be applied via
# apply_desired_heights.sh after all panes are settled — equalize is
# a transient step, not the final allocation.

cd "$HOME/MUME"
source bridge/runtime/startup.conf 2>/dev/null || true
source bridge/layout/right_column_budget.sh

mapfile -t RC_INDICES < <(
    tmux list-panes -t mume:cockpit -F '#{pane_top} #{pane_index} #{pane_title}' 2>/dev/null \
    | awk '$3 ~ /^(status|timers|group|comm|ui|dev)$/' \
    | sort -n \
    | awk '{print $2}'
)
N_RC=${#RC_INDICES[@]}
[ "$N_RC" -lt 2 ] && exit 0

AVAILABLE=$(rc_available_rows "$N_RC")
SHARE=$(( AVAILABLE / N_RC ))

for ((i=0; i<N_RC-1; i++)); do
    tmux resize-pane -t "mume:cockpit.${RC_INDICES[$i]}" -y "$SHARE"
done
