#!/usr/bin/env bash
# bridge/release/strip_core_collisions.sh — strip user-typed shadowing
# aliases from a profile file at save-time (ADR 0115 follow-up).
#
# Counterpart to bridge/launcher/core_aliases.py (which feeds the
# profile-editor save filter) and to sanitize_profile.sh (post-#class
# write hygiene). This script closes the remaining vector: a
# live-typed `#alias {cp} {...}` at the tt++ prompt that `#class write`
# would otherwise serialise into the profile file on the next save.
# Stripping at _save_profile post-write keeps the on-disk file clean
# and limits the override to the current session — the escape hatch
# per ADR 0115 stays intact, just without permanence.
#
# Usage:
#   strip_core_collisions.sh <profile_path>
#
# Input: bridge/runtime/core_aliases.list (one alias pattern per line,
# produced at launcher startup by core_aliases.py).
#
# Lines stripped: any line matching
#   ^#alias \{name\} \{body\}                (canonical two-arg form)
#   ^#alias \{name\} \{body\} \{priority\}   (three-arg form)
# where <name> is in the core-alias set. Multi-line alias bodies are
# out of scope — `#class write` does not emit them and hand-edits in
# that shape are left alone.
#
# Contract:
#   - Non-existent profile path: exit 0 silently (mirrors sanitize).
#   - Empty / missing core_aliases.list: exit 0 silently (fail open).
#   - No collisions found: file unchanged, no stdout, exit 0.
#   - Collisions found: file rewritten atomically (temp + rename) and
#     stdout receives two lines:
#       line 1 — decimal count
#       line 2 — comma+space-joined names
#     for `_save_profile` to format into a `system_ui` message via
#     tt++'s `#script` capture. Exit 0.
#   - I/O failure: non-zero exit via set -e.

set -euo pipefail

FILE="${1:-}"
LIST="$(dirname -- "$0")/../runtime/core_aliases.list"

[ -n "$FILE" ] || exit 0
[ -f "$FILE" ] || exit 0
[ -s "$LIST" ] || exit 0

declare -A CORE
while IFS= read -r name || [ -n "$name" ]; do
    [ -n "$name" ] || continue
    CORE["$name"]=1
done < "$LIST"

dir=$(dirname -- "$FILE")
tmp=$(mktemp "${dir}/.strip_core.XXXXXX")
trap 'rm -f "$tmp"' EXIT

stripped=()
while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^#alias[[:space:]]+\{([^}]+)\}[[:space:]]+\{ ]]; then
        name="${BASH_REMATCH[1]}"
        if [ -n "${CORE[$name]:-}" ]; then
            stripped+=("$name")
            continue
        fi
    fi
    printf '%s\n' "$line" >> "$tmp"
done < "$FILE"

if [ "${#stripped[@]}" -eq 0 ]; then
    exit 0
fi

mv -- "$tmp" "$FILE"
trap - EXIT

printf '%d\n' "${#stripped[@]}"
joined=""
for n in "${stripped[@]}"; do
    if [ -z "$joined" ]; then
        joined="$n"
    else
        joined="$joined, $n"
    fi
done
printf '%s\n' "$joined"
