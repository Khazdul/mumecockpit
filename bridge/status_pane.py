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

    # Header — box drawing, exactly WIDTH cols each
    lines.append(C_FRAME + "┌" + "─" * (WIDTH - 2) + "┐" + C_RESET)
    title  = "Character Panel"
    inner  = WIDTH - 2                          # 31
    lpad   = (inner - len(title)) // 2
    rpad   = inner - len(title) - lpad
    lines.append(
        C_FRAME + "│" + C_RESET
        + " " * lpad + C_TITLE + title + C_RESET + " " * rpad
        + C_FRAME + "│" + C_RESET
    )
    lines.append(C_FRAME + "└" + "─" * (WIDTH - 2) + "┘" + C_RESET)

    # Content rows
    name  = c.get("character") or "—"
    level = c.get("level")
    lines.append(_pair("Name:", name, "Lv:", level if level is not None else "—"))

    xp = _fmt_num(c.get("xp"))
    tp = _fmt_num(c.get("tp"))
    lines.append(_pair("XP:", xp, "TP:", tp))

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

    game_time = c.get("game_time")
    lines.append(_row("Time:", game_time if game_time is not None else "—"))

    lines.append(C_LABEL + "Affected by:" + C_RESET)
    affects = c.get("affects") or []
    if affects:
        for aff in affects:
            line = "  " + str(aff)
            if len(line) > WIDTH:
                line = line[:WIDTH]
            lines.append(C_VALUE + line + C_RESET)
    else:
        lines.append(C_VALUE + "  —" + C_RESET)

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
