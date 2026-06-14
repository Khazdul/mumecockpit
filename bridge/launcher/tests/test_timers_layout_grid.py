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
    timers_color_hex,
    timers_color_index,
)


def _plain(frags):
    """Concatenate fragment text, ignoring styles/handlers."""
    return "".join(f[1] for f in frags)


def _styles_for_text(frags, text):
    """Styles of every fragment whose text exactly matches `text`."""
    return [f[0] for f in frags if len(f) >= 2 and f[1] == text]


def _centre(text, width=5):
    """Centre `text` in `width` cells — mirrors the grid's _centre_in for the
    5-cell Clock / Bar header columns."""
    pad = width - len(text)
    left = pad // 2
    return " " * left + text + " " * (pad - left)


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
    # Every colour column round-trips through its #rrggbb hex.
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


def test_timers_color_hex_out_of_range_clamps_to_first():
    assert timers_color_hex(-1) == TIMERS_COLOR_ORDER[0][1]
    assert timers_color_hex(len(TIMERS_COLOR_ORDER)) == TIMERS_COLOR_ORDER[0][1]


def test_defaults_land_on_palette_swatches():
    # Every group default colour is a real coloured swatch.
    for typ in TIMERS_LAYOUT_TYPES:
        hx = TIMERS_LAYOUT_DEFAULTS[typ]["color"]
        idx = timers_color_index(hx)
        assert timers_color_hex(idx).lower() == hx.lower()


def test_global_toggle_defaults():
    # Fresh install (no conf) renders headers on + compact on — identical to
    # the historic dense layout (header + content per group, no blank lines).
    assert TIMERS_HEADERS_DEFAULT is True
    assert TIMERS_COMPACT_DEFAULT is True


# ── grid fragments ─────────────────────────────────────────────────────
def test_grid_width_positive():
    assert grid_width() > 0


def _row(label, enabled, idx, cols, maxc, clock=False, bar=True):
    return (label, enabled, idx, cols, maxc, clock, bar)


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
    # A disabled row shows no checked colour cell. (Clock and Bar are
    # independent of enabled, so set both off to isolate the colour grid.)
    rows = [_row("Spells", False, 2, 4, 6, clock=False, bar=False)]
    text = _plain(timers_grid_fragments(rows, 100, None))
    assert "[X]" not in text


# ── No None column; col 0 is Blue ──────────────────────────────────────
def test_first_header_label_is_blue():
    # The first colour column is labelled "Blue"; there is no "None" or
    # "Yellow" column any more.
    rows = [_row("Spells", True, 0, 4, 6)]
    frags = timers_grid_fragments(rows, 100, None)
    assert list(_styles_for_text(frags, " Blue ")) == [C_HINT]
    assert list(_styles_for_text(frags, " None ")) == []
    assert list(_styles_for_text(frags, "Yellow")) == []


def test_every_colour_cell_has_a_real_swatch():
    # Every enabled colour cell paints a flat bg:hex fg:hex block; no cell is a
    # blank three-space swatch any more.
    rows = [_row("Spells", True, 0, 4, 6)]   # Blue (idx 0) selected
    frags = timers_grid_fragments(rows, 100, None)
    assert not [f for f in frags if f[1] == "   " and f[0] == ""]
    assert any(f[1] == "███" and "bg:#66b2ff" in (f[0] or "") for f in frags)


# ── Bar column (mirrors the Clock column) ──────────────────────────────
def test_bar_header_label():
    # The far-right column is labelled "Bar", centred in its 5-cell column.
    rows = [_row("Spells", True, 0, 4, 6)]
    frags = timers_grid_fragments(rows, 100, None)
    assert list(_styles_for_text(frags, _centre("Bar"))) == [C_HINT]


def test_bar_checkbox_rendered_checked_and_unchecked():
    on  = _plain(timers_grid_fragments([_row("Spells", True, 0, 4, 6, bar=True)], 100, None))
    off = _plain(timers_grid_fragments([_row("Spells", True, 0, 4, 6, bar=False)], 100, None))
    # Both a Clock and a Bar checkbox: two [X] when both default on… but with
    # clock=False the Clock cell is unchecked, so exactly the Bar cell carries
    # the extra [X] in the bar=True render.
    assert on.count("[X]") == off.count("[X]") + 1


def test_bar_cursor_gold():
    # Cursor on the Bar cell (col N+3) paints gold.
    n = len(TIMERS_COLOR_ORDER)
    frags = timers_grid_fragments([_row("Spells", True, 0, 4, 6)], 100, (0, n + 3))
    assert C_CURSOR_CELL in [f[0] for f in frags]


def test_charmies_bar_cell_is_dim_inert_blank():
    # A charm row carries bar=None: the Bar cell renders as a dim blank
    # (C_PANE_OFF), never a [X], and no bar handler is invoked for it —
    # identical treatment to the clock=None cell.
    captured = []

    def make_bar_handler(ri):
        captured.append(ri)
        return f"bar-{ri}"

    rows = [_row("Charmies", True, 5, 1, 2, clock=None, bar=None)]
    frags = timers_grid_fragments(rows, 100, None, bar_handler=make_bar_handler)
    # No bar handler created for the charm row's inert Bar cell.
    assert captured == []
    # A dim blank stands in for the Bar checkbox.
    assert any(f[0] == C_PANE_OFF and f[1] == _centre("") for f in frags)


def test_charmies_bar_cell_inert_under_cursor():
    # Even with the cursor on the charm Bar cell, it stays a dim blank.
    n = len(TIMERS_COLOR_ORDER)
    rows = [_row("Charmies", True, 5, 1, 2, clock=None, bar=None)]
    frags = timers_grid_fragments(rows, 100, (0, n + 3))
    assert any(f[0] == C_PANE_OFF and f[1] == _centre("") for f in frags)
    assert C_CURSOR_CELL not in _styles_for_text(frags, _centre(""))
