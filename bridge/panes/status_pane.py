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

import pane_frame
from pane_frame import inner_height, inner_width

STATE_PATH = os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "status.state")
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
)
POLL_MS    = 0.05

# ---------------------------------------------------------------------------
# Colour constants (24-bit truecolor ANSI — consumed by _build_frame)
# ---------------------------------------------------------------------------
# Everything chromatic is palette-derived per frame from pane_frame.pane_shades
# (track/dim/mid/paneBg/vtext/label/glow), turned into SGR by _fg/_bg
# below, so the pane retints with its colour (and with terminal_bg under
# "None"). Only the structural resets and the (cross-pane) overflow amber are
# fixed here.
C_RESET     = "\x1b[0m"
C_BG_RST    = "\x1b[49m"                 # reset background only (keep fg)

C_INDICATOR = "fg:#d4a04e italic"   # overflow indicator style (shared amber)

# Ordinal step orders. The lowercased state value is matched to its index;
# an unknown/missing value leaves every tick inactive.
MOOD_STEPS  = ["wimpy", "prudent", "normal", "brave", "aggressive", "berserk"]
ALERT_STEPS = ["normal", "careful", "attentive", "vigilant", "paranoid"]
POS_STEPS   = ["sleeping", "resting", "sitting", "standing"]


def _fg(hexcolor):
    """SGR truecolor foreground escape for a #rrggbb string."""
    h = hexcolor.lstrip("#")
    return "\x1b[38;2;%d;%d;%dm" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _bg(hexcolor):
    """SGR truecolor background escape for a #rrggbb string."""
    h = hexcolor.lstrip("#")
    return "\x1b[48;2;%d;%d;%dm" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

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
# Column geometry
# ---------------------------------------------------------------------------
def _col_widths(W):
    base  = (W - 3) // 4
    extra = (W - 3) %  4
    return [base + (1 if i < extra else 0) for i in range(4)]


def _two_cols(W):
    """The gauge block's two column widths. col_left spans caps cells 1+2 (and
    their spacer); col_right spans cells 3+4. The single inter-column spacer
    lands at index c1+c2+1 — exactly the caps cell-2/cell-3 gap — so the gauge
    columns sit directly under the RIDE/CLIMB toggle gap. col_left + 1 +
    col_right == W."""
    c1, c2, c3, c4 = _col_widths(W)
    return c1 + c2 + 1, c3 + c4 + 1


def _is_on(v):
    return v == "on"


# ---------------------------------------------------------------------------
# Toggle row — filled boxes
# ---------------------------------------------------------------------------
def _toggle_box(label, colW, on, glow, track, panebg):
    """One filled toggle cell: label centered in colW, dark `paneBg` label on
    both states. On → bright `glow` box (the active step-tick shade); off →
    darker `track` box (the value-bar shade). Both carry an inverted
    (dark-on-light) label so on reads clearly and off recedes; the box shade
    carries the on/off distinction."""
    if colW <= 0:
        return ""
    t = label[:colW].center(colW)
    return _bg(glow if on else track) + _fg(panebg) + t + C_RESET


def _build_toggles_row(c, W, glow, track, panebg):
    c1, c2, c3, c4 = _col_widths(W)
    cells = [
        _toggle_box("SNEAK", c1, _is_on(c.get("sneak")), glow, track, panebg),
        _toggle_box("RIDE",  c2, _is_on(c.get("ride")),  glow, track, panebg),
        _toggle_box("CLIMB", c3, _is_on(c.get("climb")), glow, track, panebg),
        _toggle_box("SWIM",  c4, _is_on(c.get("swim")),  glow, track, panebg),
    ]
    return cells[0] + " " + cells[1] + " " + cells[2] + " " + cells[3]


# ---------------------------------------------------------------------------
# Gauge block — labels, value bars, step-ticks
# ---------------------------------------------------------------------------
def _label_cell(text, colW, label):
    """Uppercase label centered in colW, no bar background."""
    if colW <= 0:
        return ""
    return _fg(label) + text.upper()[:colW].center(colW) + C_RESET


def _bar_cell(value, colW, track, vtext):
    """The value centered on a full-width `track` bar (fg vtext). A null/empty
    value renders as an empty track bar (no text)."""
    if colW <= 0:
        return ""
    if value is None or value == "":
        return _bg(track) + " " * colW + C_RESET
    return _bg(track) + _fg(vtext) + value[:colW].center(colW) + C_RESET


def _tick_ord(steps, value, colW, glow, track):
    """Step-tick row for an ordinal stat. N ▀ ticks across the column at
    positions round(k*(colW-1)/(N-1)); collisions collapse to one ▀ (first 0,
    last colW-1 and the active index always survive). The tick matching the
    current value glows; the rest are subtle `track`; gaps are spaces. The teeth
    sit on the plain tmux pane background."""
    if colW <= 0:
        return ""
    N = len(steps)
    active = None
    if isinstance(value, str):
        try:
            active = steps.index(value.lower())
        except ValueError:
            active = None
    positions = [0 if N <= 1 else round(k * (colW - 1) / (N - 1)) for k in range(N)]
    active_pos = positions[active] if active is not None else None
    tickset = set(positions)
    glow_e, track_e = _fg(glow), _fg(track)
    out = C_BG_RST
    for i in range(colW):
        if i in tickset:
            out += (glow_e if i == active_pos else track_e) + "▀"
        else:
            out += " "
    return out + C_RESET


def _tick_wimpy(wimpy, maxhp, colW, glow):
    """Continuous wimpy caret: a single glow `^` at round(frac*(colW-1)),
    frac = wimpy / maxhp. Hidden entirely (all spaces) when wimpy is null or
    maxhp is null/0. No inactive ticks. Caret sits on the plain tmux pane
    background."""
    if colW <= 0:
        return ""
    caret = None
    if wimpy is not None and maxhp:
        frac = max(0.0, min(1.0, wimpy / maxhp))
        caret = round(frac * (colW - 1))
    glow_e = _fg(glow)
    out = C_BG_RST
    for i in range(colW):
        out += (glow_e + "^") if i == caret else " "
    return out + C_RESET


def _ord_val(v):
    """Lowercased ordinal value for a bar, or None when absent."""
    return v.lower() if isinstance(v, str) and v else None


def _row(left, right):
    """Join two column cells with the single unstyled inter-column spacer."""
    return left + " " + right


def _build_frame(data):
    """Return list of ANSI strings, one per row (no \\e[K/\\e[J/\\e[H)."""
    width = inner_width(shutil.get_terminal_size().columns)
    c = data or {}

    # Resolve the pane's shade ramp once per frame from the same pane-colour
    # value the frame border uses. track = bar bg / XP baseline / toggle
    # off-box; dim = XP session-gain bg / TP baseline / gauge labels; mid = TP
    # session-gain; glow = active step-tick / toggle on-box; paneBg = dark text
    # / tick background / toggle box label; label = level badge / player name.
    # Gauge labels use the very-dark `dim` shade — legible but receding under
    # the frame title.
    shades    = pane_frame.pane_shades("status")
    track     = shades["track"]
    dim       = shades["dim"]
    mid       = shades["mid"]
    panebg    = shades["paneBg"]
    vtext     = shades["vtext"]
    label     = shades["label"]
    glow      = shades["glow"]
    xp_bg     = _bg(track)   # XP bar background — baseline segment
    xp_new_bg = _bg(dim)     # XP bar background — session-gain segment
    tp_fg     = _fg(dim)     # TP bar ▀ fg — baseline segment
    tp_new_fg = _fg(mid)     # TP bar ▀ fg — session-gain segment

    name = c.get("character") or "—"
    name = name.capitalize()
    if len(name) > width:
        name = name[:width]
    padded     = name.center(width)
    xp_prog    = c.get("xp_progress")          or 0.0
    xp_base    = c.get("xp_progress_baseline") or 0.0
    fill_total = int(math.floor(width * xp_prog))
    fill_total = max(0, min(fill_total, width))
    fill_base  = int(math.floor(width * xp_base))
    fill_base  = max(0, min(fill_base, fill_total))

    # Overlay the level right-aligned into the name row's rightmost cells (just
    # inside the top-right corner). The name stays centered; the XP background
    # still shows behind the level cells, and the level keeps the `label` shade.
    # Null level → nothing overlaid. (Char names are short, so a centered name
    # won't reach these cells in practice; if it ever does, level wins them.)
    level = c.get("level")
    lstart = width
    display = padded
    if level is not None:
        ltext = ("L" + str(level))[:width]
        lstart = width - len(ltext)
        display = padded[:lstart] + ltext
    level_fg = _fg(label)
    name_fg  = _fg(label)   # name matches the level badge shade

    # Emit the row in segments split at every XP-background boundary and at the
    # level-overlay start, so background (xp_bg/xp_new_bg/none) and foreground
    # (name vs level) stay independent.
    bounds = sorted({0, fill_base, fill_total, lstart, width})
    row1 = ""
    for a, b in zip(bounds, bounds[1:]):
        if a >= b:
            continue
        seg_bg = xp_bg if a < fill_base else xp_new_bg if a < fill_total else C_BG_RST
        seg_fg = level_fg if a >= lstart else name_fg
        row1 += seg_bg + seg_fg + display[a:b]
    row1 += C_RESET

    tp_prog     = c.get("tp_progress")          or 0.0
    tp_base     = c.get("tp_progress_baseline") or 0.0
    tp_total    = int(math.floor(width * tp_prog))
    tp_basefill = int(math.floor(width * tp_base))
    tp_basefill = max(0, min(tp_basefill, tp_total))
    row2 = (tp_fg     + "▀" * tp_basefill
            + tp_new_fg + "▀" * (tp_total - tp_basefill)
            + C_RESET   + " " * (width - tp_total))

    toggles = _build_toggles_row(c, width, glow, track, panebg)

    colL, colR = _two_cols(width)
    mood, alert, pos = c.get("mood"), c.get("alertness"), c.get("position")
    wimpy, maxhp     = c.get("wimpy"), c.get("maxhp")
    wimpy_val = str(int(wimpy)) if wimpy is not None else None

    return [
        row1,
        row2,
        toggles,
        _row(_label_cell("MOOD", colL, dim),
             _label_cell("ALERTNESS", colR, dim)),
        _row(_bar_cell(_ord_val(mood), colL, track, vtext),
             _bar_cell(_ord_val(alert), colR, track, vtext)),
        _row(_tick_ord(MOOD_STEPS, mood, colL, glow, track),
             _tick_ord(ALERT_STEPS, alert, colR, glow, track)),
        _row(_label_cell("POSITION", colL, dim),
             _label_cell("WIMPY", colR, dim)),
        _row(_bar_cell(_ord_val(pos), colL, track, vtext),
             _bar_cell(wimpy_val, colR, track, vtext)),
        _row(_tick_ord(POS_STEPS, pos, colL, glow, track),
             _tick_wimpy(wimpy, maxhp, colR, glow)),
    ]


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
    H     = inner_height(_term_rows())
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
        filter=Condition(
            lambda: _run_active
            and len(_build_frame(_last_data)) > inner_height(_term_rows())
        ),
    )

    inner_root = HSplit([rows_window, indicator_container])
    root       = pane_frame.framed(inner_root, "status")
    layout     = Layout(root)

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
        poll_task  = asyncio.ensure_future(_poll_state(app))
        frame_task = pane_frame.start_poll(app)
        try:
            await app.run_async()
        finally:
            poll_task.cancel()
            frame_task.cancel()
            for t in (poll_task, frame_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
