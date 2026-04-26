# Character Status pane renderer.
#
# Polls bridge/status.state (JSON) every 250 ms via mtime comparison.
# Redraws in-place using ANSI sequences — no ESC[2J, no flicker.
# Internal width: 33 columns.

import json
import os
import signal
import sys
import time

STATE_PATH = os.path.join(os.environ["HOME"], "MUME", "bridge", "status.state")
POLL_MS    = 0.25   # seconds between mtime checks
WIDTH      = 33

# ---------------------------------------------------------------------------
# Colour constants (24-bit truecolor)
# ---------------------------------------------------------------------------
C_LABEL  = "\x1b[38;2;154;168;183m"    # #9AA8B7 steel-blue — labels
C_VALUE  = "\x1b[1;97m"                # bold bright white — values
C_FRAME  = "\x1b[38;2;166;140;90m"     # muted gold — box frame
C_TITLE  = "\x1b[1;38;2;222;184;135m"  # burlywood — header title
C_RESET  = "\x1b[0m"

C_AFFECT_SPELL  = "\x1b[38;2;122;169;214m"   # #7AA9D6 light steel-blue
C_AFFECT_BUFF   = "\x1b[38;2;143;188;143m"   # #8FBC8F soft sage green
C_AFFECT_DEBUFF = "\x1b[38;2;201;112;112m"   # #C97070 muted brick red

C_SUN  = "\x1b[38;2;255;176;0m"     # #FFB000 intense amber gold
C_MOON = "\x1b[38;2;74;144;226m"    # #4A90E2 vivid sky blue

_AFFECT_COLOURS = {
    "spell":  C_AFFECT_SPELL,
    "buff":   C_AFFECT_BUFF,
    "debuff": C_AFFECT_DEBUFF,
}

LEFT_W  = 16
RIGHT_W = 16

_AFFECT_SHORTNAMES = {
    "breath of briskness":             "briskness",
    "detect magic":                    "det. magic",
    "detect evil":                     "det. evil",
    "night vision":                    "night vis.",
    "sense life":                      "sense life",
    "Blood of Sauron":                 "BoS",
    "a pitch-black robe (pale tones)": "pitch robe",
    "a pure white robe (pale tones)":  "white robe",
    "heightened senses":               "h. senses",
    "heightened senses (faded)":       "h. senses-",
    "dark aura":                       "dark aura",
    "dark aura (faded)":               "dark aura-",
    "spectral health":                 "spec. health",
    "very comfortable":                "v. comfort.",
    "shadow-link":                     "shadow-link",
}

# ---------------------------------------------------------------------------
# Renderer state
# ---------------------------------------------------------------------------
_last_mtime = None
_last_data  = None
_dirty      = True   # True = force redraw even without mtime change


def _mark_dirty(signum, frame):
    global _dirty
    _dirty = True


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
def _row(label, value, width=WIDTH):
    """Single row: label left, value left (one space after label), truncated to width."""
    lbl = str(label)
    val = str(value) if value is not None else "—"
    if len(lbl) + 1 + len(val) > width:
        val = val[:max(0, width - len(lbl) - 1)]
    return C_LABEL + lbl + C_RESET + " " + C_VALUE + val + C_RESET


def _pair(l1, v1, l2, v2, width=WIDTH):
    """
    Paired row: l1:v1 on the left half, l2:v2 on the right half.
    Left half = width//2  cols, right half = width - width//2  cols.
    Each half renders as "label value" flush-left, padded with trailing spaces.
    """
    lw = width // 2
    rw = width - lw

    def _half(label, value, w):
        lbl = str(label)
        val = str(value) if value is not None else "—"
        visible = len(lbl) + 1 + len(val)
        if visible > w:
            available = w - len(lbl) - 1
            val = val[:max(0, available)]
        trailing = w - len(lbl) - 1 - len(val)
        return C_LABEL + lbl + C_RESET + " " + C_VALUE + val + C_RESET + " " * max(0, trailing)

    return _half(l1, v1, lw) + _half(l2, v2, rw)


def _time_row(time_str, period, remaining):
    """Time row: single full-width at DAY/UNSET; two-column at HOUR/MINUTE."""
    if period is None or remaining is None:
        return _row("Time:", time_str)
    lw = WIDTH // 2   # 16
    rw = WIDTH - lw   # 17

    label = "Time:"
    val = str(time_str) if time_str is not None else "—"
    if len(label) + 1 + len(val) > lw:
        val = val[:max(0, lw - len(label) - 1)]
    trailing_left = max(0, lw - len(label) - 1 - len(val))
    left = C_LABEL + label + C_RESET + " " + C_VALUE + val + C_RESET + " " * trailing_left

    icon   = "☼" if period == "night" else "☾"
    colour = C_SUN if period == "night" else C_MOON
    rem    = str(remaining)
    trailing_right = max(0, rw - 1 - 1 - 3 - 1 - len(rem))   # 1=icon, 1=sp, 3="in:", 1=sp
    right = colour + icon + C_RESET + " " + C_LABEL + "in:" + C_RESET + " " + C_VALUE + rem + C_RESET + " " * trailing_right

    return left + right


def _resolve_affect_name(name):
    """Resolve display name using MAX_NAME budget (12): shortmap → truncate → as-is."""
    if name in _AFFECT_SHORTNAMES:
        return _AFFECT_SHORTNAMES[name]
    limit = LEFT_W - 4   # 12: name + min-padding(1) + "99m"(3) must fit in LEFT_W
    if len(name) > limit:
        return name[:limit - 1] + "."
    return name


def _affect_cell(aff, cell_w):
    """Render one affect into exactly cell_w visible characters (no trailing reset)."""
    name      = str(aff.get("name") or "?")
    atype     = aff.get("type") or "spell"
    remaining = aff.get("remaining_seconds")
    colour    = _AFFECT_COLOURS.get(atype, C_VALUE)
    display   = _resolve_affect_name(name)

    if remaining is not None:
        mins   = max(0, -(-int(remaining) // 60))
        suffix = f"{mins}m"
        pad    = max(1, cell_w - len(display) - len(suffix))
        return colour + display + " " * pad + suffix
    else:
        text = display[:cell_w]
        return colour + text + " " * (cell_w - len(text))


def _fmt_num(n):
    """Format integer with comma thousands separator."""
    if n is None:
        return "—"
    try:
        return "{:,}".format(int(n))
    except (TypeError, ValueError):
        return str(n)


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------
def _build_frame(data):
    """Return list of lines (no newlines), each exactly WIDTH visible chars."""
    c = data or {}
    lines = []

    # Header — blank / centered title / blank, exactly WIDTH cols each
    blank = " " * WIDTH
    title = "Character Panel"
    inner = WIDTH
    lpad  = (inner - len(title)) // 2
    rpad  = inner - len(title) - lpad

    lines.append(blank)
    lines.append(" " * lpad + C_TITLE + title + C_RESET + " " * rpad)
    lines.append(blank)

    # Content rows
    name  = c.get("character") or "—"
    level = c.get("level")
    lines.append(_pair("Name:", name, "Lv:", level if level is not None else "—"))

    sess_xp = c.get("session_xp")
    sess_tp = c.get("session_tp")
    lines.append(_pair("Sess XP:", _fmt_num(sess_xp) if sess_xp is not None else "—",
                        "Sess TP:", _fmt_num(sess_tp) if sess_tp is not None else "—"))

    mood      = c.get("mood")      or "—"
    alertness = c.get("alertness") or "—"
    lines.append(_pair("Mood:", mood, "Alert:", alertness))

    position = c.get("position") or "—"
    sneak    = c.get("sneak")    or "off"
    lines.append(_pair("Pos:", position, "Sneak:", sneak))

    climb = c.get("climb") or "off"
    swim  = c.get("swim")  or "off"
    lines.append(_pair("Climb:", climb, "Swim:", swim))

    game_time      = c.get("game_time")
    time_period    = c.get("time_period")
    time_remaining = c.get("time_remaining")
    lines.append(_time_row(
        game_time if game_time is not None else "—",
        time_period,
        time_remaining,
    ))

    affects    = c.get("affects") or []
    n          = len(affects)
    block_rows = max(4, -(-n // 2))   # ceil(n/2), min 4

    header = "Affected by:"
    lines.append(C_LABEL + header + C_RESET + " " * (WIDTH - len(header)))

    for row in range(block_rows):
        li = row * 2
        ri = li + 1
        left  = _affect_cell(affects[li], LEFT_W)  if li < n else C_RESET + " " * LEFT_W
        right = _affect_cell(affects[ri], RIGHT_W) if ri < n else C_RESET + " " * RIGHT_W
        lines.append(left + C_RESET + " " + right + C_RESET)

    return lines


# ---------------------------------------------------------------------------
# Render one frame to stdout
# ---------------------------------------------------------------------------
def _render(lines):
    out = ["\x1b[H"]
    n = len(lines)
    for i, ln in enumerate(lines):
        out.append(ln)
        out.append("\x1b[K")
        if i < n - 1:
            out.append("\n")
    out.append("\x1b[J")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    global _last_mtime, _last_data, _dirty

    # Hide cursor; restore on SIGTERM/SIGINT
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()

    signal.signal(signal.SIGTERM, lambda s, f: (_restore_cursor(), sys.exit(0)))
    signal.signal(signal.SIGWINCH, _mark_dirty)
    # Ctrl+C in pane: stty -isig handles it; belt-and-suspenders ignore here.
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    while True:
        try:
            mtime = os.stat(STATE_PATH).st_mtime
        except OSError:
            mtime = None

        changed = mtime != _last_mtime
        if changed:
            _last_mtime = mtime
            if mtime is not None:
                try:
                    with open(STATE_PATH, "r") as fh:
                        _last_data = json.load(fh)
                except Exception:
                    pass  # keep last good state; silent recovery

        if changed or _dirty:
            _dirty = False
            lines = _build_frame(_last_data)
            _render(lines)

        time.sleep(POLL_MS)


if __name__ == "__main__":
    main()
