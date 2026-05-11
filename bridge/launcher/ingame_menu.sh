#!/usr/bin/env bash
# bridge/launcher/ingame_menu.sh — thin wrapper around ingame_menu.py.
# Launched via: tmux display-popup -E -w 80% -h 80% -x C -y C "bash .../ingame_menu.sh"
# Do NOT invoke directly from outside a tmux popup context.
# See bridge/launcher/ingame_menu.py and docs/popup-menu.md.

cd "$(dirname "$0")/../.."

exec python3 "$(dirname "$0")/ingame_menu.py" "$@"
