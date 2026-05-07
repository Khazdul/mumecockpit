#!/usr/bin/env bash
# bridge/smoke.sh — source-tree smoke checks (syntax + ADR invariants).
#
# Run manually:
#   bash bridge/smoke.sh
#
# Optional pre-commit hook (opt-in, not auto-installed):
#   ln -s ../../bridge/smoke.sh .git/hooks/pre-commit
#
# Smoke is source-only. It assumes a fresh git checkout and does not
# touch runtime artefacts (logs/, data/, bridge/*.state, etc.).
set -u

cd "$(dirname "$0")/.."

PASSED=0
FAILED=0
SKIPPED=0
FAILURES=()

echo "bridge/smoke.sh — smoke checks"
echo ""

# --- helpers ---

pass() { echo "[PASS] $1"; (( PASSED++ )); }
fail() { echo "[FAIL] $1"; (( FAILED++ )); FAILURES+=("$1"); }
skip() { echo "[SKIP] $1"; (( SKIPPED++ )); }

# --- Syntax ---

echo "Syntax"

# --- check 1: bash syntax ---

bash_files=()
while IFS= read -r f; do bash_files+=("$f"); done < <(
    find bridge install -name "*.sh" 2>/dev/null
    [ -f start.sh ] && echo "start.sh"
)

bash_errors=()
for f in "${bash_files[@]}"; do
    err=$(bash -n "$f" 2>&1) || bash_errors+=("       $f: $err")
done

if (( ${#bash_errors[@]} > 0 )); then
    fail "bash syntax: ${#bash_errors[@]} of ${#bash_files[@]} files"
    printf '%s\n' "${bash_errors[@]}"
else
    pass "bash syntax: ${#bash_files[@]} files"
fi

# --- check 2: lua syntax ---

luac_bin=$(command -v luac 2>/dev/null || command -v luac5.4 2>/dev/null || true)

if [ -z "$luac_bin" ]; then
    skip "lua syntax: luac not found"
else
    lua_files=()
    while IFS= read -r f; do lua_files+=("$f"); done < <(find lua -name "*.lua" 2>/dev/null)

    lua_errors=()
    for f in "${lua_files[@]}"; do
        err=$("$luac_bin" -p "$f" 2>&1) || lua_errors+=("       $err")
    done

    if (( ${#lua_errors[@]} > 0 )); then
        fail "lua syntax: ${#lua_errors[@]} of ${#lua_files[@]} files"
        printf '%s\n' "${lua_errors[@]}"
    else
        pass "lua syntax: ${#lua_files[@]} files"
    fi
fi

# --- check 3: python syntax ---

if ! command -v python3 &>/dev/null; then
    skip "python syntax: python3 not found"
else
    py_files=()
    while IFS= read -r f; do py_files+=("$f"); done < <(find bridge -name "*.py" -not -path "*/__pycache__/*" 2>/dev/null)

    py_errors=()
    for f in "${py_files[@]}"; do
        err=$(python3 -m py_compile "$f" 2>&1) || py_errors+=("       $f: $err")
    done

    if (( ${#py_errors[@]} > 0 )); then
        fail "python syntax: ${#py_errors[@]} of ${#py_files[@]} files"
        printf '%s\n' "${py_errors[@]}"
    else
        pass "python syntax: ${#py_files[@]} files"
    fi
fi

# --- check 4: VERSION present and non-empty ---

if [ -f VERSION ] && [ -n "$(tr -d '[:space:]' < VERSION)" ]; then
    pass "VERSION present and non-empty"
else
    fail "VERSION present and non-empty"
fi

# --- check 5: core files present ---

if [ -f ttpp/main.tin ] && [ -f lua/brain.lua ]; then
    pass "core files present (ttpp/main.tin, lua/brain.lua)"
else
    fail "core files present (ttpp/main.tin, lua/brain.lua)"
fi

# --- check 6: menu_render.sh sources cleanly ---

source_err=$(bash -c 'source bridge/launcher/menu_render.sh' 2>&1)
source_exit=$?
if [ $source_exit -ne 0 ] || [ -n "$source_err" ]; then
    fail "menu_render.sh sources cleanly"
    [ -n "$source_err" ] && echo "       $source_err"
else
    pass "menu_render.sh sources cleanly"
fi

# --- Required files & directories ---

echo ""
echo "Required files & directories"

# --- check 7: required template and library files exist ---

required_files=(
    "bridge/launcher/templates/blank_profile.tin"
    "lua/lib/dkjson.lua"
    "start.sh"
)

missing_files=()
for f in "${required_files[@]}"; do
    [ -f "$f" ] || missing_files+=("       $f")
done

if (( ${#missing_files[@]} > 0 )); then
    fail "required template and library files"
    printf '%s\n' "${missing_files[@]}"
else
    pass "required template and library files"
fi

# --- check 8: required source directories are non-empty ---

required_dirs=(
    "bridge/launcher"
    "bridge/panes"
    "bridge/layout"
    "bridge/release"
    "bridge/services"
    "bridge/runtime"
    "lua/core"
    "lua/scripts"
    "lua/brain"
    "ttpp/core"
)

empty_dirs=()
for d in "${required_dirs[@]}"; do
    if [ ! -d "$d" ]; then
        empty_dirs+=("       $d (missing)")
    else
        count=$(find "$d" -maxdepth 1 -type f | wc -l)
        (( count == 0 )) && empty_dirs+=("       $d (empty)")
    fi
done

if (( ${#empty_dirs[@]} > 0 )); then
    fail "required source directories non-empty"
    printf '%s\n' "${empty_dirs[@]}"
else
    pass "required source directories non-empty"
fi

# --- ADR invariants ---

echo ""
echo "ADR invariants"

if ! command -v git &>/dev/null || ! git rev-parse --is-inside-work-tree &>/dev/null; then
    skip "git not available — ADR invariant checks skipped"
    (( SKIPPED += 2 ))
else
    # --- check 9: no GMCP handler wraps in lua/core/ (ADR 0046) ---

    wrap_pattern='^[[:space:]]*local[[:space:]]+[a-zA-Z_][a-zA-Z0-9_]*[[:space:]]*=[[:space:]]*gmcp\.handlers\['
    wrap_matches=()
    while IFS= read -r line; do
        wrap_matches+=("       $line")
    done < <(grep -rn --include="*.lua" -E "$wrap_pattern" lua/core/ 2>/dev/null)

    if (( ${#wrap_matches[@]} > 0 )); then
        fail "no GMCP handler wraps in lua/core/ (ADR 0046)"
        printf '%s\n' "${wrap_matches[@]}"
    else
        pass "no GMCP handler wraps in lua/core/ (ADR 0046)"
    fi

    # --- check 10: ttpp/sessions/default.tin not tracked (ADR 0042) ---

    tracked_default=$(git ls-files ttpp/sessions/default.tin 2>/dev/null)
    if [ -n "$tracked_default" ]; then
        fail "default.tin not tracked (ADR 0042)"
    else
        pass "default.tin not tracked (ADR 0042)"
    fi

    # --- check 11: runtime artefacts not tracked ---

    tracked_artefacts=$(git ls-files 2>/dev/null | grep -E '\.(state|cache)$|^logs/.*\.log$|^bridge/.*\.conf$' || true)
    if [ -n "$tracked_artefacts" ]; then
        fail "runtime artefacts not tracked"
        while IFS= read -r line; do
            echo "       $line"
        done <<< "$tracked_artefacts"
    else
        pass "runtime artefacts not tracked"
    fi
fi

# --- Format ---

echo ""
echo "Format"

# --- check 12: VERSION is strict semver ---

version=$(tr -d '[:space:]' < VERSION 2>/dev/null || true)
if [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    pass "VERSION is semver"
else
    fail "VERSION is semver"
fi

# --- summary ---

total=$(( PASSED + FAILED + SKIPPED ))
echo ""
if (( FAILED == 0 )); then
    echo "${PASSED}/${total} checks passed."
else
    echo "${PASSED}/${total} checks passed (${FAILED} failed)."
fi

(( FAILED == 0 ))
