# Run with: python -m unittest bridge.launcher.tests.test_profile_io
#   (from PROJECT_DIR) — or `python -m unittest discover bridge/launcher/tests`.

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Allow `import profile_io` when run directly via the launcher's sys.path
# convention.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profile_io  # noqa: E402
from profile_io import (  # noqa: E402
    Entry, Passthrough, load_profile, save_profile,
    _parse_line, _split_brace_args,
)

SCRIPT_DIR = Path(__file__).resolve().parent.parent
BLANK_TEMPLATE = SCRIPT_DIR / "templates" / "blank_profile.tin"


class TestBraceSplitter(unittest.TestCase):
    def test_two_args(self):
        self.assertEqual(_split_brace_args(" {a} {b}"), ["a", "b"])

    def test_three_args(self):
        self.assertEqual(_split_brace_args(" {a} {b} {3}"), ["a", "b", "3"])

    def test_nested_braces(self):
        self.assertEqual(_split_brace_args(" {a} {x{y}z}"), ["a", "x{y}z"])

    def test_escaped_brace(self):
        # `\}` inside the brace must not close the arg.
        self.assertEqual(_split_brace_args(r" {a} {b\}c}"), ["a", r"b\}c"])

    def test_escape_passthrough(self):
        # `\e` (and any `\X`) survives untouched.
        self.assertEqual(_split_brace_args(r" {\eOp} {flee}"),
                         [r"\eOp", "flee"])

    def test_trailing_garbage(self):
        self.assertIsNone(_split_brace_args(" {a} {b} junk"))

    def test_unbalanced(self):
        self.assertIsNone(_split_brace_args(" {a} {b"))


class TestParseLine(unittest.TestCase):
    def test_alias(self):
        e = _parse_line("#alias {k} {kill %1}\n")
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.kind, "alias")
        self.assertEqual(e.pattern, "k")
        self.assertEqual(e.body, "kill %1")
        self.assertIsNone(e.priority)

    def test_macro_with_escape(self):
        e = _parse_line(r"#macro {\eOp} {flee}" + "\n")
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.kind, "macro")
        self.assertEqual(e.pattern, r"\eOp")
        self.assertEqual(e.body, "flee")

    def test_three_arg_priority(self):
        e = _parse_line("#action {Bubba} {bow} {3}\n")
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.priority, 3)

    def test_sub_short_alias(self):
        e = _parse_line("#sub {orc} {ORC}\n")
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.kind, "substitute")

    def test_substitute_full_name(self):
        e = _parse_line("#substitute {orc} {ORC}\n")
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.kind, "substitute")

    def test_highlight(self):
        e = _parse_line("#highlight {orc} {red}\n")
        self.assertIsInstance(e, Entry)
        self.assertEqual(e.kind, "highlight")

    def test_nop_dropped(self):
        self.assertIsNone(_parse_line("#nop a comment\n"))
        self.assertIsNone(_parse_line("#nop\n"))

    def test_unknown_passthrough(self):
        p = _parse_line("#var {foo} {bar}\n")
        self.assertIsInstance(p, Passthrough)
        self.assertEqual(p.raw, "#var {foo} {bar}")

    def test_blank_passthrough(self):
        p = _parse_line("\n")
        self.assertIsInstance(p, Passthrough)
        self.assertEqual(p.raw, "")

    def test_malformed_passthrough(self):
        # Missing closing brace → passthrough.
        p = _parse_line("#alias {k\n")
        self.assertIsInstance(p, Passthrough)

    def test_prefix_lookalike(self):
        # `#aliasfoo` is not `#alias`.
        p = _parse_line("#aliasfoo {x} {y}\n")
        self.assertIsInstance(p, Passthrough)

    def test_substitute_not_eaten_by_sub_match(self):
        # Must match `#substitute` as the full token, not as `#sub` + `stitute`.
        e = _parse_line("#substitute {a} {b}\n")
        self.assertEqual(e.kind, "substitute")
        self.assertEqual(e._raw, "#substitute {a} {b}")


class TestEntriesOf(unittest.TestCase):
    def test_filters_by_kind(self):
        prof = load_profile(BLANK_TEMPLATE)
        macros = prof.entries_of("macro")
        self.assertEqual(len(macros), 10)
        self.assertEqual(prof.entries_of("alias"), [])


class TestRoundTrip(unittest.TestCase):
    def _round_trip(self, source):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = load_profile(src)
            prof.path = dst
            save_profile(prof)
            return dst.read_text()

    def _strip_nop(self, source):
        out = []
        for line in source.splitlines(keepends=True):
            if line.lstrip().startswith("#nop") and (
                len(line.lstrip()) == 4
                or line.lstrip()[4] in (" ", "\t", "{", "\n", "\r")
            ):
                continue
            out.append(line)
        return "".join(out)

    def test_blank_template(self):
        source = BLANK_TEMPLATE.read_text()
        result = self._round_trip(source)
        self.assertEqual(result, self._strip_nop(source))

    def test_macro_escape_preserved(self):
        source = "#macro {\\eOp} {flee}\n"
        self.assertEqual(self._round_trip(source), source)

    def test_passthrough_var_and_event(self):
        source = (
            "#var {mytarget} {orc}\n"
            "\n"
            "#event {SESSION CONNECTED} {#showme welcome}\n"
            "#alias {k} {kill %1}\n"
        )
        self.assertEqual(self._round_trip(source), source)

    def test_nop_dropped(self):
        source = (
            "#nop a header comment\n"
            "#macro {\\eOp} {flee}\n"
            "#nop trailing\n"
        )
        expected = "#macro {\\eOp} {flee}\n"
        self.assertEqual(self._round_trip(source), expected)


class TestCaseInsensitiveAndMultiLine(unittest.TestCase):
    """Regression coverage for the bug-report fix: tt++ command names are
    case-insensitive, and brace-group args may be separated by newlines."""

    def _round_trip(self, source):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = load_profile(src)
            prof.path = dst
            save_profile(prof)
            return prof, dst.read_text()

    def test_all_caps_single_line_parses_as_macro(self):
        source = "#MACRO {\\eOm} {close exit}\n"
        prof, out = self._round_trip(source)
        macros = prof.entries_of("macro")
        self.assertEqual(len(macros), 1)
        self.assertEqual(macros[0].pattern, "\\eOm")
        self.assertEqual(macros[0].body,    "close exit")
        self.assertEqual(out, source)   # byte-exact

    def test_multi_line_parses_as_macro(self):
        # The bug report's primary example: brace groups split by newlines
        # with whitespace-only intervening lines.
        source = "#macro {\\eOm}\n{\n    close exit\n}\n"
        prof, out = self._round_trip(source)
        macros = prof.entries_of("macro")
        self.assertEqual(len(macros), 1)
        self.assertEqual(macros[0].pattern, "\\eOm")
        self.assertEqual(macros[0].body,    "\n    close exit\n")
        self.assertEqual(out, source)   # byte-exact via _raw

    def test_extra_inter_arg_whitespace_parses_as_macro(self):
        # Regression for what should already work: arbitrary spaces between
        # args (still on a single line).
        source = "#macro    {\\eOm}    {close exit}\n"
        prof, out = self._round_trip(source)
        macros = prof.entries_of("macro")
        self.assertEqual(len(macros), 1)
        self.assertEqual(out, source)

    def test_mixed_file_count_is_correct(self):
        # The editor's tab-strip count must include the previously-missed
        # all-caps and multi-line forms.
        source = (
            "#macro {\\eOp} {flee}\n"
            "#MACRO {\\eOm} {close exit}\n"
            "#macro {\\eOr}\n"
            "{\n"
            "    south\n"
            "}\n"
            "#alias {k} {kill %1}\n"
        )
        prof, _out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("macro")), 3)
        self.assertEqual(len(prof.entries_of("alias")), 1)

    def test_all_known_kinds_case_insensitive(self):
        source = (
            "#ALIAS {k} {kill %1}\n"
            "#Action {Bubba} {bow}\n"
            "#HIGHLIGHT {orc} {red}\n"
            "#Substitute {a} {b}\n"
            "#SUB {c} {d}\n"
        )
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("alias")),      1)
        self.assertEqual(len(prof.entries_of("action")),     1)
        self.assertEqual(len(prof.entries_of("highlight")),  1)
        self.assertEqual(len(prof.entries_of("substitute")), 2)
        self.assertEqual(out, source)


if __name__ == "__main__":
    unittest.main()
