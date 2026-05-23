#!/usr/bin/env bash
# bridge/layout/apply_border_style.sh — single authority for tmux pane border
# colour. Reads terminal_bg from bridge/runtime/layout.conf and styles the
# inter-pane separator row to match the host terminal background, so the
# divider is invisible against any theme. Falls back to black when
# terminal_bg is empty or missing — only reached on the launcher-skipped
# -d / -u / --no-menu paths; the normal flow always writes a value.
# Called from build_initial_layout.sh and from toggle_pane.sh's headers
# branch — no other script should set pane-border-style.

set -u

LAYOUT_CONF="$HOME/MUME/bridge/runtime/layout.conf"

terminal_bg=""
if [ -f "$LAYOUT_CONF" ]; then
    # shellcheck disable=SC1090
    source "$LAYOUT_CONF" 2>/dev/null || true
fi

if [[ "${terminal_bg:-}" =~ ^#[0-9a-fA-F]{6}$ ]]; then
    style="fg=${terminal_bg} bg=${terminal_bg}"
else
    style="fg=black bg=black"
fi

tmux set-option -t mume pane-border-style        "$style"
tmux set-option -t mume pane-active-border-style "$style"
