#!/bin/bash
# bridge/launcher.sh — pre-tmux startup menu for the MUME cockpit.
# Called by start.sh when no bypass flags are given.
# Execs into bridge/tmux_start.sh or `tmux attach` on user selection.

cd "$(dirname "$0")/.."

CONF="bridge/startup.conf"
RENDER="bridge/menu_render.sh"

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
source "$RENDER"

# ---------------------------------------------------------------------------
# Detect UTF-8 locale for wrap_text (awk character-correct word wrap)
# ---------------------------------------------------------------------------
_WRAP_LOCALE="C"
if locale -a 2>/dev/null | grep -qF 'en_US.UTF-8'; then
    _WRAP_LOCALE="en_US.UTF-8"
elif locale -a 2>/dev/null | grep -qF 'C.UTF-8'; then
    _WRAP_LOCALE="C.UTF-8"
fi

# Alt screen + cursor: enter on start, restore on any exit path.
# exec does NOT fire EXIT trap — clear trap before each exec.
_restore_terminal() {
    printf '\e[?1007h\e[?25h\e[?1049l'
}
trap '_restore_terminal' EXIT INT TERM HUP

printf '\e[?1049h\e[?25l'
# Disable mouse reporting and alternate scroll while launcher is active.
# 1000=x10 1002=cell-motion 1003=all-motion 1006=SGR 1007=alt-scroll
printf '\e[?1000l\e[?1002l\e[?1003l\e[?1006l\e[?1007l'

# ---------------------------------------------------------------------------
# Conf — create with defaults if missing, then source
# ---------------------------------------------------------------------------
if [ ! -f "$CONF" ]; then
    printf '# Phase 1 cosmetic options — launcher display only\n'  > "$CONF"
    printf 'connection_mode=mmapper\n'                             >> "$CONF"
    printf 'show_ui=1\n'                                           >> "$CONF"
    printf 'show_dev=0\n'                                          >> "$CONF"
    printf 'show_input=1\n'                                        >> "$CONF"
    printf 'profile=default\n'                                     >> "$CONF"
fi
source "$CONF"

# Defaults for keys that may be absent from an older conf
connection_mode="${connection_mode:-mmapper}"
show_ui="${show_ui:-1}"
show_dev="${show_dev:-0}"
show_input="${show_input:-1}"
profile="${profile:-default}"

# ---------------------------------------------------------------------------
# _save_conf — write all tracked settings to startup.conf
# ---------------------------------------------------------------------------
_save_conf() {
    printf '# Phase 1 cosmetic options — launcher display only\n'  > "$CONF"
    printf 'connection_mode=%s\n' "$connection_mode"               >> "$CONF"
    printf 'show_ui=%s\n'        "$show_ui"                        >> "$CONF"
    printf 'show_dev=%s\n'       "$show_dev"                       >> "$CONF"
    printf 'show_input=%s\n'     "$show_input"                     >> "$CONF"
    printf 'profile=%s\n'        "$profile"                        >> "$CONF"
}

# One-shot migration: profile=mume → profile=default (file renamed in Phase 1 r3)
if [ "$profile" = "mume" ]; then
    profile="default"
    _save_conf
fi

# ---------------------------------------------------------------------------
# Read version once; used by draw_ascii_title via global
# ---------------------------------------------------------------------------
_COCKPIT_VERSION="0.1.0"
[ -f "VERSION" ] && _COCKPIT_VERSION=$(tr -d '[:space:]' < VERSION 2>/dev/null || echo "0.1.0")

# ---------------------------------------------------------------------------
# Pick one random Tolkien quote for this launcher run (stable across redraws)
# ---------------------------------------------------------------------------
_QUOTE_TEXT=""
_QUOTE_ATTR=""
_load_random_quote() {
    local f="bridge/quotes.txt"
    [ ! -f "$f" ] && return
    local lines=()
    while IFS= read -r line; do
        [[ -n "$line" && ! "$line" =~ ^# ]] && lines+=("$line")
    done < "$f"
    [ "${#lines[@]}" -eq 0 ] && return
    local idx=$(( RANDOM % ${#lines[@]} ))
    local sel="${lines[$idx]}"
    _QUOTE_TEXT="${sel%%|*}"
    _QUOTE_ATTR="${sel##*|}"
}
_load_random_quote

# ---------------------------------------------------------------------------
# Detect existing tmux session — and whether it is already attached
# ---------------------------------------------------------------------------
HAS_SESSION=0
ATTACHED=0
if tmux has-session -t mume 2>/dev/null; then
    HAS_SESSION=1
    ATTACHED=$(tmux list-clients -t mume 2>/dev/null | wc -l)
    ATTACHED=$(( ATTACHED + 0 ))
fi

# Menu order: Start/Continue/Mirror, Profile, Options, Scripts, About, Quit
if [ "$HAS_SESSION" -eq 0 ]; then
    _ITEMS=("Start new session" "Profile" "Options" "Scripts" "About" "Quit")
elif [ "$ATTACHED" -eq 0 ]; then
    _ITEMS=("Continue session" "Profile" "Options" "Scripts" "About" "Quit")
else
    _ITEMS=("Mirror session (attached elsewhere)" "Profile" "Options" "Scripts" "About" "Quit")
fi
_NITEMS=${#_ITEMS[@]}

_SEL=0

# ---------------------------------------------------------------------------
# Global dirty flag — set by SIGWINCH trap and after each key action
# ---------------------------------------------------------------------------
_DIRTY=1
trap '_DIRTY=1' WINCH

# ---------------------------------------------------------------------------
# Main menu render
# ---------------------------------------------------------------------------
_render_main() {
    local cols; cols=$(tput cols 2>/dev/null || echo 80)
    {
        draw_ascii_title

        local i
        for i in "${!_ITEMS[@]}"; do
            draw_menu_item "${_ITEMS[$i]}" $(( i == _SEL ? 1 : 0 ))
        done

        if [ -n "$_QUOTE_TEXT" ]; then
            printf '\n'
            local qlen=$(( ${#_QUOTE_TEXT} + 2 ))
            local qpad=$(( (cols - qlen) / 2 ))
            [ "$qpad" -lt 0 ] && qpad=0
            printf "%${qpad}s${_MR_ITALIC_GREY}\"%s\"${_MR_RESET}\n" "" "$_QUOTE_TEXT"
            local attr="— ${_QUOTE_ATTR}"
            local apad=$(( (cols - ${#attr}) / 2 ))
            [ "$apad" -lt 0 ] && apad=0
            printf "%${apad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$attr"
        fi

        printf '\n'
        local footer="↑↓ Navigate · Enter/Space Select"
        local fpad=$(( (cols - ${#footer}) / 2 ))
        printf "%${fpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$footer"
    } | render_frame
}

# ---------------------------------------------------------------------------
# Quit confirmation
# ---------------------------------------------------------------------------
_quit_confirm() {
    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            local cols; cols=$(tput cols 2>/dev/null || echo 80)
            local msg="Quit? Press Y to confirm, any other key to cancel."
            local pad=$(( (cols - ${#msg}) / 2 ))
            { printf '\n\n'; printf "%${pad}s${_MR_WHITE}%s${_MR_RESET}\n" "" "$msg"; } | render_frame
        fi
        read_key 0.2 || continue
        break
    done
    _DIRTY=1
    [ "$LAST_KEY" = "y" ] || [ "$LAST_KEY" = "Y" ] && exit 0
}

# ---------------------------------------------------------------------------
# Options sub-menu
# ---------------------------------------------------------------------------
_options_menu() {
    local _ui="$show_ui"
    local _dev="$show_dev"
    local _inp="$show_input"
    local _conn="$connection_mode"

    # Selectable items: 0=UI 1=Dev 2=Input 3=MMapper 4=Direct 5=Back
    local _osel=0
    local _OCOUNT=6

    _oitem() {
        local idx="$1" label="$2"
        local active=0
        [ "$idx" -eq "$_osel" ] && active=1
        draw_menu_item "$label" "$active"
    }

    _section_hdr() {
        local title="$1"
        local cols; cols=$(tput cols 2>/dev/null || echo 80)
        local pad=$(( (cols - ${#title}) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
        printf "%${pad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$title"
    }

    _render_opts() {
        local cols; cols=$(tput cols 2>/dev/null || echo 80)
        local rows; rows=$(tput lines 2>/dev/null || echo 24)
        local chk_ui="[ ]" chk_dev="[ ]" chk_inp="[ ]"
        [ "$_ui"  -eq 1 ] && chk_ui="[x]"
        [ "$_dev" -eq 1 ] && chk_dev="[x]"
        [ "$_inp" -eq 1 ] && chk_inp="[x]"
        local r_mm="( )" r_di="( )"
        [ "$_conn" = "mmapper" ] && r_mm="(•)"
        [ "$_conn" = "direct"  ] && r_di="(•)"

        local title="─── Options ───"
        local tpad=$(( (cols - ${#title}) / 2 ))
        local footer="↑↓ Navigate · Enter/Space Toggle · ESC Back"
        local fpad=$(( (cols - ${#footer}) / 2 ))

        # Responsive: drop optional sections as terminal shrinks.
        # Thresholds: rows < 18 → headings, < 21 → mockup, < 31 → desc block.
        local show_headings=1 show_mockup=0 show_desc=0
        [ "$rows" -lt 18 ] && show_headings=0
        [ "$rows" -ge 21 ] && show_mockup=1
        [ "$rows" -ge 31 ] && show_desc=1

        {
            printf '\n\n'
            printf "%${tpad}s${_MR_WHITE}%s${_MR_RESET}\n\n" "" "$title"
            [ "$show_headings" -eq 1 ] && _section_hdr "Panes"
            _oitem 0 "$chk_ui  UI pane"
            _oitem 1 "$chk_dev Dev pane"
            _oitem 2 "$chk_inp Input pane"
            printf '\n'
            [ "$show_headings" -eq 1 ] && _section_hdr "Connection"
            _oitem 3 "$r_mm MMapper  (localhost:4242)"
            _oitem 4 "$r_di Direct   (mume.org:4242)"
            printf '\n'
            _oitem 5 "Back"
            if [ "$show_mockup" -eq 1 ]; then
                printf '\n'
                draw_layout_mockup "$_ui" "$_dev" "$_inp" "$show_desc"
            fi
            printf '\n'
            printf "%${fpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$footer"
        } | render_frame
    }

    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            _render_opts
        fi

        read_key 0.2 || continue

        _DIRTY=1
        case "$LAST_KEY" in
            UP)    _osel=$(( (_osel - 1 + _OCOUNT) % _OCOUNT )) ;;
            DOWN)  _osel=$(( (_osel + 1) % _OCOUNT )) ;;
            ENTER|SPACE)
                case "$_osel" in
                    0) _ui=$(( 1 - _ui )) ;;
                    1) _dev=$(( 1 - _dev )) ;;
                    2) _inp=$(( 1 - _inp )) ;;
                    3) _conn="mmapper" ;;
                    4) _conn="direct" ;;
                    5) show_ui="$_ui"; show_dev="$_dev"; show_input="$_inp"
                       connection_mode="$_conn"; _save_conf; return ;;
                esac
                ;;
            ESC) show_ui="$_ui"; show_dev="$_dev"; show_input="$_inp"
                 connection_mode="$_conn"; _save_conf; return ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Create new profile flow — called from _profile_page
# ---------------------------------------------------------------------------
_create_profile_flow() {
    local cols

    # === Phase 1: Name entry — char-by-char with ESC cancel + SIGWINCH redraw ===
    local buf="" errmsg="" nr=1
    while true; do
        if [ "$_DIRTY" -eq 1 ] || [ "$nr" -eq 1 ]; then
            _DIRTY=0; nr=0
            cols=$(tput cols 2>/dev/null || echo 80)
            local ctitle="─── Create New Profile ───"
            local ctpad=$(( (cols - ${#ctitle}) / 2 ))
            local hint="letters and _ only · must start with a letter · max 32"
            local hpad=$(( (cols - ${#hint}) / 2 ))
            local pfooter="Enter  Confirm · ESC  Cancel"
            local pfpad=$(( (cols - ${#pfooter}) / 2 ))
            local dpad=$(( (cols - ${#buf} - 4) / 2 ))
            [ "$dpad" -lt 0 ] && dpad=0
            {
                printf '\n\n'
                printf "%${ctpad}s${_MR_WHITE}%s${_MR_RESET}\n\n\n" "" "$ctitle"
                printf "%${dpad}s${_MR_GREY}> ${_MR_WHITE}%s${_MR_DIM}_${_MR_RESET}\n" "" "$buf"
                printf '\n'
                printf "%${hpad}s${_MR_DIM}%s${_MR_RESET}\n" "" "$hint"
                if [ -n "$errmsg" ]; then
                    local epad=$(( (cols - ${#errmsg}) / 2 ))
                    printf "\n%${epad}s${_MR_YELLOW}%s${_MR_RESET}\n" "" "$errmsg"
                fi
                printf '\n'
                printf "%${pfpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$pfooter"
            } | render_frame
        fi
        local c
        if IFS= read -rsn1 -t 0.2 c 2>/dev/null; then
            case "$c" in
                $'\e')
                    local _seq=""
                    while IFS= read -rsn1 -t 0.01 _sc 2>/dev/null; do _seq+="$_sc"; done
                    [ -z "$_seq" ] && { _DIRTY=1; return; }  # bare ESC → cancel
                    ;;
                $'\n'|$'\r'|'')
                    if [[ -z "$buf" ]]; then
                        errmsg="Name cannot be empty."; nr=1
                    elif [[ ! "$buf" =~ ^[a-zA-Z][a-zA-Z0-9_]*$ ]]; then
                        errmsg="Must start with a letter; only letters, numbers, _ allowed."; nr=1
                    elif [ -f "ttpp/sessions/${buf}.tin" ]; then
                        errmsg="Profile \"${buf}\" already exists."; nr=1
                    else
                        break
                    fi
                    ;;
                $'\x7f'|$'\b')
                    if [ -n "$buf" ]; then buf="${buf%?}"; errmsg=""; nr=1; fi
                    ;;
                *)
                    if [[ "$c" =~ [[:print:]] ]] && (( ${#buf} < 32 )); then
                        buf+="$c"; errmsg=""; nr=1
                    fi
                    ;;
            esac
        fi
    done
    local new_name="$buf"

    # === Phase 2: Blank vs Copy — dirty-flag loop with SIGWINCH redraw ===
    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            cols=$(tput cols 2>/dev/null || echo 80)
            local p2title="─── Create New Profile ───"
            local p2tpad=$(( (cols - ${#p2title}) / 2 ))
            local bfooter="B  Blank profile · C  Copy from existing · ESC  Cancel"
            local bfpad=$(( (cols - ${#bfooter}) / 2 ))
            local nlabel="Name:  ${new_name}"
            local npad=$(( (cols - ${#nlabel}) / 2 ))
            {
                printf '\n\n'
                printf "%${p2tpad}s${_MR_WHITE}%s${_MR_RESET}\n\n" "" "$p2title"
                printf "%${npad}s${_MR_GREY}Name:  ${_MR_WHITE}%s${_MR_RESET}\n\n\n" "" "$new_name"
                printf "%${bfpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$bfooter"
            } | render_frame
        fi
        read_key 0.2 || continue
        case "$LAST_KEY" in
            ESC) _DIRTY=1; return ;;
            'b'|'B')
                printf '#nop %s.tin — MUME Cockpit profile\n' "$new_name" \
                    > "ttpp/sessions/${new_name}.tin"
                printf '#nop Loaded when this profile is selected in the startup menu.\n' \
                    >> "ttpp/sessions/${new_name}.tin"
                profile="$new_name"; _save_conf
                _DIRTY=1; return
                ;;
            'c'|'C')
                # === Phase 3: Copy picker — dirty-flag loop with SIGWINCH redraw ===
                local -a src_profiles=()
                local f bn
                for f in ttpp/sessions/*.tin; do
                    [ -f "$f" ] || continue
                    bn="${f##*/}"; src_profiles+=("${bn%.tin}")
                done
                IFS=$'\n' read -d '' -ra src_profiles \
                    < <(printf '%s\n' "${src_profiles[@]}" | sort && printf '\0') 2>/dev/null || true

                if [ "${#src_profiles[@]}" -eq 0 ]; then
                    _DIRTY=1
                    while true; do
                        if [ "$_DIRTY" -eq 1 ]; then
                            _DIRTY=0
                            cols=$(tput cols 2>/dev/null || echo 80)
                            local etitle="─── Create New Profile ───"
                            local etpad=$(( (cols - ${#etitle}) / 2 ))
                            local emsg="No profiles available to copy from."
                            local epad=$(( (cols - ${#emsg}) / 2 ))
                            local ekftr="Any key to continue"
                            local ekpad=$(( (cols - ${#ekftr}) / 2 ))
                            {
                                printf '\n\n'
                                printf "%${etpad}s${_MR_WHITE}%s${_MR_RESET}\n\n\n" "" "$etitle"
                                printf "%${epad}s${_MR_YELLOW}%s${_MR_RESET}\n\n\n" "" "$emsg"
                                printf "%${ekpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$ekftr"
                            } | render_frame
                        fi
                        read_key 0.2 || continue
                        break
                    done
                    _DIRTY=1; return
                fi

                local csel=0
                _DIRTY=1
                while true; do
                    if [ "$_DIRTY" -eq 1 ]; then
                        _DIRTY=0
                        cols=$(tput cols 2>/dev/null || echo 80)
                        local cptitle="─── Create New Profile ───"
                        local cptpad=$(( (cols - ${#cptitle}) / 2 ))
                        local cfooter="↑↓ Navigate · Enter  Select · ESC  Cancel"
                        local cfpad=$(( (cols - ${#cfooter}) / 2 ))
                        local cplabel="Copy from:"
                        local cplpad=$(( (cols - ${#cplabel}) / 2 ))
                        {
                            printf '\n\n'
                            printf "%${cptpad}s${_MR_WHITE}%s${_MR_RESET}\n\n" "" "$cptitle"
                            printf "%${cplpad}s${_MR_GREY}%s${_MR_RESET}\n\n" "" "$cplabel"
                            local ci
                            for ci in "${!src_profiles[@]}"; do
                                draw_menu_item "${src_profiles[$ci]}" $(( ci == csel ? 1 : 0 ))
                            done
                            printf '\n'
                            printf "%${cfpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$cfooter"
                        } | render_frame
                    fi
                    read_key 0.2 || continue
                    _DIRTY=1
                    case "$LAST_KEY" in
                        UP)   csel=$(( (csel - 1 + ${#src_profiles[@]}) % ${#src_profiles[@]} )) ;;
                        DOWN) csel=$(( (csel + 1) % ${#src_profiles[@]} )) ;;
                        ENTER|SPACE)
                            cp "ttpp/sessions/${src_profiles[$csel]}.tin" \
                               "ttpp/sessions/${new_name}.tin"
                            profile="$new_name"; _save_conf
                            _DIRTY=1; return
                            ;;
                        ESC) _DIRTY=1; return ;;
                    esac
                done
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Profile page
# ---------------------------------------------------------------------------
_profile_page() {
    local -a _profiles=()

    _load_profiles() {
        _profiles=()
        local f bn
        for f in ttpp/sessions/*.tin; do
            [ -f "$f" ] || continue
            bn="${f##*/}"; _profiles+=("${bn%.tin}")
        done
        IFS=$'\n' read -d '' -ra _profiles \
            < <(printf '%s\n' "${_profiles[@]}" | sort && printf '\0') 2>/dev/null || true
    }

    _load_profiles

    local _psel=0 i
    for i in "${!_profiles[@]}"; do
        [ "${_profiles[$i]}" = "$profile" ] && { _psel="$i"; break; }
    done

    _render_profile() {
        local create_idx=${#_profiles[@]}
        local back_idx=$(( create_idx + 1 ))
        local cols; cols=$(tput cols 2>/dev/null || echo 80)
        local title="─── Profile ───"
        local tpad=$(( (cols - ${#title}) / 2 ))
        local footer="↑↓ Navigate · Enter Select · D Delete · ESC Back"
        local fpad=$(( (cols - ${#footer}) / 2 ))
        {
            printf '\n\n'
            printf "%${tpad}s${_MR_WHITE}%s${_MR_RESET}\n\n" "" "$title"
            local idx
            for idx in "${!_profiles[@]}"; do
                local name="${_profiles[$idx]}"
                local marker="( )"
                [ "$name" = "$profile" ] && marker="(•)"
                draw_menu_item "$marker $name" $(( _psel == idx ? 1 : 0 ))
            done
            printf '\n'
            draw_menu_item "Create new profile…" $(( _psel == create_idx ? 1 : 0 ))
            printf '\n'
            draw_menu_item "Back" $(( _psel == back_idx ? 1 : 0 ))
            printf '\n'
            printf "%${fpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$footer"
        } | render_frame
    }

    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            _render_profile
        fi
        read_key 0.2 || continue
        _DIRTY=1

        local create_idx=${#_profiles[@]}
        local back_idx=$(( create_idx + 1 ))
        local ptotal=$(( back_idx + 1 ))

        case "$LAST_KEY" in
            UP)   _psel=$(( (_psel - 1 + ptotal) % ptotal )) ;;
            DOWN) _psel=$(( (_psel + 1) % ptotal )) ;;
            ENTER|SPACE)
                if [ "$_psel" -lt "${#_profiles[@]}" ]; then
                    profile="${_profiles[$_psel]}"; _save_conf; return
                elif [ "$_psel" -eq "$create_idx" ]; then
                    _create_profile_flow
                    _DIRTY=1
                    _load_profiles
                    _psel=0
                    for i in "${!_profiles[@]}"; do
                        [ "${_profiles[$i]}" = "$profile" ] && { _psel="$i"; break; }
                    done
                else
                    return
                fi
                ;;
            'd'|'D')
                if [ "$_psel" -ge "${#_profiles[@]}" ]; then
                    _DIRTY=0  # ignore on Create/Back rows
                else
                    local cols; cols=$(tput cols 2>/dev/null || echo 80)
                    local dname="${_profiles[$_psel]}"
                    local dtitle="─── Profile ───"
                    local dtpad=$(( (cols - ${#dtitle}) / 2 ))
                    if [ "$dname" = "default" ]; then
                        local emsg="You can't delete the default profile."
                        local epad=$(( (cols - ${#emsg}) / 2 ))
                        local kfooter="Any key to continue"
                        local kfpad=$(( (cols - ${#kfooter}) / 2 ))
                        local _eddirty=1
                        while true; do
                            if [ "$_eddirty" -eq 1 ]; then
                                _eddirty=0
                                {
                                    printf '\n\n'
                                    printf "%${dtpad}s${_MR_WHITE}%s${_MR_RESET}\n\n\n" "" "$dtitle"
                                    printf "%${epad}s${_MR_ERR}%s${_MR_RESET}\n\n\n" "" "$emsg"
                                    printf "%${kfpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$kfooter"
                                } | render_frame
                            fi
                            read_key 0.2 || { _eddirty=1; continue; }
                            break
                        done
                    else
                        local cmsg="Delete profile '${dname}'?  (y/N)"
                        local cpad=$(( (cols - ${#cmsg}) / 2 ))
                        local cfooter="Y to confirm · any other key to cancel"
                        local cfpad=$(( (cols - ${#cfooter}) / 2 ))
                        local _cddirty=1
                        local _confirmed=0
                        while true; do
                            if [ "$_cddirty" -eq 1 ]; then
                                _cddirty=0
                                {
                                    printf '\n\n'
                                    printf "%${dtpad}s${_MR_WHITE}%s${_MR_RESET}\n\n\n" "" "$dtitle"
                                    printf "%${cpad}s${_MR_WHITE}%s${_MR_RESET}\n\n\n" "" "$cmsg"
                                    printf "%${cfpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$cfooter"
                                } | render_frame
                            fi
                            read_key 0.2 || { _cddirty=1; continue; }
                            [ "$LAST_KEY" = "y" ] || [ "$LAST_KEY" = "Y" ] && _confirmed=1
                            break
                        done
                        if [ "$_confirmed" -eq 1 ]; then
                            rm "ttpp/sessions/${dname}.tin"
                            if [ "$profile" = "$dname" ]; then
                                profile="default"; _save_conf
                            fi
                            _load_profiles
                            local new_ptotal=$(( ${#_profiles[@]} + 2 ))
                            [ "$_psel" -ge "$new_ptotal" ] && _psel=$(( new_ptotal - 1 ))
                        fi
                    fi
                fi
                ;;
            ESC) return ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# About page — scrollable, cached word-wrap
# ---------------------------------------------------------------------------
_about_page() {
    local -a _alines=()
    local _aoffset=0
    local _acols=0  # cols at last wrap; checked to skip unnecessary re-wraps

    _load_about_lines() {
        local cols; cols=$(tput cols 2>/dev/null || echo 80)
        local width=$(( cols - 4 ))
        [ "$width" -gt 76 ] && width=76
        [ "$width" -lt 20 ] && width=20
        # Skip re-wrap when cols unchanged and cache is populated
        [ "$cols" -eq "$_acols" ] && [ "${#_alines[@]}" -gt 0 ] && return
        _acols="$cols"
        _alines=()
        [ -f "bridge/about.txt" ] || return
        while IFS= read -r aline; do
            _alines+=("$aline")
        done < <(wrap_text "$width" < "bridge/about.txt")
    }

    _render_about() {
        local cols; cols=$(tput cols 2>/dev/null || echo 80)
        local rows; rows=$(tput lines 2>/dev/null || echo 24)
        local width=$(( cols - 4 ))
        [ "$width" -gt 76 ] && width=76
        [ "$width" -lt 20 ] && width=20
        local pad=$(( (cols - width) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
        local p; printf -v p "%${pad}s" ""
        local title="─── About ───"
        local tpad=$(( (cols - ${#title}) / 2 ))

        # Header: 3 rows (blank + title + blank). Footer: 2 rows. Reserve 5.
        local visible=$(( rows - 5 ))
        [ "$visible" -lt 1 ] && visible=1
        local atotal=${#_alines[@]}
        local max_off=$(( atotal - visible ))
        [ "$max_off" -lt 0 ] && max_off=0
        # Clamp offset in main process (not inside the pipe subshell)
        [ "$_aoffset" -gt "$max_off" ] && _aoffset="$max_off"

        local footer="ESC  Back"
        [ "$atotal" -gt "$visible" ] && footer="↑↓ Scroll · ESC Back"
        local fpad=$(( (cols - ${#footer}) / 2 ))

        {
            printf '\n'
            printf "%${tpad}s${_MR_WHITE}%s${_MR_RESET}\n\n" "" "$title"
            local shown=0 i
            for (( i = _aoffset; i < atotal && shown < visible; i++ )); do
                local aline="${_alines[$i]}"
                if [ -z "$aline" ]; then
                    printf '\n'
                else
                    printf "%s${_MR_GREY}%s${_MR_RESET}\n" "$p" "$aline"
                fi
                (( shown++ ))
            done
            printf '\n'
            printf "%${fpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$footer"
        } | render_frame
    }

    _load_about_lines  # initial wrap at page entry

    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            _load_about_lines  # re-wraps only when cols changed (SIGWINCH)
            _render_about
        fi
        read_key 0.2 || continue

        local atotal=${#_alines[@]}
        local rows; rows=$(tput lines 2>/dev/null || echo 24)
        local visible=$(( rows - 5 ))
        [ "$visible" -lt 1 ] && visible=1
        local max_off=$(( atotal - visible ))
        [ "$max_off" -lt 0 ] && max_off=0

        _DIRTY=1
        case "$LAST_KEY" in
            ESC) return ;;
            UP)
                if [ "$_aoffset" -gt 0 ]; then
                    _aoffset=$(( _aoffset - 1 ))
                else
                    _DIRTY=0
                fi
                ;;
            DOWN)
                if [ "$_aoffset" -lt "$max_off" ]; then
                    _aoffset=$(( _aoffset + 1 ))
                else
                    _DIRTY=0
                fi
                ;;
            *) _DIRTY=0 ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Scripts page — reads bridge/scripts.cache written by brain.lua
# ---------------------------------------------------------------------------
_scripts_page() {
    local -a _slines=()
    local _sin_script=0

    _load_scripts_lines() {
        _slines=()
        _sin_script=0
        if [ ! -f "bridge/scripts.cache" ] || [ ! -s "bridge/scripts.cache" ]; then
            _slines=("M:No scripts cached yet — start the client once to populate.")
            return
        fi
        while IFS= read -r line; do
            case "$line" in
                SCRIPT:*)
                    [ "$_sin_script" -eq 1 ] && _slines+=("B:")
                    _sin_script=1
                    _slines+=("A:${line#SCRIPT:}")
                    ;;
                SUMMARY:*) _slines+=("S:${line#SUMMARY:}") ;;
                HELP:*)    _slines+=("H:${line#HELP:}")    ;;
            esac
        done < "bridge/scripts.cache"
    }

    _load_scripts_lines

    local _soffset=0
    local _stotal=${#_slines[@]}

    _render_scripts() {
        local cols; cols=$(tput cols 2>/dev/null || echo 80)
        local rows; rows=$(tput lines 2>/dev/null || echo 24)
        local pad=$(( (cols - 60) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
        local p; printf -v p "%${pad}s" ""
        local title="─── Scripts ───"
        local tpad=$(( (cols - ${#title}) / 2 ))

        # Header: 4 rows. Footer: 2 rows. Reserve 6.
        local visible=$(( rows - 6 ))
        [ "$visible" -lt 1 ] && visible=1
        local max_off=$(( _stotal - visible ))
        [ "$max_off" -lt 0 ] && max_off=0
        [ "$_soffset" -gt "$max_off" ] && _soffset="$max_off"

        local footer="ESC  Back"
        [ "$_stotal" -gt "$visible" ] && footer="↑↓ Scroll · ESC Back"
        local fpad=$(( (cols - ${#footer}) / 2 ))

        {
            printf '\n'
            printf "%${tpad}s${_MR_WHITE}%s${_MR_RESET}\n\n" "" "$title"
            local shown=0 i
            for (( i = _soffset; i < _stotal && shown < visible; i++ )); do
                local entry="${_slines[$i]}"
                local tag="${entry:0:2}" text="${entry:2}"
                case "$tag" in
                    A:) printf "%s${_MR_TEAL}▶ ${_MR_WHITE}%s${_MR_RESET}\n" \
                            "$p" "$(printf '%s' "$text" | tr '[:lower:]' '[:upper:]')" ;;
                    S:) printf "%s  ${_MR_GREY}%s${_MR_RESET}\n" "$p" "$text" ;;
                    H:) printf "%s  %s\n" "$p" "$text" ;;
                    B:) printf '\n' ;;
                    M:) printf "%s${_MR_GREY}%s${_MR_RESET}\n" "$p" "$text" ;;
                esac
                (( shown++ ))
            done
            printf '\n'
            printf "%${fpad}s${_MR_GREY}%s${_MR_RESET}\n" "" "$footer"
        } | render_frame
    }

    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            _render_scripts
        fi
        read_key 0.2 || continue

        _DIRTY=1
        case "$LAST_KEY" in
            ESC) return ;;
            UP)
                [ "$_soffset" -gt 0 ] && _soffset=$(( _soffset - 1 )) || _DIRTY=0
                ;;
            DOWN)
                local rows; rows=$(tput lines 2>/dev/null || echo 24)
                local vis=$(( rows - 6 ))
                [ "$vis" -lt 1 ] && vis=1
                local mx=$(( _stotal - vis ))
                [ "$mx" -lt 0 ] && mx=0
                if [ "$_soffset" -lt "$mx" ]; then
                    _soffset=$(( _soffset + 1 ))
                else
                    _DIRTY=0
                fi
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# check_min_size — runs in alt screen (already entered above)
# ---------------------------------------------------------------------------
check_min_size

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
while true; do
    if [ "$_DIRTY" -eq 1 ]; then
        _DIRTY=0
        _render_main
    fi

    read_key 0.2 || continue

    _DIRTY=1
    case "$LAST_KEY" in
        UP)
            _SEL=$(( (_SEL - 1 + _NITEMS) % _NITEMS ))
            ;;
        DOWN)
            _SEL=$(( (_SEL + 1) % _NITEMS ))
            ;;
        ENTER|SPACE)
            case "$_SEL" in
                0)  # Start new session / Continue session / Mirror session
                    trap - EXIT INT TERM HUP
                    printf '\e[?1007h'  # re-enable alt-scroll before tmux takes over
                    if [ "$HAS_SESSION" -eq 1 ]; then
                        exec tmux attach -t mume
                    else
                        exec bash bridge/tmux_start.sh
                    fi
                    ;;
                1) _profile_page ;;
                2) _options_menu ;;
                3) _scripts_page ;;
                4) _about_page   ;;
                5) _quit_confirm ;;
            esac
            ;;
    esac
done
