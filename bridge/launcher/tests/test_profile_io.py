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
    parse_profile, serialize_profile, resolve_kind,
    _parse_line, _split_brace_args, _serialize_entry,
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


class TestPriorityArity(unittest.TestCase):
    """tt++ accepts an optional third brace-arg as priority on four of
    the five GUI-editable kinds; `#macro` is the exception. Non-integer
    priority falls through to Passthrough; four-arg forms fall through;
    macro with three args falls through."""

    def _round_trip(self, source):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = load_profile(src)
            prof.path = dst
            save_profile(prof)
            return prof, dst.read_text()

    # ----- 3-arg forms parse correctly for the four priority kinds ----
    def test_alias_three_arg_priority(self):
        prof, out = self._round_trip("#alias {test} {test} {1}\n")
        entries = prof.entries_of("alias")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].priority, 1)
        self.assertEqual(out, "#alias {test} {test} {1}\n")

    def test_action_three_arg_priority(self):
        prof, out = self._round_trip("#action {Bubba} {bow} {3}\n")
        entries = prof.entries_of("action")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].priority, 3)
        self.assertEqual(out, "#action {Bubba} {bow} {3}\n")

    def test_highlight_three_arg_priority(self):
        prof, out = self._round_trip("#highlight {orc} {red} {5}\n")
        entries = prof.entries_of("highlight")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].priority, 5)
        self.assertEqual(out, "#highlight {orc} {red} {5}\n")

    def test_substitute_three_arg_priority(self):
        prof, out = self._round_trip("#substitute {orc} {ORC} {2}\n")
        entries = prof.entries_of("substitute")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].priority, 2)
        self.assertEqual(out, "#substitute {orc} {ORC} {2}\n")

    # ----- 2-arg forms still parse for every kind (no regression) -----
    def test_two_arg_still_parses_for_all_kinds(self):
        cases = [
            ("alias",      "#alias {k} {kill %1}\n"),
            ("action",     "#action {Bubba} {bow}\n"),
            ("macro",      "#macro {\\eOp} {flee}\n"),
            ("highlight",  "#highlight {orc} {red}\n"),
            ("substitute", "#substitute {orc} {ORC}\n"),
        ]
        for kind, source in cases:
            with self.subTest(kind=kind):
                prof, out = self._round_trip(source)
                entries = prof.entries_of(kind)
                self.assertEqual(len(entries), 1)
                self.assertIsNone(entries[0].priority)
                self.assertEqual(out, source)

    # ----- Negative cases (Passthrough) -------------------------------
    def test_macro_three_arg_is_passthrough(self):
        # `#macro` never accepts a priority. The bytes must round-trip
        # verbatim via Passthrough.
        source = "#macro {\\eOp} {flee} {1}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("macro")), 0)
        self.assertTrue(any(isinstance(it, Passthrough) for it in prof.items))
        self.assertEqual(out, source)

    def test_alias_non_int_priority_is_passthrough(self):
        source = "#alias {test} {test} {notanint}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("alias")), 0)
        self.assertTrue(any(isinstance(it, Passthrough) for it in prof.items))
        self.assertEqual(out, source)

    def test_alias_four_arg_is_passthrough(self):
        source = "#alias {a} {b} {c} {d}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("alias")), 0)
        self.assertTrue(any(isinstance(it, Passthrough) for it in prof.items))
        self.assertEqual(out, source)

    def test_action_four_arg_is_passthrough(self):
        # Four args even when the third is integer-parseable must fall
        # through — we don't reinterpret unknown forms.
        source = "#action {a} {b} {1} {2}\n"
        prof, out = self._round_trip(source)
        self.assertEqual(len(prof.entries_of("action")), 0)
        self.assertTrue(any(isinstance(it, Passthrough) for it in prof.items))
        self.assertEqual(out, source)

    # ----- Mixed file round-trip -------------------------------------
    def test_mixed_file_round_trips_byte_exact(self):
        source = (
            "#alias {k} {kill %1}\n"
            "#alias {test} {test} {1}\n"
            "#action {Bubba} {bow}\n"
            "#action {Bubba} {bow} {3}\n"
            "#macro {\\eOp} {flee}\n"
            "#highlight {orc} {red}\n"
            "#highlight {troll} {yellow} {5}\n"
            "#substitute {a} {b}\n"
            "#substitute {c} {d} {2}\n"
            "#var {target} {orc}\n"
        )
        prof, out = self._round_trip(source)
        self.assertEqual(out, source)
        # And the kind/priority breakdown matches.
        aliases = prof.entries_of("alias")
        self.assertEqual([(e.pattern, e.priority) for e in aliases],
                         [("k", None), ("test", 1)])
        actions = prof.entries_of("action")
        self.assertEqual([(e.pattern, e.priority) for e in actions],
                         [("Bubba", None), ("Bubba", 3)])
        macros = prof.entries_of("macro")
        self.assertEqual([(e.pattern, e.priority) for e in macros],
                         [("\\eOp", None)])
        highlights = prof.entries_of("highlight")
        self.assertEqual([(e.pattern, e.priority) for e in highlights],
                         [("orc", None), ("troll", 5)])
        subs = prof.entries_of("substitute")
        self.assertEqual([(e.pattern, e.priority) for e in subs],
                         [("a", None), ("c", 2)])

    def test_delete_between_priority_entries_keeps_neighbours_byte_exact(self):
        # Deleting a non-priority entry that sits between two priority
        # entries must leave the surviving entries byte-exact in the
        # written file (their `_raw` is preserved through the delete).
        source = (
            "#alias {first} {body1} {1}\n"
            "#alias {middle} {body2}\n"
            "#alias {last} {body3} {2}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = load_profile(src)
            # Drop the middle (no-priority) entry.
            middle = next(e for e in prof.entries_of("alias")
                          if e.pattern == "middle")
            prof.items.remove(middle)
            prof.path = dst
            save_profile(prof)
            self.assertEqual(
                dst.read_text(),
                "#alias {first} {body1} {1}\n"
                "#alias {last} {body3} {2}\n",
            )

    # ----- Whitespace variants of the priority arg --------------------
    def test_priority_strips_whitespace(self):
        prof, out = self._round_trip("#alias {a} {b} { 7 }\n")
        entries = prof.entries_of("alias")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].priority, 7)
        # _raw preserved so the inner whitespace round-trips verbatim.
        self.assertEqual(out, "#alias {a} {b} { 7 }\n")

    def test_priority_negative_int(self):
        prof, _out = self._round_trip("#alias {a} {b} {-3}\n")
        entries = prof.entries_of("alias")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].priority, -3)


class TestSerializerPriorityGuard(unittest.TestCase):
    """The serializer regenerates `#<kind> {p} {b} [{priority}]` from a
    bare Entry. `#macro` must never emit a third brace-arg even if its
    Entry has `priority` set defensively."""

    def test_alias_emits_priority(self):
        e = Entry(kind="alias", pattern="a", body="b", priority=5, _raw=None)
        self.assertEqual(_serialize_entry(e), "#alias {a} {b} {5}")

    def test_macro_drops_priority_defensively(self):
        e = Entry(kind="macro", pattern="\\eOp", body="flee",
                  priority=1, _raw=None)
        # The third arg must not appear — `#macro` has no priority slot.
        self.assertEqual(_serialize_entry(e), "#macro {\\eOp} {flee}")

    def test_kinds_without_priority_emit_two_args(self):
        for kind in ("alias", "action", "highlight", "substitute"):
            with self.subTest(kind=kind):
                e = Entry(kind=kind, pattern="p", body="b",
                          priority=None, _raw=None)
                self.assertEqual(
                    _serialize_entry(e),
                    f"#{kind} {{p}} {{b}}",
                )


class TestStringHelpers(unittest.TestCase):
    """`parse_profile(src, path)` and `serialize_profile(profile)` are the
    pure string-mode helpers underlying load/save. They share all the
    invariants documented on load/save — `_raw` byte-exact for unmodified
    entries, canonical regeneration on mutation, `#nop` drop, empty-
    pattern drop — but bypass disk I/O so the editor's mode-flip can
    round-trip in memory."""

    PATH = Path("/dev/null/profile.tin")

    def _round_trip_str(self, source):
        prof = parse_profile(source, self.PATH)
        return prof, serialize_profile(prof)

    def test_parse_profile_attaches_path(self):
        prof = parse_profile("", Path("/tmp/whatever.tin"))
        self.assertEqual(prof.path, Path("/tmp/whatever.tin"))
        self.assertEqual(prof.items, [])

    def test_parse_profile_accepts_str_path(self):
        # `path` accepts both `pathlib.Path` and `str` (load_profile
        # historically accepted either; the helper preserves that).
        prof = parse_profile("", "/tmp/whatever.tin")
        self.assertEqual(prof.path, Path("/tmp/whatever.tin"))

    def test_blank_template_round_trip_str(self):
        source = BLANK_TEMPLATE.read_text()
        prof, out = self._round_trip_str(source)
        # Same #nop-drop semantics as load/save.
        expected = "".join(
            line for line in source.splitlines(keepends=True)
            if not (line.lstrip().startswith("#nop") and (
                len(line.lstrip()) == 4
                or line.lstrip()[4] in (" ", "\t", "{", "\n", "\r")))
        )
        self.assertEqual(out, expected)
        # The path attached at parse time survives round-trip.
        self.assertEqual(prof.path, self.PATH)

    def test_multi_line_entry_round_trip_str(self):
        source = "#macro {\\eOm}\n{\n    close exit\n}\n"
        prof, out = self._round_trip_str(source)
        self.assertEqual(len(prof.entries_of("macro")), 1)
        self.assertEqual(out, source)

    def test_priority_entry_round_trip_str(self):
        source = (
            "#alias {a} {b} {1}\n"
            "#action {Bubba} {bow} {3}\n"
            "#highlight {Orc} {red} {5}\n"
            "#substitute {x} {y} {2}\n"
        )
        prof, out = self._round_trip_str(source)
        self.assertEqual(out, source)
        # Priorities decoded as ints, not strings.
        self.assertEqual(prof.entries_of("alias")[0].priority,      1)
        self.assertEqual(prof.entries_of("action")[0].priority,     3)
        self.assertEqual(prof.entries_of("highlight")[0].priority,  5)
        self.assertEqual(prof.entries_of("substitute")[0].priority, 2)

    def test_mixed_entry_and_passthrough_round_trip_str(self):
        source = (
            "#var {target} {orc}\n"
            "\n"
            "#alias {k} {kill %1}\n"
            "#event {SESSION CONNECTED} {#showme welcome}\n"
            "#macro {\\eOp} {flee}\n"
        )
        prof, out = self._round_trip_str(source)
        self.assertEqual(out, source)
        self.assertEqual(len(prof.entries_of("alias")), 1)
        self.assertEqual(len(prof.entries_of("macro")), 1)
        # The Passthroughs survive in order.
        passthroughs = [it for it in prof.items
                        if isinstance(it, Passthrough)]
        self.assertEqual(len(passthroughs), 3)

    def test_serialize_drops_nop_and_empty_pattern(self):
        # Direct construction — verify the same drop rules as save_profile.
        prof = profile_io.Profile(path=self.PATH, items=[
            Entry(kind="alias", pattern="",  body="x",
                  priority=None, _raw=None),
            Entry(kind="alias", pattern="k", body="kill",
                  priority=None, _raw=None),
        ])
        self.assertEqual(serialize_profile(prof), "#alias {k} {kill}\n")

    def test_serialize_empty_profile_is_empty_string(self):
        prof = profile_io.Profile(path=self.PATH, items=[])
        self.assertEqual(serialize_profile(prof), "")

    def test_edit_then_serialize_regenerates_canonically(self):
        source = "#alias    {keep}    {body}\n#alias {touch} {old}\n"
        prof = parse_profile(source, self.PATH)
        touch = next(e for e in prof.entries_of("alias")
                     if e.pattern == "touch")
        touch.body = "new"
        self.assertEqual(
            serialize_profile(prof),
            # `keep` keeps its odd whitespace via _raw, `touch` is
            # regenerated canonically.
            "#alias    {keep}    {body}\n#alias {touch} {new}\n",
        )

    def test_load_save_still_work_via_helpers(self):
        # Sanity: the disk wrappers go through the same code paths as
        # parse/serialize, so a load → save round-trip continues to be
        # byte-exact for the same inputs the string helpers preserve.
        source = "#alias {k} {kill %1}\n#var {x} {y}\n"
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = load_profile(src)
            prof.path = dst
            save_profile(prof)
            self.assertEqual(dst.read_text(), source)


if __name__ == "__main__":
    unittest.main()
