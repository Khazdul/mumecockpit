#!/usr/bin/env python3
# bridge/panes/pane_frame.py — shared in-pane frame helper for the right-column
# prompt_toolkit panes (ADR 0037).
#
# Wraps a pane's inner content container in a foreground-only border: a top row
# carrying a left-aligned header label, a bottom row, and 1-column left/right
# edges. Drawn with half-block glyphs and the resolved corner glyphs so the
# tmux pane background (select-pane -P bg=) shows through everywhere.
#
# ADR 0126: bridge/panes must not import bridge/launcher. The pane-colour →
# border-colour table and the label map are RESTATED here, not imported from
# palette.py. Keep PANE_BORDER_COLORS mirrored with palette.PANE_COLORS.

import asyncio
import os

from prompt_toolkit.filters import Condition
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_RUNTIME = os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime")
STARTUP_PATH = os.path.join(_RUNTIME, "startup.conf")
LAYOUT_PATH  = os.path.join(_RUNTIME, "layout.conf")

# ---------------------------------------------------------------------------
# Restated constants (do NOT import from bridge/launcher — ADR 0126)
# ---------------------------------------------------------------------------
# Pane-colour name (as stored in startup.conf under pane_color_<key>) → the
# border foreground hex for that tint. A shade or two lighter than the pane bg.
PANE_BORDER_COLORS = {
    "black":  "#2a2a2a",   # terminal default / no bg override
    "grey":   "#2a2a2a",   # #161616
    "red":    "#2e2222",   # #1a0e0e
    "green":  "#222e22",   # #0e1a0e
    "blue":   "#222830",   # #0e141c
    "orange": "#30281e",   # #1c140a
    "purple": "#2a2430",   # #16101c
}
_DEFAULT_BORDER = "#2a2a2a"

# Header label per pane key. Lives on the frame's top border, not in content.
LABELS = {
    "status": "Character",
    "timers": "Timers",
    "group":  "Group",
    "comm":   "Comm",
    "ui":     "UI",
}

# Corner glyph sets: (top-left, top-right, bottom-left, bottom-right).
_CORNERS_QUADRANT = ("▛", "▜", "▙", "▟")  # ▛ ▜ ▙ ▟
_CORNERS_BLOCK    = ("█", "█", "█", "█")  # █ █ █ █

# Half-block edge glyphs.
_TOP_EDGE    = "▀"   # ▀ upper half
_BOTTOM_EDGE = "▄"   # ▄ lower half
_LEFT_EDGE   = "▌"   # ▌ left half
_RIGHT_EDGE  = "▐"   # ▐ right half


# ---------------------------------------------------------------------------
# Cache (refreshed by start_poll; no per-call file I/O)
# ---------------------------------------------------------------------------
_frames_enabled = False
_pane_colors    = {}            # pane_key -> colour name (from startup.conf)
_startup_mtime  = None
_corners        = _CORNERS_BLOCK   # resolved once at import


def _parse_conf(path):
    """Read a trivial key=value config (one per line; # comments) into a dict.
    Returns {} on any read error."""
    out = {}
    try:
        with open(path, "r") as fh:
            raw = fh.read()
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _load_startup():
    """Refresh _frames_enabled and _pane_colors from startup.conf.
    Returns True if anything changed."""
    global _frames_enabled, _pane_colors
    conf = _parse_conf(STARTUP_PATH)

    enabled = conf.get("show_pane_dividers", "1").strip() == "1"
    colors = {}
    for key in LABELS:
        name = conf.get("pane_color_" + key)
        if name is not None:
            colors[key] = name.strip()

    changed = (enabled != _frames_enabled) or (colors != _pane_colors)
    _frames_enabled = enabled
    _pane_colors    = colors
    return changed


def _load_corners():
    """Resolve the corner glyph set ONCE from frame_corners_resolved in
    layout.conf. 'quadrant' → quadrant glyphs; anything else (block, missing,
    invalid) → full blocks. Font changes require a relaunch, so this is not
    polled."""
    conf = _parse_conf(LAYOUT_PATH)
    if conf.get("frame_corners_resolved", "").strip() == "quadrant":
        return _CORNERS_QUADRANT
    return _CORNERS_BLOCK


# Resolve corners and the initial config at import.
_corners = _load_corners()
_load_startup()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def frames_enabled():
    """True when in-pane frames are on (show_pane_dividers=1). Cached."""
    return _frames_enabled


def border_style(pane_key):
    """prompt_toolkit style string ('fg:#xxxxxx') for the pane's border,
    derived from its pane colour. Cached."""
    name = _pane_colors.get(pane_key, "black")
    return "fg:" + PANE_BORDER_COLORS.get(name, _DEFAULT_BORDER)


def corners():
    """The resolved corner glyph set (TL, TR, BL, BR)."""
    return _corners


def inner_width(full_w):
    """Width available to pane content: full_w-2 when framed, else full_w."""
    return full_w - 2 if _frames_enabled else full_w


def inner_height(full_h):
    """Height available to pane content: full_h-2 when framed, else full_h."""
    return full_h - 2 if _frames_enabled else full_h


def _term_cols():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _term_lines():
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


def framed(inner_container, pane_key):
    """Wrap inner_container in the foreground-only border for pane_key.

    When frames_enabled() is False every border collapses (ConditionalContainer)
    and the layout reduces to inner_container at full size."""
    tl, tr, bl, br = _corners
    label = LABELS.get(pane_key, "")

    def _top_text():
        w = _term_cols()
        # <TL> + "▀▀ " + label + " " + "▀"*fill + <TR> == exactly w columns.
        fill = w - 6 - len(label)
        if fill < 0:
            fill = 0
        text = tl + _TOP_EDGE * 2 + " " + label + " " + _TOP_EDGE * fill + tr
        return [(border_style(pane_key), text[:w])]

    def _bottom_text():
        w = _term_cols()
        mid = w - 2
        if mid < 0:
            mid = 0
        return [(border_style(pane_key), bl + _BOTTOM_EDGE * mid + br)]

    top_border = Window(
        content=FormattedTextControl(_top_text, focusable=False),
        height=1,
        dont_extend_height=True,
    )
    bottom_border = Window(
        content=FormattedTextControl(_bottom_text, focusable=False),
        height=1,
        dont_extend_height=True,
    )
    left_border = Window(
        width=1,
        char=_LEFT_EDGE,
        style=lambda: border_style(pane_key),
    )
    right_border = Window(
        width=1,
        char=_RIGHT_EDGE,
        style=lambda: border_style(pane_key),
    )

    on = Condition(frames_enabled)
    return HSplit([
        ConditionalContainer(top_border, filter=on),
        VSplit([
            ConditionalContainer(left_border, filter=on),
            inner_container,
            ConditionalContainer(right_border, filter=on),
        ]),
        ConditionalContainer(bottom_border, filter=on),
    ])


def start_poll(app, interval=0.25):
    """Spawn an asyncio task that re-reads startup.conf on mtime change and
    invalidates the app when frames_enabled / pane colours change. Corners are
    not polled (font changes require a relaunch). Returns the task."""
    async def _poll():
        global _startup_mtime
        while True:
            try:
                mtime = os.stat(STARTUP_PATH).st_mtime
            except OSError:
                mtime = None
            if mtime != _startup_mtime:
                _startup_mtime = mtime
                if _load_startup():
                    app.invalidate()
            await asyncio.sleep(interval)

    return asyncio.ensure_future(_poll())
