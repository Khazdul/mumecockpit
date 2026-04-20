#!/bin/bash
# bridge/tmux_start.sh — creates and attaches to the MUME tmux cockpit session.
# Reads show_ui / show_dev / show_input from bridge/startup.conf.
# Called by start.sh (--no-menu / -d / -u) or bridge/launcher.sh ("Start new session").

cd "$(dirname "$0")/.."

CONF="bridge/startup.conf"

# Create startup.conf with defaults if missing
if [ ! -f "$CONF" ]; then
    printf 'connection_mode=mmapper\nshow_ui=1\nshow_dev=0\nshow_input=1\n' > "$CONF"
fi
source "$CONF"

# start.sh may export override variables for backwards-compat -d / -u flags.
# These apply for this run only and are never written back to startup.conf.
[ -n "$_OVERRIDE_SHOW_UI"  ] && show_ui="$_OVERRIDE_SHOW_UI"
[ -n "$_OVERRIDE_SHOW_DEV" ] && show_dev="$_OVERRIDE_SHOW_DEV"

SHOW_UI="${show_ui:-1}"
SHOW_DEV="${show_dev:-0}"
SHOW_INPUT="${show_input:-1}"

# ---------------------------------------------------------------------------
# 1. Dirs, permissions, log reset
# ---------------------------------------------------------------------------
mkdir -p bridge logs

chmod +x bridge/open_pane.sh
chmod +x bridge/focus_input.sh

touch logs/debug.log logs/ui.log
> logs/debug.log
> logs/ui.log

# ---------------------------------------------------------------------------
# 2. Kill any old session and create a fresh one
# ---------------------------------------------------------------------------
tmux kill-session -t mume 2>/dev/null || true

TERM_COLS=$(tput cols)
TERM_LINES=$(tput lines)

# Delay tt++ launch until the pane setup below (split-window, resize-pane)
# has completed. Otherwise tt++/Lua emit startup output while tail -f
# is still reflowing, and the first lines are lost into tmux scrollback.
tmux new-session -d -s mume -x "$TERM_COLS" -y "$TERM_LINES" -n cockpit \
    "sleep 0.3 && cd $HOME/MUME && exec tt++ -G ttpp/main.tin"
tmux set-option -t mume status off
tmux set-option -t mume mouse on

tmux set-option -t mume pane-border-status top
tmux set-option -t mume pane-border-format "#{?#{==:#{pane_title},MUME},,#{?#{==:#{pane_title},input},,#{?pane_title,#{pane_title},}}}"
tmux set-option -t mume pane-border-style "fg=colour238"
tmux set-option -t mume pane-active-border-style "fg=colour238"

# ---------------------------------------------------------------------------
# 3. Build layout
# ---------------------------------------------------------------------------
LAYOUT_CONF="bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || printf "ui_width=33\nwindow_cols=0\nui_height_ratio=60\n" > "$LAYOUT_CONF"
grep -q "^window_cols="     "$LAYOUT_CONF" || echo "window_cols=0"      >> "$LAYOUT_CONF"
grep -q "^ui_height_ratio=" "$LAYOUT_CONF" || echo "ui_height_ratio=60" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"
LEFT_WIDTH=$(( TERM_COLS - ui_width - 1 ))
sed -i "s/^window_cols=.*/window_cols=$TERM_COLS/" "$LAYOUT_CONF"

if [ "$SHOW_UI" -eq 1 ] && [ "$SHOW_DEV" -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f $HOME/MUME/logs/ui.log; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux split-window -v -t mume:cockpit.1 "bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f $HOME/MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.2 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ "$SHOW_UI" -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f $HOME/MUME/logs/ui.log; printf \"\\n[pane kept alive — use cp -u to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ "$SHOW_DEV" -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f $HOME/MUME/logs/debug.log; printf \"\\n[pane kept alive — use cp -d to close]\\n\"; sleep 0.2; done'"
    tmux select-pane -t mume:cockpit.1 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

if [ "$SHOW_UI" -eq 1 ] && [ "$SHOW_DEV" -eq 1 ]; then
    UI_H=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
        | awk '$1=="ui" {print $2; exit}')
    DEV_H=$(tmux list-panes -t mume:cockpit -F '#{pane_title} #{pane_height}' \
        | awk '$1=="dev" {print $2; exit}')
    TOTAL=$(( UI_H + DEV_H + 1 ))
    APPLY_UI_H=$(( TOTAL * ui_height_ratio / 100 ))
    UI_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | awk '$2=="ui" {print $1; exit}')
    [ -n "$UI_INDEX" ] && tmux resize-pane -t "mume:cockpit.$UI_INDEX" -y "$APPLY_UI_H"
fi

# ---------------------------------------------------------------------------
# 4. Register layout hooks
# ---------------------------------------------------------------------------
tmux set-hook -t mume window-resized \
    "run-shell 'bash $HOME/MUME/bridge/on_window_resize.sh'"
tmux bind-key -n MouseDragEnd1Border \
    "run-shell 'bash $HOME/MUME/bridge/on_pane_resize.sh'"

# ---------------------------------------------------------------------------
# 5. TT++ started directly in pane 0 (via new-session above) — no send-keys.
# ---------------------------------------------------------------------------
tmux select-pane -t mume:cockpit.0 -T "MUME"
sleep 0.2 && tmux select-pane -t mume:cockpit.0 -T "MUME" &

# ---------------------------------------------------------------------------
# 6. Open input pane
# ---------------------------------------------------------------------------
if [ "$SHOW_INPUT" -eq 1 ]; then
    bash "$HOME/MUME/bridge/open_pane.sh" input
fi

# ---------------------------------------------------------------------------
# 7. Focus input pane (or game pane if input is off)
# ---------------------------------------------------------------------------
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '/^[0-9]+ input$/{print $1}')
if [ -n "$INPUT_INDEX" ]; then
    tmux select-pane -t mume:cockpit.$INPUT_INDEX
else
    tmux select-pane -t mume:cockpit.0
fi

exec tmux attach -t mume
