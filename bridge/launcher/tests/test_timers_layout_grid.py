# bridge/launcher/tests/test_timers_layout_grid.py — unit tests for the
# shared Timers-layout grid (render + toggle + cols clamp). Runs without
# prompt_toolkit.

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from timers_layout_grid import (  # noqa: E402
    TIMERS_COMPACT_DEFAULT,
    TIMERS_HEADERS_DEFAULT,
    TIMERS_LAYOUT_DEFAULTS,
    TIMERS_LAYOUT_LABELS,
    TIMERS_LAYOUT_TYPES,
    apply_cell_toggle,
    clamp_cols,
    grid_width,
    max_cols_for,
    step_cols,
    timers_grid_fragments,
)
from palette import (  # noqa: E402
    C_CURSOR_CELL,
    C_HINT,
    C_PANE_OFF,
    TIMERS_COLOR_ORDER,
    TIMERS_NONE_COLOR,
    timers_color_hex,
    timers_color_index,
)


def _plain(frags):
    """Concatenate fragment text, ignoring styles/handlers."""
    return "".join(f[1] for f in frags)


def _styles_for_text(frags, text):
    """Styles of every fragment whose text exactly matches `text`."""
    return [f[0] for f in frags if len(f) >= 2 and f[1] == text]


# ── apply_cell_toggle (re-exported from panes_grid) ────────────────────
def test_apply_cell_toggle_turns_on_with_colour():
    assert apply_cell_toggle(False, 0, 3) == (True, 3)


def test_apply_cell_toggle_turns_off_keeps_colour():
    # Clicking the active colour turns the group off but remembers the colour.
    assert apply_cell_toggle(True, 4, 4) == (False, 4)


# ── cols clamp / stepper ───────────────────────────────────────────────
def test_max_cols_for():
    assert max_cols_for("charm") == 2
    assert max_cols_for("spell") == 6


def test_clamp_cols_charm_caps_at_two():
    assert clamp_cols("charm", "5") == 2
    assert clamp_cols("charm", "1") == 1


def test_clamp_cols_others_cap_at_six():
    assert clamp_cols("spell", "9") == 6
    assert clamp_cols("spell", "0") == 1   # floor 1


def test_clamp_cols_bad_value_is_none():
    assert clamp_cols("spell", "abc") is None
    assert clamp_cols("spell", None) is None


def test_step_cols_clamps():
    assert step_cols(1, 6, -1) == 1          # floor
    assert step_cols(6, 6, +1) == 6          # ceiling
    assert step_cols(2, 2, +1) == 2          # charm ceiling
    assert step_cols(3, 6, +1) == 4


# ── palette index/hex round trip ───────────────────────────────────────
def test_timers_color_roundtrip():
    # Index 0 is the None column: its hex entry is Python None, its stored
    # token is "none".
    assert timers_color_index(TIMERS_NONE_COLOR) == 0
    assert timers_color_hex(0) == TIMERS_NONE_COLOR
    # Colour columns (index >= 1) round-trip through their #rrggbb hex.
    for i, (_name, hx) in enumerate(TIMERS_COLOR_ORDER):
        if hx is None:
            continue
        assert timers_color_index(hx) == i
        assert timers_color_hex(i) == hx


def test_timers_color_index_none_token():
    # The "none" token (any case) resolves to the None column at index 0.
    assert timers_color_index("none") == 0
    assert timers_color_index("NONE") == 0


def test_timers_color_index_case_insensitive():
    # Charm's default is stored uppercase; it must resolve to Violet (idx 6).
    assert timers_color_index("#B388FF") == 6
    assert timers_color_index("#b388ff") == 6


def test_timers_color_index_unknown_is_zero():
    assert timers_color_index("") == 0
    assert timers_color_index("#123456") == 0
    assert timers_color_index(None) == 0


def test_timers_color_hex_out_of_range_clamps_to_none():
    assert timers_color_hex(-1) == TIMERS_NONE_COLOR
    assert timers_color_hex(len(TIMERS_COLOR_ORDER)) == TIMERS_NONE_COLOR


def test_defaults_land_on_palette_swatches():
    # Every group default colour is a real coloured swatch (never None).
    for typ in TIMERS_LAYOUT_TYPES:
        hx = TIMERS_LAYOUT_DEFAULTS[typ]["color"]
        idx = timers_color_index(hx)
        assert idx >= 1
        assert timers_color_hex(idx).lower() == hx.lower()


def test_global_toggle_defaults():
    # Fresh install (no conf) renders headers on + compact on — identical to
    # the historic dense layout (header + content per group, no blank lines).
    assert TIMERS_HEADERS_DEFAULT is True
    assert TIMERS_COMPACT_DEFAULT is True


# ── grid fragments ─────────────────────────────────────────────────────
def test_grid_width_positive():
    assert grid_width() > 0


def _row(label, enabled, idx, cols, maxc, clock=False, inert_none=False):
    return (label, enabled, idx, cols, maxc, clock, inert_none)


def test_grid_fragments_row_count_with_header():
    rows = [_row("Spells", True, 0, 4, 6), _row("Charmies", False, 5, 1, 2)]
    frags = timers_grid_fragments(rows, 100, (0, 0))
    text = _plain(frags)
    # One leading colour-name header row + one newline per group row.
    assert text.count("\n") == 3


def test_grid_fragments_header_names_and_cols_label():
    rows = [_row("Spells", True, 0, 4, 6)]
    frags = timers_grid_fragments(rows, 100, None)
    text = _plain(frags)
    # Header carries each colour name (Magenta truncates to "Magent") and
    # the "Cols" label above the stepper.
    for name, _hex in TIMERS_COLOR_ORDER:
        assert name[:6] in text
    assert "Cols" in text


def test_grid_fragments_header_is_dim_with_no_handlers():
    rows = [_row("Spells", True, 0, 4, 6)]
    frags = timers_grid_fragments(
        rows, 100, None,
        cell_handler=lambda r, c: (lambda ev: None),
        stepper_handler=lambda r, d: (lambda ev: None),
    )
    # The header is everything up to and including its trailing newline.
    header = []
    for f in frags:
        header.append(f)
        if f[1] == "\n":
            break
    # Colour-name / Cols fragments are styled C_HINT; none carry a handler.
    assert any(f[0] == C_HINT for f in header)
    assert all(len(f) == 2 for f in header)


def test_grid_fragments_has_stepper_and_count():
    rows = [_row("Spells", True, 0, 4, 6)]
    text = _plain(timers_grid_fragments(rows, 100, None))
    assert "◄" in text and "►" in text   # ◄ ►
    assert " 4 " in text                            # current cols digit


def test_grid_fragments_cursor_gold_on_colour_cell():
    rows = [_row("Spells", True, 0, 4, 6)]
    frags = timers_grid_fragments(rows, 100, (0, 0))
    assert C_CURSOR_CELL in [f[0] for f in frags]


def test_grid_fragments_cursor_gold_on_stepper_arrow():
    rows = [_row("Spells", True, 0, 4, 6)]
    n = len(TIMERS_COLOR_ORDER)
    # Cursor on the ► arrow (col N+1) paints gold.
    frags = timers_grid_fragments(rows, 100, (0, n + 1))
    assert C_CURSOR_CELL in [f[0] for f in frags]


def test_grid_fragments_checked_box_present():
    rows = [_row("Spells", True, 2, 4, 6)]
    text = _plain(timers_grid_fragments(rows, 100, None))
    assert "[X]" in text


def test_grid_fragments_disabled_row_no_check():
    rows = [_row("Spells", False, 2, 4, 6)]
    text = _plain(timers_grid_fragments(rows, 100, None))
    assert "[X]" not in text


# ── None column (mirrors the panes black/None column) ──────────────────
def test_first_header_label_is_none():
    # The first colour column is labelled "None", centred in its 6-cell
    # column; no column is labelled "Yellow" any more.
    rows = [_row("Spells", True, 1, 4, 6)]
    frags = timers_grid_fragments(rows, 100, None)
    assert list(_styles_for_text(frags, " None ")) == [C_HINT]
    assert list(_styles_for_text(frags, "Yellow")) == []


def test_none_column_enabled_swatch_is_no_fill():
    # An enabled row's None column (col 0) swatch renders as three plain
    # spaces with an empty style; coloured columns keep their bg:hex fill and
    # no swatch ever paints bg:none.
    rows = [_row("Spells", True, 1, 4, 6)]   # Blue (idx 1) selected
    frags = timers_grid_fragments(rows, 100, None)
    blanks = [f for f in frags if f[1] == "   " and f[0] == ""]
    assert len(blanks) == 1
    assert all("bg:none" not in (f[0] or "") for f in frags)
    # The selected colour swatch still paints a flat bg:hex fg:hex block.
    assert any(f[1] == "███" and "bg:#66b2ff" in (f[0] or "") for f in frags)


def test_none_column_selectable_via_brackets():
    # Selecting None for a non-charm group shows the [X] in col 0; the swatch
    # itself stays blank (selection is carried by the brackets only).
    rows = [_row("Spells", True, 0, 4, 6)]   # None (idx 0) selected
    text = _plain(timers_grid_fragments(rows, 100, None))
    assert "[X]" in text


def test_charmies_none_cell_is_dim_inert_blank():
    # A charm row carries inert_none=True: col 0 renders as a 6-cell dim
    # blank (C_PANE_OFF), never a [X]/swatch, and no cell handler is wired
    # for (charm_row, 0) — identical treatment to the clock=None cell.
    captured = []

    def make_handler(ri, ci):
        captured.append((ri, ci))
        return f"h-{ri}-{ci}"

    rows = [_row("Charmies", True, 1, 1, 2, clock=None, inert_none=True)]
    frags = timers_grid_fragments(rows, 100, None, cell_handler=make_handler)
    # No handler was created for the inert None cell.
    assert (0, 0) not in captured
    # A 6-cell dim blank stands in for the None column.
    assert any(f[0] == C_PANE_OFF and f[1] == "      " for f in frags)


def test_charmies_none_cell_inert_under_cursor():
    # Even with the cursor on (charm_row, 0), the inert None cell stays a dim
    # blank — never gold, never a checkbox.
    rows = [_row("Charmies", True, 1, 1, 2, clock=None, inert_none=True)]
    frags = timers_grid_fragments(rows, 100, (0, 0))
    assert any(f[0] == C_PANE_OFF and f[1] == "      " for f in frags)
    # The cursor never paints the inert blank gold.
    assert C_CURSOR_CELL not in _styles_for_text(frags, "      ")
