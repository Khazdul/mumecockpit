# Character Status pane renderer.
#
# Polls bridge/status.state (JSON) every 50 ms via mtime comparison.
# Redraws in-place using ANSI sequences — no ESC[2J, no flicker.
# Width is read from the live pane size (shutil.get_terminal_size) on every
# render; SIGWINCH sets a dirty flag so the next poll tick redraws.
# Minimum useful width: 29 columns (enforced by the bridge, not here).

import json
import os
import shutil
import signal
import sys
import time

STATE_PATH = os.path.join(os.environ["HOME"], "MUME", "bridge", "status.state")
POLL_MS    = 0.05   # seconds between mtime checks
MIN_WIDTH  = 29     # bridge enforces this floor; renderer trusts the pane size

# ---------------------------------------------------------------------------
# Colour constants (24-bit truecolor)
# ---------------------------------------------------------------------------
C_LABEL  = "\x1b[38;2;154;168;183m"    # #9AA8B7 steel-blue — labels
C_VALUE  = "\x1b[1;97m"                # bold bright white — values
C_RESET  = "\x1b[0m"

C_SUN  = "\x1b[38;2;255;176;0m"     # #FFB000 intense amber gold
C_MOON = "\x1b[38;2;74;144;226m"    # #4A90E2 vivid sky blue

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
def _row(label, value, width):
    """Single row: label left, value left (one space after label), truncated to width."""
    lbl = str(label)
    val = str(value) if value is not None else "—"
    if len(lbl) + 1 + len(val) > width:
        val = val[:max(0, width - len(lbl) - 1)]
    return C_LABEL + lbl + C_RESET + " " + C_VALUE + val + C_RESET


def _pair(l1, v1, l2, v2, width):
    """
    Paired row: l1:v1 on the left half, l2:v2 on the right half.
    lw = width//2, rw = width - 1 - lw, separator = 1 space.
    Total visible = lw + 1 + rw = width.
    """
    lw = width // 2
    rw = width - 1 - lw

    def _half(label, value, w):
        lbl = str(label)
        val = str(value) if value is not None else "—"
        visible = len(lbl) + 1 + len(val)
        if visible > w:
            available = w - len(lbl) - 1
            val = val[:max(0, available)]
        trailing = w - len(lbl) - 1 - len(val)
        return C_LABEL + lbl + C_RESET + " " + C_VALUE + val + C_RESET + " " * max(0, trailing)

    return _half(l1, v1, lw) + " " + _half(l2, v2, rw)


def _time_row(time_str, period, remaining, width):
    """Time row: single full-width at DAY/UNSET; two-column at HOUR/MINUTE."""
    if period is None or remaining is None:
        return _row("Time:", time_str, width)
    lw = width // 2
    rw = width - 1 - lw

    label = "Time:"
    val = str(time_str) if time_str is not None else "—"
    if len(label) + 1 + len(val) > lw:
        val = val[:max(0, lw - len(label) - 1)]
    trailing_left = max(0, lw - len(label) - 1 - len(val))
    left = C_LABEL + label + C_RESET + " " + C_VALUE + val + C_RESET + " " * trailing_left

    icon   = "☼" if period == "day" else "☾"
    colour = C_SUN if period == "day" else C_MOON
    rem    = str(remaining)
    if len(rem) > rw - 2:
        rem = rem[:rw - 2]
    trailing_right = max(0, rw - 2 - len(rem))   # 1=icon, 1=sp
    right = colour + icon + C_RESET + " " + C_VALUE + rem + C_RESET + " " * trailing_right

    return left + " " + right



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
    """Return list of lines (no newlines), each exactly `width` visible chars."""
    width = shutil.get_terminal_size().columns
    lw    = width // 2
    rw    = width - 1 - lw

    c = data or {}
    lines = []

    name  = c.get("character") or "—"
    level = c.get("level")
    lines.append(_pair("Name:", name, "Lv:", level if level is not None else "—", width))

    sess_xp = c.get("session_xp")
    sess_tp = c.get("session_tp")
    lines.append(_pair("Sess XP:", _fmt_num(sess_xp) if sess_xp is not None else "—",
                        "Sess TP:", _fmt_num(sess_tp) if sess_tp is not None else "—", width))

    mood      = c.get("mood")      or "—"
    alertness = c.get("alertness") or "—"
    lines.append(_pair("Mood:", mood, "Alert:", alertness, width))

    position = c.get("position") or "—"
    sneak    = c.get("sneak")    or "off"
    lines.append(_pair("Pos:", position, "Sneak:", sneak, width))

    climb = c.get("climb") or "off"
    swim  = c.get("swim")  or "off"
    lines.append(_pair("Climb:", climb, "Swim:", swim, width))

    game_time      = c.get("game_time")
    time_period    = c.get("time_period")
    time_remaining = c.get("time_remaining")
    lines.append(_time_row(
        game_time if game_time is not None else "—",
        time_period,
        time_remaining,
        width,
    ))

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
