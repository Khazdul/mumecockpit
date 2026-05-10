#!/usr/bin/env bash
# bridge/launcher/build_initial_layout.sh — builds the cockpit pane layout post-attach.
# Fired by a one-shot client-attached hook registered in tmux_start.sh.
# Reads true terminal width from tmux (authoritative post-attach) rather than
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
LEFT_WIDTH=$(( COLS - ui_width - 1 ))

if [ "$SHOW_UI" -eq 1 ] && [ "$SHOW_DEV" -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $HOME/MUME/bridge/panes/ui_pane.py; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux split-window -v -t mume:cockpit.1 "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $HOME/MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.2 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ "$SHOW_UI" -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do python3 $HOME/MUME/bridge/panes/ui_pane.py; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ "$SHOW_DEV" -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "bash -c 'stty -isig 2>/dev/null; trap \"\" INT; while true; do tail -f $HOME/MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.1 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

if [ "$SHOW_STATUS" -eq 1 ]; then
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" status
fi
if [ "$SHOW_BUFFS" -eq 1 ]; then
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" buffs
fi
if [ "$SHOW_GROUP" -eq 1 ]; then
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" group
fi
if [ "$SHOW_COMM" -eq 1 ]; then
    bash "$HOME/MUME/bridge/launcher/open_pane.sh" comm
fi
bash "$HOME/MUME/bridge/layout/apply_layout.sh"

bash "$HOME/MUME/bridge/launcher/open_pane.sh" input

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
