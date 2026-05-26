#!/usr/bin/env bash
# supervisor.sh — Windows/WSLg deployment entry point.
#
# Owns the foot terminal lifecycle: launches foot fullscreen running the
# cockpit, then loops if the cockpit asks for a terminal relaunch (Phase 3).
# In Phase 1 nothing writes the sentinel, so the loop body runs exactly once.
#
# Invoked by the WSLg .desktop entry (install/mume-cockpit.desktop). Not used
# on native Linux or macOS — those platforms launch the cockpit directly via
# start.sh from the user's own terminal.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SENTINEL="$REPO_ROOT/bridge/runtime/.relaunch_terminal"

# foot inherits this env var and propagates it to the cockpit; later phases
# read it to detect a managed terminal. Export now so Phase 2 only touches
# the launcher.
export MUME_TERMINAL=foot-managed

# Clear any stale sentinel from a previous crash mid-relaunch. Mirrors how
# tmux_start.sh clears .return_to_menu — a cold start must not be mis-routed
# into "we were relaunching" mode.
mkdir -p "$REPO_ROOT/bridge/runtime"
rm -f "$SENTINEL"

while :; do
    foot -- bash "$REPO_ROOT/start.sh"

    if [ -f "$SENTINEL" ]; then
        rm -f "$SENTINEL"
        continue
    fi
    break
done
