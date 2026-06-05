# bridge/launcher/timers_layout_grid.py — shared Timers-layout grid.
#
# Pure module: no prompt_toolkit import, no global state. Imported by both
# launcher.py (Options → Timers layout) and ingame_menu.py (popup Options →
# Timers layout) to render the (group × colour) grid with a trailing per-row
# column stepper that drives bridge/runtime/timers_layout.conf.
#
# Modelled on panes_grid.py (ADR 0086). The colour cells reuse panes_grid's
# palette-agnostic 0-or-1 apply_cell_toggle and the same swatch-cell colour
# grammar (C_ACTIVE / C_HINT / C_CURSOR_CELL / C_PANE_OFF); a disabled row
# paints dim end-to-end as in panes. The extra element here is the inline
# "◄ N ►" stepper that sets each group's column count.
#
# The defaults table and the per-type cols clamp are deliberately restated
# here (and in bridge/panes/timers_pane.py) — the bridge/launcher and
# bridge/panes packages share no import path. See docs/decisions/0126 and
# docs/timers-pane.md.

from palette import (
    C_ACTIVE,
    C_CURSOR_CELL,
    C_HINT,
    C_ITEM,
    C_PANE_OFF,
    TIMERS_COLOR_ORDER,
)
# Re-exported so callers depend on one module for the grid's toggle logic.
from panes_grid import apply_cell_toggle  # noqa: F401

__all__ = [
    "TIMERS_LAYOUT_TYPES",
    "TIMERS_LAYOUT_LABELS",
    "TIMERS_LAYOUT_DEFAULTS",
    "TIMERS_HEADERS_DEFAULT",
    "TIMERS_COMPACT_DEFAULT",
    "max_cols_for",
    "clamp_cols",
    "step_cols",
    "apply_cell_toggle",
    "timers_grid_fragments",
    "grid_width",
]

# ── Config contract (restated from bridge/panes/timers_pane.py) ────────
# Type tokens have no internal underscore (the conf parser splits on the
# last '_' to separate the attribute), so the key is timers_<type>_<attr>.
TIMERS_LAYOUT_TYPES = ("spell", "buff", "debuff", "stored", "blind", "charm")

TIMERS_LAYOUT_LABELS = {
    "spell":  "Spells",
    "buff":   "Buffs",
    "debuff": "Debuffs",
    "stored": "Stored",
    "blind":  "Blinds",
    "charm":  "Charmies",
}

# Defaults reproduce the timers pane's historic hardcoded grid exactly.
TIMERS_LAYOUT_DEFAULTS = {
    "spell":  {"enabled": True, "color": "#66b2ff", "cols": 4},
    "buff":   {"enabled": True, "color": "#00d900", "cols": 4},
    "debuff": {"enabled": True, "color": "#d90000", "cols": 4},
    "stored": {"enabled": True, "color": "#ff66ff", "cols": 4},
    "blind":  {"enabled": True, "color": "#00cccc", "cols": 2},
    "charm":  {"enabled": True, "color": "#B388FF", "cols": 1},
}

# Group header labels above each rendered timer group. This is a GLOBAL toggle,
# not a per-type key: True (default) renders a dim "Group:" label row above each
# rendered (enabled and non-empty) group, which doubles as the separator; False
# reproduces the historic dense layout (no headers, no blank lines). Restated
# here (and in bridge/panes/timers_pane.py) for the same cross-package reason as
# TIMERS_LAYOUT_DEFAULTS — see ADR 0126.
TIMERS_HEADERS_DEFAULT = True

# Blank line between rendered groups. GLOBAL toggle, INDEPENDENT of headers:
# True (default) = compact, no blank lines between groups; False = one blank
# row separates consecutive rendered groups. The four headers×compact
# combinations are documented in docs/timers-pane.md. Restated here (and in
# bridge/panes/timers_pane.py) for the same cross-package reason as
# TIMERS_LAYOUT_DEFAULTS — see ADR 0126.
TIMERS_COMPACT_DEFAULT = True


def max_cols_for(typ):
    """Upper bound on a group's column count: charm → 2, everything else 6."""
    return 2 if typ == "charm" else 6


def clamp_cols(typ, raw):
    """Parse and clamp a cols value: charm → [1, 2]; others → [1, 6]; floor 1.
    Returns None when unparseable so the caller keeps the type's default —
    same contract as timers_pane._clamp_cols."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    lo, hi = (1, max_cols_for(typ))
    return max(lo, min(hi, n))


def step_cols(cols, max_cols, delta):
    """Step a column count by delta, clamped to [1, max_cols]."""
    return max(1, min(max_cols, cols + delta))


# ── Grid geometry ──────────────────────────────────────────────────────
# A colour cell is `[X]███` / `[ ]███` — a 3-cell checkbox plus a 3-cell
# swatch, identical to panes. The trailing stepper is `◄ N ►` (the digit is
# display-only, not a cursor stop). Cursor columns per row: colour cols
# 0..N-1, then ◄ at N and ► at N+1.
_CELL_W    = 6
_COL_GAP   = 1
_LABEL_GAP = 2
_LABEL_W   = 8    # widest group label ("Charmies")
_STEP_GAP  = 2
_STEP_W    = 5    # "◄ N ►" — single-digit N (cols never exceeds 6)


def grid_width():
    """Total horizontal width of the grid (label + swatches + stepper)."""
    n = len(TIMERS_COLOR_ORDER)
    return (_LABEL_W + _LABEL_GAP + n * _CELL_W + (n - 1) * _COL_GAP
            + _STEP_GAP + _STEP_W)


def _swatch_style(colour_index):
    """Solid fill for an enabled colour cell — fg and bg both painted with
    the swatch hex so the cell reads as a flat colour block."""
    hex_color = TIMERS_COLOR_ORDER[colour_index][1]
    return f"bg:{hex_color} fg:{hex_color}"


def _centre_in(text, width):
    """Centre ``text`` within ``width`` cells, truncating when it overflows."""
    if len(text) >= width:
        return text[:width]
    pad = width - len(text)
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def timers_grid_fragments(rows, term_cols, cursor,
                          cell_handler=None, stepper_handler=None):
    """Fragments for a dim colour-name header row, then one row per group:
    label, N colour swatches, and an inline `◄ N ►` column stepper.

    Args:
        rows: iterable of ``(label, enabled, colour_index, cols, max_cols)``.
            ``colour_index`` is ignored when ``enabled`` is False.
        term_cols: terminal width — used to centre the grid.
        cursor: ``(row_idx, col_idx)`` of the focused cell, or ``None`` when
            the cursor sits outside the grid (e.g. on Back). Colour cells are
            cols ``0..N-1``; ``◄`` is col ``N``; ``►`` is col ``N+1``.
        cell_handler: optional ``f(row_idx, col_idx) -> mouse_handler`` for a
            colour cell; its fragments become 3-tuples when provided.
        stepper_handler: optional ``f(row_idx, delta) -> mouse_handler`` where
            ``delta`` is ``-1`` (◄) or ``+1`` (►).

    Cell-colour precedence mirrors the panes grid: cursor cell → gold
    (``C_CURSOR_CELL``); else on an enabled row, checked ``[X]`` → ``C_ACTIVE``,
    unchecked ``[ ]`` → ``C_HINT``; on a disabled row everything paints
    ``C_PANE_OFF`` except the cursor cell which stays gold. The stepper arrows
    follow the same precedence; the digit is never a cursor stop and never
    gold (``C_ITEM`` enabled, ``C_PANE_OFF`` disabled).
    """
    n_cols = len(TIMERS_COLOR_ORDER)
    total_w = grid_width()
    pad = " " * max(0, (term_cols - total_w) // 2)

    frags = []

    # Header row: blank where the labels live, then the colour name centred
    # above each swatch, then "Cols" centred above the ◄ N ► stepper. Styled
    # flat C_HINT (dim) like the panes grid; it carries no mouse handlers and
    # is not a cursor stop — purely a leading rendered line, so the grid's
    # (row_idx, col_idx) mapping is unchanged.
    frags.append(("", pad))
    frags.append(("", " " * (_LABEL_W + _LABEL_GAP)))
    for ci, (name, _hex) in enumerate(TIMERS_COLOR_ORDER):
        if ci > 0:
            frags.append(("", " " * _COL_GAP))
        frags.append((C_HINT, _centre_in(name, _CELL_W)))
    frags.append(("", " " * _STEP_GAP))
    frags.append((C_HINT, _centre_in("Cols", _STEP_W)))
    frags.append(("", "\n"))

    for ri, (label, enabled, colour_index, cols, _max_cols) in enumerate(rows):
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

            swatch_style = C_PANE_OFF if not enabled else _swatch_style(ci)
            bracket = "[X]" if checked else "[ ]"

            if cell_handler is not None:
                h = cell_handler(ri, ci)
                frags.append((bracket_style, bracket, h))
                frags.append((swatch_style, "███", h))
            else:
                frags.append((bracket_style, bracket))
                frags.append((swatch_style, "███"))

        # Inline column stepper: ◄ N ►.
        frags.append(("", " " * _STEP_GAP))

        left_cursor  = (cursor is not None and cursor == (ri, n_cols))
        right_cursor = (cursor is not None and cursor == (ri, n_cols + 1))

        def _arrow_style(is_cur):
            if is_cur:
                return C_CURSOR_CELL
            if not enabled:
                return C_PANE_OFF
            return C_HINT

        left_style  = _arrow_style(left_cursor)
        right_style = _arrow_style(right_cursor)
        num_style   = C_PANE_OFF if not enabled else C_ITEM

        if stepper_handler is not None:
            frags.append((left_style,  "◄", stepper_handler(ri, -1)))
            frags.append((num_style,   f" {cols} "))
            frags.append((right_style, "►", stepper_handler(ri, +1)))
        else:
            frags.append((left_style,  "◄"))
            frags.append((num_style,   f" {cols} "))
            frags.append((right_style, "►"))

        frags.append(("", "\n"))

    return frags
