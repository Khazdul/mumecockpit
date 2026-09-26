# Unit tests for bridge/launcher/log_export.py — the export editor's
# exclusion / comment model, sidecar persistence and the two exporters.

import os
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import log_export  # noqa: E402
import log_player  # noqa: E402


def _events(texts, start_us=1_000_000_000, step_us=1_000_000, run_id="r1"):
    out = []
    for i, t in enumerate(texts):
        out.append(log_player.LogEvent(
            ts_us=start_us + i * step_us, direction="in", text=t,
            run_id=run_id, fragments=log_player.parse_ansi(t)))
    return out


class TestExclusion(unittest.TestCase):
    def test_exclude_from_runs_to_end_when_nothing_follows(self):
        e = log_export.ExportEdits(n=10)
        e.exclude_from(4)
        self.assertEqual(e.excludes, [(4, 10)])
        self.assertTrue(e.is_excluded(9))
        self.assertFalse(e.is_excluded(3))

    def test_stop_excluding_closes_range_keeping_the_stop_line(self):
        e = log_export.ExportEdits(n=10)
        e.exclude_from(4)
        e.stop_excluding(7)
        self.assertEqual(e.excludes, [(4, 7)])
        self.assertFalse(e.is_excluded(7))
        self.assertEqual(e.excluded_count(), 3)

    def test_stop_on_first_line_removes_range(self):
        e = log_export.ExportEdits(n=10)
        e.exclude_from(4)
        e.stop_excluding(4)
        self.assertEqual(e.excludes, [])

    def test_exclude_before_existing_range_merges_into_it(self):
        e = log_export.ExportEdits(n=20)
        e.exclude_from(10)
        e.stop_excluding(15)
        e.exclude_from(3)
        self.assertEqual(e.excludes, [(3, 15)])

    def test_noop_cases(self):
        e = log_export.ExportEdits(n=5)
        e.stop_excluding(2)            # not excluded
        e.exclude_from(9)              # out of range
        self.assertEqual(e.excludes, [])
        e.exclude_from(1)
        e.exclude_from(3)              # already excluded
        self.assertEqual(e.excludes, [(1, 5)])


class TestComments(unittest.TestCase):
    def test_items_place_comments_before_their_anchor_and_end_sentinel(self):
        e = log_export.ExportEdits(n=3)
        a = e.add_comment(0, "intro")
        e.add_comment(3, "outro")
        e.add_comment(0, "second", after=a)
        kinds = [(k, v.text if k == "comment" else v) for k, v in e.items()]
        self.assertEqual(kinds, [
            ("comment", "intro"), ("comment", "second"), ("event", 0),
            ("event", 1), ("event", 2), ("comment", "outro"), ("end", 3)])

    def test_blank_comment_is_rejected_and_whitespace_collapsed(self):
        e = log_export.ExportEdits(n=2)
        self.assertIsNone(e.add_comment(0, "   "))
        c = e.add_comment(1, "  a \t b  ")
        self.assertEqual(c.text, "a b")

    def test_hold_is_clamped_between_5_and_20_seconds(self):
        self.assertEqual(log_export.comment_hold_seconds("hi"), 5.0)
        self.assertEqual(log_export.comment_hold_seconds("x" * 1000), 20.0)
        self.assertAlmostEqual(log_export.comment_hold_seconds("x" * 150), 12.0)

    def test_comment_lines_prefix_every_line(self):
        lines = log_export.comment_lines("word " * 40, width=40)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(l.startswith("## ") for l in lines))
        self.assertTrue(all(len(l) <= 40 for l in lines))


class TestSidecar(unittest.TestCase):
    def test_roundtrip_by_timestamp(self):
        evs = _events([f"line {i}" for i in range(10)])
        e = log_export.ExportEdits(n=10, title="Fight in DT", fmt="text")
        e.exclude_from(2)
        e.stop_excluding(5)
        e.exclude_from(8)
        e.add_comment(0, "intro")
        e.add_comment(10, "outro")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.export.json")
            log_export.save_edits(path, e, evs)
            back = log_export.load_edits(path, evs)
        self.assertEqual(back.excludes, [(2, 5), (8, 10)])
        self.assertEqual([(c.anchor, c.text) for c in back.comments],
                         [(0, "intro"), (10, "outro")])
        self.assertEqual((back.title, back.fmt), ("Fight in DT", "text"))

    def test_empty_edits_remove_sidecar_and_missing_file_is_empty(self):
        evs = _events(["a", "b"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.export.json")
            with open(path, "w") as f:
                f.write("{}")
            log_export.save_edits(path, log_export.ExportEdits(n=2), evs)
            self.assertFalse(os.path.exists(path))
            e = log_export.load_edits(path, evs)
        self.assertEqual((e.excludes, e.comments), ([], []))

    def test_malformed_sidecar_is_ignored(self):
        evs = _events(["a"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.export.json")
            with open(path, "w") as f:
                f.write("not json")
            e = log_export.load_edits(path, evs)
        self.assertEqual(e.n, 1)


class TestExporters(unittest.TestCase):
    def test_text_export_drops_excluded_strips_ansi_and_adds_comments(self):
        evs = _events(["\x1b[31mred\x1b[0m", "cut me", "kept"])
        e = log_export.ExportEdits(n=3)
        e.exclude_from(1)
        e.stop_excluding(2)
        e.add_comment(2, "after the cut")
        self.assertEqual(log_export.build_text(evs, e),
                         "red\n## after the cut\nkept\n")

    def test_html_data_offsets_cuts_holds_and_markers(self):
        evs = _events(["one", "two", "three", "x has drawn his last breath! R.I.P."],
                      step_us=2_000_000)
        e = log_export.ExportEdits(n=4)
        e.exclude_from(1)
        e.stop_excluding(2)            # cut: 0 -> 2 is a 4 s gap, collapsed
        e.add_comment(3, "look")
        ts_sec = evs[3].ts_us // 1_000_000
        data = log_export.build_html_data(
            evs, e, "Rasta", marker_events=[("pkill", ts_sec, "")])
        self.assertEqual(len(data["lines"]), 4)       # one, three, comment, R.I.P.
        self.assertEqual(data["offsets"], [0, 500, 500, 2500])
        self.assertEqual(data["holds"], {2: 5000})
        self.assertIn('class="cm"', data["lines"][2])
        self.assertEqual(data["markers"], [{"l": "K", "o": 2500, "t": "PvP kill"}])

    def test_html_build_embeds_payload_safely(self):
        evs = _events(["</script><b>"])
        e = log_export.ExportEdits(n=1, title="A <title>")
        page = log_export.build_html(log_export.build_html_data(evs, e, "Rasta"))
        self.assertNotIn("</script><b>", page)
        self.assertIn("<title>A &lt;title&gt;</title>", page)

    def test_dest_path_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            first = log_export.dest_path(d, "Fight/in DT", "html")
            self.assertEqual(os.path.basename(first), "Fight-in DT.html")
            open(first, "w").close()
            second = log_export.dest_path(d, "Fight/in DT", "html")
            self.assertEqual(os.path.basename(second), "Fight-in DT-2.html")


if __name__ == "__main__":
    unittest.main()
