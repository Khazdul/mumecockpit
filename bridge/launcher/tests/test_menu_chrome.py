# Unit tests for bridge/launcher/menu_chrome.py — the shared title /
# footer / button-cell helpers used by the launcher and the in-game
# popup. Tests run without prompt_toolkit installed (the module itself
# imports nothing from prompt_toolkit).

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import menu_chrome  # noqa: E402
from palette import (  # noqa: E402
    C_ACTIVE,
    C_BUTTON_ACTIVE_FOCUSED,
    C_BUTTON_ACTIVE_UNFOCUSED,
    C_BUTTON_DISABLED,
    C_BUTTON_INACTIVE,
    C_CURSOR_CELL,
    C_HINT,
    C_HOVER,
    C_ITEM,
    C_SECTION,
)


def _count_blank_rows(frags):
    """Count `("", "\\n")` tuples — each is one blank visual row."""
    return sum(1 for f in frags if f == ("", "\n"))


def _title_index(frags):
    """Index of the styled title fragment (the `(C_SECTION, title)` tuple)."""
    for i, f in enumerate(frags):
        if len(f) >= 2 and f[0] == C_SECTION:
            return i
    raise AssertionError("no title fragment found")


class TestTitleBlock(unittest.TestCase):
    def test_blank_above_launcher(self):
        # blank_above=2 → two blanks, padding, title, two trailing newlines
        # (title-row terminator + trailing blank row) → total blank_rows = 4.
        frags = menu_chrome.title_block("─── Panes ───", 80, 2)
        # Two blank rows before, plus the title-row terminator, plus the
        # trailing blank row.
        self.assertEqual(_count_blank_rows(frags), 4)

    def test_blank_above_popup(self):
        # blank_above=1 → one blank, title row terminator, trailing blank
        # → 3 total newline-only fragments.
        frags = menu_chrome.title_block("─── Panes ───", 80, 1)
        self.assertEqual(_count_blank_rows(frags), 3)

    def test_blank_above_zero(self):
        frags = menu_chrome.title_block("─── x ───", 20, 0)
        # No leading blanks: just title-row + trailing blank → 2 newlines.
        self.assertEqual(_count_blank_rows(frags), 2)
        # The first non-newline fragment is the padding.
        self.assertEqual(frags[0][0], "")

    def test_title_styled_with_c_section(self):
        frags = menu_chrome.title_block("─── x ───", 20, 1)
        idx = _title_index(frags)
        self.assertEqual(frags[idx], (C_SECTION, "─── x ───"))

    def test_title_centred(self):
        title = "─── Panes ───"
        frags = menu_chrome.title_block(title, 40, 2)
        idx = _title_index(frags)
        # The fragment immediately before the title is the left-pad string.
        pad_text = frags[idx - 1][1]
        self.assertEqual(len(pad_text), (40 - len(title)) // 2)
        self.assertTrue(set(pad_text) <= {" "})

    def test_title_no_pad_when_overflowing(self):
        # When title is wider than term_cols the helper returns zero pad,
        # not a negative-width string (would otherwise crash on `" " * -1`
        # — Python returns "" for negative repeats, but the contract is
        # to use max(0, …) defensively).
        title = "x" * 40
        frags = menu_chrome.title_block(title, 10, 1)
        idx = _title_index(frags)
        self.assertEqual(frags[idx - 1][1], "")


class TestTitleBlockHeight(unittest.TestCase):
    def test_height_formula(self):
        self.assertEqual(menu_chrome.title_block_height(0), 2)
        self.assertEqual(menu_chrome.title_block_height(1), 3)
        self.assertEqual(menu_chrome.title_block_height(2), 4)


class TestFooterBlock(unittest.TestCase):
    def test_padding_for_typical_frame(self):
        # term_rows=24, content_rows=10 → pad = 24 - 10 - 1 = 13 blanks
        # before the footer, then footer-row (no trailing newline).
        frags = menu_chrome.footer_block("ESC Back", 80, 24, 10)
        self.assertEqual(_count_blank_rows(frags), 13)

    def test_zero_pad_when_exact_fit(self):
        # term_rows=10, content_rows=9 → pad = 10 - 9 - 1 = 0.
        frags = menu_chrome.footer_block("ESC", 80, 10, 9)
        self.assertEqual(_count_blank_rows(frags), 0)

    def test_zero_pad_on_overflow(self):
        # term_rows=10, content_rows=15 → would-be pad = -6, clamped to 0.
        frags = menu_chrome.footer_block("ESC", 80, 10, 15)
        self.assertEqual(_count_blank_rows(frags), 0)

    def test_zero_pad_when_content_equals_rows(self):
        # content_rows == term_rows — footer still emits but with no padding.
        frags = menu_chrome.footer_block("ESC", 80, 10, 10)
        self.assertEqual(_count_blank_rows(frags), 0)

    def test_footer_styled_with_c_hint(self):
        frags = menu_chrome.footer_block("ESC Back", 80, 24, 10)
        # Last fragment is the styled footer text.
        self.assertEqual(frags[-1], (C_HINT, "ESC Back"))

    def test_footer_centred(self):
        text = "ESC Back"
        frags = menu_chrome.footer_block(text, 40, 24, 10)
        pad_text = frags[-2][1]
        self.assertEqual(len(pad_text), (40 - len(text)) // 2)
        self.assertTrue(set(pad_text) <= {" "})

    def test_footer_no_trailing_newline(self):
        # Footer is the last visual row; no "\n" should follow.
        frags = menu_chrome.footer_block("ESC", 80, 24, 10)
        self.assertNotEqual(frags[-1], ("", "\n"))


class TestButtonFragment(unittest.TestCase):
    def _style(self, state, label="ACTIONS", width=13):
        return menu_chrome.button_fragment(label, width, state)[0]

    def test_inactive_style(self):
        self.assertEqual(self._style("inactive"), C_BUTTON_INACTIVE)

    def test_hover_style(self):
        self.assertEqual(self._style("hover"), C_BUTTON_ACTIVE_UNFOCUSED)

    def test_selected_unfocused_style(self):
        self.assertEqual(
            self._style("selected_unfocused"),
            C_BUTTON_ACTIVE_UNFOCUSED,
        )

    def test_selected_focused_style(self):
        self.assertEqual(
            self._style("selected_focused"), C_BUTTON_ACTIVE_FOCUSED,
        )

    def test_disabled_style(self):
        self.assertEqual(self._style("disabled"), C_BUTTON_DISABLED)

    def test_label_centred_in_width(self):
        _, text = menu_chrome.button_fragment("OK", 8, "inactive")
        # 8 cells, 2-char label → 3 left + OK + 3 right.
        self.assertEqual(text, "   OK   ")

    def test_label_centred_odd_padding(self):
        # 7 cells, 2-char label → 2 left + OK + 3 right (left = pad//2).
        _, text = menu_chrome.button_fragment("OK", 7, "inactive")
        self.assertEqual(text, "  OK   ")

    def test_label_exact_width(self):
        _, text = menu_chrome.button_fragment("ACTIONS", 7, "inactive")
        self.assertEqual(text, "ACTIONS")

    def test_label_truncates_when_too_long(self):
        _, text = menu_chrome.button_fragment("SUBSTITUTES", 5, "inactive")
        self.assertEqual(text, "SUBST")

    def test_returns_two_tuple(self):
        out = menu_chrome.button_fragment("OK", 4, "inactive")
        self.assertIsInstance(out, tuple)
        self.assertEqual(len(out), 2)


class TestMenuRow(unittest.TestCase):
    def test_selected_uses_gold_arrows_and_active_label(self):
        # selected → "<< " and " >>" in gold (C_CURSOR_CELL); label in
        # C_ACTIVE; label emitted unpadded so the arrows hug it.
        frags = menu_chrome.menu_row("Options", "selected")
        self.assertEqual(frags[0], (C_CURSOR_CELL, "<< "))
        self.assertEqual(frags[1], (C_ACTIVE,      "Options"))
        self.assertEqual(frags[2], (C_CURSOR_CELL, " >>"))

    def test_hover_uses_blank_arrows_and_hover_label(self):
        # hover → three-space prefix/suffix, label in C_HOVER.
        frags = menu_chrome.menu_row("Options", "hover")
        self.assertEqual(frags[0], ("",      "   "))
        self.assertEqual(frags[1], (C_HOVER, "Options"))
        self.assertEqual(frags[2], ("",      "   "))

    def test_inactive_uses_blank_arrows_and_item_label(self):
        # inactive → three-space prefix/suffix, label in C_ITEM by default.
        frags = menu_chrome.menu_row("Options", "inactive")
        self.assertEqual(frags[0], ("",     "   "))
        self.assertEqual(frags[1], (C_ITEM, "Options"))
        self.assertEqual(frags[2], ("",     "   "))

    def test_inactive_style_override(self):
        # inactive with an explicit inactive_style recolours only the
        # label; hover and selected states ignore the override.
        frags = menu_chrome.menu_row("Placeholder", "inactive",
                                     inactive_style=C_HINT)
        self.assertEqual(frags[1][0], C_HINT)
        frags = menu_chrome.menu_row("Placeholder", "hover",
                                     inactive_style=C_HINT)
        self.assertEqual(frags[1][0], C_HOVER)
        frags = menu_chrome.menu_row("Placeholder", "selected",
                                     inactive_style=C_HINT)
        self.assertEqual(frags[1][0], C_ACTIVE)

    def test_label_emitted_unpadded(self):
        # No trailing pad — the label rides between the 3-cell arrows
        # bare, so `<< >>` hugs the label regardless of length.
        frags = menu_chrome.menu_row("[ ] X", "inactive")
        self.assertEqual(frags[1][1], "[ ] X")
        frags = menu_chrome.menu_row("Exactly10!", "inactive")
        self.assertEqual(frags[1][1], "Exactly10!")
        frags = menu_chrome.menu_row("Too long label", "inactive")
        self.assertEqual(frags[1][1], "Too long label")

    def test_row_width_is_label_plus_six(self):
        # Total visual width of the row = len(label) + 6 (3-cell
        # prefix + label + 3-cell suffix), in every state.
        for state in ("selected", "hover", "inactive"):
            for label in ("X", "Options", "[X] Display pane headers"):
                frags = menu_chrome.menu_row(label, state)
                width = sum(len(f[1]) for f in frags)
                self.assertEqual(width, len(label) + 6)

    def test_arrows_abut_the_label(self):
        # `<< ` ends with a single space and ` >>` starts with one —
        # so there is exactly one space between the arrows and the
        # label, no trailing pad before the closing arrow.
        frags = menu_chrome.menu_row("Enter MUME", "selected")
        self.assertEqual(frags[0][1], "<< ")
        self.assertEqual(frags[1][1], "Enter MUME")
        self.assertEqual(frags[2][1], " >>")

    def test_fixed_three_cell_prefix_suffix(self):
        # The "<<"/">>"/" " bits are always exactly 3 cells, in every
        # state — the row width grows only with the label.
        for state in ("selected", "hover", "inactive"):
            frags = menu_chrome.menu_row("X", state)
            self.assertEqual(len(frags[0][1]), 3)
            self.assertEqual(len(frags[2][1]), 3)

    def test_mouse_handler_passthrough(self):
        sentinel = object()
        frags = menu_chrome.menu_row(
            "Options", "selected", mouse_handler=sentinel,
        )
        self.assertEqual(len(frags), 3)
        for f in frags:
            self.assertEqual(len(f), 3)
            self.assertIs(f[2], sentinel)

    def test_no_mouse_handler_gives_two_tuples(self):
        frags = menu_chrome.menu_row("Options", "inactive")
        for f in frags:
            self.assertEqual(len(f), 2)


class TestTitleBlockMouseHandler(unittest.TestCase):
    def test_handler_attached_to_every_fragment(self):
        sentinel = object()
        frags = menu_chrome.title_block(
            "─── Panes ───", 40, 2, mouse_handler=sentinel,
        )
        self.assertTrue(frags)
        for f in frags:
            self.assertEqual(len(f), 3)
            self.assertIs(f[2], sentinel)

    def test_no_handler_gives_two_tuples(self):
        frags = menu_chrome.title_block("─── x ───", 20, 1)
        for f in frags:
            self.assertEqual(len(f), 2)


class TestFooterBlockMouseHandler(unittest.TestCase):
    def test_handler_attached_to_every_fragment(self):
        sentinel = object()
        frags = menu_chrome.footer_block(
            "ESC Back", 80, 24, 10, mouse_handler=sentinel,
        )
        self.assertTrue(frags)
        for f in frags:
            self.assertEqual(len(f), 3)
            self.assertIs(f[2], sentinel)

    def test_no_handler_gives_two_tuples(self):
        frags = menu_chrome.footer_block("ESC", 80, 24, 10)
        for f in frags:
            self.assertEqual(len(f), 2)


if __name__ == "__main__":
    unittest.main()
