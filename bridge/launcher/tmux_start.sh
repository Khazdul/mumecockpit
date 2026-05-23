#!/usr/bin/env bash
# bridge/launcher/tmux_start.sh — creates and attaches to the MUME tmux cockpit session.
# Session options, hooks, and keybinds are configured here. Pane layout is built
# by build_initial_layout.sh in one of two modes (see docs/launcher.md "Initial
# layout build"): pre-attach when LAUNCHER_COLS/ROWS are provided by launcher.py,
# post-attach via a one-shot client-attached hook otherwise (ADR 0041 fallback).
# Called by start.sh (--no-menu / -d / -u) or bridge/launcher/launcher.sh ("Enter MUME").

# Keep terminal in alt-screen across this script so any incidental output
# stays hidden from the user's normal terminal buffer. Idempotent if the
# caller (launcher.py) already entered alt-screen.
printf '\e[?1049h\e[?25l'

cd "$(dirname "$0")/../.."

# When launched from the prompt_toolkit launcher, LAUNCHER_COLS/ROWS carry
# the true terminal dimensions. Their presence selects the pre-attach
# layout build path; absence (--no-menu, Windows shortcut) falls back to
# the post-attach hook described in ADR 0041.
PRE_ATTACH_BUILD=0
if [ -n "${LAUNCHER_COLS:-}" ] && [ -n "${LAUNCHER_ROWS:-}" ]; then
    PRE_ATTACH_BUILD=1
fi

# ---------------------------------------------------------------------------
# 0. One-shot migration: v0.6.x runtime files at bridge/ root → bridge/runtime/
# ---------------------------------------------------------------------------
mkdir -p bridge/runtime
for f in bridge/*.state bridge/*.cache bridge/*.conf bridge/.[a-zA-Z]*; do
    [ -e "$f" ] || continue
    mv "$f" bridge/runtime/ 2>/dev/null || true
done
[ -d bridge/.update_preserve ] && mv bridge/.update_preserve bridge/runtime/

# ttpp/sessions/ → ttpp/profiles/ (ADR 0048)
if [ -d ttpp/sessions ] && [ ! -d ttpp/profiles ]; then
    mv ttpp/sessions ttpp/profiles
fi

# Clear any stale sentinels left by a crash before doing anything else.
rm -f bridge/runtime/.return_to_menu
rm -f bridge/runtime/.popup_open
rm -f bridge/runtime/.user_reconnecting
rm -f bridge/runtime/.layout_ready

CONF="bridge/runtime/startup.conf"

# Create startup.conf with defaults if missing
if [ ! -f "$CONF" ]; then
    printf 'connection_mode=mmapper\nshow_status=1\nshow_comm=1\nshow_ui=1\nshow_dev=0\nshow_pane_dividers=1\nprofile=default\n' > "$CONF"
fi
source "$CONF"

# ---------------------------------------------------------------------------
# 1. Dirs, permissions, log reset
# ---------------------------------------------------------------------------
mkdir -p bridge/runtime logs

chmod +x bridge/layout/apply_layout.sh
chmod +x bridge/launcher/open_pane.sh
chmod +x bridge/layout/focus_input.sh
chmod +x bridge/layout/toggle_pane.sh
chmod +x bridge/layout/equalize_right_column.sh
chmod +x bridge/services/read_version.sh
chmod +x bridge/launcher/build_initial_layout.sh
chmod +x bridge/launcher/wait_for_layout.sh
chmod +x bridge/layout/detect_terminal_bg.sh
chmod +x bridge/layout/apply_border_style.sh

touch logs/debug.log logs/ui.log
> logs/debug.log
> logs/ui.log

# Probe the host terminal background via OSC 11 before tmux owns /dev/tty.
# Result is persisted to layout.conf and consumed by apply_border_style.sh
# so the inter-pane separator row blends into whatever theme the user runs.
# Bounded ~0.3s read timeout — never blocks startup if the terminal does
# not respond.
bash bridge/layout/detect_terminal_bg.sh

# ---------------------------------------------------------------------------
# 2. Kill any old session and create a fresh one
# ---------------------------------------------------------------------------
tmux kill-session -t mume 2>/dev/null || true

if [ "$PRE_ATTACH_BUILD" -eq 1 ]; then
    tmux new-session -d -x "$LAUNCHER_COLS" -y "$LAUNCHER_ROWS" \
        -s mume -n cockpit \
        "bash $HOME/MUME/bridge/launcher/wait_for_layout.sh"
else
    tmux new-session -d -s mume -n cockpit \
        "bash $HOME/MUME/bridge/launcher/wait_for_layout.sh"
fi
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
  "#{?#{==:#{pane_title},status},#[fg=colour235] Character #[default],#{?#{==:#{pane_title},buffs},#[fg=colour235] Buffs #[default],#{?#{==:#{pane_title},group},#[fg=colour235] Group #[default],#{?#{==:#{pane_title},comm},#[fg=colour235] Communication #[default],#{?#{==:#{pane_title},ui},#[fg=colour235] UI #[default],#{?#{==:#{pane_title},dev},#[fg=colour235] Dev #[default],}}}}}}"

# ---------------------------------------------------------------------------
# 3. Register layout hooks
# ---------------------------------------------------------------------------
tmux set-hook -t mume window-resized \
    "run-shell 'bash $HOME/MUME/bridge/layout/on_window_resize.sh'"
tmux bind-key -n MouseDragEnd1Border \
    "run-shell '$HOME/MUME/bridge/layout/on_pane_resize.sh' ; run-shell '$HOME/MUME/bridge/layout/focus_input.sh --sweep'"
tmux bind-key -n MouseDragEnd1Status      "run-shell '$HOME/MUME/bridge/layout/focus_input.sh --sweep'"
tmux bind-key -n MouseDragEnd1StatusLeft  "run-shell '$HOME/MUME/bridge/layout/focus_input.sh --sweep'"
tmux bind-key -n MouseDragEnd1StatusRight "run-shell '$HOME/MUME/bridge/layout/focus_input.sh --sweep'"

# Fast escape disambiguation so ESC feels instant.
tmux set-option -s escape-time 10

# ESC opens the in-game popup menu from any pane.
tmux bind-key -T root Escape display-popup -E \
    -w 80% -h 80% -x C -y C \
    "bash $HOME/MUME/bridge/launcher/ingame_menu.sh"

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
        'run-shell $HOME/MUME/bridge/layout/focus_input.sh'"

# Start ping monitor. Guarded against double-starts; self-terminates when
# tmux:mume dies.
bash "$HOME/MUME/bridge/services/ping_monitor.sh" \
    </dev/null >/dev/null 2>&1 &
disown

# ---------------------------------------------------------------------------
# 4. Label pane 0; register one-shot layout hook; attach.
# ---------------------------------------------------------------------------
tmux select-pane -t mume:cockpit.0 -T "MUME"
sleep 0.2 && tmux select-pane -t mume:cockpit.0 -T "MUME" &

# build_initial_layout.sh splits panes, then touches .layout_ready so
# wait_for_layout.sh unblocks and hands off to tt++.
#
# Pre-attach build (launcher path): dimensions came in via env vars, the
# session was created with explicit -x/-y, so we can build synchronously
# against the detached session and attach to a fully-built cockpit.
#
# Post-attach build (--no-menu, Windows shortcut): no reliable
# dimensions yet — defer to the first client-attached event so tmux can
# read the true window size. See ADR 0041.
if [ "$PRE_ATTACH_BUILD" -eq 1 ]; then
    bash "$HOME/MUME/bridge/launcher/build_initial_layout.sh"
else
    tmux set-hook -t mume client-attached \
        "run-shell 'bash $HOME/MUME/bridge/launcher/build_initial_layout.sh'"
fi

tmux attach -t mume

# Resumes here when the session dies or the user detaches.
# Check for the return-to-menu sentinel written by ingame_menu.sh before
# firing cp -e; if set, exec back into the launcher (no extra bash frame).
if [ -f bridge/runtime/.return_to_menu ]; then
    rm -f bridge/runtime/.return_to_menu
    printf '\e[?1049h\e[?25l'
    exec bash bridge/launcher/launcher.sh
fi
# No sentinel → fall through to shell cleanly.
