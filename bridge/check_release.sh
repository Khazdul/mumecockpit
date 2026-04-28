#!/usr/bin/env bash
# bridge/check_release.sh — pre-tag sanity check: VERSION must match the intended tag.
# Usage: bash bridge/check_release.sh vX.Y.Z
# Exit codes: 0=match (safe to tag), 1=mismatch or missing VERSION, 2=bad usage.

set -u

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
    echo "Usage: bash bridge/check_release.sh vX.Y.Z" >&2
    exit 2
fi

INTENDED_TAG="$1"
STRIPPED_TAG="${INTENDED_TAG#v}"

if [ ! -f "VERSION" ]; then
    echo "VERSION is missing or empty." >&2
    exit 1
fi

CURRENT=$(tr -d '[:space:]' < VERSION 2>/dev/null || echo "")
if [ -z "$CURRENT" ]; then
    echo "VERSION is missing or empty." >&2
    exit 1
fi

if [ "$CURRENT" = "$STRIPPED_TAG" ]; then
    echo "VERSION matches ${INTENDED_TAG}. Safe to tag."
    exit 0
else
    echo "VERSION says ${CURRENT} but tag would be ${INTENDED_TAG}. Bump VERSION first." >&2
    exit 1
fi
