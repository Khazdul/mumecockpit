#!/usr/bin/env bash
# bridge/version_check.sh — queries GitHub for the latest release tag and caches it.
# Usage: bash bridge/version_check.sh [--force]
# Writes bridge/version.cache atomically (temp-file + rename) with a 6h TTL.
# Silent on all error paths; never blocks the caller.

set -u

cd "$(dirname "$0")/.."

CACHE="bridge/version.cache"
REPO="Khazdul/mumecockpit"
TTL=21600

# --- Read current version ---
[ ! -f "VERSION" ] && exit 0
current=$(tr -d '[:space:]' < VERSION 2>/dev/null)
[ -z "$current" ] && exit 0

# --- Check cache freshness (skip unless --force) ---
if [ "${1:-}" != "--force" ] && [ -f "$CACHE" ]; then
    checked_at=""
    while IFS='=' read -r k v; do
        [ "$k" = "checked_at" ] && checked_at="$v"
    done < "$CACHE"
    if [ -n "$checked_at" ]; then
        now=$(date +%s)
        age=$(( now - checked_at ))
        [ "$age" -lt "$TTL" ] && exit 0
    fi
fi

# --- Query GitHub ---
latest=""

response=$(curl -fsS --max-time 3 \
    "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null) || true

if [ -n "$response" ]; then
    latest=$(printf '%s' "$response" \
        | grep -m1 '"tag_name"' \
        | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
    [ "$latest" = "null" ] && latest=""
fi

[ -z "$latest" ] && exit 0

# --- Write cache atomically ---
now=$(date +%s)
tmp="${CACHE}.$$"
printf 'latest=%s\nchecked_at=%s\n' "$latest" "$now" > "$tmp" 2>/dev/null || exit 0
mv "$tmp" "$CACHE" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; exit 0; }
