#!/usr/bin/env bash
# bridge/release/update.sh — safe self-update runner for the MUME cockpit.
# Usage: bash bridge/release/update.sh
# Exit codes: 0=updated, 10=no update, 20=dev checkout, 21=dirty tree,
#             22=ahead of latest release tag, 30=git failure.
# Checks out the latest release tag named in bridge/runtime/version.cache.
# Clients end up on detached HEAD — correct for a stable install.
# All output is a single human-friendly line; caller renders it verbatim.
# User-created files in ttpp/profiles/ and lua/scripts/ are preserved
# across the reset; see docs/bridge-services.md for details.

set -u

cd "$(dirname "$0")/../.."

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
if [ ! -f "bridge/runtime/version.cache" ]; then
    echo "Already up to date."
    exit 10
fi
latest=""
while IFS='=' read -r k v; do
    [ "$k" = "latest" ] && latest="$v"
done < "bridge/runtime/version.cache"
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
# ttpp/profiles/ and lua/scripts/ are excluded — auto-save writes there normally.
if ! git diff --quiet -- ':(exclude)ttpp/profiles/*' \
                         ':(exclude)lua/scripts/*'; then
    echo "Uncommitted local changes outside user data directories. Update refuses to overwrite them. Commit or stash first."
    exit 21
fi
if ! git diff --cached --quiet -- ':(exclude)ttpp/profiles/*' \
                                   ':(exclude)lua/scripts/*'; then
    echo "Staged local changes outside user data directories. Update refuses to overwrite them. Commit or stash first."
    exit 21
fi

# Untracked files: ignore the two user-data dirs
untracked=$(git ls-files --others --exclude-standard \
            | grep -v -E '^(ttpp/profiles|lua/scripts)/' || true)
if [ -n "$untracked" ]; then
    echo "Untracked files present outside user data directories. Update refuses to overwrite them. Commit, stash, or delete first."
    exit 21
fi

# Step 4c: local commits ahead of the latest release tag
LATEST_TAG="$latest"
git fetch --tags --quiet 2>/dev/null || {
    echo "git fetch failed (network?)."
    exit 30
}
AHEAD=$(git rev-list --count "refs/tags/$LATEST_TAG"..HEAD 2>/dev/null || echo "0")
if [ "${AHEAD:-0}" -gt 0 ]; then
    echo "Local commits ahead of the latest release tag. Update refuses to discard them. Push or reset manually."
    exit 22
fi

# Step 4.5: snapshot user-created files before the reset
_UPDATE_OK=0
trap '
    if [ "$_UPDATE_OK" -eq 0 ] && [ -d "bridge/runtime/.update_preserve" ]; then
        echo "Update interrupted. Preserved user files are in bridge/runtime/.update_preserve/. Restore manually if needed." >&2
    fi
' EXIT

PRESERVE_DIR="bridge/runtime/.update_preserve"
rm -rf "$PRESERVE_DIR"

for dir in ttpp/profiles lua/scripts; do
    [ -d "$dir" ] || continue
    for f in "$dir"/*; do
        [ -f "$f" ] || continue
        relpath="$f"
        if [ "$relpath" = "ttpp/profiles/default.tin" ]; then
            mkdir -p "$PRESERVE_DIR/$(dirname "$relpath")"
            cp -p "$f" "$PRESERVE_DIR/$relpath"
            continue
        fi
        if ! git cat-file -e "refs/tags/$LATEST_TAG:$relpath" 2>/dev/null; then
            mkdir -p "$PRESERVE_DIR/$(dirname "$relpath")"
            cp -p "$f" "$PRESERVE_DIR/$relpath"
        fi
    done
done

# Step 5: perform update — check out the release tag (detached HEAD is correct)
git -c advice.detachedHead=false checkout --quiet "refs/tags/$LATEST_TAG" || { echo "git checkout failed."; exit 30; }
git reset --hard "refs/tags/$LATEST_TAG" --quiet || { echo "git reset failed."; exit 30; }

# Restore preserved user files
if [ -d "$PRESERVE_DIR" ]; then
    cp -rp "$PRESERVE_DIR"/. .
    rm -rf "$PRESERVE_DIR"
fi

# Step 6: success
_UPDATE_OK=1
NEW_VERSION=$(tr -d '[:space:]' < VERSION 2>/dev/null || echo "?")
echo "Updated to v${NEW_VERSION#v}."
exit 0
