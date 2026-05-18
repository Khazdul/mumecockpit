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


def _reset_editor_state(profile, *, focus=1, active_tab=0):
    """Place `profile` into the editor's module-level state, fresh defaults.

    `focus` defaults to 1 (list); pass `focus=2` to drive the detail-
    panel editing paths. `active_tab` defaults to 0 (Aliases); pass a
    different index for phase-4 cross-kind tests."""
    launcher._editor_profile_path = profile.path
    launcher._editor_data         = profile
    launcher._editor_active_tab   = active_tab
    launcher._editor_hover_tab    = None
    launcher._editor_focus        = focus
    launcher._editor_list_cursor  = 0
    launcher._editor_list_scroll  = 0
    launcher._editor_sort_dir     = "asc"
    launcher._editor_hover_row    = None
    launcher._editor_hover_sort   = False
    launcher._editor_detail_field    = 0
    launcher._editor_pattern_cursor  = 0
    launcher._editor_body_line       = 0
    launcher._editor_body_col        = 0
    launcher._editor_pattern_touched = False
    launcher._editor_palette_row     = 0
    launcher._editor_palette_col     = 0
    launcher._editor_palette_hover_row = None
    launcher._editor_palette_hover_col = None
    launcher._editor_palette_custom_value = None
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
    """`Del` on a selected list row removes the cursor Entry from
    `Profile.items` immediately (no confirmation). The next save
    reflects the deletion."""

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
        launcher._editor_list_cursor = 0
        launcher._profile_editor_request_delete()
        remaining = [e.pattern for it in prof.items
                     if isinstance(it, profile_io.Entry)
                     for e in [it]]
        self.assertNotIn("ab", remaining)
        self.assertEqual(set(remaining), {"ws", "nw"})

    def test_delete_persists_through_save(self):
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, td = _make_profile(source)
        _reset_editor_state(prof)
        # Cursor on "ab" (display row 0 in asc).
        launcher._editor_list_cursor = 0
        launcher._profile_editor_request_delete()
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

    def test_sentinel_cursor_is_noop(self):
        # Cursor on the "+ New entry" sentinel row → no-op (there is no
        # entry to delete).
        source = "#alias {only} {body}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        # Position cursor on the sentinel (index == len(view)).
        launcher._editor_list_cursor = len(launcher._profile_editor_display_view())
        launcher._profile_editor_request_delete()
        self.assertEqual(launcher._profile_editor_active_count(), 1)

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
        # Cursor on "ab" — display sort is asc → row 0.
        launcher._editor_list_cursor = 0
        launcher._profile_editor_request_delete()
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
        launcher._profile_editor_request_delete()
        # Two entries remain; cursor should clamp to 1 (the new last).
        self.assertEqual(launcher._profile_editor_active_count(), 2)
        self.assertEqual(launcher._editor_list_cursor, 1)

    def test_cursor_resets_to_zero_when_list_empties(self):
        source = "#alias {only} {body}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        launcher._editor_list_cursor = 0
        launcher._profile_editor_request_delete()
        self.assertEqual(launcher._profile_editor_active_count(), 0)
        self.assertEqual(launcher._editor_list_cursor, 0)

    def test_cursor_stays_on_first_when_first_row_deleted(self):
        # Cursor at row 0 deletes "ab"; cursor stays at 0 (now pointing
        # at "nw" — the new first entry).
        source = (
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
            "#alias {ws} {wake;stand}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        launcher._editor_list_cursor = 0
        launcher._profile_editor_request_delete()
        self.assertEqual(launcher._profile_editor_active_count(), 2)
        self.assertEqual(launcher._editor_list_cursor, 0)
        new_view = launcher._profile_editor_display_view()
        self.assertEqual(new_view[0].pattern, "nw")


class TestDetailPanelLayout(unittest.TestCase):
    """Detail-panel render: phase 3.5 hides Priority entirely; the field
    chain is just Pattern + (kind-labelled) Commands box. Priority is
    preserved on disk via `Entry.priority` and the serializer, but no
    longer surfaced in the editor UI."""

    def _detail_text(self, entry):
        # Render the detail rows for `entry` against a fresh profile so
        # `_editor_current_entry` etc. resolve correctly. Each row is a
        # list of 2- or 3-tuple fragments; join their texts and strip
        # trailing pad for clean comparison.
        prof, _src, _td = _make_profile("")
        prof.items.append(entry)
        _reset_editor_state(prof)
        rows = launcher._editor_detail_lines(entry, total_lines=20)
        return ["".join(f[1] for f in row).rstrip() for row in rows]

    def test_priority_label_absent_from_panel(self):
        e = launcher.profile_io.Entry(
            kind="alias", pattern="test", body="kill %1",
            priority=1, _raw=None)
        lines = self._detail_text(e)
        for line in lines:
            self.assertNotIn("Priority", line,
                             f"unexpected Priority label: {line!r}")
            self.assertNotIn("(optional)", line,
                             f"unexpected priority placeholder: {line!r}")

    def test_alias_body_label_is_commands(self):
        e = launcher.profile_io.Entry(
            kind="alias", pattern="k", body="kill", priority=None, _raw=None)
        lines = self._detail_text(e)
        self.assertIn("Commands", lines)
        self.assertNotIn("Body", lines)

    def test_detail_labels_map_matches_kinds(self):
        # Phase 4 / 5 plug the rest in; the data lives in this map.
        self.assertEqual(launcher.DETAIL_LABELS["alias"],
                         ("Pattern", "Commands"))
        self.assertEqual(launcher.DETAIL_LABELS["macro"][0],   "Key")
        self.assertEqual(launcher.DETAIL_LABELS["highlight"][1], "Color")
        self.assertEqual(launcher.DETAIL_LABELS["substitute"],
                         ("Text", "New text"))


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

    def test_brace_unbalanced_pattern_fires_as_error(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_set_pattern("orc {x")
        self.assertEqual(
            launcher._editor_validation_error(),
            "Unbalanced braces in Pattern.")

    def test_brace_balanced_pattern_no_error(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_set_pattern("orc {x}")
        self.assertIsNone(launcher._editor_validation_error())

    def test_brace_escaped_pattern_no_error(self):
        # `\{` and `\}` are literal braces in tt++ — they don't count.
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_set_pattern(r"k\{x")
        self.assertIsNone(launcher._editor_validation_error())

    def test_brace_unbalanced_body_fires_as_error(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        entry = launcher._editor_current_entry()
        entry.body = "kill orc {"
        self.assertEqual(
            launcher._editor_validation_error(),
            "Unbalanced braces in Commands.")

    def test_required_takes_precedence_over_brace(self):
        # Empty pattern + unbalanced body → the required message wins
        # because empty-pattern is the harder block.
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        launcher._editor_create_new_entry()
        launcher._profile_editor_set_focus(2, field=1)
        entry = launcher._editor_current_entry()
        entry.body = "kill {"
        self.assertEqual(launcher._editor_validation_error(),
                         "Pattern is required.")


class TestBraceBalancedHelper(unittest.TestCase):
    """Unit tests for the brace-balance primitive used by the editor's
    inline validation. The helper also handles `\\X` escapes — `\\{`
    and `\\}` do not count toward the depth."""

    def test_empty_string_is_balanced(self):
        self.assertTrue(launcher._braces_balanced(""))

    def test_simple_pair(self):
        self.assertTrue(launcher._braces_balanced("{x}"))

    def test_nested_pairs(self):
        self.assertTrue(launcher._braces_balanced("{a{b}c}"))

    def test_open_only(self):
        self.assertFalse(launcher._braces_balanced("{abc"))

    def test_close_only(self):
        self.assertFalse(launcher._braces_balanced("abc}"))

    def test_close_before_open(self):
        self.assertFalse(launcher._braces_balanced("}abc{"))

    def test_escaped_open_does_not_count(self):
        self.assertTrue(launcher._braces_balanced(r"\{x"))

    def test_escaped_close_does_not_count(self):
        self.assertTrue(launcher._braces_balanced(r"x\}"))

    def test_double_escape_then_brace_counts(self):
        # `\\` is `\` literal; the following `{` is unescaped.
        self.assertFalse(launcher._braces_balanced(r"\\{"))


class TestPriorityPreservedThroughEditor(unittest.TestCase):
    """Priority is no longer surfaced in the editor UI but must continue
    to round-trip on disk. Editing an unrelated field of a priority
    entry regenerates `#alias {pattern} {body} {priority}` from the
    Entry fields; never touching a priority entry leaves its `_raw`
    intact byte-for-byte."""

    def test_unrelated_body_edit_preserves_priority(self):
        source = "#alias {edited} {old}\n#alias {with_prio} {body} {7}\n"
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

    def test_never_touched_priority_entry_round_trips_byte_exact(self):
        source = "#alias {with_prio} {body} {7}\n"
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            _reset_editor_state(prof)
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), source)

    def test_editing_priority_entry_keeps_priority_when_serialised(self):
        # Even when the entry's `_raw` is cleared by a body edit, the
        # canonical serialiser still emits the third brace-arg from
        # Entry.priority.
        source = "#alias {touch} {body} {7}\n"
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            touched = prof.entries_of("alias")[0]
            touched.body = "new body"
            self.assertIsNone(touched._raw)
            self.assertEqual(touched.priority, 7)
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(),
                             "#alias {touch} {new body} {7}\n")


class TestPatternCursorMovement(unittest.TestCase):
    """Phase-3.5 in-buffer cursor — ←/→ move within the Pattern
    buffer, insert/backspace operate at the cursor position."""

    def test_left_right_move_within_buffer(self):
        prof, _src, _td = _make_profile("#alias {kill} {body}\n")
        _reset_editor_state(prof, focus=2)
        # _editor_refresh_buffers lands the cursor at end-of-buffer.
        self.assertEqual(launcher._editor_pattern_cursor, 4)
        launcher._editor_pattern_move_left()
        self.assertEqual(launcher._editor_pattern_cursor, 3)
        launcher._editor_pattern_move_left()
        launcher._editor_pattern_move_left()
        launcher._editor_pattern_move_left()
        self.assertEqual(launcher._editor_pattern_cursor, 0)
        # No fall-through past start of buffer.
        launcher._editor_pattern_move_left()
        self.assertEqual(launcher._editor_pattern_cursor, 0)
        # Right walks back across the buffer.
        launcher._editor_pattern_move_right()
        self.assertEqual(launcher._editor_pattern_cursor, 1)

    def test_insert_at_cursor_in_middle(self):
        prof, _src, _td = _make_profile("#alias {kill} {body}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_pattern_cursor = 2   # between 'i' and 'l'
        launcher._editor_pattern_insert_char("X")
        self.assertEqual(launcher._editor_current_entry().pattern, "kiXll")
        self.assertEqual(launcher._editor_pattern_cursor, 3)

    def test_backspace_at_cursor_in_middle(self):
        prof, _src, _td = _make_profile("#alias {kill} {body}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_pattern_cursor = 3   # between 'l' and 'l'
        launcher._editor_pattern_backspace()
        self.assertEqual(launcher._editor_current_entry().pattern, "kil")
        self.assertEqual(launcher._editor_pattern_cursor, 2)


class TestBodyCursorMovement(unittest.TestCase):
    """Body cursor is a (line, col) pair. ←/→ traverse line boundaries;
    ↑/↓ preserve column as far as the destination line allows."""

    def test_left_at_start_of_line_wraps_to_prev_line_end(self):
        prof, _src, _td = _make_profile("#alias {k} {abc\ndef}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 1
        launcher._editor_body_col  = 0
        launcher._editor_body_move_left()
        self.assertEqual(launcher._editor_body_line, 0)
        self.assertEqual(launcher._editor_body_col,  3)

    def test_right_at_end_of_line_wraps_to_next_line_start(self):
        prof, _src, _td = _make_profile("#alias {k} {abc\ndef}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 0
        launcher._editor_body_col  = 3
        launcher._editor_body_move_right()
        self.assertEqual(launcher._editor_body_line, 1)
        self.assertEqual(launcher._editor_body_col,  0)

    def test_up_returns_false_at_top_edge(self):
        # `_editor_body_move_line` returns False at the buffer edge so
        # the keybind can fall through to focus the Pattern field.
        prof, _src, _td = _make_profile("#alias {k} {only line}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 0
        self.assertFalse(launcher._editor_body_move_line(-1))

    def test_up_in_multi_line_preserves_column(self):
        prof, _src, _td = _make_profile("#alias {k} {abcdef\nghi}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 1
        launcher._editor_body_col  = 3   # end of "ghi"
        self.assertTrue(launcher._editor_body_move_line(-1))
        self.assertEqual(launcher._editor_body_line, 0)
        self.assertEqual(launcher._editor_body_col,  3)   # preserved

    def test_up_clamps_column_to_shorter_line(self):
        prof, _src, _td = _make_profile("#alias {k} {ab\nabcdef}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 1
        launcher._editor_body_col  = 5
        self.assertTrue(launcher._editor_body_move_line(-1))
        self.assertEqual(launcher._editor_body_line, 0)
        self.assertEqual(launcher._editor_body_col,  2)   # clamped to len(ab)

    def test_body_insert_at_cursor_splits_line(self):
        prof, _src, _td = _make_profile("#alias {k} {abc}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 0
        launcher._editor_body_col  = 2   # between 'b' and 'c'
        launcher._editor_body_insert_char("X")
        self.assertEqual(launcher._editor_current_entry().body, "abXc")
        self.assertEqual(launcher._editor_body_col, 3)

    def test_body_backspace_at_start_of_line_joins(self):
        prof, _src, _td = _make_profile("#alias {k} {abc\ndef}\n")
        _reset_editor_state(prof, focus=2)
        launcher._editor_detail_field = 1
        launcher._editor_body_line = 1
        launcher._editor_body_col  = 0
        launcher._editor_body_backspace()
        self.assertEqual(launcher._editor_current_entry().body, "abcdef")
        self.assertEqual(launcher._editor_body_line, 0)
        self.assertEqual(launcher._editor_body_col,  3)


class TestPhase4MultiKind(unittest.TestCase):
    """Phase 4 activates Actions, Substitutes, and Highlights. The
    list and detail panel dispatch on the active kind via
    `DETAIL_LABELS` + `_EDITOR_DETAIL_BUILDERS`."""

    MIXED_PROFILE = (
        "#alias {k} {kill %1}\n"
        "#action {Bubba} {bow} {3}\n"
        "#macro {\\eOp} {flee}\n"
        "#highlight {Orc} {light yellow}\n"
        "#substitute {orc} {ORC}\n"
        "#var {target} {orc}\n"
    )

    def test_round_trip_byte_exact_no_edits(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(self.MIXED_PROFILE)
            prof = profile_io.load_profile(src)
            _reset_editor_state(prof)
            # Walk every tab — the renderer must not mutate items.
            for tab in range(len(launcher._PROFILE_EDITOR_TABS)):
                launcher._profile_editor_set_tab(tab)
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), self.MIXED_PROFILE)

    def test_each_tab_lists_its_kind(self):
        prof, _src, _td = _make_profile(self.MIXED_PROFILE)
        _reset_editor_state(prof)
        expected_kinds = [
            ("Aliases",     "alias"),
            ("Actions",     "action"),
            ("Macros",      "macro"),
            ("Highlights",  "highlight"),
            ("Substitutes", "substitute"),
        ]
        for i, (label, kind) in enumerate(expected_kinds):
            launcher._profile_editor_set_tab(i)
            self.assertEqual(launcher._profile_editor_active_kind(), kind,
                             f"tab {label}")

    def test_list_header_labels_follow_active_kind(self):
        prof, _src, _td = _make_profile(self.MIXED_PROFILE)
        _reset_editor_state(prof)
        # Substitutes header reads "Text" + "New text".
        launcher._profile_editor_set_tab(4)
        frags = launcher._editor_list_header_frag(visible_rows=5)
        joined = "".join(f[1] for f in frags)
        self.assertIn("Text",      joined)
        self.assertIn("New text",  joined)
        # Highlights header reads "Pattern" + "Color".
        launcher._profile_editor_set_tab(3)
        frags = launcher._editor_list_header_frag(visible_rows=5)
        joined = "".join(f[1] for f in frags)
        self.assertIn("Color",     joined)


class TestPhase5MacrosTab(unittest.TestCase):
    """Phase 5 — the Macros tab renders the Key (press-to-bind) cell
    + Commands editor and shows readable key names in the list."""

    def test_detail_panel_shows_key_cell(self):
        prof, _src, _td = _make_profile("#macro {\\eOp} {flee}\n")
        _reset_editor_state(prof, active_tab=2)
        entry = launcher._editor_current_entry()
        rows = launcher._editor_detail_lines(entry, total_lines=18)
        joined = " ".join("".join(f[1] for f in row).strip() for row in rows)
        # No more "phase 5" placeholder.
        self.assertNotIn("phase 5", joined.lower())
        # Key + Commands labels and the readable name appear.
        self.assertIn("Key", joined)
        self.assertIn("Numpad 0", joined)
        self.assertIn("Commands", joined)
        self.assertIn("flee", joined)

    def test_list_row_renders_display_name(self):
        prof, _src, _td = _make_profile("#macro {\\eOp} {flee}\n")
        _reset_editor_state(prof, active_tab=2)
        entry = prof.entries_of("macro")[0]
        frags = launcher._editor_list_row_text(
            entry, is_cursor=False, is_hover=False)
        joined = "".join(f[1] for f in frags)
        self.assertIn("Numpad 0", joined)
        self.assertNotIn("\\eOp", joined)

    def test_list_row_custom_escape(self):
        prof, _src, _td = _make_profile("#macro {abc} {flee}\n")
        _reset_editor_state(prof, active_tab=2)
        entry = prof.entries_of("macro")[0]
        frags = launcher._editor_list_row_text(
            entry, is_cursor=False, is_hover=False)
        joined = "".join(f[1] for f in frags)
        # The 8-char Pattern column truncates "Custom: abc" but the
        # "Custom:" prefix is what tells the user the escape is unknown.
        self.assertIn("Custom:", joined)


class TestPhase5MacroCreate(unittest.TestCase):
    """`+ New entry` appends a blank macro and auto-pushes the
    key-capture overlay; ESC removes the entry, accept commits."""

    def test_create_appends_blank_and_pushes_overlay(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, active_tab=2)
        before = len(prof.entries_of("macro"))
        launcher._editor_create_new_entry()
        self.assertEqual(len(prof.entries_of("macro")), before + 1)
        entry = prof.entries_of("macro")[-1]
        self.assertEqual(entry.pattern, "")
        self.assertEqual(launcher._current_frame, "profile_editor_macro_keybind")
        self.assertTrue(launcher._editor_keybind_just_created)
        # Clean up to avoid leaking the pushed frame state into other tests.
        launcher._editor_keybind_cancel()

    def test_cancel_after_create_drops_entry(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, active_tab=2)
        launcher._editor_create_new_entry()
        self.assertEqual(len(prof.entries_of("macro")), 1)
        launcher._editor_keybind_cancel()
        self.assertEqual(len(prof.entries_of("macro")), 0)
        self.assertFalse(launcher._editor_keybind_just_created)


class TestPhase5MacroSaveDropsEmpty(unittest.TestCase):
    """Phase 3's drop-empty-pattern rule applies uniformly to macros:
    an abandoned create (empty pattern) survives ESC out of the editor
    only if the save path also drops it."""

    def test_abandoned_macro_is_not_serialised(self):
        prof, _src, td = _make_profile("")
        _reset_editor_state(prof, active_tab=2)
        # Simulate an abandoned create by appending an empty-pattern
        # macro directly. (The auto-pushed overlay's ESC handler clears
        # this; we want to verify save_profile's drop rule independently.)
        prof.items.append(profile_io.Entry(
            kind="macro", pattern="", body="", priority=None, _raw=None))
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(dst.read_text(), "")


class TestPhase4PerKindDefaults(unittest.TestCase):
    """`+ New entry` honours per-kind body defaults — new highlights
    start on `light yellow` so the cursor lands on a visible swatch."""

    def test_new_alias_has_empty_body(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, active_tab=0)
        launcher._editor_create_new_entry()
        e = launcher._editor_current_entry()
        self.assertEqual(e.pattern, "")
        self.assertEqual(e.body,    "")

    def test_new_highlight_defaults_to_light_yellow(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, active_tab=3)
        launcher._editor_create_new_entry()
        e = launcher._editor_current_entry()
        self.assertEqual(e.kind, "highlight")
        self.assertEqual(e.body, "light yellow")
        # Palette cursor lands on the matching swatch.
        pos = launcher._editor_palette_position_for_color("light yellow")
        self.assertEqual(
            (launcher._editor_palette_row, launcher._editor_palette_col),
            pos,
        )
        self.assertIsNone(launcher._editor_palette_custom_value)

    def test_new_substitute_has_empty_body(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, active_tab=4)
        launcher._editor_create_new_entry()
        e = launcher._editor_current_entry()
        self.assertEqual(e.kind, "substitute")
        self.assertEqual(e.body, "")


class TestPhase4PaletteWidget(unittest.TestCase):
    """The highlights tab swaps the Body TextArea for a 14-cell color
    palette grid plus an optional Custom slot."""

    def _setup_highlight(self, source):
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof, focus=2, active_tab=3)
        launcher._editor_detail_field = 1
        return prof

    def test_palette_cursor_initialises_to_palette_color(self):
        self._setup_highlight("#highlight {Orc} {light yellow}\n")
        # `light yellow` lives at row=2, col=1.
        self.assertEqual(
            (launcher._editor_palette_row, launcher._editor_palette_col),
            (2, 1),
        )
        self.assertIsNone(launcher._editor_palette_custom_value)

    def test_custom_slot_appears_for_non_palette_body(self):
        prof = self._setup_highlight(
            "#highlight {Snowy} {bold red}\n")
        # Cursor parked on the Custom slot.
        self.assertEqual(launcher._editor_palette_row,
                         launcher._EDITOR_PALETTE_ROWS)
        self.assertEqual(launcher._editor_palette_custom_value, "bold red")
        # Cell renderer surfaces the Custom slot in the detail rows.
        entry = launcher._editor_current_entry()
        rows = launcher._editor_detail_lines(entry, total_lines=20)
        joined = " ".join("".join(f[1] for f in row).strip() for row in rows)
        self.assertIn("Custom: bold red", joined)

    def test_palette_navigation_updates_entry_body_live(self):
        self._setup_highlight("#highlight {Orc} {light yellow}\n")
        entry = launcher._editor_current_entry()
        # Move to row=0 col=0 (white) — body becomes "white".
        launcher._editor_palette_set_cursor(0, 0)
        self.assertEqual(entry.body, "white")
        # And to row=4 col=1 (light cyan).
        launcher._editor_palette_set_cursor(4, 1)
        self.assertEqual(entry.body, "light cyan")

    def test_custom_revert_after_palette_visit(self):
        self._setup_highlight("#highlight {Snowy} {bold red}\n")
        entry = launcher._editor_current_entry()
        # Body starts at "bold red" (Custom). Move to a palette swatch.
        launcher._editor_palette_set_cursor(2, 1)   # light yellow
        self.assertEqual(entry.body, "light yellow")
        self.assertEqual(launcher._editor_palette_custom_value, "bold red")
        # Navigate back to Custom — body restored.
        launcher._editor_palette_set_cursor(
            launcher._EDITOR_PALETTE_ROWS, 0)
        self.assertEqual(entry.body, "bold red")

    def test_palette_move_returns_false_at_top_edge(self):
        # Returns False so the `↑` keybind can fall through to the
        # Pattern field instead of staying in the grid.
        self._setup_highlight("#highlight {Orc} {white}\n")
        # white is row=0 col=0.
        self.assertEqual(
            (launcher._editor_palette_row, launcher._editor_palette_col),
            (0, 0),
        )
        moved = launcher._editor_palette_move(-1, 0)
        self.assertFalse(moved)

    def test_palette_down_into_custom_when_visible(self):
        self._setup_highlight("#highlight {Snowy} {bold red}\n")
        # Stub the cursor onto the last palette row.
        launcher._editor_palette_set_cursor(
            launcher._EDITOR_PALETTE_ROWS - 1, 0)
        moved = launcher._editor_palette_move(1, 0)
        self.assertTrue(moved)
        self.assertEqual(launcher._editor_palette_row,
                         launcher._EDITOR_PALETTE_ROWS)

    def test_palette_down_clamped_when_no_custom(self):
        # No custom slot → ↓ at last grid row returns False.
        self._setup_highlight("#highlight {Orc} {magenta}\n")
        launcher._editor_palette_set_cursor(
            launcher._EDITOR_PALETTE_ROWS - 1, 0)
        moved = launcher._editor_palette_move(1, 0)
        self.assertFalse(moved)


class TestPhase4HighlightListColorColumn(unittest.TestCase):
    """The Highlights list panel renders the `Color` column in the
    swatch's own colour for palette values; custom values render in
    default text style."""

    def test_palette_value_uses_color_style(self):
        prof, _src, _td = _make_profile(
            "#highlight {Orc} {light yellow}\n")
        _reset_editor_state(prof, active_tab=3)
        entry = launcher._editor_current_entry()
        frags = launcher._editor_list_row_text(entry, False, False)
        # Two-fragment form: [(C_ITEM, pat+gap), (color_style, body)].
        self.assertEqual(len(frags), 2)
        body_style, body_text = frags[1]
        self.assertIn("light yellow", body_text)
        self.assertEqual(body_style,
                         launcher.TTPP_COLOR_STYLES["light yellow"])

    def test_custom_value_falls_back_to_plain_style(self):
        prof, _src, _td = _make_profile(
            "#highlight {Snowy} {bold red}\n")
        _reset_editor_state(prof, active_tab=3)
        entry = launcher._editor_current_entry()
        frags = launcher._editor_list_row_text(entry, False, False)
        # Single-fragment fallback uses C_ITEM throughout.
        self.assertEqual(len(frags), 1)
        style, _text = frags[0]
        self.assertEqual(style, launcher.C_ITEM)


class TestPhase4CrossKindEditing(unittest.TestCase):
    """A multi-kind editing session: edit an alias, edit a highlight,
    delete an action — ESC writes exactly those three changes and
    nothing else."""

    def test_three_changes_in_one_save(self):
        source = (
            "#alias {keep} {body}\n"
            "#alias {touch} {old}\n"
            "#action {dropme} {bow}\n"
            "#highlight {Snowy} {bold red}\n"
            "#substitute {orc} {ORC}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            _reset_editor_state(prof)
            # Edit alias "touch" → body = "new"
            touch = next(e for e in prof.entries_of("alias")
                         if e.pattern == "touch")
            touch.body = "new"
            # Edit highlight "Snowy" → palette swatch "light yellow"
            snowy = next(e for e in prof.entries_of("highlight")
                         if e.pattern == "Snowy")
            snowy.body = "light yellow"
            # Delete action "dropme"
            drop = next(e for e in prof.entries_of("action")
                        if e.pattern == "dropme")
            prof.items.remove(drop)
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(
                dst.read_text(),
                "#alias {keep} {body}\n"
                "#alias {touch} {new}\n"
                "#highlight {Snowy} {light yellow}\n"
                "#substitute {orc} {ORC}\n",
            )


if __name__ == "__main__":
    unittest.main()
