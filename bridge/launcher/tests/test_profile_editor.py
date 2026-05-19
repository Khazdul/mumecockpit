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
    launcher._editor_hover_row    = None
    launcher._editor_detail_field    = 0
    launcher._editor_pattern_cursor  = 0
    launcher._editor_body_line       = 0
    launcher._editor_body_col        = 0
    launcher._editor_pattern_touched = False
    launcher._editor_hl_style_cursor = 0
    launcher._editor_hl_text_row     = 0
    launcher._editor_hl_text_col     = 0
    launcher._editor_hl_text_sel     = None
    launcher._editor_hl_bg_row       = 0
    launcher._editor_hl_bg_col       = 0
    launcher._editor_hl_bg_sel       = None
    launcher._editor_hl_hover        = None
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

    def test_parse_sorts_items_alphabetically(self):
        # Phase 6.2: parse_profile sorts items into command groups,
        # alphabetical within each group. The presentation view then
        # mirrors this — no separate sort direction state.
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        items_patterns = [it.pattern for it in prof.items
                          if isinstance(it, profile_io.Entry)]
        self.assertEqual(items_patterns, ["ab", "nw", "ws"])
        view = launcher._profile_editor_display_view()
        self.assertEqual([e.pattern for e in view], ["ab", "nw", "ws"])

    def test_save_emits_sorted_grouped_output(self):
        # Save reflects the sort+group canonical form — Phase 6.2.
        source = (
            "#alias {ws} {wake;stand}\n"
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
        )
        expected = (
            "#alias {ab} {abandon}\n"
            "#alias {nw} {northwest}\n"
            "#alias {ws} {wake;stand}\n"
        )
        prof, _src, td = _make_profile(source)
        _reset_editor_state(prof)
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(dst.read_text(), expected)


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
        # The "ab" line is gone; surviving entries serialise in the
        # Phase 6.2 sorted+grouped form.
        self.assertNotIn("{ab}", written)
        self.assertEqual(
            written,
            "#alias {nw} {northwest}\n"
            "#alias {ws} {wake;stand}\n",
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

    def test_passthrough_lines_survive_delete_in_canonical_order(self):
        # Classifiable Passthrough lines (#var, #event) survive a delete
        # operation; they re-emit in canonical sorted+grouped form (the
        # blank line on input is dropped during the sort pass).
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
            "#alias {ws} {wake;stand}\n"
            "\n"
            "#event {SESSION CONNECTED} {#showme welcome}\n"
            "\n"
            "#var {mytarget} {orc}\n",
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
            # Phase 6.2: alphabetical order is also_keep, keep, touch.
            # `keep` keeps its odd whitespace via _raw; `also_keep`
            # round-trips _raw verbatim; `touch` regenerates canonically.
            self.assertEqual(
                dst.read_text(),
                "#alias {also_keep} {body3} {5}\n"
                "#alias    {keep}    {body1}\n"
                "#alias {touch} {new_body}\n",
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
        # Phase 6.2: #macro lines emerge alphabetised; the #nop header
        # and the blank separator are dropped on the sort pass.
        expected = (
            "#macro {\\eOk} {open exit}\n"
            "#macro {\\eOm} {close exit}\n"
            "#macro {\\eOp} {flee}\n"
            "#macro {\\eOr} {south}\n"
            "#macro {\\eOs} {down}\n"
            "#macro {\\eOt} {west}\n"
            "#macro {\\eOu} {exits}\n"
            "#macro {\\eOv} {east}\n"
            "#macro {\\eOx} {north}\n"
            "#macro {\\eOy} {up}\n"
        )
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

    def test_round_trip_emits_sorted_grouped_no_edits(self):
        # Phase 6.2: parse → sort gives a canonical grouped form.
        # Walking every tab in the editor must not perturb it.
        expected = (
            "#action {Bubba} {bow} {3}\n"
            "\n"
            "#alias {k} {kill %1}\n"
            "\n"
            "#highlight {Orc} {light yellow}\n"
            "\n"
            "#macro {\\eOp} {flee}\n"
            "\n"
            "#substitute {orc} {ORC}\n"
            "\n"
            "#var {target} {orc}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(self.MIXED_PROFILE)
            prof = profile_io.load_profile(src)
            _reset_editor_state(prof)
            for tab in range(len(launcher._PROFILE_EDITOR_TABS)):
                launcher._profile_editor_set_tab(tab)
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), expected)

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
        # New entries default to "light yellow" (per DETAIL_NEW_DEFAULTS).
        self.assertEqual(e.body, "light yellow")
        # Text palette cursor parks on Yellow (row 2, col 1) AND that
        # swatch is the active selection.
        self.assertEqual(launcher._editor_hl_text_row, 2)
        self.assertEqual(launcher._editor_hl_text_col, 1)
        self.assertEqual(launcher._editor_hl_text_sel, (2, 1))
        # No background selection.
        self.assertIsNone(launcher._editor_hl_bg_sel)

    def test_new_substitute_has_empty_body(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, active_tab=4)
        launcher._editor_create_new_entry()
        e = launcher._editor_current_entry()
        self.assertEqual(e.kind, "substitute")
        self.assertEqual(e.body, "")


class TestHighlightPaletteRedesign(unittest.TestCase):
    """Phase 6.2 — Highlights detail panel: 4 inline Style toggles +
    Text grid + BG grid; selection is decoupled from cursor (cursor
    navigates freely, Enter / click on a swatch toggles whether it is
    the selected swatch). The body string is composed of
    `[styles] <text-colour> [b <bg-colour>]`; the parser handles the
    lowercase + capitalised + `light <colour>` conventions."""

    def _setup_highlight(self, source):
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof, focus=2, active_tab=3)
        launcher._editor_detail_field = 2   # Text grid
        return prof

    # --- parsing & serialising ------------------------------------
    def test_parse_simple_color(self):
        styles, tc, bg = launcher._hl_parse_body("red")
        self.assertEqual(styles, set())
        self.assertEqual(tc, "red")
        self.assertIsNone(bg)

    def test_parse_light_form_normalised(self):
        styles, tc, bg = launcher._hl_parse_body("light yellow")
        self.assertEqual(tc, "Yellow")
        self.assertIsNone(bg)

    def test_parse_styles_text_and_bg(self):
        styles, tc, bg = launcher._hl_parse_body(
            "underscore Red b green")
        self.assertEqual(styles, {"underscore"})
        self.assertEqual(tc, "Red")
        self.assertEqual(bg, "green")

    def test_parse_multiple_styles(self):
        styles, tc, bg = launcher._hl_parse_body(
            "reverse blink Yellow")
        self.assertEqual(styles, {"reverse", "blink"})
        self.assertEqual(tc, "Yellow")
        self.assertIsNone(bg)

    def test_parse_rejects_unknown_token(self):
        # `<faa>` is a custom VT100 form — parser punts (no Custom slot
        # in Phase 6.2; the original body simply persists).
        self.assertIsNone(launcher._hl_parse_body("<faa>"))

    def test_parse_accepts_bold_token(self):
        # Phase 6.2: `bold` joined the supported style set (ADR 0084).
        styles, tc, bg = launcher._hl_parse_body("bold red")
        self.assertEqual(styles, {"bold"})
        self.assertEqual(tc, "red")
        self.assertIsNone(bg)

    def test_serialize_round_trip(self):
        body = "underscore Red b green"
        styles, tc, bg = launcher._hl_parse_body(body)
        self.assertEqual(
            launcher._hl_serialize(styles, tc, bg),
            body,
        )

    def test_serialize_omits_b_when_no_bg(self):
        self.assertEqual(
            launcher._hl_serialize({"reverse"}, "Yellow", None),
            "reverse Yellow",
        )

    def test_serialize_only_color(self):
        self.assertEqual(
            launcher._hl_serialize(set(), "red", None),
            "red",
        )

    def test_serialize_bold_emitted_first(self):
        # _HL_STYLE_TOKENS lists bold first, so the serializer's
        # stable-ordered output begins with it when active.
        self.assertEqual(
            launcher._hl_serialize({"bold", "blink"}, "red", None),
            "bold blink red",
        )

    # --- cursor + selection on load -------------------------------
    def test_cursor_and_selection_land_on_text_swatch(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        # red is text row 0 col 0; selection mirrors cursor.
        self.assertEqual(launcher._editor_hl_text_row, 0)
        self.assertEqual(launcher._editor_hl_text_col, 0)
        self.assertEqual(launcher._editor_hl_text_sel, (0, 0))
        # No BG selection — cursor parks at (0, 0).
        self.assertIsNone(launcher._editor_hl_bg_sel)
        self.assertEqual(launcher._editor_hl_bg_row, 0)

    def test_cursor_lands_on_light_variant(self):
        self._setup_highlight("#highlight {Orc} {Yellow}\n")
        self.assertEqual(
            (launcher._editor_hl_text_row, launcher._editor_hl_text_col),
            (2, 1),
        )
        self.assertEqual(launcher._editor_hl_text_sel, (2, 1))

    def test_cursor_for_styles_text_bg(self):
        self._setup_highlight(
            "#highlight {Orc} {underscore Red b green}\n")
        self.assertEqual(
            (launcher._editor_hl_text_row, launcher._editor_hl_text_col),
            (0, 1),
        )
        self.assertEqual(launcher._editor_hl_text_sel, (0, 1))
        self.assertEqual(
            (launcher._editor_hl_bg_row, launcher._editor_hl_bg_col),
            (1, 0),
        )
        self.assertEqual(launcher._editor_hl_bg_sel, (1, 0))

    def test_unparseable_body_leaves_body_untouched(self):
        # No more Custom slot — the body persists verbatim, cursor parks
        # at (0,0) with no swatch selected on either dimension.
        self._setup_highlight("#highlight {Snowy} {<faa>}\n")
        entry = launcher._editor_current_entry()
        self.assertEqual(entry.body, "<faa>")
        self.assertIsNone(launcher._editor_hl_text_sel)
        self.assertIsNone(launcher._editor_hl_bg_sel)
        self.assertEqual(
            (launcher._editor_hl_text_row, launcher._editor_hl_text_col),
            (0, 0))

    # --- selection toggling drives the body -----------------------
    def test_cursor_move_does_not_change_body(self):
        # Phase 6.2: cursor is decoupled from selection — moving the
        # cursor must not rewrite entry.body.
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = launcher._editor_current_entry()
        launcher._editor_hl_set_text_cursor(2, 0)   # yellow under cursor
        self.assertEqual(entry.body, "red")        # but body unchanged
        # The selection is still red.
        self.assertEqual(launcher._editor_hl_text_sel, (0, 0))

    def test_toggle_text_selection_at_cursor_updates_body(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = launcher._editor_current_entry()
        launcher._editor_hl_set_text_cursor(2, 1)        # Yellow
        launcher._editor_hl_toggle_text_selection_at_cursor()
        self.assertEqual(entry.body, "Yellow")
        self.assertEqual(launcher._editor_hl_text_sel, (2, 1))

    def test_toggle_text_selection_off_clears_color(self):
        # When cursor sits on the currently-selected swatch, toggling
        # deselects (no text colour in the body).
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = launcher._editor_current_entry()
        # Cursor parks on the selected swatch on load.
        launcher._editor_hl_toggle_text_selection_at_cursor()
        self.assertIsNone(launcher._editor_hl_text_sel)
        self.assertEqual(entry.body, "")  # no color, no styles

    def test_toggle_bg_selection_adds_b_clause(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = launcher._editor_current_entry()
        launcher._editor_detail_field = 3
        launcher._editor_hl_set_bg_cursor(1, 0)        # green
        launcher._editor_hl_toggle_bg_selection_at_cursor()
        self.assertEqual(entry.body, "red b green")
        # Toggling the same swatch off drops the b-clause.
        launcher._editor_hl_toggle_bg_selection_at_cursor()
        self.assertEqual(entry.body, "red")

    def test_style_toggle_adds_modifier(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = launcher._editor_current_entry()
        launcher._editor_hl_toggle_style("underscore")
        self.assertEqual(entry.body, "underscore red")
        launcher._editor_hl_toggle_style("blink")
        self.assertEqual(entry.body, "underscore blink red")
        launcher._editor_hl_toggle_style("underscore")
        self.assertEqual(entry.body, "blink red")

    def test_editing_text_preserves_styles_and_bg(self):
        self._setup_highlight(
            "#highlight {Orc} {underscore Red b green}\n")
        entry = launcher._editor_current_entry()
        # Move cursor to blue (row 3 col 0) and toggle selection there.
        launcher._editor_hl_set_text_cursor(3, 0)
        launcher._editor_hl_toggle_text_selection_at_cursor()
        self.assertEqual(entry.body, "underscore blue b green")

    def test_editing_bg_preserves_text_and_styles(self):
        self._setup_highlight(
            "#highlight {Orc} {underscore Red b green}\n")
        entry = launcher._editor_current_entry()
        launcher._editor_detail_field = 3
        launcher._editor_hl_set_bg_cursor(4, 1)        # Magenta
        launcher._editor_hl_toggle_bg_selection_at_cursor()
        self.assertEqual(entry.body, "underscore Red b Magenta")


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

    def test_unparseable_value_falls_back_to_plain_style(self):
        # `<faa>` doesn't parse — list cell falls back to plain C_ITEM.
        prof, _src, _td = _make_profile(
            "#highlight {Snowy} {<faa>}\n")
        _reset_editor_state(prof, active_tab=3)
        entry = launcher._editor_current_entry()
        frags = launcher._editor_list_row_text(entry, False, False)
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
            # Phase 6.2: save emits the canonical sorted+grouped form.
            self.assertEqual(
                dst.read_text(),
                "#alias {keep} {body}\n"
                "#alias {touch} {new}\n"
                "\n"
                "#highlight {Snowy} {light yellow}\n"
                "\n"
                "#substitute {orc} {ORC}\n",
            )


class TestEditorModeFlip(unittest.TestCase):
    """Phase 6 — menu/editor mode toggle. The two views are live-bound
    to the same in-memory Profile: menu → editor serialises the items
    into the text buffer; editor → menu parses the buffer back."""

    def _setup_in_menu_mode(self, source=""):
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        launcher._editor_mode           = "menu"
        launcher._editor_toggle_focused = False
        launcher._editor_toggle_hover   = None
        launcher._editor_buffer_text    = ""
        launcher._editor_buffer_cursor  = 0
        launcher._editor_buffer_scroll  = 0
        return prof

    def test_default_mode_is_menu_on_open(self):
        # No call to _enter_profile_editor here — the test harness sets
        # menu mode directly, mirroring the editor-state reset.
        prof = self._setup_in_menu_mode("#alias {k} {kill}\n")
        self.assertEqual(launcher._editor_mode, "menu")
        # Buffer text is empty until the first flip.
        self.assertEqual(launcher._editor_buffer_text, "")

    def test_flip_to_editor_serialises_profile(self):
        source = "#alias {k} {kill %1}\n#var {x} {y}\n"
        # Phase 6.2: parse → sort means the buffer reflects the canonical
        # grouped form, not the source verbatim.
        expected_buffer = "#alias {k} {kill %1}\n\n#var {x} {y}\n"
        prof = self._setup_in_menu_mode(source)
        launcher._editor_flip_mode()
        self.assertEqual(launcher._editor_mode, "editor")
        self.assertEqual(launcher._editor_buffer_text, expected_buffer)
        # Cursor lands at offset 0 on flip.
        self.assertEqual(launcher._editor_buffer_cursor, 0)
        self.assertEqual(launcher._editor_buffer_scroll, 0)

    def test_flip_back_to_menu_parses_buffer(self):
        # User edits the buffer in editor mode; flipping back into menu
        # rebuilds the Profile from the buffer text.
        prof = self._setup_in_menu_mode("#alias {k} {kill}\n")
        launcher._editor_flip_mode()  # → editor
        # Append a fresh entry through the buffer-mutation primitives.
        launcher._editor_buffer_cursor = len(launcher._editor_buffer_text)
        for ch in "#alias {ws} {wake;stand}\n":
            launcher._editor_buffer_insert(ch)
        launcher._editor_flip_mode()  # → menu
        self.assertEqual(launcher._editor_mode, "menu")
        aliases = prof.entries_of("alias")
        self.assertEqual([(e.pattern, e.body) for e in aliases],
                         [("k", "kill"), ("ws", "wake;stand")])

    def test_round_trip_one_of_each_kind_emits_sorted(self):
        # Phase 6.2: parse → sort + group is the canonical form. A
        # profile with one entry of each kind plus a #var (blank line
        # in input is dropped on sort) round-trips through the canonical
        # form when flipped to editor and back.
        source = (
            "#alias {k} {kill %1}\n"
            "#action {Bubba} {bow}\n"
            "#macro {\\eOp} {flee}\n"
            "#highlight {Orc} {red}\n"
            "#substitute {orc} {ORC}\n"
            "#var {target} {orc}\n"
            "\n"
        )
        expected = (
            "#action {Bubba} {bow}\n"
            "\n"
            "#alias {k} {kill %1}\n"
            "\n"
            "#highlight {Orc} {red}\n"
            "\n"
            "#macro {\\eOp} {flee}\n"
            "\n"
            "#substitute {orc} {ORC}\n"
            "\n"
            "#var {target} {orc}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.tin"
            dst = Path(td) / "out.tin"
            src.write_text(source)
            prof = profile_io.load_profile(src)
            _reset_editor_state(prof)
            launcher._editor_mode = "menu"
            launcher._editor_buffer_text = ""
            launcher._editor_buffer_cursor = 0
            launcher._editor_buffer_scroll = 0
            launcher._editor_toggle_focused = False
            launcher._editor_toggle_hover = None
            launcher._editor_flip_mode()
            self.assertEqual(launcher._editor_buffer_text, expected)
            launcher._editor_flip_mode()
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), expected)

    def test_edits_survive_flip_round_trip(self):
        # Edit in menu mode → flip to editor → flip back to menu — the
        # menu-mode edit must persist (parser preserves it as the same
        # canonical Entry).
        prof = self._setup_in_menu_mode("#alias {k} {kill}\n")
        # Edit through the menu-mode helper.
        alias_k = prof.entries_of("alias")[0]
        alias_k.body = "kill orc"
        # Flip to editor and back.
        launcher._editor_flip_mode()
        self.assertIn("kill orc", launcher._editor_buffer_text)
        launcher._editor_flip_mode()
        self.assertEqual(prof.entries_of("alias")[0].body, "kill orc")


class TestEditorModeBufferCursor(unittest.TestCase):
    """Editor-mode buffer cursor model. Cursor is an absolute offset
    into `_editor_buffer_text`; helpers convert to `(line, col)` and
    the line-starts table backs visual layout / scroll-into-view."""

    def _setup_buffer(self, text):
        # Drop into editor mode with `text` as the buffer content.
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        launcher._editor_mode           = "editor"
        launcher._editor_toggle_focused = False
        launcher._editor_buffer_text    = text
        launcher._editor_buffer_cursor  = 0
        launcher._editor_buffer_scroll  = 0

    def test_cursor_to_line_col_first_line(self):
        self._setup_buffer("hello\nworld\n")
        launcher._editor_buffer_cursor = 3
        self.assertEqual(launcher._editor_buffer_cursor_to_line_col(),
                         (0, 3))

    def test_cursor_to_line_col_second_line(self):
        self._setup_buffer("hello\nworld\n")
        launcher._editor_buffer_cursor = 8   # 6 (start of "world") + 2
        self.assertEqual(launcher._editor_buffer_cursor_to_line_col(),
                         (1, 2))

    def test_insert_at_cursor_advances_offset(self):
        self._setup_buffer("ab")
        launcher._editor_buffer_cursor = 1
        launcher._editor_buffer_insert("X")
        self.assertEqual(launcher._editor_buffer_text, "aXb")
        self.assertEqual(launcher._editor_buffer_cursor, 2)

    def test_backspace_at_offset(self):
        self._setup_buffer("abc")
        launcher._editor_buffer_cursor = 2
        launcher._editor_buffer_backspace()
        self.assertEqual(launcher._editor_buffer_text, "ac")
        self.assertEqual(launcher._editor_buffer_cursor, 1)

    def test_backspace_at_start_is_noop(self):
        self._setup_buffer("abc")
        launcher._editor_buffer_cursor = 0
        launcher._editor_buffer_backspace()
        self.assertEqual(launcher._editor_buffer_text, "abc")

    def test_delete_at_offset(self):
        self._setup_buffer("abc")
        launcher._editor_buffer_cursor = 1
        launcher._editor_buffer_delete()
        self.assertEqual(launcher._editor_buffer_text, "ac")
        # Cursor stays put — delete consumes the character to the right.
        self.assertEqual(launcher._editor_buffer_cursor, 1)

    def test_delete_at_end_is_noop(self):
        self._setup_buffer("abc")
        launcher._editor_buffer_cursor = 3
        launcher._editor_buffer_delete()
        self.assertEqual(launcher._editor_buffer_text, "abc")

    def test_set_cursor_from_line_col_clamps_to_line_length(self):
        self._setup_buffer("ab\nlonger line\n")
        launcher._editor_buffer_set_cursor_from_line_col(0, 99)
        # Line 0 is "ab" (length 2) — col clamps to 2.
        self.assertEqual(launcher._editor_buffer_cursor, 2)

    def test_line_count_handles_trailing_newline(self):
        # Vim-style line count: a trailing \n creates an empty phantom
        # line so the cursor at end-of-buffer has a real (line, col)
        # mapping.
        self._setup_buffer("a\nb\n")
        self.assertEqual(launcher._editor_buffer_line_count(), 3)

    def test_line_count_no_trailing_newline(self):
        self._setup_buffer("a\nb")
        self.assertEqual(launcher._editor_buffer_line_count(), 2)


class TestEditorModeToggle(unittest.TestCase):
    """Toggle-row focus + activation. Enter/Space flips mode, click on
    the inactive block flips mode, click on the active block is a
    no-op."""

    def _setup(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof)
        launcher._editor_mode           = "menu"
        launcher._editor_toggle_focused = False
        launcher._editor_toggle_hover   = None
        launcher._editor_buffer_text    = ""
        launcher._editor_buffer_cursor  = 0
        launcher._editor_buffer_scroll  = 0
        return prof

    def test_focus_toggle_sets_flag(self):
        self._setup()
        launcher._editor_focus_toggle()
        self.assertTrue(launcher._editor_toggle_focused)

    def test_setting_menu_focus_clears_toggle_focus(self):
        self._setup()
        launcher._editor_focus_toggle()
        launcher._profile_editor_set_focus(1)
        self.assertFalse(launcher._editor_toggle_focused)

    def test_flip_mode_menu_to_editor_serialises(self):
        prof = self._setup()
        launcher._editor_flip_mode()
        self.assertEqual(launcher._editor_mode, "editor")
        self.assertEqual(launcher._editor_buffer_text,
                         "#alias {k} {kill}\n")

    def test_button_style_inactive_when_other_mode(self):
        self._setup()
        # mode = menu — the EDITOR button is inactive.
        self.assertEqual(
            launcher._editor_toggle_button_style("editor"),
            launcher.C_BUTTON_INACTIVE,
        )

    def test_button_style_active_focused_amber(self):
        self._setup()
        launcher._editor_focus_toggle()
        # mode = menu, toggle focused → MENU is active-focused.
        self.assertEqual(
            launcher._editor_toggle_button_style("menu"),
            launcher.C_BUTTON_ACTIVE_FOCUSED,
        )

    def test_button_style_active_unfocused_grey(self):
        self._setup()
        # mode = menu, toggle NOT focused → MENU is active-unfocused.
        self.assertEqual(
            launcher._editor_toggle_button_style("menu"),
            launcher.C_BUTTON_ACTIVE_UNFOCUSED,
        )

    def test_button_hover_on_inactive_previews_unfocused(self):
        self._setup()
        # mode = menu — hover on EDITOR previews active-unfocused.
        launcher._editor_toggle_hover = "editor"
        self.assertEqual(
            launcher._editor_toggle_button_style("editor"),
            launcher.C_BUTTON_ACTIVE_UNFOCUSED,
        )


if __name__ == "__main__":
    unittest.main()
