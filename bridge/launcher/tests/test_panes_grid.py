# Unit tests for bridge/launcher/panes_grid.py — the shared pane×colour
# grid render + toggle module backing the launcher and the popup. Tests
# run without prompt_toolkit installed; the module itself imports nothing
# from prompt_toolkit.

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import panes_grid  # noqa: E402
from palette import (  # noqa: E402
    C_ACTIVE,
    C_CURSOR_CELL,
    C_HINT,
    C_ITEM,
    C_PANE_OFF,
    PANE_COLOR_ORDER,
)


def _styles_for_text(frags, text):
    """Yield styles from fragments whose text exactly matches `text`."""
    for f in frags:
        if len(f) >= 2 and f[1] == text:
            yield f[0]


def _sample_rows():
    # Mix of enabled/disabled with different colour selections so each
    # test can pick the row it needs.
    return [
        ("Character",     True,  0),   # row 0 — enabled, Black
        ("Buffs",         False, 0),   # row 1 — disabled
        ("Group",         True,  3),   # row 2 — enabled, Blue (index 3)
        ("Communication", False, 0),   # row 3 — disabled
        ("UI",            True,  6),   # row 4 — enabled, Purple (index 6)
        ("Developer",     False, 0),   # row 5 — disabled
    ]


class TestApplyCellToggle(unittest.TestCase):

    def test_off_pane_click_turns_on_with_that_colour(self):
        self.assertEqual(panes_grid.apply_cell_toggle(False, 0, 3), (True, 3))
        self.assertEqual(panes_grid.apply_cell_toggle(False, 5, 0), (True, 0))

    def test_on_pane_click_active_colour_turns_off(self):
        # The colour_index is preserved on the off transition so the
        # frame can keep showing the previous selection if it wants to;
        # the caller decides whether to honour it after `enabled` flips.
        self.assertEqual(panes_grid.apply_cell_toggle(True, 3, 3), (False, 3))
        self.assertEqual(panes_grid.apply_cell_toggle(True, 0, 0), (False, 0))

    def test_on_pane_click_other_colour_switches_colour(self):
        self.assertEqual(panes_grid.apply_cell_toggle(True, 2, 5), (True, 5))
        self.assertEqual(panes_grid.apply_cell_toggle(True, 0, 6), (True, 6))
        self.assertEqual(panes_grid.apply_cell_toggle(True, 6, 0), (True, 0))


class TestGridWidth(unittest.TestCase):
    def test_grid_width_matches_layout(self):
        # 13-cell label + 2 gap + 7 cells of 6 + 6 inter-column gaps of 1
        # = 13 + 2 + 42 + 6 = 63.
        self.assertEqual(panes_grid.grid_width(), 63)


class TestFragmentsCellColourPrecedence(unittest.TestCase):

    def test_cursor_bracket_paints_gold_on_enabled_row(self):
        # Cursor on row 0 (Character / enabled / colour 0): the checked
        # `[X]` for the active cell should be gold, not bright-white.
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=(0, 0),
        )
        bracket_styles = list(_styles_for_text(frags, "[X]"))
        # Exactly one cell is checked in row 0; it is also the cursor cell.
        self.assertEqual(bracket_styles.count(C_CURSOR_CELL), 1)
        # The other rows have no checked cell shared with the cursor, so
        # any remaining [X] bracket is in the bright-checked colour.
        for style in bracket_styles:
            self.assertIn(style, (C_CURSOR_CELL, C_ACTIVE))

    def test_cursor_bracket_paints_gold_on_disabled_row(self):
        # Cursor on row 1 (Buffs / disabled). Every cell on the row is
        # `[ ]`. The cursor cell's brackets must stay gold; all other
        # cells stay dim so the row reads as off.
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=(1, 4),
        )
        # Walk fragments looking for the bracket fragments on row 1.
        bracket_styles_on_row = _row_bracket_styles(frags, row_idx=1)
        self.assertEqual(len(bracket_styles_on_row), 7)
        # Only the column-4 cell is the cursor.
        self.assertEqual(bracket_styles_on_row[4], C_CURSOR_CELL)
        for i, s in enumerate(bracket_styles_on_row):
            if i != 4:
                self.assertEqual(s, C_PANE_OFF)

    def test_checked_bracket_bright_off_cursor(self):
        # Cursor outside the grid → no cell takes the gold treatment.
        # Row 0 has its [X] bracket painted in C_ACTIVE (bright).
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=None,
        )
        bracket_styles = list(_styles_for_text(frags, "[X]"))
        # Three enabled rows in the sample, each with one checked cell.
        self.assertEqual(len(bracket_styles), 3)
        for s in bracket_styles:
            self.assertEqual(s, C_ACTIVE)

    def test_unchecked_bracket_dim_on_enabled_row(self):
        # On enabled rows, unchecked `[ ]` brackets are C_HINT.
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=None,
        )
        # Pick the brackets specifically on row 0 (Character, enabled).
        bracket_styles_on_row = _row_bracket_styles(frags, row_idx=0)
        # 7 cells, one [X] at column 0, six [ ] at columns 1..6.
        self.assertEqual(bracket_styles_on_row[0], C_ACTIVE)
        for s in bracket_styles_on_row[1:]:
            self.assertEqual(s, C_HINT)

    def test_disabled_row_label_swatches_dim(self):
        # Disabled row label, all brackets and all swatches paint in
        # C_PANE_OFF (cursor is None so nothing escapes the dim treatment).
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=None,
        )
        # The Buffs row label is left-padded to _LABEL_W (13) cells.
        buffs_label = "Buffs".ljust(13)
        buffs_label_styles = list(_styles_for_text(frags, buffs_label))
        self.assertEqual(buffs_label_styles, [C_PANE_OFF])

        # Every bracket on row 1 is dim.
        bracket_styles_on_row = _row_bracket_styles(frags, row_idx=1)
        self.assertTrue(all(s == C_PANE_OFF for s in bracket_styles_on_row))

        # Every swatch on row 1 is dim too — no coloured swatch leaks
        # through on a disabled row.
        swatch_styles_on_row = _row_swatch_styles(frags, row_idx=1)
        self.assertEqual(len(swatch_styles_on_row), 7)
        self.assertTrue(all(s == C_PANE_OFF for s in swatch_styles_on_row))

    def test_enabled_row_label_uses_c_item(self):
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=None,
        )
        char_label = "Character".ljust(13)
        styles = list(_styles_for_text(frags, char_label))
        self.assertEqual(styles, [C_ITEM])

    def test_header_row_styled_c_hint(self):
        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=None,
        )
        # Look for one of the colour names (centred to 6 cells).
        # `Purple` is exactly 6 chars wide so it renders without padding.
        styles = list(_styles_for_text(frags, "Purple"))
        self.assertEqual(styles, [C_HINT])

    def test_cell_handler_attaches_three_tuples(self):
        captured = []

        def make_handler(row_idx, col_idx):
            captured.append((row_idx, col_idx))
            return f"h-{row_idx}-{col_idx}"

        frags = panes_grid.panes_grid_fragments(
            _sample_rows(), term_cols=120, cursor=None,
            cell_handler=make_handler,
        )
        # 6 rows × 7 columns × 2 fragments (bracket + swatch) — but the
        # callback fires once per (row, col) and the handler is reused.
        n_rows = len(_sample_rows())
        n_cols = len(PANE_COLOR_ORDER)
        self.assertEqual(len(captured), n_rows * n_cols)

        # At least one bracket fragment is now a 3-tuple carrying the
        # handler. (Spot-check row 0, column 0.)
        row0_brackets = [
            f for f in frags
            if len(f) == 3 and f[1] in ("[X]", "[ ]") and f[2] == "h-0-0"
        ]
        self.assertEqual(len(row0_brackets), 1)
        # And the matching swatch.
        row0_swatch = [
            f for f in frags
            if len(f) == 3 and f[1] == "███" and f[2] == "h-0-0"
        ]
        self.assertEqual(len(row0_swatch), 1)


def _row_bracket_styles(frags, row_idx):
    """Return the styles of the seven bracket fragments on the given row.

    The grid emits a leading pad fragment + label + label-gap before each
    pane row, then alternating col-gap + bracket + swatch fragments. We
    skip the header row by counting newlines.
    """
    styles = []
    rows_seen = -1   # header row counts as row -1; first "\n" enters row 0.
    for f in frags:
        text = f[1] if len(f) >= 2 else ""
        if text == "\n":
            rows_seen += 1
            continue
        if rows_seen != row_idx:
            continue
        if text in ("[X]", "[ ]"):
            styles.append(f[0])
    return styles


def _row_swatch_styles(frags, row_idx):
    styles = []
    rows_seen = -1
    for f in frags:
        text = f[1] if len(f) >= 2 else ""
        if text == "\n":
            rows_seen += 1
            continue
        if rows_seen != row_idx:
            continue
        if text == "███":
            styles.append(f[0])
    return styles


if __name__ == "__main__":
    unittest.main()
