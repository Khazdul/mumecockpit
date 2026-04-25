#!/bin/bash
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
LOCK="$HOME/MUME/bridge/.layout_lock"

[ -f "$LOCK" ] && exit 0

# ── Width persistence ─────────────────────────────────────────────────────
NEW_WIDTH=$(tmux list-panes -t mume:cockpit \
  -F '#{pane_title} #{pane_width}' \
  | awk '$1=="ui" || $1=="dev" || $1=="status" {print $2; exit}')
[ -z "$NEW_WIDTH" ] && exit 0

HAS_STATUS=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^status$')

# Clamp: status pane requires ≥ 33 cols for its field layout
if [ -n "$HAS_STATUS" ] && [ "$NEW_WIDTH" -lt 33 ]; then
    NEW_WIDTH=33
fi
sed -i "s/^ui_width=.*/ui_width=$NEW_WIDTH/" "$LAYOUT_CONF"

# ── Height drag detection (status open: detect which border moved) ─────────
if [ -n "$HAS_STATUS" ]; then
    grep -q "^ui_height=" "$LAYOUT_CONF" || echo "ui_height=20" >> "$LAYOUT_CONF"
    source "$LAYOUT_CONF"

    S=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
        | awk '$1=="status" {print $2; exit}')

    if [ -n "$S" ] && [ "$S" -ne "${status_height:-12}" ]; then
        # Top border (char↔ui) dragged — snap back only, no persistence.
        : # apply_layout.sh below restores everything
    else
        # S is at configured height; check if ui↔dev bottom border was dragged.
        U=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
            | awk '$1=="ui" {print $2; exit}')
        if [ -n "$U" ] && [ "$U" -ge 3 ] && [ "$U" -ne "${ui_height:-20}" ]; then
            # Bottom border (ui↔dev) dragged — persist new ui height.
            sed -i "s/^ui_height=.*/ui_height=$U/" "$LAYOUT_CONF"
        fi
    fi
fi

bash "$HOME/MUME/bridge/apply_layout.sh"
