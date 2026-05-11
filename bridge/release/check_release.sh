#!/usr/bin/env bash
# bridge/release/check_release.sh — pre-tag sanity check: VERSION must match the intended tag.
# Usage: bash bridge/release/check_release.sh vX.Y.Z
# Exit codes: 0=match (safe to tag), 1=mismatch or missing VERSION, 2=bad usage.

set -u

cd "$(dirname "$0")/../.."

if [ $# -lt 1 ]; then
    echo "Usage: bash bridge/release/check_release.sh vX.Y.Z" >&2
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

if [ "$CURRENT" != "$STRIPPED_TAG" ]; then
    echo "VERSION says ${CURRENT} but tag would be ${INTENDED_TAG}. Bump VERSION first." >&2
    exit 1
fi

# #nop is not opaque to ';' — see docs/decisions/0057-nop-not-opaque-to-semicolons.md.
NOP_HITS=$(grep -nE '^[[:space:]]*#nop[[:space:]][^{].*;' $(git ls-files '*.tin') || true)
if [ -n "$NOP_HITS" ]; then
    echo "ERROR: unbraced #nop lines contain ';' — see ADR 0057" >&2
    echo "$NOP_HITS" >&2
    exit 1
fi

echo "VERSION matches ${INTENDED_TAG}. Safe to tag."
exit 0
