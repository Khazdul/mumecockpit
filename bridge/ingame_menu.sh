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

_ITEMS=("Continue" "Exit to main menu")
_NITEMS=2
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

_render_main() {
    local cols; cols=$(tput cols 2>/dev/null || echo 80)
    {
        _draw_cockpit_banner

        local i
        for i in "${!_ITEMS[@]}"; do
            local active=0; [ "$i" -eq "$_SEL" ] && active=1
            if [ "$i" -eq 1 ]; then
                draw_menu_item "${_ITEMS[$i]}" "$active" "" "$_MR_ERR"
                local sub="Terminates current session"
                local subpad=$(( (cols - ${#sub} - 3) / 2 ))
                [ "$subpad" -lt 0 ] && subpad=0
                printf "%${subpad}s   ${_MR_ERR}%s${_MR_RESET}\n" "" "$sub"
            else
                draw_menu_item "${_ITEMS[$i]}" "$active"
            fi
        done

        printf '\n'
        local footer="↑↓ Navigate · Enter Select · ESC Dismiss"
        local fpad=$(( (cols - ${#footer}) / 2 ))
        [ "$fpad" -lt 0 ] && fpad=0
        printf "%${fpad}s${_MR_HINT}%s${_MR_RESET}\n" "" "$footer"
    } | render_frame
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

    read_key 0.2 || continue

    _DIRTY=1
    case "$LAST_KEY" in
        UP)         _SEL=$(( (_SEL - 1 + _NITEMS) % _NITEMS )) ;;
        DOWN)       _SEL=$(( (_SEL + 1) % _NITEMS )) ;;
        ESC)        exit 0 ;;
        ENTER|SPACE)
            case "$_SEL" in
                0) exit 0 ;;
                1) _exit_confirm ;;
            esac
            ;;
    esac
done
