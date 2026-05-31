# bridge/launcher/tests/test_timers_layout_grid.py — unit tests for the
# shared Timers-layout grid (render + toggle + cols clamp). Runs without
# prompt_toolkit.

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from timers_layout_grid import (  # noqa: E402
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
    TIMERS_COLOR_ORDER,
    timers_color_hex,
    timers_color_index,
)


def _plain(frags):
    """Concatenate fragment text, ignoring styles/handlers."""
    return "".join(f[1] for f in frags)


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
    for i, (_name, hx) in enumerate(TIMERS_COLOR_ORDER):
        assert timers_color_index(hx) == i
        assert timers_color_hex(i) == hx


def test_timers_color_index_case_insensitive():
    # Charm's default is stored uppercase; it must resolve to Violet (idx 5).
    assert timers_color_index("#B388FF") == 5
    assert timers_color_index("#b388ff") == 5


def test_timers_color_index_unknown_is_zero():
    assert timers_color_index("") == 0
    assert timers_color_index("#123456") == 0
    assert timers_color_index(None) == 0


def test_defaults_land_on_palette_swatches():
    # Every group default colour is a real swatch (the first six entries).
    for typ in TIMERS_LAYOUT_TYPES:
        hx = TIMERS_LAYOUT_DEFAULTS[typ]["color"]
        assert timers_color_index(hx) is not None
        assert timers_color_hex(timers_color_index(hx)).lower() == hx.lower()


# ── grid fragments ─────────────────────────────────────────────────────
def test_grid_width_positive():
    assert grid_width() > 0


def _row(label, enabled, idx, cols, maxc):
    return (label, enabled, idx, cols, maxc)


def test_grid_fragments_row_count_no_header():
    rows = [_row("Spells", True, 0, 4, 6), _row("Charmies", False, 5, 1, 2)]
    frags = timers_grid_fragments(rows, 100, (0, 0))
    text = _plain(frags)
    # No colour-name header row: one newline per group row.
    assert text.count("\n") == 2


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
