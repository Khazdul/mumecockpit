#!/usr/bin/env bash
# bridge/layout/reset_heights.sh — restore shipped per-pane desired heights.
# Strips desired_<pane> lines from layout.conf, appends DEFAULT_DESIRED
# from right_column_budget.sh, then soft-reapplies via
# apply_desired_heights.sh (no pane create/kill).
# Wired to the `cp -reset-heights` alias.

LAYOUT_CONF="$HOME/MUME/bridge/runtime/layout.conf"
source "$HOME/MUME/bridge/layout/right_column_budget.sh"

[ -f "$LAYOUT_CONF" ] || exit 0

for p in status buffs group comm ui dev; do
    sed -i "/^desired_${p}=/d" "$LAYOUT_CONF"
    echo "desired_${p}=${DEFAULT_DESIRED[$p]}" >> "$LAYOUT_CONF"
done

bash "$HOME/MUME/bridge/layout/apply_desired_heights.sh"
