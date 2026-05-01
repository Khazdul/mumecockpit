#!/usr/bin/env bash
# bridge/tmux_start.sh — creates and attaches to the MUME tmux cockpit session.
# Reads show_ui / show_dev / show_status / show_comm from bridge/startup.conf.
# Called by start.sh (--no-menu / -d / -u) or bridge/launcher.sh ("New session").

cd "$(dirname "$0")/.."

# Clear any stale sentinel left by a crash before doing anything else.
# The sentinel is set by ingame_menu.sh just before firing cp -e; if tmux
# died uncleanly the file may linger and mis-route the next cold start.
rm -f bridge/.return_to_menu
rm -f bridge/.popup_open

CONF="bridge/startup.conf"

# Create startup.conf with defaults if missing
if [ ! -f "$CONF" ]; then
    printf 'connection_mode=mmapper\nshow_status=1\nshow_comm=1\nshow_ui=1\nshow_dev=0\nshow_pane_dividers=1\nprofile=default\n' > "$CONF"
fi
source "$CONF"

# start.sh may export override variables for backwards-compat -d / -u flags.
# These apply for this run only and are never written back to startup.conf.
[ -n "$_OVERRIDE_SHOW_UI"  ] && show_ui="$_OVERRIDE_SHOW_UI"
[ -n "$_OVERRIDE_SHOW_DEV" ] && show_dev="$_OVERRIDE_SHOW_DEV"

SHOW_UI="${show_ui:-1}"
SHOW_DEV="${show_dev:-0}"
SHOW_STATUS="${show_status:-0}"
SHOW_BUFFS="${show_buffs:-0}"
SHOW_COMM="${show_comm:-0}"
SHOW_DIVIDERS="${show_pane_dividers:-1}"

# ---------------------------------------------------------------------------
# 1. Dirs, permissions, log reset
# ---------------------------------------------------------------------------
mkdir -p bridge logs

chmod +x bridge/apply_layout.sh
chmod +x bridge/open_pane.sh
chmod +x bridge/focus_input.sh
chmod +x bridge/toggle_pane.sh
chmod +x bridge/read_version.sh

touch logs/debug.log logs/ui.log
> logs/debug.log
> logs/ui.log

# ---------------------------------------------------------------------------
# 2. Kill any old session and create a fresh one
# ---------------------------------------------------------------------------
tmux kill-session -t mume 2>/dev/null || true

read -r TERM_LINES TERM_COLS < <(stty size </dev/tty 2>/dev/null || echo "24 80")

# Delay tt++ launch until the pane setup below (split-window, resize-pane)
# has completed. Otherwise tt++/Lua emit startup output while tail -f
# is still reflowing, and the first lines are lost into tmux scrollback.
tmux new-session -d -s mume -x "$TERM_COLS" -y "$TERM_LINES" -n cockpit \
    "sleep 0.3 && cd $HOME/MUME && exec tt++ -G ttpp/main.tin"
tmux set-option -t mume status off
tmux set-option -t mume mouse on

# Truecolor (24-bit RGB) passthrough.
# Without this, tmux downsamples every 24-bit colour escape to the
# 256-colour palette, collapsing many distinct dark colours onto the
# same palette entry — most visibly affecting the status pane's XP/TP
# bars, but a problem for any future panel using exact RGB values.
# "*:RGB" advertises truecolor for whatever TERM the host terminal
# exposes (alacritty, xterm-256color, tmux-256color, …) — no
# per-terminal hardcoding.
tmux set-option -g  default-terminal   "tmux-256color"
tmux set-option -as terminal-overrides ",*:RGB"
tmux set-option -as terminal-features  ",*:RGB"

tmux set-option -t mume pane-border-format \
  "#{?#{==:#{pane_title},status}, Character ,#{?#{==:#{pane_title},buffs}, Buffs ,#{?#{==:#{pane_title},comm}, Communication ,#{?#{==:#{pane_title},ui}, UI ,#{?#{==:#{pane_title},dev}, Dev ,}}}}}"
if [ "$SHOW_DIVIDERS" -eq 1 ]; then
    tmux set-option -t mume pane-border-status top
    tmux set-option -t mume pane-border-style "fg=colour235"
    tmux set-option -t mume pane-active-border-style "fg=colour235"
else
    tmux set-option -t mume pane-border-status off
    tmux set-option -t mume pane-border-style "fg=black"
    tmux set-option -t mume pane-active-border-style "fg=black"
fi

# ---------------------------------------------------------------------------
# 3. Build layout
# ---------------------------------------------------------------------------
LAYOUT_CONF="bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || printf "ui_width=33\nwindow_cols=0\n" > "$LAYOUT_CONF"
grep -q "^window_cols=" "$LAYOUT_CONF" || echo "window_cols=0" >> "$LAYOUT_CONF"
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

# ---------------------------------------------------------------------------
# 4. Register layout hooks
# ---------------------------------------------------------------------------
tmux set-hook -t mume window-resized \
    "run-shell 'bash $HOME/MUME/bridge/on_window_resize.sh'"
tmux bind-key -n MouseDragEnd1Border \
    "run-shell 'bash $HOME/MUME/bridge/on_pane_resize.sh'"

# Fast escape disambiguation so ESC feels instant.
tmux set-option -s escape-time 10

# ESC opens the in-game popup menu from any pane.
tmux bind-key -T root Escape display-popup -E \
    -w 80% -h 80% -x C -y C \
    "bash $HOME/MUME/bridge/ingame_menu.sh"

# ---------------------------------------------------------------------------
# Cockpit interaction lockdown — hide tmux from the player.
# ---------------------------------------------------------------------------

# Right-click context menus — removed; no useful action for the player.
tmux unbind-key -n MouseDown3Pane
tmux unbind-key -n MouseDown3Status
tmux unbind-key -n MouseDown3StatusLeft
tmux unbind-key -n MouseDown3StatusRight

# Prefix key — disabled; tt++ macros and prompt_toolkit own all keys.
tmux set-option -t mume prefix None

# OSC 52 clipboard — lets selection reach the system clipboard via terminal
# emulator (Alacritty, Windows Terminal, kitty, iTerm2, modern xterm).
tmux set-option -s set-clipboard on

# Wheel in status pane = no-op; stock copy-mode behaviour preserved elsewhere.
# Confirmed stock WheelUpPane (tmux list-keys -T root | grep Wheel):
#   if-shell -F "#{||:#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } { copy-mode -e }
# WheelDownPane had no explicit root binding — complementary form used.
STOCK_WHEEL_UP='if-shell -F "#{||:#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } { copy-mode -e }'
STOCK_WHEEL_DOWN='if-shell -F "#{||:#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } {}'
tmux bind-key -n WheelUpPane   "if-shell -F '#{==:#{pane_title},status}' '' '$STOCK_WHEEL_UP'"
tmux bind-key -n WheelDownPane "if-shell -F '#{==:#{pane_title},status}' '' '$STOCK_WHEEL_DOWN'"

# Refocus input pane when any other pane leaves copy-mode.
# Covers wheel-down past bottom, drag-end, q, Escape, Enter — all paths.
# Guard: pane_in_mode != 1 means we are exiting (entry hook fires too);
#        pane_title != input avoids self-refocus.
tmux set-hook -g pane-mode-changed \
    "if-shell -F '#{&&:#{!=:#{pane_in_mode},1},#{!=:#{pane_title},input}}' \
        'run-shell $HOME/MUME/bridge/focus_input.sh'"

# Start ping monitor. Guarded against double-starts; self-terminates when
# tmux:mume dies.
bash "$HOME/MUME/bridge/ping_monitor.sh" \
    </dev/null >/dev/null 2>&1 &
disown

# ---------------------------------------------------------------------------
# 5. TT++ started directly in pane 0 (via new-session above) — no send-keys.
# ---------------------------------------------------------------------------
tmux select-pane -t mume:cockpit.0 -T "MUME"
sleep 0.2 && tmux select-pane -t mume:cockpit.0 -T "MUME" &

# ---------------------------------------------------------------------------
# 6. Open right-column panes (top to bottom: status → comm → ui → dev)
# ---------------------------------------------------------------------------
if [ "$SHOW_STATUS" -eq 1 ]; then
    bash "$HOME/MUME/bridge/open_pane.sh" status
fi
if [ "$SHOW_BUFFS" -eq 1 ]; then
    bash "$HOME/MUME/bridge/open_pane.sh" buffs
fi
if [ "$SHOW_COMM" -eq 1 ]; then
    bash "$HOME/MUME/bridge/open_pane.sh" comm
fi
bash bridge/apply_layout.sh

# ---------------------------------------------------------------------------
# 7. Open input pane
# ---------------------------------------------------------------------------
bash "$HOME/MUME/bridge/open_pane.sh" input

# ---------------------------------------------------------------------------
# 8. Focus input pane
# ---------------------------------------------------------------------------
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '/^[0-9]+ input$/{print $1}')
tmux select-pane -t mume:cockpit.$INPUT_INDEX

tmux attach -t mume

# Resumes here when the session dies or the user detaches.
# Check for the return-to-menu sentinel written by ingame_menu.sh before
# firing cp -e; if set, exec back into the launcher (no extra bash frame).
if [ -f bridge/.return_to_menu ]; then
    rm -f bridge/.return_to_menu
    exec bash bridge/launcher.sh
fi
# No sentinel → fall through to shell cleanly.
