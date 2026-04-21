#!/bin/bash
# bridge/update.sh — safe self-update runner for the MUME cockpit.
# Usage: bash bridge/update.sh
# Exit codes: 0=updated, 10=no update, 20=dev checkout, 21=dirty tree,
#             22=ahead of origin, 30=git failure.
# All output is a single human-friendly line; caller renders it verbatim.

set -u

cd "$(dirname "$0")/.."

_strip_v() {
    local s="$1"
    echo "${s#v}"
}

# Step 2: verify git work tree
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Not a git repository."
    exit 30
fi

# Step 3: check version.cache
if [ ! -f "bridge/version.cache" ]; then
    echo "Already up to date."
    exit 10
fi
latest=""
while IFS='=' read -r k v; do
    [ "$k" = "latest" ] && latest="$v"
done < "bridge/version.cache"
if [ -z "$latest" ]; then
    echo "Already up to date."
    exit 10
fi
current=""
[ -f "VERSION" ] && current=$(tr -d '[:space:]' < VERSION 2>/dev/null || echo "")
if [ "$(_strip_v "$latest")" = "$(_strip_v "$current")" ]; then
    echo "Already up to date."
    exit 10
fi

# Step 4a: developer fingerprint check
AUTHOR_EMAIL=$(git config user.email 2>/dev/null || echo "")
if [ -n "$AUTHOR_EMAIL" ] && \
   git log --author="$AUTHOR_EMAIL" -1 --format=%H 2>/dev/null | grep -q .; then
    echo "Developer checkout detected (git user.email has authored commits here). Update disabled."
    exit 20
fi

# Step 4b: dirty working tree / untracked files
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Uncommitted local changes. Update refuses to overwrite them. Commit or stash first."
    exit 21
fi
if [ -n "$(git ls-files --others --exclude-standard)" ]; then
    echo "Untracked files present. Update refuses to overwrite them. Commit, stash, or delete first."
    exit 21
fi

# Step 4c: local commits ahead of origin/main
git fetch origin main --quiet 2>/dev/null || {
    echo "git fetch failed (network?)."
    exit 30
}
AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "0")
if [ "${AHEAD:-0}" -gt 0 ]; then
    echo "Local commits ahead of origin/main. Update refuses to discard them. Push or reset manually."
    exit 22
fi

# Step 5: perform update
git fetch origin main --tags --quiet || { echo "git fetch failed."; exit 30; }
git reset --hard origin/main --quiet || { echo "git reset failed."; exit 30; }

# Step 6: success
NEW_VERSION=$(tr -d '[:space:]' < VERSION 2>/dev/null || echo "?")
echo "Updated to v${NEW_VERSION#v}."
exit 0
