#!/usr/bin/env bash
# bridge/launcher/launcher.sh — thin wrapper around launcher.py.
# Called by start.sh, the return-to-menu chain in tmux_start.sh, the Windows
# shortcut target, and the update flow's restart path.
# See bridge/launcher/launcher.py and docs/launcher.md.

cd "$(dirname "$0")/../.."

exec python3 "$(dirname "$0")/launcher.py" "$@"
