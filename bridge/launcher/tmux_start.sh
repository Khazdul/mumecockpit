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

# Stamp this cockpit launch. The in-game popup gates exit-rating on this so
# only a run that started during the current session can be rated; a stale
# run from a prior session is never offered. Refreshed on every "Enter MUME"
# (both menu and --no-menu paths funnel through here). Runtime file → gitignored.
date +%s > bridge/runtime/.session_start

# Regenerate bridge/runtime/core_aliases.list — the runtime snapshot of
# names registered by ttpp/main.tin + ttpp/core/*.tin that the profile
# editor's save path uses to strip shadowing aliases (ADR 0115 follow-up).
# Fail open: errors print to stderr but don't abort the cockpit start.
python3 bridge/launcher/core_aliases.py 2>&1 || true

CONF="bridge/runtime/startup.conf"
CONF_TEMPLATE="bridge/launcher/templates/startup.conf"

# Seed startup.conf from the shipped template on a fresh install. Single
# source of truth for fresh-install defaults (ADR 0101); the
# ${show_*:-N} fallback guards in build_initial_layout.sh stay as the
# safety net for upgrades that pre-date a given key.
if [ ! -f "$CONF" ]; then
    if [ -f "$CONF_TEMPLATE" ]; then
        cp "$CONF_TEMPLATE" "$CONF"
    else
        mkdir -p logs
        echo "[tmux_start] startup.conf template missing at $CONF_TEMPLATE; falling back to in-script guards" >> logs/debug.log
    fi
fi
[ -f "$CONF" ] && source "$CONF"

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
chmod +x bridge/layout/apply_border_style.sh

touch logs/debug.log logs/ui.log
> logs/debug.log
> logs/ui.log

# Host terminal background detection lives in launcher.py (OSC 11 over the
# launcher's cooked tty, before prompt_toolkit takes over). The launcher
# writes terminal_bg=<hex> into layout.conf; apply_border_style.sh reads it
# below. On the --no-menu / -d / -u path the launcher is skipped, no value
# is written, and apply_border_style.sh falls back to fg=default bg=default.

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
  "#{?#{==:#{pane_title},status},#[fg=colour235] Character #[default],#{?#{==:#{pane_title},timers},#[fg=colour235] Timers #[default],#{?#{==:#{pane_title},group},#[fg=colour235] Group #[default],#{?#{==:#{pane_title},comm},#[fg=colour235] Communication #[default],#{?#{==:#{pane_title},ui},#[fg=colour235] UI #[default],#{?#{==:#{pane_title},dev},#[fg=colour235] Dev #[default],}}}}}}"

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

# ESC is context-sensitive on the game pane (the only raw tt++ pane, whose
# scrollback is tmux copy-mode):
#   - game pane scrolled (in copy-mode) → exit the scroll. The existing
#     pane-mode-changed hook fires on copy-mode exit and refocuses input, so
#     no explicit refocus is added here (it would be a duplicate).
#   - otherwise → open the in-game popup menu, unchanged.
# Consequence: while scrolled, the first Escape exits the scroll and a second
# Escape opens the popup.
tmux bind-key -T root Escape if-shell -F -t mume:cockpit.0 '#{pane_in_mode}' \
    "send-keys -t mume:cockpit.0 -X cancel" \
    "display-popup -E -w 80% -h 80% -x C -y C -S fg=#008787 'bash $HOME/MUME/bridge/launcher/ingame_menu.sh'"

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
#
# For the game pane (pane_title == MUME) — the only raw tt++ pane, whose
# scrollback is tmux copy-mode — run the stock wheel action and then refocus
# the input pane, so wheel scroll never steals focus to tt++ (typed letters
# would otherwise land in copy-mode and raise the "(goto line)" prompt). The
# refocus runs on every tick: idempotent and harmless at the live tail. Every
# other pane (status no-op, prompt_toolkit panes) keeps the stock behaviour
# unchanged — they handle the wheel internally and never enter copy-mode.
STOCK_WHEEL_UP='if-shell -F "#{||:#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } { copy-mode -e }'
STOCK_WHEEL_DOWN='if-shell -F "#{||:#{pane_in_mode},#{mouse_any_flag}}" { send-keys -M } {}'
REFOCUS_IF_MUME="if-shell -F '#{==:#{pane_title},MUME}' 'run-shell $HOME/MUME/bridge/layout/focus_input.sh'"
tmux bind-key -n WheelUpPane   "if-shell -F '#{==:#{pane_title},status}' '' { $STOCK_WHEEL_UP ; $REFOCUS_IF_MUME }"
tmux bind-key -n WheelDownPane "if-shell -F '#{==:#{pane_title},status}' '' { $STOCK_WHEEL_DOWN ; $REFOCUS_IF_MUME }"

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
