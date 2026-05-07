#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

PASSED=0
FAILED=0
SKIPPED=0
FAILURES=()

echo "bridge/smoke.sh — syntax checks"
echo ""

# --- helpers ---

pass() { echo "[PASS] $1"; (( PASSED++ )); }
fail() { echo "[FAIL] $1"; (( FAILED++ )); FAILURES+=("$1"); }
skip() { echo "[SKIP] $1"; (( SKIPPED++ )); }

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

source_err=$(bash -c 'source bridge/menu_render.sh' 2>&1)
source_exit=$?
if [ $source_exit -ne 0 ] || [ -n "$source_err" ]; then
    fail "menu_render.sh sources cleanly"
    [ -n "$source_err" ] && echo "       $source_err"
else
    pass "menu_render.sh sources cleanly"
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
