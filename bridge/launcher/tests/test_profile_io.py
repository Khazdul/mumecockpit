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
    Entry, Passthrough, load_profile, save_profile, resolve_kind,
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


class TestResolveKind(unittest.TestCase):
    """Direct unit tests for the prefix resolver."""

    # Full abbreviation matrix from the bug report.
    ABBREVS = {
        "alias":      ["al", "ali", "alia", "alias"],
        "action":     ["ac", "act", "acti", "actio", "action"],
        "macro":      ["ma", "mac", "macr", "macro"],
        "highlight":  ["hi", "hig", "high", "highl", "highli",
                       "highlig", "highligh", "highlight"],
        "substitute": ["su", "sub", "subs", "subst", "substi",
                       "substit", "substitu", "substitut", "substitute"],
    }

    def test_every_abbreviation_resolves(self):
        for kind, prefixes in self.ABBREVS.items():
            for prefix in prefixes:
                with self.subTest(kind=kind, prefix=prefix):
                    self.assertEqual(resolve_kind(prefix), kind)
                    # Case-insensitive: upper-case must resolve too.
                    self.assertEqual(resolve_kind(prefix.upper()), kind)

    def test_plurals_do_not_resolve(self):
        for plural in ("macros", "aliases", "actions",
                       "highlights", "substitutes"):
            with self.subTest(plural=plural):
                self.assertIsNone(resolve_kind(plural))

    def test_single_char_does_not_resolve(self):
        for ch in ("m", "a", "s", "h"):
            with self.subTest(ch=ch):
                self.assertIsNone(resolve_kind(ch))

    def test_empty_does_not_resolve(self):
        self.assertIsNone(resolve_kind(""))

    def test_unknown_does_not_resolve(self):
        # `nop` is not a prefix of any GUI-editable kind; `bell`, `var`,
        # `event`, etc. similarly fall through.
        for token in ("nop", "bell", "var", "event", "class", "zap"):
            with self.subTest(token=token):
                self.assertIsNone(resolve_kind(token))


class TestAbbreviationsThroughParser(unittest.TestCase):
    """End-to-end coverage: every abbreviated form parses as an Entry of
    the correct kind, and round-trips byte-exact via `_raw`."""

    def _round_trip(self, source):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = load_profile(src)
            prof.path = dst
            save_profile(prof)
            return prof, dst.read_text()

    def test_every_abbrev_parses_and_round_trips(self):
        for kind, prefixes in TestResolveKind.ABBREVS.items():
            for prefix in prefixes:
                with self.subTest(kind=kind, prefix=prefix):
                    source = f"#{prefix} {{p}} {{b}}\n"
                    prof, out = self._round_trip(source)
                    entries = prof.entries_of(kind)
                    self.assertEqual(len(entries), 1)
                    self.assertEqual(entries[0].pattern, "p")
                    self.assertEqual(entries[0].body,    "b")
                    self.assertEqual(out, source)

    def test_abbrev_uppercase_parses(self):
        # Spot-check the upper-case path through the parser (the matrix
        # test above only uses lower-case in `#<prefix>`).
        source = "#MAC {\\eOp} {flee}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("macro")), 1)
        self.assertEqual(out, source)

    def test_abbrev_multi_line(self):
        # Abbreviated command name + multi-line brace args together.
        source = "#hi {Snowy}\n{light yellow}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("highlight")), 1)
        self.assertEqual(out, source)

    def test_plural_is_passthrough(self):
        # `#macros` is not a tt++ command (it's longer than `#macro`).
        # The parser must surface it as Passthrough so the bytes
        # round-trip and the tab-strip count does not include it.
        source = "#macros {x} {y}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("macro")), 0)
        self.assertEqual(out, source)
        self.assertTrue(any(isinstance(it, Passthrough) for it in prof.items))

    def test_single_char_is_passthrough(self):
        # `#m` could be `#macro`, `#message`, or any number of other
        # commands — tt++ rejects it as ambiguous, so do we.
        source = "#m {x} {y}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("macro")), 0)
        self.assertEqual(out, source)

    def test_mixed_abbrev_count_correct(self):
        # Mix abbreviated, canonical, mixed-case, and multi-line forms;
        # the per-kind count must include them all.
        source = (
            "#mac {\\eOp} {flee}\n"
            "#MACRO {\\eOm} {close exit}\n"
            "#macr {\\eOr}\n"
            "{south}\n"
            "#Al {ws} {wake;stand}\n"
            "#HI {Snowy} {light yellow}\n"
            "#sub {orc} {ORC}\n"
            "#macros {not} {me}\n"   # plural — Passthrough
        )
        prof, _out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("macro")),      3)
        self.assertEqual(len(prof.entries_of("alias")),      1)
        self.assertEqual(len(prof.entries_of("highlight")),  1)
        self.assertEqual(len(prof.entries_of("substitute")), 1)


if __name__ == "__main__":
    unittest.main()
