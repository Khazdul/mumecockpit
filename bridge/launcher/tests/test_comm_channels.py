# Unit tests for bridge/launcher/comm_channels.py — the shared channel
# on/off list render + conf read/write module backing the launcher and the
# popup Options → Panes → Communication frames. Tests run without
# prompt_toolkit installed; the module itself imports nothing from it.

import os
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import comm_channels  # noqa: E402
from palette import (  # noqa: E402
    C_ACTIVE,
    C_CURSOR_CELL,
    C_ITEM,
    C_PANE_OFF,
)


def _styles_for_text(frags, text):
    """Yield styles from fragments whose text exactly matches `text`."""
    for f in frags:
        if len(f) >= 2 and f[1] == text:
            yield f[0]


def _sample_rows():
    """A mix of enabled / disabled channels keyed off the real CHANNEL_ORDER.
    Index 0 (tales) disabled, index 1 (tells) enabled, everything else
    enabled — so each test can pick the row it needs."""
    filters = {"tales": False, "tells": True}
    return comm_channels.channel_rows(filters)


class TestLabels(unittest.TestCase):

    def test_display_override(self):
        self.assertEqual(comm_channels.channel_label("tales"), "Narrates")

    def test_title_case_fallback(self):
        self.assertEqual(comm_channels.channel_label("questions"), "Questions")
        self.assertEqual(comm_channels.channel_label("songs"), "Songs")

    def test_channel_rows_cover_order_with_sparse_default(self):
        rows = comm_channels.channel_rows({"tales": False})
        names = [r[0] for r in rows]
        self.assertEqual(names, comm_channels.CHANNEL_ORDER)
        by_name = {r[0]: r[2] for r in rows}
        # Explicit False honoured; every other (missing) channel is enabled.
        self.assertFalse(by_name["tales"])
        self.assertTrue(by_name["tells"])
        self.assertTrue(by_name["socials"])


class TestFiltersRoundTrip(unittest.TestCase):

    def test_sparse_write_read_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "comm_filters.conf")
            filters = {"tales": False, "yells": True}
            comm_channels.write_filters(filters, path=path)
            got = comm_channels.read_filters(path=path)
            self.assertEqual(got, filters)

    def test_only_explicit_keys_written(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "comm_filters.conf")
            comm_channels.write_filters({"tales": False}, path=path)
            with open(path) as fh:
                body = fh.read()
            self.assertEqual(body, "tales=false\n")
            # No enabled channel leaks into the file.
            self.assertNotIn("tells", body)

    def test_missing_file_reads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "absent.conf")
            self.assertEqual(comm_channels.read_filters(path=path), {})

    def test_garbage_lines_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "comm_filters.conf")
            with open(path, "w") as fh:
                fh.write("# a comment\n")
                fh.write("noequalshere\n")
                fh.write("tales=maybe\n")     # not true/false → skipped
                fh.write("tells=false\n")
            got = comm_channels.read_filters(path=path)
            self.assertEqual(got, {"tells": False})


class TestPrefsRoundTrip(unittest.TestCase):

    def test_default_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "absent.conf")
            self.assertTrue(comm_channels.read_show_header(path=path))

    def test_write_read_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "comm_prefs.conf")
            comm_channels.write_show_header(False, path=path)
            self.assertFalse(comm_channels.read_show_header(path=path))
            comm_channels.write_show_header(True, path=path)
            self.assertTrue(comm_channels.read_show_header(path=path))

    def test_single_key_body(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "comm_prefs.conf")
            comm_channels.write_show_header(False, path=path)
            with open(path) as fh:
                self.assertEqual(fh.read(), "show_header=false\n")


class TestToggleHelpers(unittest.TestCase):

    def test_toggle_channel_from_default_enabled(self):
        filters = {}
        # Missing key counts as enabled → first toggle writes explicit False.
        self.assertFalse(comm_channels.toggle_channel(filters, "tells"))
        self.assertEqual(filters, {"tells": False})
        # Toggling again flips back to enabled.
        self.assertTrue(comm_channels.toggle_channel(filters, "tells"))
        self.assertEqual(filters, {"tells": True})

    def test_toggle_channel_from_explicit_false(self):
        filters = {"tales": False}
        self.assertTrue(comm_channels.toggle_channel(filters, "tales"))
        self.assertEqual(filters, {"tales": True})

    def test_toggle_header(self):
        self.assertFalse(comm_channels.toggle_header(True))
        self.assertTrue(comm_channels.toggle_header(False))


class TestFragments(unittest.TestCase):

    def test_enabled_row_styles(self):
        # tells (index 1) is enabled: bright [X], coloured swatch, C_ITEM label.
        frags = comm_channels.comm_channels_fragments(
            _sample_rows(), term_cols=80, cursor=None,
        )
        self.assertEqual(list(_styles_for_text(frags, "[X]")).count(C_ACTIVE),
                         len([r for r in _sample_rows() if r[2]]))
        # tells label rendered in C_ITEM; padded to the label column width.
        tells_label = "Tells".ljust(comm_channels._LABEL_W)
        self.assertEqual(list(_styles_for_text(frags, tells_label)), [C_ITEM])

    def test_disabled_row_styles(self):
        # tales (index 0) is disabled: dim [ ], greyed swatch, C_PANE_OFF label.
        frags = comm_channels.comm_channels_fragments(
            _sample_rows(), term_cols=80, cursor=None,
        )
        narrates_label = "Narrates".ljust(comm_channels._LABEL_W)
        self.assertEqual(list(_styles_for_text(frags, narrates_label)),
                         [C_PANE_OFF])
        # The disabled row's checkbox and swatch are both dim.
        bracket = _row_bracket_style(frags, row_idx=0)
        self.assertEqual(bracket, C_PANE_OFF)
        swatch = _row_swatch_style(frags, row_idx=0)
        self.assertEqual(swatch, C_PANE_OFF)

    def test_enabled_swatch_paints_channel_colour(self):
        frags = comm_channels.comm_channels_fragments(
            _sample_rows(), term_cols=80, cursor=None,
        )
        # tells swatch is row 1; its fill is the tells channel hex.
        swatch = _row_swatch_style(frags, row_idx=1)
        self.assertEqual(swatch, "bg:#008000 fg:#008000")

    def test_cursor_row_brackets_gold(self):
        # Cursor on the enabled tells row (index 1): its [X] turns gold.
        frags = comm_channels.comm_channels_fragments(
            _sample_rows(), term_cols=80, cursor=1,
        )
        self.assertEqual(_row_bracket_style(frags, row_idx=1), C_CURSOR_CELL)
        # Cursor on the disabled tales row (index 0): its [ ] turns gold too.
        frags = comm_channels.comm_channels_fragments(
            _sample_rows(), term_cols=80, cursor=0,
        )
        self.assertEqual(_row_bracket_style(frags, row_idx=0), C_CURSOR_CELL)

    def test_row_handler_attaches_three_tuples(self):
        captured = []

        def make_handler(row_idx):
            captured.append(row_idx)
            return f"h-{row_idx}"

        rows = _sample_rows()
        frags = comm_channels.comm_channels_fragments(
            rows, term_cols=80, cursor=None, row_handler=make_handler,
        )
        self.assertEqual(captured, list(range(len(rows))))
        # Row 1's bracket fragment is a 3-tuple carrying its handler.
        row1_brackets = [
            f for f in frags
            if len(f) == 3 and f[1] in ("[X]", "[ ]") and f[2] == "h-1"
        ]
        self.assertEqual(len(row1_brackets), 1)


def _row_bracket_style(frags, row_idx):
    """Return the style of the single bracket fragment on the given row.
    Rows are newline-separated; each row has exactly one [X]/[ ] fragment."""
    rows_seen = 0
    for f in frags:
        text = f[1] if len(f) >= 2 else ""
        if text in ("[X]", "[ ]"):
            if rows_seen == row_idx:
                return f[0]
        if text == "\n":
            rows_seen += 1
    return None


def _row_swatch_style(frags, row_idx):
    """Return the style of the swatch fragment (immediately after the bracket)
    on the given row."""
    rows_seen = 0
    prev_was_bracket = False
    for f in frags:
        text = f[1] if len(f) >= 2 else ""
        if prev_was_bracket and rows_seen == row_idx:
            return f[0]
        prev_was_bracket = text in ("[X]", "[ ]")
        if text == "\n":
            rows_seen += 1
    return None


if __name__ == "__main__":
    unittest.main()
