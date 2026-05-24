#!/usr/bin/env bash
LAYOUT_CONF="$HOME/MUME/bridge/runtime/layout.conf"
LOCK="$HOME/MUME/bridge/runtime/.layout_lock"

source "$HOME/MUME/bridge/lib/conf_io.sh"

[ -f "$LOCK" ] && exit 0

# ── Width persistence ─────────────────────────────────────────────────────
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="comm" || $1=="dev" || $1=="status" || $1=="buffs" {print $2; exit}')
[ -z "$NEW_WIDTH" ] && exit 0

sed_inplace "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"

# ── Height persistence ───────────────────────────────────────────────────
# Snapshot each right-column pane's body height into desired_<pane>. A
# horizontal-border drag changes no heights → these writes are no-ops. A
# vertical-border drag affects two neighbours → both get persisted. The
# values written are content rows (pane_height excludes the title row),
# matching the semantics of desired_*.
while IFS= read -r line; do
    pname=$(echo "$line" | awk '{print $2}')
    pheight=$(echo "$line" | awk '{print $3}')
    case "$pname" in
        status|buffs|group|comm|ui|dev)
            if grep -q "^desired_${pname}=" "$LAYOUT_CONF"; then
                sed_inplace "s/^desired_${pname}=.*/desired_${pname}=${pheight}/" "$LAYOUT_CONF"
            else
                echo "desired_${pname}=${pheight}" >> "$LAYOUT_CONF"
            fi
            ;;
    esac
done < <(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title} #{pane_height}')

bash "$HOME/MUME/bridge/layout/apply_layout.sh"
