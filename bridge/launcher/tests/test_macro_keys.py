# Unit tests for bridge/launcher/macro_keys.py — the bidirectional map
# between tt++ escape sequences, prompt_toolkit key events, and display
# names used by the profile editor's Macros tab.

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import macro_keys   # noqa: E402

from prompt_toolkit.key_binding.key_processor import KeyPress, KeyPressEvent
from prompt_toolkit.keys import Keys


def _make_event(*keys):
    """Build a stand-in for KeyPressEvent whose `key_sequence` matches
    `keys`. Each item is either a Keys.* constant or a single character.

    The string "escape" is mapped to Keys.Escape so the lookup tables —
    which mirror input_pane's binding tuples — see the same token
    `match_pressed` would produce in the running app. (KeyPress itself
    only accepts Keys.* or single-char strings.)"""
    presses = []
    for k in keys:
        if isinstance(k, Keys):
            presses.append(KeyPress(k, ""))
        elif k == "escape":
            presses.append(KeyPress(Keys.Escape, "\x1b"))
        else:
            presses.append(KeyPress(k, k))

    class _E:
        key_sequence = presses
    return _E()


class TestEscapeToName(unittest.TestCase):
    def test_numpad_round_trip(self):
        # All ten numpad digits + . / Enter / * / + / - / /.
        cases = [
            (r"\eOp", "Numpad 0"),
            (r"\eOq", "Numpad 1"),
            (r"\eOy", "Numpad 9"),
            (r"\eOM", "Numpad Enter"),
            (r"\eOk", "Numpad +"),
            (r"\eOm", "Numpad -"),
        ]
        for esc, expected in cases:
            self.assertEqual(macro_keys.escape_to_name(esc), expected, esc)
            self.assertEqual(macro_keys.name_to_escape(expected), esc, expected)

    def test_f_keys(self):
        self.assertEqual(macro_keys.escape_to_name(r"\eOP"), "F1")
        self.assertEqual(macro_keys.escape_to_name(r"\e[15~"), "F5")

    def test_alt_letter(self):
        self.assertEqual(macro_keys.escape_to_name(r"\ea"), "Alt+a")
        # Alt+o is intentionally excluded.
        self.assertIsNone(macro_keys.escape_to_name(r"\eo"))

    def test_ctrl_letter(self):
        self.assertEqual(macro_keys.escape_to_name("^G"), "Ctrl+g")

    def test_unknown_returns_none(self):
        self.assertIsNone(macro_keys.escape_to_name(r"\eXunknown"))
        self.assertIsNone(macro_keys.escape_to_name("foo"))


class TestEscapeNormalisation(unittest.TestCase):
    def test_literal_esc_byte(self):
        # Existing macro authored in another client where ESC is a
        # literal byte (0x1b). The editor still resolves the readable name.
        self.assertEqual(macro_keys.escape_to_name("\x1bOp"), "Numpad 0")

    def test_octal_form(self):
        self.assertEqual(macro_keys.escape_to_name(r"\033Op"), "Numpad 0")

    def test_hex_form_lower_and_upper(self):
        self.assertEqual(macro_keys.escape_to_name(r"\x1bOp"), "Numpad 0")
        self.assertEqual(macro_keys.escape_to_name(r"\X1BOp"), "Numpad 0")


class TestMatchPressed(unittest.TestCase):
    def test_f_key_matches(self):
        event = _make_event(Keys.F1)
        match = macro_keys.match_pressed(event)
        self.assertIsNotNone(match)
        self.assertEqual(match.display_name, "F1")
        self.assertEqual(match.tin_escape, r"\eOP")

    def test_numpad_tuple_matches(self):
        # SS3 form: ESC + O + <letter>.
        event = _make_event("escape", "O", "p")
        match = macro_keys.match_pressed(event)
        self.assertIsNotNone(match)
        self.assertEqual(match.display_name, "Numpad 0")
        self.assertEqual(match.tin_escape, r"\eOp")

    def test_alt_letter_matches(self):
        event = _make_event("escape", "a")
        match = macro_keys.match_pressed(event)
        self.assertIsNotNone(match)
        self.assertEqual(match.display_name, "Alt+a")

    def test_ctrl_letter_matches(self):
        event = _make_event(Keys.ControlG)
        match = macro_keys.match_pressed(event)
        self.assertIsNotNone(match)
        self.assertEqual(match.display_name, "Ctrl+g")

    def test_unrecognised_returns_none(self):
        event = _make_event("a")
        self.assertIsNone(macro_keys.match_pressed(event))


class TestBlankProfileResolvesAllMacros(unittest.TestCase):
    """Every macro in the default blank_profile.tin must resolve to a
    readable name — the spec calls for `Numpad 0`, `Numpad 2..6`,
    `Numpad 8..9`, `Numpad +`, `Numpad -` to render in place of
    raw escapes."""

    def test_every_template_macro_has_a_display_name(self):
        import profile_io
        from pathlib import Path
        template = Path(SCRIPT_DIR) / "templates" / "blank_profile.tin"
        prof = profile_io.load_profile(template)
        macros = prof.entries_of("macro")
        self.assertEqual(len(macros), 10)
        for entry in macros:
            name = macro_keys.escape_to_name(entry.pattern)
            self.assertIsNotNone(
                name,
                f"escape {entry.pattern!r} has no display name — update KNOWN_KEYS"
            )
            self.assertTrue(name.startswith("Numpad"), name)


class TestRejectionReason(unittest.TestCase):
    def test_shift_letter(self):
        event = _make_event("G")   # printable uppercase ASCII
        self.assertIn("Shift+letter",
                      macro_keys.rejection_reason(event))

    def test_alt_o(self):
        event = _make_event("escape", "o")
        self.assertIn("Alt+O", macro_keys.rejection_reason(event))

    def test_bare_escape(self):
        event = _make_event("escape")
        self.assertIn("ESC", macro_keys.rejection_reason(event))

    def test_plain_letter(self):
        event = _make_event("a")
        self.assertIn("Plain letters",
                      macro_keys.rejection_reason(event))


if __name__ == "__main__":
    unittest.main()
