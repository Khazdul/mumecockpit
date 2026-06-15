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
import re
import sys

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
    "grey":   "#2a2a2a",   # #161616
    "red":    "#2e2222",   # #1a0e0e
    "green":  "#222e22",   # #0e1a0e
    "blue":   "#222830",   # #0e141c
    "orange": "#30281e",   # #1c140a
    "purple": "#2a2430",   # #16101c
}
_DEFAULT_BORDER = "#2a2a2a"

# Per-palette (hue, saturation) for the pane shade ramp (pane_shades). Restated
# here, like PANE_BORDER_COLORS, rather than imported from bridge/launcher
# (ADR 0126). The hue/saturation match the pane bg/border family (ADR 0086);
# pane_shades walks the ramp by HSL lightness only, keeping a single hue.
PANE_SHADE_HS = {
    "red":    (2,   60),
    "green":  (130, 42),
    "blue":   (210, 58),
    "grey":   (0,   0),
    "orange": (28,  62),
    "purple": (278, 46),
}

# The terminal-default ("black"/None) pane has no bg override, so its border is
# derived from the live terminal background (layout.conf terminal_bg, the same
# source apply_border_style.sh uses) rather than a static grey — a touch lighter
# than the terminal so it reads as a frame, not a fill. On a black terminal this
# yields #141414, visibly darker than the grey pane's #2a2a2a.
_TERMINAL_DEFAULT_NAMES = ("black",)


def lighten(hexcolor, delta=0x14):
    """Lighten a #rrggbb hex colour by adding ``delta`` to each channel, clamped
    at 0xFF. Returns a #rrggbb string."""
    h = hexcolor.lstrip("#")
    r = min(0xFF, int(h[0:2], 16) + delta)
    g = min(0xFF, int(h[2:4], 16) + delta)
    b = min(0xFF, int(h[4:6], 16) + delta)
    return "#%02x%02x%02x" % (r, g, b)


def _hsl_to_hex(h, s, l):
    """Convert HSL (h in degrees, s and l in percent 0-100) to a #rrggbb string.
    Used by pane_shades to walk a single hue down its lightness ramp."""
    h = (h % 360) / 360.0
    s = max(0.0, min(100.0, s)) / 100.0
    l = max(0.0, min(100.0, l)) / 100.0
    if s == 0:
        r = g = b = l
    else:
        def _channel(p, q, t):
            t %= 1.0
            if t < 1 / 6:
                return p + (q - p) * 6 * t
            if t < 1 / 2:
                return q
            if t < 2 / 3:
                return p + (q - p) * (2 / 3 - t) * 6
            return p

        q = l * (1 + s) if l < 0.5 else l + s - l * s
        p = 2 * l - q
        r = _channel(p, q, h + 1 / 3)
        g = _channel(p, q, h)
        b = _channel(p, q, h - 1 / 3)
    return "#%02x%02x%02x" % (
        int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    )


def _hex_to_hs(hexcolor):
    """Convert a #rrggbb string to its (hue degrees, saturation percent) pair —
    the inputs pane_shades feeds back into _hsl_to_hex. Lightness is discarded
    (the ramp supplies its own). Returns (0, 0) for a non-#rrggbb literal so a
    missing/garbled value collapses to a neutral grey ramp."""
    if not _HEX_RE.match(hexcolor or ""):
        return (0, 0)
    h = hexcolor.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return (0, 0)  # achromatic: hue undefined, saturation 0
    d = mx - mn
    s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
    if mx == r:
        hue = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        hue = (b - r) / d + 2
    else:
        hue = (r - g) / d + 4
    return (hue * 60.0, s * 100.0)

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
# Derived pane key
# ---------------------------------------------------------------------------
# The border state is per-pane (border_<key> in startup.conf), so each pane
# process must know which key it owns. Derive it from the running script's
# filename: status_pane.py → "status". A name that is not one of the framed
# keys (e.g. dev, or an unexpected entry point) yields None, and the border
# resolves to off — safe by default.
def _derive_pane_key():
    try:
        name = os.path.basename(sys.argv[0])
    except (IndexError, TypeError):
        return None
    suffix = "_pane.py"
    if name.endswith(suffix):
        key = name[: -len(suffix)]
        if key in LABELS:
            return key
    return None


_PANE_KEY = _derive_pane_key()

# ---------------------------------------------------------------------------
# Cache (refreshed by start_poll; no per-call file I/O)
# ---------------------------------------------------------------------------
# Border-relevant startup.conf subset: border_<key> for each framed pane plus
# the retired show_pane_dividers fallback. frames_enabled() resolves the
# per-pane contract against this cache.
_border_conf    = {}
_pane_colors    = {}            # pane_key -> colour name (from startup.conf)
_startup_mtime  = None
_layout_mtime   = None
_corners        = _CORNERS_BLOCK   # refreshed from layout.conf by start_poll
_terminal_bg    = "#000000"        # from layout.conf; read once at import (set at startup)


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
    """Refresh the border-relevant conf subset and _pane_colors from
    startup.conf. Returns True if anything changed."""
    global _border_conf, _pane_colors
    conf = _parse_conf(STARTUP_PATH)

    border = {}
    for key in LABELS:
        bkey = "border_" + key
        if bkey in conf:
            border[bkey] = conf[bkey].strip()
    if "show_pane_dividers" in conf:
        border["show_pane_dividers"] = conf["show_pane_dividers"].strip()

    colors = {}
    for key in LABELS:
        name = conf.get("pane_color_" + key)
        if name is not None:
            colors[key] = name.strip()

    changed = (border != _border_conf) or (colors != _pane_colors)
    _border_conf = border
    _pane_colors = colors
    return changed


def _load_corners():
    """Resolve the corner glyph set from frame_corners_resolved in
    layout.conf. 'quadrant' → quadrant glyphs; anything else (block, missing,
    invalid) → full blocks. Polled by start_poll so a live corner-style change
    (popup Panes → Corner style) re-renders without a relaunch."""
    conf = _parse_conf(LAYOUT_PATH)
    if conf.get("frame_corners_resolved", "").strip() == "quadrant":
        return _CORNERS_QUADRANT
    return _CORNERS_BLOCK


def _reload_corners():
    """Refresh the cached corner glyph set from layout.conf.
    Returns True if it changed."""
    global _corners
    new = _load_corners()
    if new != _corners:
        _corners = new
        return True
    return False


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _load_terminal_bg():
    """Read terminal_bg from layout.conf (the OSC-11 / startup value, ADR 0099).
    Falls back to #000000 when absent or not a #rrggbb literal. terminal_bg is
    set once at startup, so this is read once at import — no polling needed."""
    val = _parse_conf(LAYOUT_PATH).get("terminal_bg", "").strip()
    return val if _HEX_RE.match(val) else "#000000"


# Resolve corners, terminal_bg, and the initial config at import.
_corners = _load_corners()
_terminal_bg = _load_terminal_bg()
_load_startup()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def frames_enabled(pane_key=None):
    """True when the pane's in-pane frame is on, per the border-resolution
    contract (restated independently, ADR 0126): border_<key>=1 → on; when
    border_<key> is absent fall back to show_pane_dividers (the retired global
    key); when that is also absent default to on. A pane_key that is not one
    of the framed keys (dev / unknown, including the derived None) → off.
    ``pane_key`` defaults to the derived key for this pane process. Cached."""
    key = pane_key if pane_key is not None else _PANE_KEY
    if key not in LABELS:
        return False
    v = _border_conf.get("border_" + key)
    if v is not None:
        return v == "1"
    v = _border_conf.get("show_pane_dividers")
    if v is not None:
        return v == "1"
    return True


def border_color(pane_key):
    """Hex colour ('#rrggbb') used for the pane's border line and header label,
    derived from its pane colour. Shared by border_style and exposed so a pane
    can tint in-content elements (e.g. gauge labels) to match its frame title.
    Cached."""
    name = _pane_colors.get(pane_key, "black")
    if name in _TERMINAL_DEFAULT_NAMES:
        # No bg override: derive the border from the live terminal background.
        return lighten(_terminal_bg, 0x14)
    return PANE_BORDER_COLORS.get(name, _DEFAULT_BORDER)


def border_style(pane_key):
    """prompt_toolkit style string ('fg:#xxxxxx') for the pane's border,
    derived from its pane colour. Cached."""
    return "fg:" + border_color(pane_key)


def pane_shades(pane_key, term_bg=None):
    """Five-shade ramp for a pane, derived by HSL from its configured pane
    colour's hue/saturation (PANE_SHADE_HS, restated — ADR 0126). One hue,
    walked down its lightness ramp. Keys:

      track  L15 — bar background / XP baseline bg
      dim    L27 — XP session-gain bg / TP baseline fg / gauge labels /
                   toggle off-box bg
      mid    L42 — TP session-gain fg
      box_on L37 — toggle on-box bg
      paneBg L8  — near-bg dark text / tick bg / toggle box label (on and off)
      vtext  L72 — gauge value text
      label  L60 — level badge (on the name row) / player name
      glow   L64 — active highlight: active step-tick, wimpy caret

    For the terminal-default ('black'/None) pane — and any unknown colour — the
    hue/saturation come from ``term_bg`` (the live terminal background, ADR 0099)
    instead of the palette, so the bars track a tinted terminal. A neutral /
    black terminal background has saturation ≈ 0, so the ramp collapses to the
    same greys as the chromatic-free case (no regression, including the ConPTY
    black fallback); a missing/garbled value falls back to neutral too.
    ``term_bg`` defaults to the live terminal background. Cached pane-colour
    lookup; no file I/O."""
    if term_bg is None:
        term_bg = _terminal_bg
    name = _pane_colors.get(pane_key, "black")
    if name in _TERMINAL_DEFAULT_NAMES or name not in PANE_SHADE_HS:
        h, s = _hex_to_hs(term_bg)
    else:
        h, s = PANE_SHADE_HS[name]
    return {
        "track":  _hsl_to_hex(h, max(s - 8,  0), 15),
        "dim":    _hsl_to_hex(h, s,              27),
        "mid":    _hsl_to_hex(h, s,              42),
        "box_on": _hsl_to_hex(h, s,              37),
        "paneBg": _hsl_to_hex(h, s,              8),
        "vtext":  _hsl_to_hex(h, max(s - 30, 0), 72),
        "label":  _hsl_to_hex(h, max(s - 22, 0), 60),
        "glow":   _hsl_to_hex(h, max(s - 18, 0), 64),
    }


def corners():
    """The resolved corner glyph set (TL, TR, BL, BR)."""
    return _corners


def inner_width(full_w):
    """Width available to pane content: full_w-2 when framed, else full_w.
    Resolves against this pane's derived key."""
    return full_w - 2 if frames_enabled() else full_w


def inner_height(full_h):
    """Height available to pane content: full_h-2 when framed, else full_h.
    Resolves against this pane's derived key."""
    return full_h - 2 if frames_enabled() else full_h


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
    label = LABELS.get(pane_key, "")

    # Read corners() at render time (not once at build time) so a live
    # corner-style change picked up by start_poll re-renders the glyphs.
    def _top_text():
        tl, tr, _bl, _br = corners()
        w = _term_cols()
        bstyle = border_style(pane_key)

        # <TL> + "▀▀ " + label + " " + "▀"*fill + <TR> == exactly w columns.
        fill = w - 6 - len(label)
        if fill < 0:
            fill = 0
        text = tl + _TOP_EDGE * 2 + " " + label + " " + _TOP_EDGE * fill + tr
        return [(bstyle, text[:w])]

    def _bottom_text():
        _tl, _tr, bl, br = corners()
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

    on = Condition(lambda: frames_enabled(pane_key))
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
    """Spawn an asyncio task that re-reads startup.conf and layout.conf on
    mtime change and invalidates the app when frames_enabled / pane colours
    (startup.conf) or the resolved corner glyphs (layout.conf
    frame_corners_resolved) change. The latter lets a live corner-style change
    re-render the corners without a relaunch. Returns the task."""
    async def _poll():
        global _startup_mtime, _layout_mtime
        while True:
            invalidate = False

            try:
                smtime = os.stat(STARTUP_PATH).st_mtime
            except OSError:
                smtime = None
            if smtime != _startup_mtime:
                _startup_mtime = smtime
                if _load_startup():
                    invalidate = True

            try:
                lmtime = os.stat(LAYOUT_PATH).st_mtime
            except OSError:
                lmtime = None
            if lmtime != _layout_mtime:
                _layout_mtime = lmtime
                if _reload_corners():
                    invalidate = True

            if invalidate:
                app.invalidate()
            await asyncio.sleep(interval)

    return asyncio.ensure_future(_poll())
