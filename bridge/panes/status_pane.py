#!/usr/bin/env python3
# bridge/panes/status_pane.py — character status pane renderer.
# prompt_toolkit Application; polls bridge/runtime/status.state every 50 ms.
# Anchor-top: top rows always visible; overflow indicator when clipped.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import asyncio
import atexit
import json
import math
import os
import shutil
import signal
import sys

STATE_PATH = os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "status.state")
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
)
POLL_MS    = 0.05

# ---------------------------------------------------------------------------
# Colour constants (24-bit truecolor ANSI — consumed by _build_frame)
# ---------------------------------------------------------------------------
C_RESET     = "\x1b[0m"
C_NAME      = "\x1b[38;2;192;192;192m"   # row 1 text (fg only)
C_XP_BG     = "\x1b[48;2;0;30;40m"       # XP bar background — baseline (pre-session) segment
C_XP_NEW_BG = "\x1b[48;2;92;15;91m"      # #5C0F5B — session-gain XP segment
C_BG_RST    = "\x1b[49m"                 # reset background only (keep fg)
C_TP_FG     = "\x1b[38;2;0;40;50m"       # TP bar ▀ foreground — baseline (pre-session) segment
C_TP_NEW_FG = "\x1b[38;2;61;10;60m"      # #3D0A3C — session-gain TP segment
C_LABEL     = "\x1b[38;2;128;128;128m"   # data row label foreground
C_VALUE     = "\x1b[38;2;192;192;192m"   # data row value foreground

C_TOG_OFF_LABEL = "\x1b[38;2;83;72;56m"    # #534838 — warm dark brown
C_TOG_ON_LABEL  = "\x1b[38;2;212;160;78m"  # #D4A04E — warm gold (matches overflow indicator)

C_INDICATOR = "fg:#d4a04e italic"   # overflow indicator style

# ---------------------------------------------------------------------------
# Renderer state
# ---------------------------------------------------------------------------
_last_mtime = None
_last_data  = None
_app        = None
_run_active = False


def _term_rows():
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


# ---------------------------------------------------------------------------
# Data-row helpers
# ---------------------------------------------------------------------------
def _col_widths(W):
    base  = (W - 3) // 4
    extra = (W - 3) %  4
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


def _is_on(v):
    return v == "on"


def _render_toggle(label, col_w, on):
    label_eff = label[: max(col_w, 0)]
    pad       = " " * max(col_w - len(label_eff), 0)
    if on:
        return C_TOG_ON_LABEL  + label_eff + C_RESET + pad
    return     C_TOG_OFF_LABEL + label_eff + C_RESET + pad


def _build_toggles_row(c, W):
    c1, c2, c3, c4 = _col_widths(W)
    cells = [
        _render_toggle("SNEAK", c1, _is_on(c.get("sneak"))),
        _render_toggle("RIDE",  c2, _is_on(c.get("ride"))),
        _render_toggle("CLIMB", c3, _is_on(c.get("climb"))),
        _render_toggle("SWIM",  c4, _is_on(c.get("swim"))),
    ]
    return cells[0] + " " + cells[1] + " " + cells[2] + " " + cells[3]


def _build_data_rows(c, W):
    c1, c2, c3, c4 = _col_widths(W)

    def row(l1, v1, l2, v2):
        return (
            C_LABEL + _trunc_label(l1, c1) +
            C_RESET + " " +
            C_VALUE + _trunc_value(v1, c2) +
            C_RESET + " " +
            C_LABEL + _trunc_label(l2, c3) +
            C_RESET + " " +
            C_VALUE + _trunc_value(v2, c4) +
            C_RESET
        )

    wimpy_val = str(int(c["wimpy"])) if c.get("wimpy") is not None else ""

    return [
        row("MOOD:",  c.get("mood"), "ALERTNESS:", c.get("alertness")),
        row("WIMPY:", wimpy_val,     "POSITION:",  c.get("position")),
    ]


def _build_frame(data):
    """Return list of ANSI strings, one per row (no \\e[K/\\e[J/\\e[H)."""
    width = shutil.get_terminal_size().columns
    c = data or {}

    name = c.get("character") or "—"
    name = name.capitalize()
    if len(name) > width:
        name = name[:width]
    padded     = name.center(width)
    xp_prog    = c.get("xp_progress")          or 0.0
    xp_base    = c.get("xp_progress_baseline") or 0.0
    fill_total = int(math.floor(width * xp_prog))
    fill_base  = int(math.floor(width * xp_base))
    fill_base  = max(0, min(fill_base, fill_total))
    row1 = (C_NAME
            + C_XP_BG     + padded[:fill_base]
            + C_XP_NEW_BG + padded[fill_base:fill_total]
            + C_BG_RST    + padded[fill_total:]
            + C_RESET)

    tp_prog     = c.get("tp_progress")          or 0.0
    tp_base     = c.get("tp_progress_baseline") or 0.0
    tp_total    = int(math.floor(width * tp_prog))
    tp_basefill = int(math.floor(width * tp_base))
    tp_basefill = max(0, min(tp_basefill, tp_total))
    row2 = (C_TP_FG     + "▀" * tp_basefill
            + C_TP_NEW_FG + "▀" * (tp_total - tp_basefill)
            + C_RESET    + " " * (width - tp_total))

    blank = " " * width
    return [row1, row2, _build_toggles_row(c, width), blank] + _build_data_rows(c, width)


# ---------------------------------------------------------------------------
# prompt_toolkit text providers
# ---------------------------------------------------------------------------
def _status_text():
    if not _run_active:
        return [("", "")]
    frags = []
    for i, row_ansi in enumerate(_build_frame(_last_data)):
        if i > 0:
            frags.append(("", "\n"))
        frags.extend(to_formatted_text(ANSI(row_ansi)))
    return frags


def _indicator_text():
    if not _run_active:
        return [("", "")]
    total = len(_build_frame(_last_data))
    H     = _term_rows()
    n     = total - (H - 1)
    return [(C_INDICATOR, f"↓ {n} more rows")]


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


async def _poll_state(app):
    global _last_mtime, _last_data, _run_active

    while True:
        try:
            mtime = os.stat(STATE_PATH).st_mtime
        except OSError:
            mtime = None

        if mtime != _last_mtime:
            _last_mtime = mtime
            if mtime is not None:
                try:
                    with open(STATE_PATH, "r") as fh:
                        _last_data = json.load(fh)
                except Exception:
                    pass
            app.invalidate()

        new_run_active = os.path.exists(CONNECTION_STATE_PATH)
        if new_run_active != _run_active:
            _run_active = new_run_active
            app.invalidate()

        await asyncio.sleep(POLL_MS)


kb = KeyBindings()


@kb.add("q")
@kb.add("c-c")
def _quit(event):
    event.app.exit()


def main():
    global _app

    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()
    atexit.register(_restore_cursor)

    rows_window = Window(
        content=FormattedTextControl(_status_text, focusable=False),
        wrap_lines=False,
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text, focusable=False),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _run_active and len(_build_frame(_last_data)) > _term_rows()),
    )

    root   = HSplit([rows_window, indicator_container])
    layout = Layout(root)

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        color_depth=ColorDepth.DEPTH_24_BIT,
    )
    _app = app

    signal.signal(signal.SIGTERM, lambda s, f: (_restore_cursor(), sys.exit(0)))
    signal.signal(signal.SIGINT,  signal.SIG_IGN)

    async def _run():
        poll_task = asyncio.ensure_future(_poll_state(app))
        try:
            await app.run_async()
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
