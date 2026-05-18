# Phase-2 + Phase-3 launcher editor tests.
# - Phase 2: display-list sort, delete from items, save reflects deletion,
#   cursor clamps after deletion, priority-line presence in detail panel.
# - Phase 3: editing Pattern/Body/Priority via the live-binding helpers;
#   "+ New entry" sentinel + create flow; save_profile drops empty-pattern
#   entries; field mutation regenerates canonically; untouched entries
#   continue to emit `_raw` verbatim; priority round-trips through the
#   editor for unrelated edits.
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


def _reset_editor_state(profile, *, focus=1):
    """Place `profile` into the editor's module-level state, fresh defaults.

    Phase-3 adds detail-panel state. `focus` defaults to 1 (list) since
    most tests exercise list-level behaviour; pass `focus=2` to drive
    the detail-panel editing paths."""
    launcher._editor_profile_path = profile.path
    launcher._editor_data         = profile
    launcher._editor_active_tab   = 0   # Aliases
    launcher._editor_hover_tab    = None
    launcher._editor_focus        = focus
    launcher._editor_list_cursor  = 0
    launcher._editor_list_scroll  = 0
    launcher._editor_sort_dir     = "asc"
    launcher._editor_hover_row    = None
    launcher._editor_hover_sort   = False
    launcher._editor_delete_entry = None
    launcher._editor_detail_field    = 0
    launcher._editor_body_line       = 0
    launcher._editor_priority_buf    = ""
    launcher._editor_pattern_touched = False
    launcher._editor_refresh_buffers()


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
    """Detail-panel render — phase 3 shows the Priority field as its own
    bordered box rather than the phase-2 "Priority: <N>" label line. The
    priority value appears inside the box when set; the box renders
    empty (with the placeholder hint beside the label) when unset."""

    def _detail_text(self, entry):
        # Render the detail rows for `entry` against a fresh profile so
        # the renderer can resolve `_editor_current_entry` etc. Each row
        # is a list of (style, text) fragments — join their texts and
        # strip trailing pad for clean comparison.
        prof, _src, _td = _make_profile("")
        prof.items.append(entry)
        _reset_editor_state(prof)
        rows = launcher._editor_detail_lines(entry, total_lines=20)
        return ["".join(t for (_s, t) in row).rstrip() for row in rows]

    def test_priority_box_shows_value_when_set(self):
        e = launcher.profile_io.Entry(
            kind="alias", pattern="test", body="kill %1",
            priority=1, _raw=None)
        lines = self._detail_text(e)
        # The Priority label sits above its narrow box; the value lives
        # inside `│ 1   │`.
        self.assertIn("Priority", lines)
        self.assertTrue(
            any(stripped.startswith("│ 1") for stripped in lines),
            f"expected priority value in box, lines were: {lines!r}")

    def test_priority_placeholder_when_unset(self):
        e = launcher.profile_io.Entry(
            kind="alias", pattern="test", body="kill %1",
            priority=None, _raw=None)
        lines = self._detail_text(e)
        # No "Priority: <N>" legacy line.
        for line in lines:
            self.assertFalse(line.startswith("Priority:"),
                             f"unexpected legacy priority line: {line!r}")
        # The `(optional)` placeholder appears beside the label when the
        # buffer is empty.
        self.assertTrue(
            any("(optional)" in line for line in lines),
            f"expected placeholder hint, lines were: {lines!r}")


class TestEntryMarkModified(unittest.TestCase):
    """Mutating any of `Entry.pattern` / `Entry.body` / `Entry.priority`
    clears `_raw` so `save_profile` regenerates the entry canonically."""

    def test_pattern_mutation_clears_raw(self):
        e = profile_io.Entry(
            kind="alias", pattern="k", body="kill",
            priority=None, _raw="#alias {k} {kill}")
        self.assertEqual(e._raw, "#alias {k} {kill}")
        e.pattern = "kk"
        self.assertIsNone(e._raw)

    def test_body_mutation_clears_raw(self):
        e = profile_io.Entry(
            kind="alias", pattern="k", body="kill",
            priority=None, _raw="#alias {k} {kill}")
        e.body = "kill troll"
        self.assertIsNone(e._raw)

    def test_priority_mutation_clears_raw(self):
        e = profile_io.Entry(
            kind="alias", pattern="k", body="kill",
            priority=None, _raw="#alias {k} {kill}")
        e.priority = 3
        self.assertIsNone(e._raw)

    def test_assignment_to_same_value_preserves_raw(self):
        # A no-op assignment must NOT clear _raw — otherwise reading a
        # field through the GUI would silently force a canonical
        # regeneration even if the user never changed anything.
        e = profile_io.Entry(
            kind="alias", pattern="k", body="kill",
            priority=None, _raw="#alias {k} {kill}")
        e.pattern = "k"
        e.body = "kill"
        e.priority = None
        self.assertEqual(e._raw, "#alias {k} {kill}")


class TestSaveDropsEmptyPattern(unittest.TestCase):
    """Phase-3 abandoned create attempts (empty-pattern entries) are
    dropped before write so the resulting file has no malformed lines."""

    def test_empty_pattern_entry_is_dropped(self):
        source = "#alias {k} {kill %1}\n"
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            # Simulate an abandoned `+ New entry` row.
            prof.items.append(profile_io.Entry(
                kind="alias", pattern="", body="", priority=None, _raw=None))
            prof.path = dst
            profile_io.save_profile(prof)
            # The empty-pattern Entry is gone; the real one is preserved.
            self.assertEqual(dst.read_text(), source)

    def test_whitespace_only_pattern_also_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "out.tin"
            prof = profile_io.Profile(path=dst, items=[
                profile_io.Entry(
                    kind="alias", pattern="   ", body="x",
                    priority=None, _raw=None),
                profile_io.Entry(
                    kind="alias", pattern="k", body="kill",
                    priority=None, _raw=None),
            ])
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), "#alias {k} {kill}\n")


class TestEditedEntryRegeneratesCanonically(unittest.TestCase):
    """An edited entry serialises as `#<kind> {pattern} {body}[ {priority}]`;
    entries that were not touched continue to emit `_raw` byte-exact in
    the same file."""

    def test_mixed_edited_and_untouched_in_same_file(self):
        source = (
            "#alias    {keep}    {body1}\n"
            "#alias {touch} {body2}\n"
            "#alias {also_keep} {body3} {5}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            target = next(e for e in prof.entries_of("alias")
                          if e.pattern == "touch")
            # Edit through the helper that clears _raw via __setattr__.
            target.body = "new_body"
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(
                dst.read_text(),
                # `keep` keeps its odd whitespace via _raw, `touch` is
                # regenerated canonically, `also_keep` (with priority)
                # round-trips its _raw verbatim.
                "#alias    {keep}    {body1}\n"
                "#alias {touch} {new_body}\n"
                "#alias {also_keep} {body3} {5}\n",
            )


class TestPriorityRoundTripThroughEditor(unittest.TestCase):
    """Open a profile that contains a priority entry, edit an unrelated
    entry, save — the priority entry remains byte-exact."""

    def test_unrelated_edit_leaves_priority_entry_byte_exact(self):
        source = (
            "#alias {edited} {old}\n"
            "#alias {with_prio} {body} {7}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            edited = next(e for e in prof.entries_of("alias")
                          if e.pattern == "edited")
            edited.body = "new"
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(
                dst.read_text(),
                "#alias {edited} {new}\n"
                "#alias {with_prio} {body} {7}\n",
            )


class TestRoundTripIdentityAfterEditorOpen(unittest.TestCase):
    """Loading and saving without any edits preserves byte-exact
    contents — even after running the editor's buffer-refresh helper,
    which only touches transient state."""

    def test_blank_template_round_trip(self):
        td = tempfile.mkdtemp()
        src = Path(td) / "in.tin"
        dst = Path(td) / "out.tin"
        BLANK = (Path(__file__).resolve().parent.parent
                 / "templates" / "blank_profile.tin")
        source = BLANK.read_text()
        src.write_text(source)
        prof = profile_io.load_profile(src)
        _reset_editor_state(prof)
        prof.path = dst
        profile_io.save_profile(prof)
        # Strip #nop lines from the original for the comparison —
        # save_profile drops them per ADR 0042 and we don't want this
        # test to fail on that pre-existing semantic.
        expected = "\n".join(
            line for line in source.splitlines()
            if not (line.lstrip().startswith("#nop")
                    and (len(line.lstrip()) == 4
                         or line.lstrip()[4] in (" ", "\t", "{", "\n", "\r")))
        )
        if source.endswith("\n"):
            expected += "\n"
        self.assertEqual(dst.read_text(), expected)


class TestEditPatternResorts(unittest.TestCase):
    """Editing the Pattern field via `_editor_set_pattern` re-sorts the
    displayed list and keeps the list cursor anchored to the edited
    entry — so the user's cursor stays under their hand as the row
    moves."""

    def test_pattern_edit_re_anchors_cursor(self):
        source = (
            "#alias {ab} {a}\n"
            "#alias {nw} {n}\n"
            "#alias {ws} {w}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof, focus=2)
        # Display order asc: ab, nw, ws. Position cursor on ab.
        launcher._editor_list_cursor = 0
        launcher._editor_refresh_buffers()
        self.assertEqual(launcher._editor_current_entry().pattern, "ab")
        # Rename ab → zz (last in asc order).
        launcher._editor_set_pattern("zz")
        # The cursor follows the entry: it should now point to zz at the
        # end of the asc-sorted view.
        view = launcher._profile_editor_display_view()
        self.assertEqual([e.pattern for e in view], ["nw", "ws", "zz"])
        self.assertEqual(view[launcher._editor_list_cursor].pattern, "zz")

    def test_pattern_mutation_clears_raw_via_setattr(self):
        source = "#alias {ab} {body}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof, focus=2)
        entry = launcher._editor_current_entry()
        self.assertIsNotNone(entry._raw)
        launcher._editor_set_pattern("abc")
        self.assertIsNone(entry._raw)


class TestSentinelAndCreate(unittest.TestCase):
    """The display list always has a "+ New entry" sentinel at the
    bottom (cursor index `len(view)`). `_editor_create_new_entry`
    appends a blank Entry, moves the cursor onto it, and focuses the
    detail panel's Pattern field."""

    def test_display_total_includes_sentinel(self):
        source = "#alias {a} {x}\n#alias {b} {y}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        self.assertEqual(launcher._profile_editor_active_count(), 2)
        self.assertEqual(launcher._profile_editor_display_total(), 3)
        # Sentinel sits at index len(view) regardless of sort direction.
        launcher._editor_sort_dir = "desc"
        self.assertEqual(launcher._profile_editor_display_total(), 3)

    def test_create_appends_blank_entry_and_focuses_pattern(self):
        prof, _src, _td = _make_profile("#alias {keep} {body}\n")
        _reset_editor_state(prof)
        launcher._editor_create_new_entry()
        # Items grew by one — a blank Entry of the active kind.
        aliases = prof.entries_of("alias")
        self.assertEqual(len(aliases), 2)
        new_entry = next(e for e in aliases if e.pattern == "")
        self.assertEqual(new_entry.kind, "alias")
        self.assertEqual(new_entry.body, "")
        self.assertIsNone(new_entry.priority)
        # Cursor parked on the new entry and detail.Pattern focused.
        view = launcher._profile_editor_display_view()
        self.assertEqual(view[launcher._editor_list_cursor], new_entry)
        self.assertEqual(launcher._editor_focus, 2)
        self.assertEqual(launcher._editor_detail_field, 0)

    def test_abandoned_create_is_dropped_on_save(self):
        prof, _src, td = _make_profile("#alias {keep} {body}\n")
        _reset_editor_state(prof)
        launcher._editor_create_new_entry()
        # User pressed ESC without typing — the new entry stays blank.
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(dst.read_text(), "#alias {keep} {body}\n")


class TestValidation(unittest.TestCase):
    """Pattern-required error is armed once the user leaves the field
    with an empty buffer; brace warning fires live as soon as the
    pattern contains an unescaped `{` or `}`."""

    def test_pattern_required_not_armed_on_first_focus(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        launcher._editor_create_new_entry()
        # Fresh blank entry — no error yet because the user hasn't left
        # the Pattern field.
        self.assertIsNone(launcher._editor_validation_error())

    def test_pattern_required_appears_after_leaving_field(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        launcher._editor_create_new_entry()
        # Tab away to Body — the touched flag arms.
        launcher._profile_editor_set_focus(2, field=1)
        self.assertEqual(launcher._editor_validation_error(),
                         "Pattern is required.")

    def test_pattern_required_clears_when_pattern_nonempty(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        launcher._editor_create_new_entry()
        launcher._profile_editor_set_focus(2, field=1)
        self.assertIsNotNone(launcher._editor_validation_error())
        # Type a character into Pattern.
        launcher._profile_editor_set_focus(2, field=0)
        launcher._editor_set_pattern("k")
        self.assertIsNone(launcher._editor_validation_error())

    def test_brace_warning_fires_on_unescaped_brace(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_set_pattern("k{x")
        self.assertEqual(
            launcher._editor_validation_warning(),
            "Unescaped braces may confuse tt++ — use \\{ and \\}.")

    def test_brace_warning_quiet_on_escaped_brace(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_set_pattern(r"k\{x")
        self.assertIsNone(launcher._editor_validation_warning())


class TestPriorityBuffer(unittest.TestCase):
    """Priority is stored as a string buffer in the editor; empty buffer
    means `priority=None`, non-empty means `priority=int(buffer)`. The
    `<any>` handler swallows non-digits — covered indirectly by these
    helper-level tests."""

    def test_empty_buffer_means_none(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        entry = launcher._editor_current_entry()
        launcher._editor_priority_buf = ""
        launcher._editor_set_priority_from_buf()
        self.assertIsNone(entry.priority)

    def test_nonempty_buffer_sets_int_priority(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        entry = launcher._editor_current_entry()
        launcher._editor_priority_buf = "12"
        launcher._editor_set_priority_from_buf()
        self.assertEqual(entry.priority, 12)

    def test_priority_buffer_refresh_from_entry(self):
        # Loading a priority entry into the editor surfaces the int as
        # a string buffer the user can edit.
        prof, _src, _td = _make_profile("#alias {k} {kill} {7}\n")
        _reset_editor_state(prof, focus=2)
        self.assertEqual(launcher._editor_priority_buf, "7")


if __name__ == "__main__":
    unittest.main()
