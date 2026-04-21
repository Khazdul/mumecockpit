#!/bin/bash
# bridge/ingame_menu.sh — in-game popup menu (Phase 3)
# Launched via: tmux display-popup -E -w 80% -h 80% -x C -y C "bash .../ingame_menu.sh"
# Do NOT invoke directly from outside a tmux popup context.

cd "$(dirname "$0")/.."

source bridge/menu_render.sh

printf '\e[?1049h\e[?25l'
printf '\e[?1000l\e[?1002l\e[?1003l\e[?1006l\e[?1007l'

_restore_terminal() {
    printf '\e[?1007h\e[?25h\e[?1049l'
}
trap '_restore_terminal' EXIT INT TERM HUP

_DIRTY=1
trap '_DIRTY=1' WINCH

_ITEMS=("Continue" "Options" "Exit to main menu")
_NITEMS=3
_SEL=0

_draw_cockpit_banner() {
    local cols; cols=$(tput cols 2>/dev/null || echo 80)
    local lines=(
        '██ ███ ██ █ █ ██ █ ███'
        '█  █ █ █  ██  ██ █  █ '
        '██ ███ ██ █ █ █  █  █ '
    )
    printf '\n'
    local line vw pad
    for line in "${lines[@]}"; do
        vw=${#line}
        pad=$(( (cols - vw) / 2 ))
        [ "$pad" -lt 0 ] && pad=0
        printf "%${pad}s${_MR_TITLE}%s${_MR_RESET}\n" "" "$line"
    done
    printf '\n'
}

_render_status_header() {
    local cols; cols=$(tput cols 2>/dev/null || echo 80)

    local profile="default" connection_mode="mmapper"
    [ -f bridge/startup.conf ] && source bridge/startup.conf

    local mode_label="MMapper"
    case "$connection_mode" in
        direct)  mode_label="Direct" ;;
        *)       mode_label="MMapper" ;;
    esac

    local connected_at=""
    if [ -f bridge/session.state ]; then
        while IFS='=' read -r k v; do
            case "$k" in
                connected_at) connected_at="$v" ;;
            esac
        done < bridge/session.state
    fi

    local line
    if [ -n "$connected_at" ] && [ "$connected_at" -gt 0 ] 2>/dev/null; then
        local now; now=$(date +%s)
        local elapsed=$(( now - connected_at ))
        local h=$(( elapsed / 3600 ))
        local m=$(( (elapsed % 3600) / 60 ))
        local s=$(( elapsed % 60 ))
        local uptime; printf -v uptime "%d:%02d:%02d" "$h" "$m" "$s"
        line="Profile: ${profile}  ·  ${mode_label}  ·  up ${uptime}"
    else
        line="Profile: ${profile}  ·  Disconnected"
    fi

    local vw=${#line}
    local pad=$(( (cols - vw) / 2 ))
    [ "$pad" -lt 0 ] && pad=0
    printf "%${pad}s${_MR_BODY}%s${_MR_RESET}\n" "" "$line"
    printf '\n'
}

_render_main() {
    local cols; cols=$(tput cols 2>/dev/null || echo 80)
    {
        _draw_cockpit_banner
        _render_status_header

        local i
        for i in "${!_ITEMS[@]}"; do
            local active=0; [ "$i" -eq "$_SEL" ] && active=1
            if [ "$i" -eq 2 ]; then
                draw_menu_item "${_ITEMS[$i]}" "$active" "" "$_MR_ERR"
                local sub="Terminates current session"
                local subpad=$(( (cols - ${#sub} - 3) / 2 ))
                [ "$subpad" -lt 0 ] && subpad=0
                printf "%${subpad}s   ${_MR_ERR}%s${_MR_RESET}\n" "" "$sub"
            else
                draw_menu_item "${_ITEMS[$i]}" "$active"
            fi
            if [ "$i" -eq 1 ]; then
                local sep="────────────────────"
                local spad=$(( (cols - ${#sep}) / 2 ))
                [ "$spad" -lt 0 ] && spad=0
                printf "%${spad}s${_MR_HINT}%s${_MR_RESET}\n" "" "$sep"
            fi
        done

        printf '\n'
        local footer="↑↓ Navigate · Enter Select · ESC Dismiss"
        local fpad=$(( (cols - ${#footer}) / 2 ))
        [ "$fpad" -lt 0 ] && fpad=0
        printf "%${fpad}s${_MR_HINT}%s${_MR_RESET}\n" "" "$footer"
    } | render_frame
}

_options_submenu() {
    local _osel=0
    local _OCOUNT=5
    local _ODIRTY=1
    local _targets=(ui dev input headers)

    while true; do
        if [ "$_ODIRTY" -eq 1 ]; then
            _ODIRTY=0
            local cols; cols=$(tput cols 2>/dev/null || echo 80)

            local _chk_ui="[ ]" _chk_dev="[ ]" _chk_inp="[ ]" _chk_hdr="[ ]"
            tmux list-panes -t mume:cockpit -F '#{pane_title}' 2>/dev/null | grep -q '^ui$'    && _chk_ui="[x]"
            tmux list-panes -t mume:cockpit -F '#{pane_title}' 2>/dev/null | grep -q '^dev$'   && _chk_dev="[x]"
            tmux list-panes -t mume:cockpit -F '#{pane_title}' 2>/dev/null | grep -q '^input$' && _chk_inp="[x]"
            [ "$(tmux show-option -t mume pane-border-status 2>/dev/null | awk '{print $2}')" != "off" ] && _chk_hdr="[x]"

            local _olabels=(
                "$_chk_ui UI pane"
                "$_chk_dev Dev pane"
                "$_chk_inp Input pane"
                "$_chk_hdr Pane headers"
                "    Back"
            )

            local maxw=0 w _lbl
            for _lbl in "${_olabels[@]}"; do
                w=${#_lbl}; (( w > maxw )) && maxw=$w
            done
            local pad=$(( (cols - maxw) / 2 ))
            (( pad < 0 )) && pad=0

            local title="─── Options ───"
            local tpad=$(( (cols - ${#title}) / 2 ))
            [ "$tpad" -lt 0 ] && tpad=0
            local footer="↑↓ Navigate · Enter/Space Toggle · ESC Back"
            local fpad=$(( (cols - ${#footer}) / 2 ))
            [ "$fpad" -lt 0 ] && fpad=0

            {
                printf '\n\n'
                printf "%${tpad}s${_MR_TITLE}%s${_MR_RESET}\n\n" "" "$title"
                local i
                for i in "${!_olabels[@]}"; do
                    local active=0; [ "$i" -eq "$_osel" ] && active=1
                    draw_menu_item "${_olabels[$i]}" "$active" "$pad"
                done
                printf '\n'
                printf "%${fpad}s${_MR_HINT}%s${_MR_RESET}\n" "" "$footer"
            } | render_frame
        fi

        read_key 0.2 || { _ODIRTY=1; continue; }

        _ODIRTY=1
        case "$LAST_KEY" in
            UP)         _osel=$(( (_osel - 1 + _OCOUNT) % _OCOUNT )) ;;
            DOWN)       _osel=$(( (_osel + 1) % _OCOUNT )) ;;
            ESC)        return ;;
            ENTER|SPACE)
                case "$_osel" in
                    0|1|2|3)
                        bash "$HOME/MUME/bridge/toggle_pane.sh" "${_targets[$_osel]}" --persist
                        ;;
                    4) return ;;
                esac
                ;;
        esac
    done
}

_exit_confirm() {
    _DIRTY=1
    while true; do
        if [ "$_DIRTY" -eq 1 ]; then
            _DIRTY=0
            local cols; cols=$(tput cols 2>/dev/null || echo 80)
            local msg="Exit to main menu?  Y to confirm, any other key to cancel."
            local pad=$(( (cols - ${#msg}) / 2 ))
            [ "$pad" -lt 0 ] && pad=0
            {
                printf '\n\n'
                printf "%${pad}s${_MR_ACTIVE}%s${_MR_RESET}\n" "" "$msg"
                printf '\n'
                local hint="↑↓ · ESC  Back to menu"
                local hpad=$(( (cols - ${#hint}) / 2 ))
                [ "$hpad" -lt 0 ] && hpad=0
                printf "%${hpad}s${_MR_HINT}%s${_MR_RESET}\n" "" "$hint"
            } | render_frame
        fi
        read_key 0.2 || continue
        case "$LAST_KEY" in
            y|Y)
                touch bridge/.return_to_menu
                tmux send-keys -t mume:cockpit.0 "cp -e" C-m
                exit 0
                ;;
            ESC|*)
                _DIRTY=1; return
                ;;
        esac
    done
}

while true; do
    if [ "$_DIRTY" -eq 1 ]; then
        _DIRTY=0
        _render_main
    fi

    read_key 0.2 || { _DIRTY=1; continue; }

    _DIRTY=1
    case "$LAST_KEY" in
        UP)         _SEL=$(( (_SEL - 1 + _NITEMS) % _NITEMS )) ;;
        DOWN)       _SEL=$(( (_SEL + 1) % _NITEMS )) ;;
        ESC)        exit 0 ;;
        ENTER|SPACE)
            case "$_SEL" in
                0) exit 0 ;;
                1) _options_submenu; _DIRTY=1 ;;
                2) _exit_confirm ;;
            esac
            ;;
    esac
done
