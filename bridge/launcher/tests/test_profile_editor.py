# Phase-2 launcher editor tests — display-list sort order, delete from
# items, save reflects the deletion, cursor clamps after deletion.
#
# Run with: python -m unittest bridge.launcher.tests.test_profile_editor
#   (from PROJECT_DIR) — or `python -m unittest discover bridge/launcher/tests`.

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Allow `import launcher` and `import profile_io` when run directly via the
# launcher's sys.path convention.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher        # noqa: E402
import profile_io      # noqa: E402


def _make_profile(source):
    """Write `source` to a temp .tin, load it, and return (profile, dst).

    `dst` lives in the same temp directory; `save_profile` writes there
    when the test mutates the profile and wants to check the file."""
    td = tempfile.mkdtemp()
    src = Path(td) / "in.tin"
    src.write_text(source)
    prof = profile_io.load_profile(src)
    return prof, src, td


def _reset_editor_state(profile):
    """Place `profile` into the editor's module-level state, fresh defaults."""
    launcher._editor_profile_path = profile.path
    launcher._editor_data         = profile
    launcher._editor_active_tab   = 0   # Aliases
    launcher._editor_hover_tab    = None
    launcher._editor_focus        = 1   # list focus — the surface under test
    launcher._editor_list_cursor  = 0
    launcher._editor_list_scroll  = 0
    launcher._editor_sort_dir     = "asc"
    launcher._editor_hover_row    = None
    launcher._editor_hover_sort   = False
    launcher._editor_delete_entry = None


class TestDisplayViewSort(unittest.TestCase):
    """The Aliases tab list is rendered in sorted order, but the underlying
    Profile.items list is not mutated by sort — so unchanged entries keep
    their _raw and the file round-trips byte-exact."""

    def test_default_is_ascending(self):
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        view = launcher._profile_editor_display_view()
        patterns = [e.pattern for e in view]
        self.assertEqual(patterns, ["ab", "nw", "ws"])

    def test_toggle_flips_direction(self):
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        launcher._editor_sort_dir = "desc"
        view = launcher._profile_editor_display_view()
        self.assertEqual([e.pattern for e in view], ["ws", "nw", "ab"])

    def test_items_unmodified_by_sort(self):
        # The display view is *presentation only* — Profile.items stays
        # in source order so unchanged entries continue to emit their
        # original `_raw` span byte-for-byte.
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        before = [it.pattern for it in prof.items
                  if isinstance(it, profile_io.Entry)]
        _ = launcher._profile_editor_display_view()
        launcher._editor_sort_dir = "desc"
        _ = launcher._profile_editor_display_view()
        after = [it.pattern for it in prof.items
                 if isinstance(it, profile_io.Entry)]
        self.assertEqual(before, ["ws", "ab", "nw"])
        self.assertEqual(before, after)

    def test_round_trip_byte_exact_after_sort(self):
        # Sorting the display view must not affect what save_profile writes.
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, td = _make_profile(source)
        _reset_editor_state(prof)
        _ = launcher._profile_editor_display_view()
        launcher._editor_sort_dir = "desc"
        _ = launcher._profile_editor_display_view()
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(dst.read_text(), source)


class TestDelete(unittest.TestCase):
    """`d` on a selected row stashes the cursor Entry in
    `_editor_delete_entry`; Enter on the confirm sub-frame removes it from
    Profile.items via `list.remove(entry)`. The next save reflects it.
    `Esc` cancels without mutation."""

    def _confirm_delete(self, prof):
        """Drive `_profile_editor_confirm_delete` while keeping the frame
        stack consistent (the underlying `_pop_frame` walks both)."""
        launcher._frame_stack.append("profile_editor")
        launcher._current_frame = "profile_editor_delete_confirm"
        launcher._profile_editor_confirm_delete()

    def _cancel_delete(self):
        launcher._frame_stack.append("profile_editor")
        launcher._current_frame = "profile_editor_delete_confirm"
        launcher._profile_editor_cancel_delete()

    def test_delete_removes_entry_from_items(self):
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        # Cursor on first display row → "ab" (ascending sort).
        view = launcher._profile_editor_display_view()
        target = view[0]
        self.assertEqual(target.pattern, "ab")
        launcher._editor_delete_entry = target
        self._confirm_delete(prof)
        remaining = [e.pattern for it in prof.items
                     if isinstance(it, profile_io.Entry)
                     for e in [it]]
        self.assertNotIn("ab", remaining)
        self.assertEqual(set(remaining), {"ws", "nw"})
        self.assertIsNone(launcher._editor_delete_entry)

    def test_delete_persists_through_save(self):
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, td = _make_profile(source)
        _reset_editor_state(prof)
        view = launcher._profile_editor_display_view()
        target = next(e for e in view if e.pattern == "ab")
        launcher._editor_delete_entry = target
        self._confirm_delete(prof)
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        written = dst.read_text()
        # The "ab" line is gone; the other two survive in their original
        # source order with their _raw bytes untouched.
        self.assertNotIn("{ab}", written)
        self.assertEqual(
            written,
            "#alias {ws} {wake;stand}\n"
            "#alias {nw} {northwest}\n",
        )

    def test_cancel_keeps_entry(self):
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
        )
        prof, _src, td = _make_profile(source)
        _reset_editor_state(prof)
        view = launcher._profile_editor_display_view()
        launcher._editor_delete_entry = view[0]   # "ab"
        self._cancel_delete()
        # No mutation: items list and file are unchanged.
        self.assertEqual(len(prof.entries_of("alias")), 2)
        self.assertIsNone(launcher._editor_delete_entry)
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(dst.read_text(), source)

    def test_passthrough_lines_untouched_by_delete(self):
        # Passthrough lines (#var, #event, blanks, etc.) must survive a
        # delete operation byte-exact. This protects the round-trip
        # contract for the rest of the file.
        source = (
            "#var {mytarget} {orc}\n"
            "\n"
            "#alias {ws} {wake;stand}\n"
            "#event {SESSION CONNECTED} {#showme welcome}\n"
            "#alias {ab} {abandon}\n"
        )
        prof, _src, td = _make_profile(source)
        _reset_editor_state(prof)
        view = launcher._profile_editor_display_view()
        launcher._editor_delete_entry = next(
            e for e in view if e.pattern == "ab")
        self._confirm_delete(prof)
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(
            dst.read_text(),
            "#var {mytarget} {orc}\n"
            "\n"
            "#alias {ws} {wake;stand}\n"
            "#event {SESSION CONNECTED} {#showme welcome}\n",
        )


class TestCursorClamp(unittest.TestCase):
    """After deletion the list cursor must land on a valid display row."""

    def _confirm_delete(self):
        launcher._frame_stack.append("profile_editor")
        launcher._current_frame = "profile_editor_delete_confirm"
        launcher._profile_editor_confirm_delete()

    def test_cursor_clamps_when_last_entry_deleted(self):
        # Cursor on the final display row; deleting that row must clamp
        # the cursor to the new last index (len-1).
        source = (
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
            "#alias {ws} {wake;stand}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        # Display sort is asc → indices map to [ab, nw, ws]. Cursor on ws.
        launcher._editor_list_cursor = 2
        view = launcher._profile_editor_display_view()
        launcher._editor_delete_entry = view[2]
        self._confirm_delete()
        # Two entries remain; cursor should clamp to 1 (the new last).
        self.assertEqual(launcher._profile_editor_active_count(), 2)
        self.assertEqual(launcher._editor_list_cursor, 1)

    def test_cursor_resets_to_zero_when_list_empties(self):
        source = "#alias {only} {body}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        view = launcher._profile_editor_display_view()
        launcher._editor_delete_entry = view[0]
        self._confirm_delete()
        self.assertEqual(launcher._profile_editor_active_count(), 0)
        self.assertEqual(launcher._editor_list_cursor, 0)

    def test_cursor_unaffected_when_earlier_row_deleted(self):
        # Cursor on row 2 ("ws"); deleting row 0 ("ab") should not move
        # the cursor (it still points at row index 1 = "ws").
        source = (
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
            "#alias {ws} {wake;stand}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        launcher._editor_list_cursor = 2
        view = launcher._profile_editor_display_view()
        launcher._editor_delete_entry = view[0]   # ab
        self._confirm_delete()
        # cursor was at 2 (ws); after removing ab there are 2 entries;
        # max(0, min(1, 2)) → 1, which still points at "ws" in the new view.
        self.assertEqual(launcher._editor_list_cursor, 1)
        new_view = launcher._profile_editor_display_view()
        self.assertEqual(new_view[launcher._editor_list_cursor].pattern, "ws")


class TestDetailPanelPriority(unittest.TestCase):
    """Detail-panel render — entries with `priority` set show an extra
    `Priority: <N>` line in `C_HINT` below the Body field. Entries
    without priority show no such line."""

    def _detail_text(self, entry):
        # Render the detail rows for `entry` at a fixed body height and
        # join the visible text. Fragments are (style, padded_text);
        # we strip each cell's trailing pad to compare cleanly.
        rows = launcher._editor_detail_lines(entry, total_lines=20)
        return [t.rstrip() for (_s, t) in rows]

    def test_priority_line_present_when_set(self):
        e = launcher.profile_io.Entry(
            kind="alias", pattern="test", body="kill %1",
            priority=1, _raw=None)
        lines = self._detail_text(e)
        # The Priority line should appear after the closing body box row.
        self.assertIn("Priority: 1", lines)

    def test_priority_line_absent_when_unset(self):
        e = launcher.profile_io.Entry(
            kind="alias", pattern="test", body="kill %1",
            priority=None, _raw=None)
        lines = self._detail_text(e)
        for line in lines:
            self.assertFalse(line.startswith("Priority:"),
                             f"unexpected priority line: {line!r}")


if __name__ == "__main__":
    unittest.main()
