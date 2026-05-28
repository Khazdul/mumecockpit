# Unit tests for bridge/launcher/scripts_view.py — the shared header
# parser, scripts.conf reader/writer, scripts.cache parser, and
# two-column body renderer backing the launcher and the popup. Tests
# run without prompt_toolkit installed; the module is dependency-free.

import os
import sys
import tempfile
import textwrap
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import scripts_view  # noqa: E402
from palette import (  # noqa: E402
    C_ACTIVE,
    C_BUTTON_ACTIVE_FOCUSED,
    C_BUTTON_ACTIVE_UNFOCUSED,
    C_HOVER,
    C_ITEM,
    C_OK,
    C_PANE_OFF,
    C_SECTION,
)


def _split_rows(frags):
    """Reconstruct the rendered body row-by-row by splitting on the
    newline fragments the renderer emits at the end of each row."""
    rows = []
    buf = ""
    for f in frags:
        text = f[1]
        if text == "\n":
            rows.append(buf)
            buf = ""
        else:
            buf += text
    if buf:
        rows.append(buf)
    return rows


SAMPLE_HEADER = textwrap.dedent("""\
    -- ============================================================
    --  coinlooter
    -- ============================================================
    -- @summary  Auto-loots coins after mob kills
    -- @alias    cl    Pick up coin piles in the current room
    -- @help     Subscribes to mob_death and sends the appropriate
    -- @help     get-coins command on each kill:
    -- @help
    -- @help       Living mob killed  →  get coins all.corpse

    local M = {}
""")


class TestHeaderParser(unittest.TestCase):

    def _write(self, body):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "test.lua")
        with open(path, "w") as fh:
            fh.write(body)
        return path

    def test_parses_summary_aliases_help(self):
        path = self._write(SAMPLE_HEADER)
        summary, aliases, help_lines = scripts_view.parse_script_header(path)
        self.assertEqual(summary, "Auto-loots coins after mob kills")
        self.assertEqual(aliases, [
            ("cl", "Pick up coin piles in the current room"),
        ])
        # 4 help lines: one blank in the middle is preserved verbatim.
        self.assertEqual(len(help_lines), 4)
        self.assertEqual(help_lines[2], "")
        self.assertIn("Living mob killed", help_lines[3])

    def test_decorative_comments_ignored(self):
        body = textwrap.dedent("""\
            -- ===
            -- @summary  Demo
            -- ---
            -- @help     line one
        """)
        path = self._write(body)
        summary, _, help_lines = scripts_view.parse_script_header(path)
        self.assertEqual(summary, "Demo")
        self.assertEqual(help_lines, ["line one"])

    def test_block_ends_at_first_non_comment(self):
        body = textwrap.dedent("""\
            -- @summary  Demo
            local M = {}
            -- @help     too late
        """)
        path = self._write(body)
        _, _, help_lines = scripts_view.parse_script_header(path)
        self.assertEqual(help_lines, [])

    def test_alias_without_description(self):
        body = "-- @alias  go\nlocal M\n"
        path = self._write(body)
        _, aliases, _ = scripts_view.parse_script_header(path)
        self.assertEqual(aliases, [("go", "")])

    def test_unknown_key_silently_ignored(self):
        body = textwrap.dedent("""\
            -- @summary  Demo
            -- @future   reserved
            -- @help     line
        """)
        path = self._write(body)
        summary, _, help_lines = scripts_view.parse_script_header(path)
        self.assertEqual(summary, "Demo")
        self.assertEqual(help_lines, ["line"])

    def test_missing_file_returns_empty(self):
        summary, aliases, help_lines = scripts_view.parse_script_header(
            "/no/such/file.lua",
        )
        self.assertEqual((summary, aliases, help_lines), ("", [], []))


class TestScriptsConf(unittest.TestCase):

    def test_read_missing_returns_none(self):
        self.assertIsNone(scripts_view.read_scripts_conf("/no/such.conf"))

    def test_read_parses_key_values(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf",
                                         delete=False) as fh:
            fh.write("# comment\nautobow=1\nautostab=0\n\n")
            path = fh.name
        try:
            out = scripts_view.read_scripts_conf(path)
            self.assertEqual(out, {"autobow": True, "autostab": False})
        finally:
            os.remove(path)

    def test_resolve_runtime_wins(self):
        d = tempfile.mkdtemp()
        runtime = os.path.join(d, "runtime.conf")
        template = os.path.join(d, "template.conf")
        with open(runtime, "w") as fh:
            fh.write("autobow=1\n")
        with open(template, "w") as fh:
            fh.write("autobow=0\n")
        out = scripts_view.resolve_scripts_conf(runtime, template)
        self.assertEqual(out, {"autobow": True})

    def test_resolve_falls_back_to_template(self):
        d = tempfile.mkdtemp()
        runtime = os.path.join(d, "runtime.conf")     # absent
        template = os.path.join(d, "template.conf")
        with open(template, "w") as fh:
            fh.write("coinlooter=0\n")
        out = scripts_view.resolve_scripts_conf(runtime, template)
        self.assertEqual(out, {"coinlooter": False})

    def test_resolve_both_missing_returns_empty(self):
        d = tempfile.mkdtemp()
        out = scripts_view.resolve_scripts_conf(
            os.path.join(d, "a"), os.path.join(d, "b"),
        )
        self.assertEqual(out, {})

    def test_write_round_trips(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "scripts.conf")
        scripts = [
            scripts_view.Script(name="autobow",  enabled=True),
            scripts_view.Script(name="autostab", enabled=False),
        ]
        scripts_view.write_scripts_conf(path, scripts)
        out = scripts_view.read_scripts_conf(path)
        self.assertEqual(out, {"autobow": True, "autostab": False})


class TestScriptsCacheParser(unittest.TestCase):

    SAMPLE_CACHE = textwrap.dedent("""\
        SCRIPT:autobow
        ENABLED:1
        SUMMARY:Bow/crossbow shoot-and-escape loop
        ALIAS:ash<dir>|e.g. ashe = autobow east
        HELP:Cycle:
        HELP:draw -> shoot
        SCRIPT:coinlooter
        ENABLED:0
        SUMMARY:Auto-loots coins after mob kills
        ALIAS:cl|Pick up coin piles in the current room
    """)

    def test_parses_records(self):
        with tempfile.NamedTemporaryFile("w", suffix=".cache",
                                         delete=False) as fh:
            fh.write(self.SAMPLE_CACHE)
            path = fh.name
        try:
            cat = scripts_view.parse_scripts_cache(path)
        finally:
            os.remove(path)
        self.assertEqual([s.name for s in cat], ["autobow", "coinlooter"])
        self.assertTrue(cat[0].enabled)
        self.assertFalse(cat[1].enabled)
        self.assertEqual(cat[0].aliases, [
            ("ash<dir>", "e.g. ashe = autobow east"),
        ])
        self.assertEqual(cat[0].help, ["Cycle:", "draw -> shoot"])
        self.assertEqual(cat[1].summary, "Auto-loots coins after mob kills")

    def test_missing_cache_returns_empty(self):
        self.assertEqual(scripts_view.parse_scripts_cache("/no/such"), [])


class TestLayoutWidths(unittest.TestCase):

    def test_list_width_floors_at_min(self):
        # One short script — still floored at MIN_LIST_W (16).
        scripts = [scripts_view.Script(name="cl")]
        self.assertEqual(
            scripts_view.list_panel_width(scripts), scripts_view.MIN_LIST_W,
        )

    def test_list_width_grows_for_long_names(self):
        scripts = [scripts_view.Script(name="x" * 30)]
        self.assertEqual(
            scripts_view.list_panel_width(scripts), 4 + 30 + 1,
        )

    def test_detail_width_floors_at_20(self):
        # Tiny terminal — detail floored at 20 even if package overflows.
        self.assertEqual(scripts_view.detail_panel_width(40, 16), 20)

    def test_detail_width_caps_on_wide_terminal(self):
        # The detail panel is capped at MAX_DETAIL_W so the package
        # has visible slack on wide terminals — the launcher's
        # "centred package" pattern needs that slack to read as centred.
        self.assertEqual(
            scripts_view.detail_panel_width(200, 16),
            scripts_view.MAX_DETAIL_W,
        )

    def test_detail_width_takes_remainder_under_cap(self):
        # cols=100, list=16: 100 - 2*OUTER_MARGIN(4) - 16 - SB(1) - GAP(3) = 76.
        # Under MAX_DETAIL_W=80, so the cap doesn't engage.
        self.assertEqual(scripts_view.detail_panel_width(100, 16), 76)


class TestDetailLines(unittest.TestCase):

    def test_enabled_status_uses_c_ok(self):
        s = scripts_view.Script(
            name="autobow", summary="Bow loop", enabled=True,
        )
        rows = scripts_view.render_detail_lines(s, 40)
        styles_on_status = [f[0] for f in rows[1]]
        self.assertEqual(styles_on_status, [C_OK])

    def test_disabled_status_uses_pane_off(self):
        s = scripts_view.Script(name="x", enabled=False)
        rows = scripts_view.render_detail_lines(s, 40)
        styles_on_status = [f[0] for f in rows[1]]
        self.assertEqual(styles_on_status, [C_PANE_OFF])

    def test_title_uses_c_section(self):
        s = scripts_view.Script(name="autobow", enabled=True)
        rows = scripts_view.render_detail_lines(s, 40)
        self.assertEqual(rows[0][0][0], C_SECTION)
        self.assertEqual(rows[0][0][1], "autobow")

    def test_alias_name_uses_c_active(self):
        # Alias names render white (C_ACTIVE / bold #ffffff) — gold and
        # blue are reserved for cursor / channel signals.
        s = scripts_view.Script(
            name="x", enabled=True,
            aliases=[("foo", "do a thing")],
        )
        rows = scripts_view.render_detail_lines(s, 40)
        # Find the row whose first fragment is the alias label.
        for r in rows:
            if r and r[0][1] == "  foo":
                self.assertEqual(r[0][0], C_ACTIVE)
                return
        self.fail("alias row missing")

    def test_help_wraps_to_detail_content_w(self):
        # Content wraps to detail_w - SB_W so wrapped rows can't overlap
        # the reserved scrollbar column.
        s = scripts_view.Script(
            name="x", enabled=True,
            help=["a b c d e f g h i j k l m n o p q r s t"],
        )
        rows = scripts_view.render_detail_lines(s, 10)
        help_idx = None
        for i, r in enumerate(rows):
            if r and r[0][1] == "Help":
                help_idx = i
                break
        self.assertIsNotNone(help_idx)
        # At least two wrapped lines for the long help line.
        wrapped = rows[help_idx + 1:]
        self.assertGreater(sum(1 for r in wrapped if r), 1)


class TestRenderBody(unittest.TestCase):

    def _scripts(self):
        return [
            scripts_view.Script(name="autobow",   enabled=True,
                                 summary="Bow loop"),
            scripts_view.Script(name="autostab",  enabled=True,
                                 summary="Backstab loop"),
            scripts_view.Script(name="coinlooter", enabled=False,
                                 summary="Loot coins"),
        ]

    def test_row_count_matches_body_h(self):
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=8, focus="list", mode="interactive",
        )
        # Body rows are newline-terminated; count newlines.
        n = sum(1 for f in frags if f[1] == "\n")
        self.assertEqual(n, 8)

    def test_cursor_row_amber_when_list_focused(self):
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=1, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
        )
        # Find the autostab list cell.
        found = False
        for f in frags:
            text = f[1]
            if "autostab" in text and text.startswith("[X]"):
                self.assertEqual(f[0], C_BUTTON_ACTIVE_FOCUSED)
                found = True
        self.assertTrue(found, "autostab cursor row not emitted")

    def test_cursor_row_grey_when_detail_focused(self):
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="detail", mode="interactive",
        )
        for f in frags:
            text = f[1]
            if "autobow" in text and text.startswith("[X]"):
                self.assertEqual(f[0], C_BUTTON_ACTIVE_UNFOCUSED)
                return
        self.fail("autobow row missing")

    def test_disabled_row_dimmed_when_not_cursor(self):
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
        )
        for f in frags:
            text = f[1]
            if "coinlooter" in text and text.startswith("[ ]"):
                self.assertEqual(f[0], C_PANE_OFF)
                return
        self.fail("coinlooter row missing")

    def test_enabled_non_cursor_row_uses_c_item(self):
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=2, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
        )
        for f in frags:
            text = f[1]
            if "autobow" in text and text.startswith("[X]"):
                self.assertEqual(f[0], C_ITEM)
                return
        self.fail("autobow row missing")

    def test_hover_paints_c_hover_in_both_modes(self):
        # Hover styling is applied in both interactive and readonly
        # modes — the popup needs hover too, and the read-only contract
        # is enforced by the mouse handlers (no toggling), not by the
        # renderer.
        for mode in ("interactive", "readonly"):
            frags = scripts_view.render_body(
                self._scripts(), cursor_idx=0, list_scroll=0,
                detail_scroll=0, term_cols=120, body_h=6, focus="list",
                mode=mode, hover_row=1,
            )
            for f in frags:
                text = f[1]
                if "autostab" in text and text.startswith("[X]"):
                    self.assertEqual(f[0], C_HOVER, f"mode={mode}")
                    break
            else:
                self.fail(f"autostab hover row missing (mode={mode})")

    def test_hover_paints_c_hover_in_interactive(self):
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
            hover_row=1,
        )
        for f in frags:
            text = f[1]
            if "autostab" in text and text.startswith("[X]"):
                self.assertEqual(f[0], C_HOVER)
                return
        self.fail("autostab hover row missing")

    def test_row_handler_attaches_3tuple(self):
        captured = []

        def make_h(idx):
            captured.append(idx)
            return f"handler-{idx}"

        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
            row_handler=make_h,
        )
        # Every script row gets a 3-tuple with a handler.
        names = {s.name for s in self._scripts()}
        for f in frags:
            if len(f) == 3 and any(n in f[1] for n in names):
                self.assertEqual(f[2], f"handler-{captured.pop(0)}")
                break
        else:
            self.fail("no handler attached to any list row")

    def test_empty_state_when_no_scripts(self):
        frags = scripts_view.render_body(
            [], cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=10, focus="list", mode="interactive",
        )
        # The empty-state copy includes "No scripts found".
        text = "".join(f[1] for f in frags)
        self.assertIn("No scripts found", text)
        self.assertIn("see docs/scripts.md", text)

    def test_cursor_idx_minus_one_suppresses_highlight(self):
        # cursor_idx=-1 (used by the launcher when the cursor sits on
        # the in-column Back row) should leave every script row in its
        # default styling.
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=-1, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
        )
        # No script row should paint amber-on-black.
        for f in frags:
            if f[0] == C_BUTTON_ACTIVE_FOCUSED:
                self.fail(f"cursor=-1 still highlighted: {f}")

    def test_detail_idx_drives_detail_when_set(self):
        # When detail_idx is supplied, the detail panel shows that
        # script regardless of cursor_idx (the launcher uses this so
        # Back doesn't lose the previously-browsed script's preview).
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=-1, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=6, focus="list", mode="interactive",
            detail_idx=2,
        )
        text = "".join(f[1] for f in frags)
        # coinlooter (index 2)'s summary should be in the detail panel.
        self.assertIn("Loot coins", text)

    def test_extra_left_rows_follow_last_script_row(self):
        # extra_left_rows are emitted in the left column immediately
        # below the last visible script row (not pinned to the bottom
        # of the body). The detail panel still fills the full body.
        marker = "★Back★"
        extra = [
            [("", " " * 6)],                # blank row
            [("fg:#ffaf00", marker)],       # mock Back row
        ]
        frags = scripts_view.render_body(
            self._scripts(), cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=8, focus="list", mode="interactive",
            extra_left_rows=extra,
        )
        rows = _split_rows(frags)
        # 3 scripts → list_h=3; extras at rows 3 (blank) and 4 (Back).
        # The Back marker must land on body row 4, not the trailing
        # filler rows 5/6/7.
        self.assertIn(marker, rows[4])
        self.assertNotIn(marker, rows[7])

    def test_extra_left_rows_shrink_visible_list(self):
        # With 5 scripts in a 4-row body that reserves 2 rows for
        # extras, the list capacity is 4-2=2 — only 2 script rows fit.
        many = [
            scripts_view.Script(name=f"s{i}", enabled=True) for i in range(5)
        ]
        extra = [[("", " " * 16)], [("", " " * 16)]]
        frags = scripts_view.render_body(
            many, cursor_idx=0, list_scroll=0, detail_scroll=0,
            term_cols=120, body_h=4, focus="list", mode="interactive",
            extra_left_rows=extra,
        )
        text = "".join(f[1] for f in frags)
        # s0 and s1 are visible; s2/s3/s4 aren't.
        self.assertIn("s0", text)
        self.assertIn("s1", text)
        self.assertNotIn("s2", text)


if __name__ == "__main__":
    unittest.main()
