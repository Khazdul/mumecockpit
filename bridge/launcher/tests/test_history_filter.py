# Unit tests for bridge/launcher/history_filter.py — the pure windowing
# computation backing the History frame's filter pill row scroll.

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import history_filter  # noqa: E402


def _w(labels):
    """Pill widths matching the launcher's `len(label) + 4` formula."""
    return [len(s) + 4 for s in labels]


class TestFitsAndTotalWidth(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(history_filter.total_row_width([]), 0)
        self.assertTrue(history_filter.fits([], 0))

    def test_single_pill(self):
        # One pill of width 7 (no separator).
        self.assertEqual(history_filter.total_row_width([7]), 7)
        self.assertTrue(history_filter.fits([7], 7))
        self.assertFalse(history_filter.fits([7], 6))

    def test_multiple_pills_include_separators(self):
        # 5 + 2 + 5 + 2 + 5 = 19
        self.assertEqual(history_filter.total_row_width([5, 5, 5]), 19)


class TestComputeWindowFits(unittest.TestCase):

    def test_fits_returns_full_range_no_arrows(self):
        widths = _w(["All", "Alice", "Bob"])  # 7 + 9 + 7 = 23 + 4 = 27
        start, end, la, ra, overflows = history_filter.compute_window(widths, 40, 0)
        self.assertEqual((start, end), (0, 3))
        self.assertFalse(la)
        self.assertFalse(ra)
        self.assertFalse(overflows)

    def test_exact_fit_no_arrows(self):
        widths = [5, 5, 5]  # total 19
        start, end, la, ra, overflows = history_filter.compute_window(widths, 19, 0)
        self.assertEqual((start, end), (0, 3))
        self.assertFalse(la)
        self.assertFalse(ra)
        self.assertFalse(overflows)


class TestComputeWindowOverflow(unittest.TestCase):

    def test_single_pill_overflow_window_clipped_to_first(self):
        # Five pills of width 5, total = 33. Available width 20 leaves
        # usable = 16. Two pills fit (5 + 2 + 5 = 12); three don't
        # (5 + 2 + 5 + 2 + 5 = 19). One pill hidden on the right.
        widths = [5, 5, 5, 5, 5]
        start, end, la, ra, overflows = history_filter.compute_window(widths, 20, 0)
        self.assertTrue(overflows)
        self.assertEqual((start, end), (0, 2))
        self.assertFalse(la)
        self.assertTrue(ra)

    def test_overflow_middle_window_both_arrows(self):
        widths = [5, 5, 5, 5, 5]
        start, end, la, ra, _ = history_filter.compute_window(widths, 20, 2)
        self.assertEqual((start, end), (2, 4))
        self.assertTrue(la)
        self.assertTrue(ra)

    def test_overflow_offset_clamped_to_max(self):
        # max_offset for 5 pills × width 5 in available=20 is 3 (so the
        # window is [3, 5)). Offsets past 3 clamp down.
        widths = [5, 5, 5, 5, 5]
        start, end, la, ra, _ = history_filter.compute_window(widths, 20, 99)
        self.assertEqual((start, end), (3, 5))
        self.assertTrue(la)
        self.assertFalse(ra)

    def test_offset_negative_clamped_to_zero(self):
        widths = [5, 5, 5, 5, 5]
        start, end, _, _, _ = history_filter.compute_window(widths, 20, -3)
        self.assertEqual((start, end), (0, 2))

    def test_degenerate_single_pill_wider_than_usable(self):
        # Usable = available - 4 = 4; pill is 10 wide. We still show one
        # pill (clips) rather than nothing.
        widths = [10, 5]
        start, end, _, _, overflows = history_filter.compute_window(widths, 8, 0)
        self.assertTrue(overflows)
        self.assertEqual((start, end), (0, 1))


class TestMaxOffset(unittest.TestCase):

    def test_max_offset_zero_when_fits(self):
        self.assertEqual(history_filter.max_offset([5, 5], 20), 0)

    def test_max_offset_overflow(self):
        # 5 pills × 5 wide, available 20, usable 16. Pills [3,4]
        # together = 5+2+5 = 12 ≤ 16; pills [2,3,4] = 19 > 16. So
        # max_offset = 3.
        self.assertEqual(history_filter.max_offset([5, 5, 5, 5, 5], 20), 3)

    def test_max_offset_with_varied_widths(self):
        # Widths [3, 9, 5, 7]; available 14, usable 10. Last pill is 7,
        # adding 5 → 5+2+7 = 14 > 10. So max_offset = 3.
        self.assertEqual(history_filter.max_offset([3, 9, 5, 7], 14), 3)


class TestScrollToCursor(unittest.TestCase):

    def test_cursor_in_window_no_change(self):
        widths = [5, 5, 5, 5, 5]
        # Offset 1 → window [1, 3). Cursor 2 already visible.
        self.assertEqual(history_filter.scroll_to_cursor(widths, 20, 2, 1), 1)

    def test_cursor_left_of_window_pans_left(self):
        widths = [5, 5, 5, 5, 5]
        # Offset 2 → window [2, 4). Cursor 0 not visible. Pan to 0.
        self.assertEqual(history_filter.scroll_to_cursor(widths, 20, 0, 2), 0)

    def test_cursor_right_of_window_pans_right_min(self):
        widths = [5, 5, 5, 5, 5]
        # Offset 0 → window [0, 2). Cursor 3 is right of window. New
        # offset: largest start ≤ 3 with [start..3] fitting in 16.
        # [3,3] = 5; [2,3] = 12; [1,3] = 5+2+5+2+5 = 19 > 16. So 2.
        self.assertEqual(history_filter.scroll_to_cursor(widths, 20, 3, 0), 2)

    def test_cursor_at_right_end(self):
        widths = [5, 5, 5, 5, 5]
        # Cursor at last pill, offset 0. Pan right until cursor is the
        # last visible. New offset = 3 (window [3,5)).
        self.assertEqual(history_filter.scroll_to_cursor(widths, 20, 4, 0), 3)

    def test_cursor_at_left_end(self):
        widths = [5, 5, 5, 5, 5]
        # Cursor at first pill while offset is at right edge. Pan back to 0.
        self.assertEqual(history_filter.scroll_to_cursor(widths, 20, 0, 3), 0)

    def test_exact_fit_returns_zero_offset(self):
        widths = [5, 5, 5]
        # 19 ≤ 19 — fits. Offset always 0 regardless of cursor.
        self.assertEqual(history_filter.scroll_to_cursor(widths, 19, 0, 0), 0)
        self.assertEqual(history_filter.scroll_to_cursor(widths, 19, 2, 99), 0)

    def test_single_pill_overflow(self):
        # Single pill hidden on the right: cursor lands on the last pill.
        widths = [5, 5, 5, 5, 5]
        # Available 23 → usable 19. Pills fit 3 (5+2+5+2+5 = 19). One
        # pill hidden on the right; offset 0 still shows [0, 3).
        start, end, _, ra, _ = history_filter.compute_window(widths, 23, 0)
        self.assertEqual((start, end), (0, 3))
        self.assertTrue(ra)
        # Moving cursor onto pill 3 should pan right minimally — window
        # becomes [1, 4).
        new_offset = history_filter.scroll_to_cursor(widths, 23, 3, 0)
        self.assertEqual(new_offset, 1)
        start, end, la, ra, _ = history_filter.compute_window(widths, 23, new_offset)
        self.assertEqual((start, end), (1, 4))
        self.assertTrue(la)
        self.assertTrue(ra)
        # Moving cursor onto the last pill scrolls one more step.
        new_offset = history_filter.scroll_to_cursor(widths, 23, 4, new_offset)
        self.assertEqual(new_offset, 2)
        start, end, la, ra, _ = history_filter.compute_window(widths, 23, new_offset)
        self.assertEqual((start, end), (2, 5))
        self.assertTrue(la)
        self.assertFalse(ra)


class TestPan(unittest.TestCase):

    def test_pan_clamps_zero(self):
        widths = [5, 5, 5, 5, 5]
        self.assertEqual(history_filter.pan(widths, 20, 0, -1), 0)

    def test_pan_clamps_max(self):
        widths = [5, 5, 5, 5, 5]
        self.assertEqual(history_filter.pan(widths, 20, 3, 1), 3)

    def test_pan_returns_zero_when_fits(self):
        widths = [5, 5]
        self.assertEqual(history_filter.pan(widths, 40, 0, 1), 0)

    def test_pan_step(self):
        widths = [5, 5, 5, 5, 5]
        self.assertEqual(history_filter.pan(widths, 20, 1, 1), 2)
        self.assertEqual(history_filter.pan(widths, 20, 2, -1), 1)


class TestEmptyRow(unittest.TestCase):

    def test_no_pills(self):
        start, end, la, ra, overflows = history_filter.compute_window([], 40, 0)
        self.assertEqual((start, end), (0, 0))
        self.assertFalse(la)
        self.assertFalse(ra)
        self.assertFalse(overflows)
        self.assertEqual(history_filter.scroll_to_cursor([], 40, 0, 0), 0)
        self.assertEqual(history_filter.max_offset([], 40), 0)
        self.assertEqual(history_filter.pan([], 40, 0, 1), 0)


if __name__ == "__main__":
    unittest.main()
