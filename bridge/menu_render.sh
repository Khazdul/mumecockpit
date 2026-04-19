#!/bin/bash
# bridge/menu_render.sh — terminal render + input helpers for the startup menu.
# Sourced by bridge/launcher.sh; designed for reuse by bridge/ingame_menu.sh (Phase 3).
# Do NOT execute directly.

# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------
_MR_RESET='\e[0m'
_MR_BOLD='\e[1m'
_MR_DIM='\e[2m'
_MR_CYAN='\e[1;36m'
_MR_WHITE='\e[1;97m'
_MR_YELLOW='\e[1;33m'
_MR_GREY='\e[2;37m'
_MR_ITALIC_GREY='\e[3;2;37m'
_MR_TEAL='\e[1;38;5;80m'   # teal #26C6DA (256-colour) for script alias headings
_MR_DESC='\e[2;37m'         # dim grey for description / hint text
_MR_ERR='\e[1;31m'          # bright red for errors

# ---------------------------------------------------------------------------
# render_frame
# Read a full frame from stdin and write it without flicker.
# Each line is written followed by \e[K (clear to end of line) so shorter
# lines fully erase previous wider content. \e[J clears anything below
# the new frame. No \e[2J — the terminal never sees a blank intermediate
# frame, so there is no visible flash.
# ---------------------------------------------------------------------------
render_frame() {
    local -a lines
    mapfile -t lines  # reads stdin; -t strips per-line trailing newlines
    local i n=${#lines[@]}
    printf '\e[H'
    for (( i = 0; i < n; i++ )); do
        if (( i < n - 1 )); then
            printf '%s\e[K\n' "${lines[i]}"
        else
            printf '%s\e[K'   "${lines[i]}"  # no newline on last line → no scroll
        fi
    done
    printf '\e[J'
}

# ---------------------------------------------------------------------------
# draw_ascii_title
# Prints the MUME block-letter banner (6 rows) immediately followed by the
# COCKPIT block-letter banner (3 rows), both centered and in the same cyan.
# ---------------------------------------------------------------------------
draw_ascii_title() {
    local cols; cols=$(tput cols 2>/dev/null || echo 80)

    # ANSI Shadow font — MUME
    local mume_lines=(
        '███╗   ███╗██╗   ██╗███╗   ███╗███████╗'
        '████╗ ████║██║   ██║████╗ ████║██╔════╝'
        '██╔████╔██║██║   ██║██╔████╔██║█████╗  '
        '██║╚██╔╝██║██║   ██║██║╚██╔╝██║██╔══╝  '
        '██║ ╚═╝ ██║╚██████╔╝██║ ╚═╝ ██║███████╗'
        '╚═╝     ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝'
    )

    local line vw pad
    printf '\n'
    for line in "${mume_lines[@]}"; do
        vw=$(printf '%s' "$line" | wc -m)
        pad=$(( (cols - vw) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
        printf "%${pad}s${_MR_CYAN}%s${_MR_RESET}\n" "" "$line"
    done

    local cockpit_lines=(
        '██ ███ ██ █ █ ██ █ ███'
        '█  █ █ █  ██  ██ █  █ '
        '██ ███ ██ █ █ █  █  █ '
    )
    for line in "${cockpit_lines[@]}"; do
        vw=$(printf '%s' "$line" | wc -m)
        pad=$(( (cols - vw) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
        printf "%${pad}s${_MR_CYAN}%s${_MR_RESET}\n" "" "$line"
    done
    printf '\n'
}

# ---------------------------------------------------------------------------
# draw_menu_item <label> <is_active>
# Prints one centered menu row.
# Active  → bright bold white  "<< label >>"
# Inactive→ dim               "   label   "  (same visual width)
# ---------------------------------------------------------------------------
draw_menu_item() {
    local label="$1" is_active="${2:-0}"
    local cols; cols=$(tput cols 2>/dev/null || echo 80)

    local prefix suffix
    if [ "$is_active" -eq 1 ]; then
        prefix="<< "
        suffix=" >>"
    else
        prefix="   "
        suffix="   "
    fi

    local full="${prefix}${label}${suffix}"
    local vw=${#full}
    local pad=$(( (cols - vw) / 2 ))
    [ "$pad" -lt 0 ] && pad=0

    if [ "$is_active" -eq 1 ]; then
        printf "%${pad}s${_MR_WHITE}%s%s%s${_MR_RESET}\n" "" "$prefix" "$label" "$suffix"
    else
        printf "%${pad}s${_MR_GREY}%s%s%s${_MR_RESET}\n" "" "$prefix" "$label" "$suffix"
    fi
}

# ---------------------------------------------------------------------------
# draw_layout_mockup <show_ui> <show_dev> <show_input>
# Prints a small ASCII wireframe of the tmux cockpit layout, centered.
# Right column inner width = 6, left column inner width = 15. Total = 24 wide.
# Followed by a 4-line pane description block.
# ---------------------------------------------------------------------------
draw_layout_mockup() {
    local show_ui="${1:-1}" show_dev="${2:-0}" show_input="${3:-1}" show_desc="${4:-1}"
    local has_right=0
    ( [ "$show_ui" -eq 1 ] || [ "$show_dev" -eq 1 ] ) && has_right=1

    local cols; cols=$(tput cols 2>/dev/null || echo 80)
    local indent=$(( (cols - 24) / 2 ))
    [ "$indent" -lt 0 ] && indent=0
    local p; printf -v p "%${indent}s" ""

    printf "${_MR_CYAN}"

    if [ "$show_ui" -eq 1 ] && [ "$show_dev" -eq 1 ] && [ "$show_input" -eq 1 ]; then
        # All on — staggered separators matching actual tmux geometry
        printf '%s┌───────────────┬──────┐\n' "$p"
        printf '%s│               │  UI  │\n' "$p"
        printf '%s│     GAME      │      │\n' "$p"
        printf '%s│               ├──────┤\n' "$p"
        printf '%s├───────────────┤      │\n' "$p"
        printf '%s│    INPUT      │ DEV  │\n' "$p"
        printf '%s└───────────────┴──────┘\n' "$p"

    elif [ "$show_ui" -eq 1 ] && [ "$show_dev" -eq 1 ]; then
        # UI + DEV, no INPUT
        printf '%s┌───────────────┬──────┐\n' "$p"
        printf '%s│               │  UI  │\n' "$p"
        printf '%s│     GAME      ├──────┤\n' "$p"
        printf '%s│               │ DEV  │\n' "$p"
        printf '%s└───────────────┴──────┘\n' "$p"

    elif [ "$has_right" -eq 1 ] && [ "$show_input" -eq 1 ]; then
        # Single right pane + INPUT
        local rl="      "
        [ "$show_ui"  -eq 1 ] && rl="  UI  "
        [ "$show_dev" -eq 1 ] && rl=" DEV  "
        printf '%s┌───────────────┬──────┐\n' "$p"
        printf '%s│               │      │\n' "$p"
        printf '%s│     GAME      │%s│\n' "$p" "$rl"
        printf '%s│               │      │\n' "$p"
        printf '%s├───────────────┤      │\n' "$p"
        printf '%s│    INPUT      │      │\n' "$p"
        printf '%s└───────────────┴──────┘\n' "$p"

    elif [ "$has_right" -eq 1 ]; then
        # Single right pane, no INPUT
        local rl="      "
        [ "$show_ui"  -eq 1 ] && rl="  UI  "
        [ "$show_dev" -eq 1 ] && rl=" DEV  "
        printf '%s┌───────────────┬──────┐\n' "$p"
        printf '%s│               │      │\n' "$p"
        printf '%s│     GAME      │%s│\n' "$p" "$rl"
        printf '%s│               │      │\n' "$p"
        printf '%s└───────────────┴──────┘\n' "$p"

    elif [ "$show_input" -eq 1 ]; then
        # No right column, with INPUT
        printf '%s┌──────────────────────┐\n' "$p"
        printf '%s│                      │\n' "$p"
        printf '%s│        GAME          │\n' "$p"
        printf '%s│                      │\n' "$p"
        printf '%s├──────────────────────┤\n' "$p"
        printf '%s│       INPUT          │\n' "$p"
        printf '%s└──────────────────────┘\n' "$p"

    else
        # GAME only
        printf '%s┌──────────────────────┐\n' "$p"
        printf '%s│                      │\n' "$p"
        printf '%s│        GAME          │\n' "$p"
        printf '%s│                      │\n' "$p"
        printf '%s└──────────────────────┘\n' "$p"
    fi

    printf "${_MR_RESET}"

    if [ "$show_desc" -eq 1 ]; then
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — MUD window\n"             "$p" "GAME"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Fixed input panel\n"      "$p" "INPUT"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Game-related messages\n"  "$p" "UI"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Debug log (developers)\n" "$p" "DEV"
    fi
}

# ---------------------------------------------------------------------------
# wrap_text <width>
# Greedy word-wrap to <width> columns, reading paragraphs from stdin.
# Blank lines separate paragraphs and are preserved in output.
# Uses LC_ALL="${_WRAP_LOCALE:-C}" so awk length() counts codepoints on UTF-8.
# ---------------------------------------------------------------------------
wrap_text() {
    local width="$1"
    LC_ALL="${_WRAP_LOCALE:-C}" awk -v w="$width" '
        BEGIN { line = "" }
        /^[[:space:]]*$/ {
            if (line != "") print line
            print ""
            line = ""
            next
        }
        {
            n = split($0, words, /[[:space:]]+/)
            for (i = 1; i <= n; i++) {
                if (words[i] == "") continue
                wl = length(words[i])
                if (line == "") {
                    line = words[i]
                } else if (length(line) + 1 + wl <= w) {
                    line = line " " words[i]
                } else {
                    print line
                    line = words[i]
                }
            }
        }
        END { if (line != "") print line }
    '
}

# ---------------------------------------------------------------------------
# read_key [timeout_seconds]
# Sets global LAST_KEY to the normalized key name.
# Returns 0 on key read, 1 on timeout or signal interrupt.
# With no argument (or empty string), blocks until a key arrives.
# Key names: UP DOWN LEFT RIGHT HOME END ENTER SPACE ESC DELETE, or raw char.
# ---------------------------------------------------------------------------
LAST_KEY=""
read_key() {
    local timeout="${1:-}"
    LAST_KEY=""
    local k="" ch2="" ch3=""

    if [ -n "$timeout" ]; then
        if ! IFS= read -rsn1 -t "$timeout" k 2>/dev/null; then
            return 1
        fi
    else
        if ! IFS= read -rsn1 k 2>/dev/null; then
            return 1   # signal interrupt or EOF
        fi
    fi

    # Enter: read -rsn1 strips newline and returns empty string
    if [[ -z "$k" ]]; then
        LAST_KEY="ENTER"
        return 0
    fi

    if [ "$k" = $'\e' ]; then
        # Peek for CSI/SS3 escape sequences (arrows, Home, End, Delete…)
        IFS= read -rsn1 -t 0.01 ch2 2>/dev/null || true
        if [ -z "$ch2" ]; then
            LAST_KEY="ESC"
            return 0
        fi
        IFS= read -rsn1 -t 0.01 ch3 2>/dev/null || true
        case "${ch2}${ch3}" in
            '[A') LAST_KEY="UP"     ;;
            '[B') LAST_KEY="DOWN"   ;;
            '[C') LAST_KEY="RIGHT"  ;;
            '[D') LAST_KEY="LEFT"   ;;
            '[H') LAST_KEY="HOME"   ;;
            '[F') LAST_KEY="END"    ;;
            'OH') LAST_KEY="HOME"   ;;   # SS3 form
            'OF') LAST_KEY="END"    ;;   # SS3 form
            '[3') # Delete: \e[3~ — consume trailing ~
                  IFS= read -rsn1 -t 0.01 2>/dev/null || true
                  LAST_KEY="DELETE" ;;
            *)    LAST_KEY="ESC"    ;;
        esac
        return 0
    fi

    # Accept both \r (0x0d) and \n (0x0a) as Enter
    case "$k" in
        $'\r'|$'\n') LAST_KEY="ENTER" ;;
        ' ')         LAST_KEY="SPACE" ;;
        *)           LAST_KEY="$k"    ;;
    esac
    return 0
}

# ---------------------------------------------------------------------------
# check_min_size
# Verifies terminal >= 80x24. Blocks with a resize prompt until satisfied.
# SIGWINCH interrupts the inner read, causing an immediate re-check.
# ---------------------------------------------------------------------------
_mr_size_ok() {
    local c l
    c=$(tput cols  2>/dev/null || echo 0)
    l=$(tput lines 2>/dev/null || echo 0)
    [ "$c" -ge 80 ] && [ "$l" -ge 24 ]
}

check_min_size() {
    _mr_size_ok && return 0

    trap ':' WINCH   # make SIGWINCH interrupt read so the loop re-checks
    while ! _mr_size_ok; do
        local c l
        c=$(tput cols  2>/dev/null || echo 0)
        l=$(tput lines 2>/dev/null || echo 0)
        {
            printf "\n${_MR_YELLOW}  Terminal too small: %dx%d${_MR_RESET}\n" "$c" "$l"
            printf "${_MR_WHITE}  Please resize to at least 80x24.${_MR_RESET}\n"
        } | render_frame
        IFS= read -rsn1 -t 2 2>/dev/null || true
    done
    trap - WINCH
}
