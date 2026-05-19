# Run with: python -m unittest bridge.launcher.widgets.tests.test_scrollbar
#   (from PROJECT_DIR) — or `python -m unittest discover bridge`.

import os
import sys
import unittest

# Allow `from scrollbar import Scrollbar` when run directly via the
# launcher's sys.path convention.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrollbar import Scrollbar   # noqa: E402


class TestPageStepClick(unittest.TestCase):
    """`Scrollbar.handle_click` implements the conventional page-step
    affordance: clicks above the thumb page up by one viewport, clicks
    below page down, clicks on the thumb itself are a no-op (drag is
    out of scope)."""

    def _bar(self, total=30, visible=10, height=10, offset=0):
        sb = Scrollbar(total_items=total, visible_items=visible, height=height)
        sb.scroll_to(offset)
        return sb

    def test_click_above_thumb_pages_up(self):
        # offset=20 → thumb sits near the bottom. A click at row 0
        # must page up by `visible` (10), landing at offset 10.
        sb = self._bar(total=30, visible=10, height=10, offset=20)
        top, h = sb._thumb_geometry()
        self.assertGreater(top, 0)        # thumb not at the very top
        sb.handle_click(0)
        self.assertEqual(sb.scroll_offset, 10)

    def test_click_above_thumb_clamps_at_zero(self):
        # Page-up from offset 5 with viewport 10 must clamp at 0 — not
        # underflow into negative.
        sb = self._bar(total=30, visible=10, height=10, offset=5)
        top, _h = sb._thumb_geometry()
        self.assertGreater(top, 0)
        sb.handle_click(0)
        self.assertEqual(sb.scroll_offset, 0)

    def test_click_below_thumb_pages_down(self):
        # offset=0 → thumb at the top. A click at the last row pages
        # down by 10 → offset 10.
        sb = self._bar(total=30, visible=10, height=10, offset=0)
        sb.handle_click(9)
        self.assertEqual(sb.scroll_offset, 10)

    def test_click_below_thumb_clamps_at_max(self):
        # Page-down from offset 15 with max_scroll 20 must clamp at 20.
        sb = self._bar(total=30, visible=10, height=10, offset=15)
        sb.handle_click(9)
        self.assertEqual(sb.scroll_offset, 20)

    def test_click_on_thumb_is_noop(self):
        # offset=0 → thumb occupies rows [0, thumb_h). A click inside
        # that range must not move the offset.
        sb = self._bar(total=30, visible=10, height=10, offset=0)
        top, h = sb._thumb_geometry()
        self.assertEqual(top, 0)
        # Click the very middle of the thumb.
        sb.handle_click(top + h // 2)
        self.assertEqual(sb.scroll_offset, 0)

    def test_click_when_not_scrollable_is_noop(self):
        # total <= visible → bar invisible; clicks are inert.
        sb = self._bar(total=5, visible=10, height=10, offset=0)
        self.assertFalse(sb.visible)
        sb.handle_click(0)
        sb.handle_click(9)
        self.assertEqual(sb.scroll_offset, 0)

    def test_no_center_snap_from_row_zero(self):
        # Regression for the centre-on-click behaviour we replaced.
        # Old behaviour: clicking row 0 from offset=10 would center the
        # thumb on row 0 (offset → 0). Page-step replacement: it should
        # only step up by one viewport.
        sb = self._bar(total=40, visible=10, height=10, offset=10)
        top, _h = sb._thumb_geometry()
        self.assertGreater(top, 0)
        sb.handle_click(0)
        self.assertEqual(sb.scroll_offset, 0)
        # …but starting from offset=20 the click only pages up by 10.
        sb = self._bar(total=40, visible=10, height=10, offset=20)
        sb.handle_click(0)
        self.assertEqual(sb.scroll_offset, 10)


if __name__ == "__main__":
    unittest.main()
