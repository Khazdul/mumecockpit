# Character Status pane renderer.
#
# Polls bridge/status.state (JSON) every 50 ms via mtime comparison.
# Redraws in-place using ANSI sequences — no ESC[2J, no flicker.
# Width is read from the live pane size (shutil.get_terminal_size) on every
# render; SIGWINCH sets a dirty flag so the next poll tick redraws.
# Minimum useful width: 29 columns (enforced by the bridge, not here).

import json
import math
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
C_RESET  = "\x1b[0m"
C_NAME   = "\x1b[38;2;192;192;192m"   # row 1 text (fg only)
C_XP_BG  = "\x1b[48;2;0;30;40m"     # XP bar background
C_BG_RST = "\x1b[49m"                 # reset background only (keep fg)
C_TP_FG  = "\x1b[38;2;0;40;50m"      # TP bar ▀ foreground
C_LABEL  = "\x1b[38;2;128;128;128m"   # data row label foreground
C_VALUE  = "\x1b[38;2;192;192;192m"   # data row value foreground

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
# Data-row helpers
# ---------------------------------------------------------------------------
def _col_widths(W):
    base  = (W - 1) // 4
    extra = (W - 1) %  4
    return [base + (1 if i < extra else 0) for i in range(4)]


def _trunc_label(full, w):
    if len(full) <= w:
        return full.ljust(w)
    return (full[:-1][:max(w - 1, 0)] + ":").ljust(w)


def _trunc_value(value, w):
    s = (value or "").lower()
    return s[:w].ljust(w)


def _fmt_sess(n):
    if n is None: return ""
    if n < 1000:  return str(int(n))
    return "{:.1f}k".format(n / 1000.0)


def _build_data_rows(c, W):
    c1, c2, c3, c4 = _col_widths(W)

    def row(l1, v1, l2, v2):
        return (
            C_LABEL + _trunc_label(l1, c1) +
            C_VALUE + _trunc_value(v1, c2) +
            C_RESET + " " +
            C_LABEL + _trunc_label(l2, c3) +
            C_VALUE + _trunc_value(v2, c4) +
            C_RESET
        )

    level_val = str(int(c["level"])) if c.get("level") is not None else ""
    wimpy_val = str(int(c["wimpy"])) if c.get("wimpy") is not None else ""

    return [
        row("RACE:",      c.get("race"),      "LEVEL:",  level_val),
        row("MOOD:",      c.get("mood"),      "SES-XP:", _fmt_sess(c.get("session_xp"))),
        row("ALERTNESS:", c.get("alertness"), "SES-TP:", _fmt_sess(c.get("session_tp"))),
        row("POSITION:",  c.get("position"),  "WIMPY:",  wimpy_val),
    ]


# ---------------------------------------------------------------------------
# Frame builder
# ---------------------------------------------------------------------------
def _build_frame(data):
    """Return list of lines (no newlines), each exactly `width` visible chars."""
    width = shutil.get_terminal_size().columns
    c = data or {}

    # Row 1: centered name with left-anchored XP-progress background
    name = c.get("character") or "—"
    name = name.capitalize()
    if len(name) > width:
        name = name[:width]
    padded   = name.center(width)
    xp_prog  = c.get("xp_progress") or 0.0
    fill     = int(math.floor(width * xp_prog))
    row1 = C_NAME + C_XP_BG + padded[:fill] + C_BG_RST + padded[fill:] + C_RESET

    # Row 2: TP-progress ▀ thin bar
    tp_prog = c.get("tp_progress") or 0.0
    tp_fill = int(math.floor(width * tp_prog))
    row2 = C_TP_FG + "▀" * tp_fill + C_RESET + " " * (width - tp_fill)

    return [row1, row2] + _build_data_rows(c, width)


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
