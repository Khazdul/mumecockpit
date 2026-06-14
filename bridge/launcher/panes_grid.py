# bridge/launcher/panes_grid.py — shared pane-options grid (render + toggle).
#
# Pure module: no prompt_toolkit import, no global state. Imported by both
# launcher.py (Options → Panes) and ingame_menu.py (popup Options → Panes)
# to render the (pane × colour) grid that replaces the per-pane subframes.
# See docs/launcher.md "Panes submenu" and docs/decisions/0086-panes-grid.md.

from palette import (
    C_ACTIVE,
    C_CURSOR_CELL,
    C_HINT,
    C_ITEM,
    C_PANE_OFF,
    PANE_COLOR_ORDER,
    pane_color_hex,
    pane_color_label,
)

__all__ = [
    "panes_grid_fragments", "apply_cell_toggle", "grid_width",
    "FRAME_CORNER_VALUES", "frame_corner_label", "next_frame_corner",
]

# ---------------------------------------------------------------------------
# Frame-corner style cycler (shared by launcher + popup, ADR 0073).
# ---------------------------------------------------------------------------
# The ordered set the "Corner style" row cycles through, the display label
# for each, and a wrapping next-value helper. Kept here so both surfaces draw
# their labels and advance their values from one source and can never drift.
FRAME_CORNER_VALUES = ("auto", "quadrant", "block")

_FRAME_CORNER_LABELS = {
    "auto":     "Auto",
    "quadrant": "Quadrant",
    "block":    "Block",
}


def frame_corner_label(value):
    """Display label ('Auto' / 'Quadrant' / 'Block') for a stored value.
    An unknown / missing value falls back to the 'Auto' label."""
    return _FRAME_CORNER_LABELS.get((value or "").strip().lower(), "Auto")


def next_frame_corner(value, delta=1):
    """The next value in FRAME_CORNER_VALUES, wrapping. ``delta`` is the
    step (+1 advances, -1 goes back). An unknown / missing current value is
    treated as the first entry ('auto')."""
    try:
        idx = FRAME_CORNER_VALUES.index((value or "").strip().lower())
    except ValueError:
        idx = 0
    return FRAME_CORNER_VALUES[(idx + delta) % len(FRAME_CORNER_VALUES)]

# Cell layout. A cell is `[X]███` or `[ ]███` — a 3-cell checkbox plus a
# 3-cell colour swatch. Columns are separated by a single space and the row
# label sits in a fixed column to the left.
_CELL_W    = 6
_COL_GAP   = 1
_LABEL_GAP = 2
_LABEL_W   = 13   # widest pane label ("Communication")


def grid_width():
    """Total horizontal width of the grid (label column + gap + cells)."""
    n = len(PANE_COLOR_ORDER)
    return _LABEL_W + _LABEL_GAP + n * _CELL_W + (n - 1) * _COL_GAP


def apply_cell_toggle(enabled, colour_index, col):
    """Pure state transition for one click on cell ``col`` of a pane row
    that is currently ``(enabled, colour_index)``.

    Clicking the active colour of an on pane turns it off; clicking any
    other cell turns the pane on with that colour. Returns the new
    ``(enabled, colour_index)`` tuple.
    """
    if enabled and colour_index == col:
        return (False, colour_index)
    return (True, col)


def panes_grid_fragments(rows, term_cols, cursor, cell_handler=None):
    """Fragments for the colour-name header row plus one row per pane.

    Args:
        rows: iterable of ``(label, enabled, colour_index)`` tuples.
            ``colour_index`` is ignored when ``enabled`` is False.
        term_cols: terminal width — used to centre the grid.
        cursor: ``(row_idx, col_idx)`` of the focused cell, or ``None``
            when the cursor sits outside the grid (e.g. on the headers
            toggle or Back).
        cell_handler: optional ``f(row_idx, col_idx) -> mouse_handler``.
            When provided, each cell's bracket and swatch fragments are
            emitted as 3-tuples carrying the returned handler. Otherwise
            cell fragments are 2-tuples.

    Cell-colour precedence per the spec:
      - Cursor cell ``[ ]`` / ``[X]`` → ``C_CURSOR_CELL`` (gold fg).
      - Else on an enabled row: checked ``[X]`` → ``C_ACTIVE`` (bright),
        unchecked ``[ ]`` → ``C_HINT`` (dim).
      - On a disabled row: everything (label, brackets, swatch) →
        ``C_PANE_OFF``, except the cursor cell's brackets which stay gold.
      - Swatches paint their colour on enabled rows, ``C_PANE_OFF`` on
        disabled rows.
      - The colour-name header row is ``C_HINT``.
    """
    n_cols = len(PANE_COLOR_ORDER)
    total_w = grid_width()
    pad = " " * max(0, (term_cols - total_w) // 2)

    frags = []

    # Header row: blank where the labels live, then colour names centred
    # above each cell column.
    frags.append(("", pad))
    frags.append(("", " " * (_LABEL_W + _LABEL_GAP)))
    for ci, name in enumerate(PANE_COLOR_ORDER):
        if ci > 0:
            frags.append(("", " " * _COL_GAP))
        frags.append((C_HINT, _centre_in(pane_color_label(name), _CELL_W)))
    frags.append(("", "\n"))

    # Pane rows.
    rows = list(rows)
    for ri, (label, enabled, colour_index) in enumerate(rows):
        frags.append(("", pad))
        frags.append((C_ITEM if enabled else C_PANE_OFF,
                      label[:_LABEL_W].ljust(_LABEL_W)))
        frags.append(("", " " * _LABEL_GAP))

        for ci in range(n_cols):
            if ci > 0:
                frags.append(("", " " * _COL_GAP))

            checked = bool(enabled) and colour_index == ci
            is_cursor = (cursor is not None and cursor == (ri, ci))

            if is_cursor:
                bracket_style = C_CURSOR_CELL
            elif not enabled:
                bracket_style = C_PANE_OFF
            else:
                bracket_style = C_ACTIVE if checked else C_HINT

            if not enabled:
                swatch_style, swatch_text = C_PANE_OFF, "███"
            else:
                swatch_style, swatch_text = _enabled_swatch(ci)
            bracket = "[X]" if checked else "[ ]"

            if cell_handler is not None:
                h = cell_handler(ri, ci)
                frags.append((bracket_style, bracket, h))
                frags.append((swatch_style, swatch_text, h))
            else:
                frags.append((bracket_style, bracket))
                frags.append((swatch_style, swatch_text))
        frags.append(("", "\n"))

    return frags


def _centre_in(text, width):
    if len(text) >= width:
        return text[:width]
    pad = width - len(text)
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def _enabled_swatch(colour_index):
    """Return ``(style, text)`` for an enabled-row swatch in the given column.

    Solid fill — both fg and bg painted with the same hex so the cell reads as
    a flat colour block regardless of the terminal's default bg. The terminal-
    default column (``pane_color_hex`` is None) instead renders three plain
    spaces with no bg style, so the swatch matches the actual terminal
    background the pane will take on (bg=default) rather than a misleading
    literal black. Selection stays visible via the gold cursor brackets / [X].
    """
    name = PANE_COLOR_ORDER[colour_index]
    hex_color = pane_color_hex(name)
    if hex_color is None:
        return "", "   "
    return f"bg:{hex_color} fg:{hex_color}", "███"
