# bridge/launcher/comm_channels.py — shared Communication-channel toggles.
#
# Pure module: no prompt_toolkit import, no global state. Imported by both
# launcher.py (Options → Panes → Communication) and ingame_menu.py (popup
# Options → Panes → Communication) to render the per-channel on/off list and
# to read/write the sparse comm_filters.conf plus the comm_prefs.conf
# show_header flag.
#
# Modelled on panes_grid.py / timers_layout_grid.py. The channel order, the
# per-channel colour hex values, and the display-label overrides are
# deliberately restated here (and live in bridge/panes/comm_pane.py) — the
# bridge/launcher and bridge/panes packages share no import path. See
# docs/decisions/0126 and docs/comm-pane.md.

import os

from palette import (
    C_ACTIVE,
    C_CURSOR_CELL,
    C_ITEM,
    C_PANE_OFF,
)

__all__ = [
    "CHANNEL_ORDER",
    "CHANNEL_COLORS",
    "CHANNEL_DISPLAY",
    "COMM_FILTERS_CONF",
    "COMM_PREFS_CONF",
    "SHOW_HEADER_DEFAULT",
    "channel_label",
    "channel_rows",
    "read_filters",
    "write_filters",
    "read_show_header",
    "write_show_header",
    "toggle_channel",
    "toggle_header",
    "comm_channels_fragments",
    "list_width",
]

# ── Config contract (restated from bridge/panes/comm_pane.py) ──────────
# Channel render order. Filter keys, mouse handlers, and comm_filters.conf
# all stay keyed on the GMCP channel name.
CHANNEL_ORDER = [
    "tales",
    "tells",
    "says",
    "yells",
    "prayers",
    "emotes",
    "whispers",
    "questions",
    "songs",
    "socials",
]

# Per-channel foreground colour, kept in the same "fg:#rrggbb" form as
# comm_pane.py's CHANNEL_COLORS; the swatch fill strips the "fg:" prefix.
CHANNEL_COLORS = {
    "tales":     "fg:#949400",  # 148,148,0
    "tells":     "fg:#008000",  # 0,128,0
    "emotes":    "fg:#008000",
    "says":      "fg:#008f8f",  # 0,143,143
    "yells":     "fg:#640064",  # 100,0,100
    "whispers":  "fg:#965a00",  # 150,90,0
    "prayers":   "fg:#c3c36e",  # 195,195,110
    "songs":     "fg:#b49696",  # 180,150,150
    "questions": "fg:#008f8f",
    "socials":   "fg:#9600a0",  # 150,0,160
}

# Neutral grey for any channel without an explicit colour.
C_VERB_UNKNOWN = "fg:#78909c"

# Display-only overrides for channels whose label must differ from
# name.title(). Unlike comm_pane.py there is no server-caption fallback —
# the launcher has no live comm.state — so a missing key → name.title().
CHANNEL_DISPLAY = {
    "tales": "Narrates",
}

# ── Conf paths ─────────────────────────────────────────────────────────
# Resolved exactly as the other launcher-side conf consumers: this file
# lives in bridge/launcher/, so bridge/runtime is two dirs up + "runtime".
_RUNTIME_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime",
)
COMM_FILTERS_CONF = os.path.join(_RUNTIME_DIR, "comm_filters.conf")
COMM_PREFS_CONF   = os.path.join(_RUNTIME_DIR, "comm_prefs.conf")

# Default for the header toggle when comm_prefs.conf is absent.
SHOW_HEADER_DEFAULT = True


# ── Labels ─────────────────────────────────────────────────────────────
def channel_label(name):
    """Display label for a channel: CHANNEL_DISPLAY override, else title-case."""
    if name in CHANNEL_DISPLAY:
        return CHANNEL_DISPLAY[name]
    return name.title()


def channel_rows(filters):
    """Build the render rows from a sparse filter map: a list of
    ``(name, label, enabled)`` tuples in CHANNEL_ORDER. A name missing from
    ``filters`` renders as enabled."""
    return [
        (name, channel_label(name), filters.get(name, True))
        for name in CHANNEL_ORDER
    ]


# ── comm_filters.conf (sparse: missing key = enabled) ──────────────────
def read_filters(path=None):
    """Read comm_filters.conf into a sparse dict. Missing key = enabled, so
    only explicit ``name=true|false`` lines are stored. Missing file → empty
    dict. Mirrors comm_pane._load_filters."""
    if path is None:
        path = COMM_FILTERS_CONF
    filters = {}
    try:
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line:
                    continue
                name, _, val = line.partition("=")
                if val in ("true", "false"):
                    filters[name] = (val == "true")
    except OSError:
        pass
    return filters


def write_filters(filters, path=None):
    """Atomic write of the sparse filter map (tmp + rename). Only explicit
    keys are written — a name absent from ``filters`` stays enabled by
    omission. Mirrors comm_pane._save_filters."""
    if path is None:
        path = COMM_FILTERS_CONF
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            for name, val in filters.items():
                fh.write(f"{name}={'true' if val else 'false'}\n")
        os.replace(tmp, path)
    except OSError:
        pass


# ── comm_prefs.conf (single key: show_header, default true) ────────────
def read_show_header(path=None):
    """Read ``show_header`` from comm_prefs.conf. Missing file or key →
    SHOW_HEADER_DEFAULT (True)."""
    if path is None:
        path = COMM_PREFS_CONF
    value = SHOW_HEADER_DEFAULT
    try:
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == "show_header" and val.strip() in ("true", "false"):
                    value = (val.strip() == "true")
    except OSError:
        pass
    return value


def write_show_header(value, path=None):
    """Atomic write of comm_prefs.conf with the single ``show_header`` key."""
    if path is None:
        path = COMM_PREFS_CONF
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as fh:
            fh.write(f"show_header={'true' if value else 'false'}\n")
        os.replace(tmp, path)
    except OSError:
        pass


# ── Toggle helpers ─────────────────────────────────────────────────────
def toggle_channel(filters, name):
    """Flip a channel's enabled state in the sparse map (in place) and return
    the new enabled bool. A name missing from ``filters`` counts as enabled,
    so the first toggle writes an explicit False."""
    new_val = not filters.get(name, True)
    filters[name] = new_val
    return new_val


def toggle_header(show_header):
    """Pure flip of the header flag."""
    return not show_header


# ── Render ─────────────────────────────────────────────────────────────
# A row is `[X]███ <Label>` / `[ ]███ <Label>` — a 3-cell checkbox, a 3-cell
# colour swatch, a gap, then the channel label. This echoes the panes grid's
# `[X]███` cell grammar but as a vertical binary list (channels are on/off
# only — no colour columns).
_CHECK_W    = 3
_SWATCH_W   = 3
_SWATCH_GAP = 1
_LABEL_W    = max(len(channel_label(n)) for n in CHANNEL_ORDER)   # "Questions"


def list_width():
    """Total horizontal width of the channel list (checkbox + swatch + label)."""
    return _CHECK_W + _SWATCH_W + _SWATCH_GAP + _LABEL_W


def _swatch_hex(name):
    """Raw ``#rrggbb`` for a channel's swatch — the CHANNEL_COLORS value with
    its ``fg:`` prefix stripped."""
    style = CHANNEL_COLORS.get(name, C_VERB_UNKNOWN)
    return style[len("fg:"):] if style.startswith("fg:") else style


def comm_channels_fragments(rows, term_cols, cursor, row_handler=None):
    """Fragments for the vertical channel on/off list — one row per channel.

    Args:
        rows: iterable of ``(name, label, enabled)`` tuples in render order.
        term_cols: terminal width — used to centre the list.
        cursor: row index of the focused channel, or ``None`` when the cursor
            sits outside the list (e.g. on the header toggle or Back).
        row_handler: optional ``f(row_idx) -> mouse_handler``. When provided,
            the row's fragments are emitted as 3-tuples carrying the returned
            handler; otherwise they are 2-tuples.

    Cell-colour precedence, echoing the panes grid:
      - Cursor row's ``[ ]`` / ``[X]`` brackets → ``C_CURSOR_CELL`` (gold fg).
      - Else enabled ``[X]`` → ``C_ACTIVE`` (bright); disabled ``[ ]`` →
        ``C_PANE_OFF`` (dim).
      - Swatch paints the channel colour when enabled, ``C_PANE_OFF`` when off.
      - Label → ``C_ITEM`` when enabled, ``C_PANE_OFF`` when off.
    """
    total_w = list_width()
    pad = " " * max(0, (term_cols - total_w) // 2)

    frags = []
    for ri, (name, label, enabled) in enumerate(rows):
        is_cursor = (cursor is not None and cursor == ri)

        if is_cursor:
            bracket_style = C_CURSOR_CELL
        elif enabled:
            bracket_style = C_ACTIVE
        else:
            bracket_style = C_PANE_OFF

        if enabled:
            hex_color = _swatch_hex(name)
            swatch_style = f"bg:{hex_color} fg:{hex_color}"
        else:
            swatch_style = C_PANE_OFF
        bracket     = "[X]" if enabled else "[ ]"
        label_style = C_ITEM if enabled else C_PANE_OFF
        label_text  = label[:_LABEL_W].ljust(_LABEL_W)

        frags.append(("", pad))
        if row_handler is not None:
            h = row_handler(ri)
            frags.append((bracket_style, bracket, h))
            frags.append((swatch_style, "███", h))
            frags.append(("", " " * _SWATCH_GAP, h))
            frags.append((label_style, label_text, h))
        else:
            frags.append((bracket_style, bracket))
            frags.append((swatch_style, "███"))
            frags.append(("", " " * _SWATCH_GAP))
            frags.append((label_style, label_text))
        frags.append(("", "\n"))

    return frags
