#!/bin/bash
# bridge/launcher/menu_render.sh — terminal render + input helpers for the startup menu.
# Sourced by bridge/launcher/launcher.sh; designed for reuse by bridge/launcher/ingame_menu.sh (Phase 3).
# Do NOT execute directly.

# ---------------------------------------------------------------------------
# Colour constants — semantic roles, not raw colours
# ---------------------------------------------------------------------------
_MR_RESET='\e[0m'
_MR_BOLD='\e[1m'
_MR_DIM='\e[2m'

# Titles / page banners / ASCII logo
_MR_TITLE='\e[1;36m'

# Active / focused row, emphasis text in prompts
_MR_ACTIVE='\e[1;97m'

# Inactive selectable menu rows
_MR_ITEM='\e[38;5;250m'

# Section headings inside pages (quieter than items)
_MR_SECTION='\e[38;5;244m'

# Body text (About prose, pane descriptions)
_MR_BODY='\e[38;5;245m'

# Footer / navigation hints
_MR_HINT='\e[2;38;5;240m'

# Quote text (italic) and attribution (sage green)
_MR_QUOTE='\e[3;38;5;245m'
_MR_QUOTE_ATTR='\e[38;5;108m'

# Accent — call-to-action markers, key/command highlights
_MR_ACCENT='\e[1;38;5;214m'

# Pane-description text inside layout mockup
_MR_DESC='\e[2;37m'

# Warnings / errors
_MR_YELLOW='\e[1;33m'
_MR_ERR='\e[1;31m'

# ---------------------------------------------------------------------------
# term_cols / term_lines
# Portable terminal-dimension queries. tput lies on macOS (BSD ncurses) when
# called from non-interactive subshells, returning the termcap default (80x24).
# `stty size </dev/tty` reads controlling-tty dimensions directly from the
# kernel and is accurate on both Linux and macOS. See ADR 0021.
# ---------------------------------------------------------------------------
term_cols()  { stty size </dev/tty 2>/dev/null | awk '{print $2}' || echo 80; }
term_lines() { stty size </dev/tty 2>/dev/null | awk '{print $1}' || echo 24; }

# ---------------------------------------------------------------------------
# file_mtime <path>
# Portable mtime in epoch seconds. macOS BSD stat uses `-f '%m'`,
# GNU/Linux stat uses `-c '%Y'`. Detect once via `uname -s` and
# cache the format string at source time.
if [ "$(uname -s)" = "Darwin" ]; then
    _FMT_MTIME="-f %m"
else
    _FMT_MTIME="-c %Y"
fi
file_mtime() {
    # shellcheck disable=SC2086  # word-splitting of $_FMT_MTIME is intentional
    stat $_FMT_MTIME "$1" 2>/dev/null
}

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
    local cols; cols=$(term_cols)

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
        printf "%${pad}s${_MR_TITLE}%s${_MR_RESET}\n" "" "$line"
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
        printf "%${pad}s${_MR_TITLE}%s${_MR_RESET}\n" "" "$line"
    done
    printf '\n'
}

# ---------------------------------------------------------------------------
# draw_menu_item <label> <is_active> [pad_override] [inactive_color]
# Prints one menu row.
# Active  → _MR_ACTIVE  "<< label >>"
# Inactive→ inactive_color (default _MR_ITEM)  "   label   "
# pad_override: if set, used as left-pad directly (left-aligns a group);
#               if unset, row is centred independently.
# ---------------------------------------------------------------------------
draw_menu_item() {
    local label="$1" is_active="${2:-0}" pad_override="${3:-}" inactive_color="${4:-}"
    local cols; cols=$(term_cols)
    [ -z "$inactive_color" ] && inactive_color="$_MR_ITEM"

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
    local pad
    if [ -n "$pad_override" ]; then
        pad="$pad_override"
    else
        pad=$(( (cols - vw) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
    fi

    if [ "$is_active" -eq 1 ]; then
        printf "%${pad}s${_MR_ACTIVE}%s%s%s${_MR_RESET}\n" "" "$prefix" "$label" "$suffix"
    else
        printf "%${pad}s${inactive_color}%s%s%s${_MR_RESET}\n" "" "$prefix" "$label" "$suffix"
    fi
}

# ---------------------------------------------------------------------------
# draw_layout_mockup <show_ui> <show_dev> <show_inp> [show_desc=1] [show_dividers=1] [show_status=0] [show_buffs=0] [show_group=0] [show_comm=0]
# Prints a small ASCII wireframe of the tmux cockpit layout, centered.
# Right column inner width = 6, left column inner width = 15. Total = 24 wide.
# Right-column panes are stacked top-to-bottom: status → buffs → group → comm → ui → dev.
# When show_dividers=0, box-drawing characters are replaced with spaces;
# labels and dimensions stay identical so the mockup doesn't jump on toggle.
# Followed by a description block when show_desc=1.
# ---------------------------------------------------------------------------
draw_layout_mockup() {
    local show_ui="${1:-1}" show_dev="${2:-0}" show_inp="${3:-1}" show_desc="${4:-1}" show_dividers="${5:-1}" show_status="${6:-0}" show_buffs="${7:-0}" show_group="${8:-0}" show_comm="${9:-0}"

    local cols; cols=$(term_cols)
    local indent=$(( (cols - 24) / 2 ))
    [ "$indent" -lt 0 ] && indent=0
    local p; printf -v p "%${indent}s" ""

    # Build right-column pane list in top-to-bottom order
    local -a _rc_labels=()
    [ "$show_status" -eq 1 ] && _rc_labels+=(" CHAR ")
    [ "$show_buffs"  -eq 1 ] && _rc_labels+=(" BUFFS")
    [ "$show_group"  -eq 1 ] && _rc_labels+=(" GROUP")
    [ "$show_comm"   -eq 1 ] && _rc_labels+=(" COMM ")
    [ "$show_ui"     -eq 1 ] && _rc_labels+=("  UI  ")
    [ "$show_dev"    -eq 1 ] && _rc_labels+=(" DEV  ")
    local N=${#_rc_labels[@]}

    _draw_box_lines() {
        printf "${_MR_TITLE}"
        if [ "$N" -gt 0 ] && [ "$show_inp" -eq 1 ]; then
            # Case A: right column + INPUT
            # body = max(2N-1, 5); natural fit when 2N-1 == body (N >= 3)
            local nm=$(( 2 * N - 1 ))
            local body; [ "$nm" -lt 5 ] && body=5 || body="$nm"
            local nat=$(( nm == body ? 1 : 0 ))
            # bot_start: first row of bottom right pane (= body for natural fit)
            local bs; [ "$nat" -eq 1 ] && bs="$body" || bs=$(( 2 * (N - 1) + 1 ))
            # bot_label_row: where to print the bottom pane label
            local blr; [ "$N" -eq 1 ] && blr=$(( (1 + body) / 2 )) || blr="$bs"
            # game_label_row: center of GAME area (rows 1..body)
            local glr=$(( (body - 1) / 2 ))

            printf '%s┌───────────────┬──────┐\n' "$p"
            local r lc rl
            for (( r = 1; r <= body; r++ )); do
                [ "$r" -eq "$glr" ] && lc="     GAME      " || lc="               "
                if [ "$N" -ge 2 ] && [ "$r" -le $(( 2 * (N - 1) )) ]; then
                    # Top panes and their separators
                    if (( r % 2 == 1 )); then
                        rl="${_rc_labels[$(( (r-1)/2 ))]}"
                        printf '%s│%s│%s│\n' "$p" "$lc" "$rl"
                    else
                        printf '%s│%s├──────┤\n' "$p" "$lc"
                    fi
                else
                    # Bottom pane (stretched or natural fit)
                    [ "$r" -eq "$blr" ] && rl="${_rc_labels[$((N-1))]}" || rl="      "
                    printf '%s│%s│%s│\n' "$p" "$lc" "$rl"
                fi
            done
            # Full-width INPUT row below the top container
            printf '%s├───────────────┴──────┤\n' "$p"
            printf '%s│       INPUT          │\n' "$p"
            printf '%s└──────────────────────┘\n' "$p"

        elif [ "$N" -gt 0 ]; then
            # Case B: right column, no INPUT
            # body = max(2N-1, 3); natural fit when N >= 2
            local nm=$(( 2 * N - 1 ))
            local body; [ "$nm" -lt 3 ] && body=3 || body="$nm"
            local nat=$(( nm == body ? 1 : 0 ))
            local glr=$(( (body + 1) / 2 ))
            local blr=$(( (body + 1) / 2 ))  # for N=1 stretched only

            printf '%s┌───────────────┬──────┐\n' "$p"
            local r lc rl
            for (( r = 1; r <= body; r++ )); do
                [ "$r" -eq "$glr" ] && lc="     GAME      " || lc="               "
                if [ "$nat" -eq 1 ]; then
                    if (( r % 2 == 1 )); then
                        rl="${_rc_labels[$(( (r-1)/2 ))]}"
                        printf '%s│%s│%s│\n' "$p" "$lc" "$rl"
                    else
                        printf '%s│%s├──────┤\n' "$p" "$lc"
                    fi
                else
                    # N=1 stretched: single pane fills body rows, label centered
                    [ "$r" -eq "$blr" ] && rl="${_rc_labels[0]}" || rl="      "
                    printf '%s│%s│%s│\n' "$p" "$lc" "$rl"
                fi
            done
            printf '%s└───────────────┴──────┘\n' "$p"

        elif [ "$show_inp" -eq 1 ]; then
            # Case C: no right column, INPUT only
            printf '%s┌──────────────────────┐\n' "$p"
            printf '%s│                      │\n' "$p"
            printf '%s│        GAME          │\n' "$p"
            printf '%s│                      │\n' "$p"
            printf '%s├──────────────────────┤\n' "$p"
            printf '%s│       INPUT          │\n' "$p"
            printf '%s└──────────────────────┘\n' "$p"
        else
            # Case D: no right column, no INPUT
            printf '%s┌──────────────────────┐\n' "$p"
            printf '%s│                      │\n' "$p"
            printf '%s│        GAME          │\n' "$p"
            printf '%s│                      │\n' "$p"
            printf '%s└──────────────────────┘\n' "$p"
        fi
        printf "${_MR_RESET}"
    }

    if [ "$show_dividers" -eq 1 ]; then
        _draw_box_lines
    else
        _draw_box_lines | sed 's/[┌┐└┘├┤┬┴┼─│]/ /g'
    fi

    if [ "$show_desc" -eq 1 ]; then
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — MUD window\n"             "$p" "GAME"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Fixed input panel\n"      "$p" "INPUT"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Comm channels\n"          "$p" "COMM"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Game-related messages\n"  "$p" "UI"
        printf "%s  ${_MR_DESC}%-7s${_MR_RESET}  — Character data panel\n"   "$p" "CHARACTER"
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
        function flush() { if (line != "") { print line; line = "" } }
        /^[[:space:]]*$/  { flush(); print ""; next }
        /^[[:space:]]/    { flush(); print;    next }
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
        END { flush() }
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
    c=$(term_cols)
    l=$(term_lines)
    [ "$c" -ge 80 ] && [ "$l" -ge 24 ]
}

check_min_size() {
    _mr_size_ok && return 0

    trap ':' WINCH   # make SIGWINCH interrupt read so the loop re-checks
    while ! _mr_size_ok; do
        local c l
        c=$(term_cols)
        l=$(term_lines)
        {
            printf "\n${_MR_YELLOW}  Terminal too small: %dx%d${_MR_RESET}\n" "$c" "$l"
            printf "${_MR_ACTIVE}  Please resize to at least 80x24.${_MR_RESET}\n"
        } | render_frame
        IFS= read -rsn1 -t 2 2>/dev/null || true
    done
    trap - WINCH
}
