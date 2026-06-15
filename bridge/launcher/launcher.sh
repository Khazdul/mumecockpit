#!/usr/bin/env bash
# bridge/launcher/launcher.sh — thin wrapper around launcher.py.
# Called by start.sh, the return-to-menu chain in tmux_start.sh, the Windows
# shortcut target, and the update flow's restart path.
# See bridge/launcher/launcher.py and docs/launcher.md.

cd "$(dirname "$0")/../.."

# Seed the bundled khazdul profile from its template when absent. Runs on
# every launcher entry — including update.sh's restart, which re-execs this
# script (not start.sh) — so existing users receive it after updating.
# Idempotent: never overwrites an existing copy, even an edited one.
# Mirrors start.sh's blank_profile → default.tin seed (ADR 0042).
if [ ! -f ttpp/profiles/khazdul.tin ] && [ -f bridge/launcher/templates/khazdul.tin ]; then
    mkdir -p ttpp/profiles
    cp bridge/launcher/templates/khazdul.tin ttpp/profiles/khazdul.tin
fi

exec python3 "$(dirname "$0")/launcher.py" "$@"
