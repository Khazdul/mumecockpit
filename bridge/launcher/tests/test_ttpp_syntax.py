# Unit tests for bridge/launcher/ttpp_syntax.py — the best-effort lexical
# tokeniser feeding the profile editor's Editor-mode syntax highlighting.
# Tests run without prompt_toolkit; ttpp_syntax imports nothing beyond
# stdlib.

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import ttpp_syntax  # noqa: E402


def _kinds(spans):
    return [k for _, _, k in spans]


def _slices(text, spans):
    return [text[s:e] for s, e, _ in spans]


class TestCommandPosition(unittest.TestCase):
    def test_command_at_line_start(self):
        spans = ttpp_syntax.tokenize("#alias foo")
        self.assertEqual(spans[0], (0, 6, "command"))

    def test_command_after_leading_whitespace(self):
        spans = ttpp_syntax.tokenize("    #nop")
        cmds = [s for s in spans if s[2] == "command"]
        self.assertEqual(cmds, [(4, 8, "command")])

    def test_command_after_brace(self):
        # `{#nop}` — `{` brace, `#nop` command, `}` brace.
        spans = ttpp_syntax.tokenize("{#nop}")
        self.assertEqual(spans, [
            (0, 1, "brace"),
            (1, 5, "command"),
            (5, 6, "brace"),
        ])

    def test_command_after_brace_with_space(self):
        spans = ttpp_syntax.tokenize("{ #nop }")
        kinds = _kinds(spans)
        self.assertIn("command", kinds)
        cmd = next(s for s in spans if s[2] == "command")
        self.assertEqual(cmd, (2, 6, "command"))

    def test_command_after_semicolon(self):
        spans = ttpp_syntax.tokenize("say hi;#nop")
        # `;` at offset 6, `#nop` at 7..11.
        self.assertIn((6, 7, "delim"), spans)
        self.assertIn((7, 11, "command"), spans)

    def test_hash_in_body_is_not_command(self):
        # `say #bar` — `#bar` is NOT in command position (after non-cmd
        # characters), so no command span is emitted.
        spans = ttpp_syntax.tokenize("say #bar")
        self.assertEqual([s for s in spans if s[2] == "command"], [])

    def test_unknown_command_still_highlights(self):
        # No whitelist — typos and unknown commands colour anyway.
        spans = ttpp_syntax.tokenize("#znopz extra")
        self.assertEqual(spans[0], (0, 6, "command"))


class TestVariables(unittest.TestCase):
    def test_braced_var_is_single_span(self):
        text = "${var}"
        spans = ttpp_syntax.tokenize(text)
        self.assertEqual(spans, [(0, 6, "var")])
        # Braces inside the var are NOT re-emitted.
        self.assertNotIn("brace", _kinds(spans))

    def test_braced_var_with_spaces(self):
        text = "${cool website}"
        spans = ttpp_syntax.tokenize(text)
        self.assertEqual(spans, [(0, len(text), "var")])

    def test_dollar_identifier(self):
        spans = ttpp_syntax.tokenize("$target")
        self.assertEqual(spans, [(0, 7, "var")])

    def test_amp_identifier(self):
        spans = ttpp_syntax.tokenize("&friendlist")
        self.assertEqual(spans, [(0, 11, "var")])

    def test_pct_digit_capture(self):
        # `%1` is one var span.
        spans = ttpp_syntax.tokenize("%1")
        self.assertEqual(spans, [(0, 2, "var")])

    def test_pct_multi_digit_capture(self):
        spans = ttpp_syntax.tokenize("%99")
        self.assertEqual(spans, [(0, 3, "var")])

    def test_pct_star(self):
        spans = ttpp_syntax.tokenize("%*")
        self.assertEqual(spans, [(0, 2, "var")])

    def test_pct_letter_is_plain_text(self):
        # `%U` (a #format code) is not a var; not in scope here.
        spans = ttpp_syntax.tokenize("%U")
        self.assertEqual([s for s in spans if s[2] == "var"], [])

    def test_unclosed_braced_var_falls_back(self):
        # `${foo` — `$` skipped as plain text, `{` then gets a brace span.
        spans = ttpp_syntax.tokenize("${foo")
        self.assertNotIn("var", _kinds(spans))
        self.assertIn((1, 2, "brace"), spans)


class TestCodes(unittest.TestCase):
    def test_three_digit_color_code(self):
        spans = ttpp_syntax.tokenize("<088>")
        self.assertEqual(spans, [(0, 5, "code")])

    def test_letter_color_code(self):
        spans = ttpp_syntax.tokenize("<aaa>")
        self.assertEqual(spans, [(0, 5, "code")])

    def test_truecolor_code(self):
        # 7 chars inside `<>` — 24-bit truecolor.
        spans = ttpp_syntax.tokenize("<F000000>")
        self.assertEqual(spans, [(0, 9, "code")])

    def test_unclosed_lt_falls_back(self):
        spans = ttpp_syntax.tokenize("< not a code")
        self.assertEqual([s for s in spans if s[2] == "code"], [])

    def test_backslash_n(self):
        spans = ttpp_syntax.tokenize("\\n")
        self.assertEqual(spans, [(0, 2, "code")])

    def test_backslash_x_hex(self):
        spans = ttpp_syntax.tokenize("\\xFF")
        self.assertEqual(spans, [(0, 4, "code")])

    def test_backslash_brace(self):
        # `\{` is an escape — single "code" span.
        spans = ttpp_syntax.tokenize("\\{")
        self.assertEqual(spans, [(0, 2, "code")])


class TestInvariants(unittest.TestCase):
    def test_empty_buffer(self):
        self.assertEqual(ttpp_syntax.tokenize(""), [])

    def test_plain_text_no_spans(self):
        self.assertEqual(ttpp_syntax.tokenize("hello world"), [])

    def test_spans_non_overlapping_and_ascending(self):
        text = "#alias {x %1} {say <088>$target;#nop ${cool var}}"
        spans = ttpp_syntax.tokenize(text)
        self.assertTrue(spans, "expected at least one span")
        prev_end = 0
        for s, e, _ in spans:
            self.assertLessEqual(prev_end, s,
                                 f"overlap or out-of-order at {s}")
            self.assertLess(s, e, "zero-or-negative-length span")
            prev_end = e

    def test_spans_cover_only_recognised_regions(self):
        # `hello` between `{` and `;` is plain text; only the surrounding
        # tokens should appear.
        text = "{hello;world}"
        spans = ttpp_syntax.tokenize(text)
        self.assertEqual(_slices(text, spans), ["{", ";", "}"])

    def test_dollar_dollar_then_var(self):
        # `$$target` — the first `$` is plain text (escape per manual);
        # `$target` is a var span. Best-effort tokeniser still picks up
        # the second `$identifier`.
        spans = ttpp_syntax.tokenize("$$target")
        vars_ = [s for s in spans if s[2] == "var"]
        self.assertEqual(vars_, [(1, 8, "var")])


if __name__ == "__main__":
    unittest.main()
