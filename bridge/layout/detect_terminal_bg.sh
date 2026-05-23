#!/usr/bin/env bash
# bridge/layout/detect_terminal_bg.sh — probe the host terminal's background
# colour via OSC 11 and persist it as terminal_bg=#rrggbb in layout.conf.
# Must run pre-tmux: /dev/tty is the host terminal here, not tmux's virtual
# terminal. On unsupported terminals or read timeout, writes terminal_bg=
# (empty) and exits 0 — never blocks startup.
# Consumed by bridge/layout/apply_border_style.sh.

set -u

LAYOUT_CONF="$HOME/MUME/bridge/runtime/layout.conf"
mkdir -p "$(dirname "$LAYOUT_CONF")"

_persist() {
    local key="$1" val="$2"
    [ -f "$LAYOUT_CONF" ] || : > "$LAYOUT_CONF"
    if grep -q "^${key}=" "$LAYOUT_CONF" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$LAYOUT_CONF"
    else
        echo "${key}=${val}" >> "$LAYOUT_CONF"
    fi
}

# No controlling tty → nothing to query.
if [ ! -e /dev/tty ]; then
    _persist terminal_bg ""
    exit 0
fi

# Snapshot tty state and guarantee restore even on early exit.
old_stty=$(stty -g </dev/tty 2>/dev/null) || { _persist terminal_bg ""; exit 0; }
trap 'stty "$old_stty" </dev/tty 2>/dev/null' EXIT

# Raw, no echo, non-blocking with ~0.3s read timeout (time is tenths of a sec).
stty raw -echo min 0 time 3 </dev/tty 2>/dev/null

# OSC 11 query: ask the terminal for its current background colour.
printf '\033]11;?\007' >/dev/tty 2>/dev/null

# Read up to 64 bytes; dd returns when read() yields 0 bytes (timeout).
reply=$(dd if=/dev/tty bs=1 count=64 2>/dev/null)

# Parse "rgb:RRRR/GGGG/BBBB" or "rgb:RR/GG/BB". Channels may also be 1 or 3
# hex digits on some terminals — normalise to two hex digits per channel.
hex=""
if [[ "$reply" =~ rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+) ]]; then
    r="${BASH_REMATCH[1]}"
    g="${BASH_REMATCH[2]}"
    b="${BASH_REMATCH[3]}"
    _trim() {
        local v="$1"
        case "${#v}" in
            1) printf '%s%s' "$v" "$v" ;;
            *) printf '%s'   "${v:0:2}" ;;
        esac
    }
    r=$(_trim "$r")
    g=$(_trim "$g")
    b=$(_trim "$b")
    hex=$(printf '#%s%s%s' "$r" "$g" "$b" | tr 'A-F' 'a-f')
fi

_persist terminal_bg "$hex"
exit 0
