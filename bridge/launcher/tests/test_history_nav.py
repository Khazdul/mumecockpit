# Unit tests for the History frame's keyboard navigation — specifically the
# filter pill row's descend affordances. ↓, Enter, and Space all drop focus
# into the runs table at row 0 without disturbing the active filter (the
# filter is applied live on pill move, so descending only changes focus).

import os
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import launcher  # noqa: E402


class TestFilterRowDescend(unittest.TestCase):
    """On the filter pill row (`_history_focused == 0`), ↓ / Enter / Space
    all land focus on the runs table at the top row, leaving the active
    filter unchanged."""

    def _setup(self):
        # Three dummy sessions — only len() matters to the table helpers.
        launcher._history_sessions      = [object(), object(), object()]
        launcher._history_filter_items  = ["All", "Char"]
        launcher._history_filter        = "All"
        launcher._history_filter_cursor = 0
        launcher._history_focused       = 0
        launcher._history_table_cursor  = 2
        launcher._history_table_scroll  = 0

    def _descends(self, handler):
        self._setup()
        handler(None)
        self.assertEqual(launcher._history_focused, 1)
        self.assertEqual(launcher._history_table_cursor, 0)
        # The filter is untouched — descending is purely a focus change.
        self.assertEqual(launcher._history_filter, "All")

    def test_down_descends(self):
        self._descends(launcher._kb_hist_down)

    def test_enter_descends(self):
        # `enter` and `space` share `_kb_hist_enter`.
        self._descends(launcher._kb_hist_enter)

    def test_space_descends(self):
        self._descends(launcher._kb_hist_enter)


if __name__ == "__main__":
    unittest.main()
