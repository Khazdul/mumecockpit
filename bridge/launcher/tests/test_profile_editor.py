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
import profile_editor  # noqa: E402
import profile_io      # noqa: E402


class _TestHost:
    """Minimal EditorHost for unit tests (no running Application).

    Tracks overlay state so tests can assert push_overlay_frame was called.
    """

    def __init__(self):
        self._overlay_active = False

    @property
    def app(self):
        return None

    @property
    def app_loop(self):
        return None

    @property
    def terminal_bg(self):
        return "#000000"

    def term_cols(self):
        return launcher.shutil.get_terminal_size().columns

    def term_rows(self):
        return launcher.shutil.get_terminal_size().lines

    def push_overlay_frame(self):
        self._overlay_active = True

    def pop_overlay_frame(self):
        self._overlay_active = False

    def focus_current_frame(self):
        pass

    def is_active(self):
        return True

    def is_overlay_active(self):
        return self._overlay_active


_test_host = _TestHost()

# Module-level editor instance — set by _reset_editor_state.
_ed = None

# Module-level clock override — when non-None, _reset_editor_state applies it
# to the new editor's _editor_click_now so tests with fake clocks work.
_test_click_clock = None


def _make_profile(source):
    """Write `source` to a temp .tin, load it, and return (profile, dst).

    `dst` lives in the same temp directory; `save_profile` writes there
    when the test mutates the profile and wants to check the file."""
    td = tempfile.mkdtemp()
    src = Path(td) / "in.tin"
    src.write_text(source)
    prof = profile_io.load_profile(src)
    return prof, src, td


def _tab_index(kind):
    """Resolve a kind string to its tab index in the current
    `_PROFILE_EDITOR_TABS`. Decouples tests from tab order — Phase 6.3
    re-sorted the buttons alphabetically."""
    for i, (_label, k) in enumerate(profile_editor._PROFILE_EDITOR_TABS):
        if k == kind:
            return i
    raise KeyError(kind)


def _reset_editor_state(profile, *, focus=1, active_tab=None, kind="alias"):
    """Create a fresh ProfileEditor for `profile` and store it in `_ed`.

    `focus` defaults to 1 (list); pass `focus=2` to drive the detail-
    panel editing paths. `kind` (default "alias") selects which tab is
    active and is resolved to the current tab index. `active_tab` (an
    integer) overrides `kind` when provided — kept for the few tests
    that need to walk every tab by index."""
    global _ed
    if active_tab is None:
        active_tab = _tab_index(kind)
    _test_host._overlay_active = False  # reset overlay state for each editor
    _ed = profile_editor.ProfileEditor(
        path=profile.path,
        profile=profile,
        on_exit=lambda p: None,
        host=_test_host,
    )
    # Override the defaults set by __init__ to match the test's request.
    _ed._editor_active_tab = active_tab
    _ed._editor_focus      = focus
    # Apply fake clock if one is active (tests using _reset_click_state).
    if _test_click_clock is not None:
        _ed._editor_click_now = _test_click_clock
    _ed._editor_refresh_buffers()


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
        view = _ed._profile_editor_display_view()
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
        view = _ed._profile_editor_display_view()
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
        view = _ed._profile_editor_display_view()
        target = view[0]
        self.assertEqual(target.pattern, "ab")
        _ed._editor_list_cursor = 0
        _ed._profile_editor_request_delete()
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
        _ed._editor_list_cursor = 0
        _ed._profile_editor_request_delete()
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
        _ed._editor_list_cursor = len(_ed._profile_editor_display_view())
        _ed._profile_editor_request_delete()
        self.assertEqual(_ed._profile_editor_active_count(), 1)

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
        _ed._editor_list_cursor = 0
        _ed._profile_editor_request_delete()
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
        _ed._editor_list_cursor = 2
        _ed._profile_editor_request_delete()
        # Two entries remain; cursor should clamp to 1 (the new last).
        self.assertEqual(_ed._profile_editor_active_count(), 2)
        self.assertEqual(_ed._editor_list_cursor, 1)

    def test_cursor_resets_to_zero_when_list_empties(self):
        source = "#alias {only} {body}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        _ed._editor_list_cursor = 0
        _ed._profile_editor_request_delete()
        self.assertEqual(_ed._profile_editor_active_count(), 0)
        self.assertEqual(_ed._editor_list_cursor, 0)

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
        _ed._editor_list_cursor = 0
        _ed._profile_editor_request_delete()
        self.assertEqual(_ed._profile_editor_active_count(), 2)
        self.assertEqual(_ed._editor_list_cursor, 0)
        new_view = _ed._profile_editor_display_view()
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
        rows = _ed._editor_detail_lines(entry, total_lines=20)
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
        self.assertEqual(profile_editor.DETAIL_LABELS["alias"],
                         ("Pattern", "Commands"))
        self.assertEqual(profile_editor.DETAIL_LABELS["macro"][0],   "Key")
        self.assertEqual(profile_editor.DETAIL_LABELS["highlight"][1], "Color")
        self.assertEqual(profile_editor.DETAIL_LABELS["substitute"],
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
        _ed._editor_list_cursor = 0
        _ed._editor_refresh_buffers()
        self.assertEqual(_ed._editor_current_entry().pattern, "ab")
        # Rename ab → zz (last in asc order).
        _ed._editor_set_pattern("zz")
        # The cursor follows the entry: it should now point to zz at the
        # end of the asc-sorted view.
        view = _ed._profile_editor_display_view()
        self.assertEqual([e.pattern for e in view], ["nw", "ws", "zz"])
        self.assertEqual(view[_ed._editor_list_cursor].pattern, "zz")

    def test_pattern_mutation_clears_raw_via_setattr(self):
        source = "#alias {ab} {body}\n"
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof, focus=2)
        entry = _ed._editor_current_entry()
        self.assertIsNotNone(entry._raw)
        _ed._editor_set_pattern("abc")
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
        self.assertEqual(_ed._profile_editor_active_count(), 2)
        self.assertEqual(_ed._profile_editor_display_total(), 3)

    def test_create_appends_blank_entry_and_focuses_pattern(self):
        prof, _src, _td = _make_profile("#alias {keep} {body}\n")
        _reset_editor_state(prof)
        _ed._editor_create_new_entry()
        # Items grew by one — a blank Entry of the active kind.
        aliases = prof.entries_of("alias")
        self.assertEqual(len(aliases), 2)
        new_entry = next(e for e in aliases if e.pattern == "")
        self.assertEqual(new_entry.kind, "alias")
        self.assertEqual(new_entry.body, "")
        self.assertIsNone(new_entry.priority)
        # Cursor parked on the new entry and detail.Pattern focused.
        view = _ed._profile_editor_display_view()
        self.assertEqual(view[_ed._editor_list_cursor], new_entry)
        self.assertEqual(_ed._editor_focus, 2)
        self.assertEqual(_ed._editor_detail_field, 0)

    def test_abandoned_create_is_dropped_on_save(self):
        prof, _src, td = _make_profile("#alias {keep} {body}\n")
        _reset_editor_state(prof)
        _ed._editor_create_new_entry()
        # User pressed ESC without typing — the new entry stays blank.
        dst = Path(td) / "out.tin"
        prof.path = dst
        profile_io.save_profile(prof)
        self.assertEqual(dst.read_text(), "#alias {keep} {body}\n")


class TestEmptyStateHintWrap(unittest.TestCase):
    """When the active kind has zero entries (or the cursor sits on the
    `+ New entry` sentinel), the detail panel shows a centred hint
    wrapped to `_EDITOR_DETAIL_W` so no line spills outside the panel."""

    def _empty_state_lines(self, kind):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, kind=kind)
        # No entries → cursor is on the sentinel and entry is None.
        self.assertIsNone(_ed._editor_current_entry())
        rows = _ed._editor_detail_lines(None, total_lines=20)
        return ["".join(f[1] for f in row) for row in rows]

    def test_substitute_empty_hint_wraps_within_panel(self):
        lines = self._empty_state_lines("substitute")
        w = profile_editor._EDITOR_DETAIL_W
        for line in lines:
            self.assertEqual(len(line), w,
                             f"row width {len(line)} != {w}: {line!r}")
        non_blank = [ln.strip() for ln in lines if ln.strip()]
        joined = " ".join(non_blank)
        self.assertIn("No substitutes yet. Press n to add one.", joined)
        self.assertGreater(len(non_blank), 1,
                           "expected the long hint to wrap to >1 line")

    def test_highlight_empty_hint_wraps_within_panel(self):
        lines = self._empty_state_lines("highlight")
        w = profile_editor._EDITOR_DETAIL_W
        for line in lines:
            self.assertEqual(len(line), w)
        joined = " ".join(ln.strip() for ln in lines if ln.strip())
        self.assertIn("No highlights yet. Press n to add one.", joined)

    def test_sentinel_prompt_wraps_within_panel(self):
        # One existing entry → sentinel sits at index 1; park cursor on it.
        prof, _src, _td = _make_profile("#substitute {x} {y}\n")
        _reset_editor_state(prof, kind="substitute")
        view = _ed._profile_editor_display_view()
        _ed._editor_list_cursor = len(view)  # sentinel row
        self.assertIsNone(_ed._editor_current_entry())
        rows = _ed._editor_detail_lines(None, total_lines=20)
        lines = ["".join(f[1] for f in row) for row in rows]
        w = profile_editor._EDITOR_DETAIL_W
        for line in lines:
            self.assertEqual(len(line), w)
        non_blank = [ln.strip() for ln in lines if ln.strip()]
        joined = " ".join(non_blank)
        self.assertIn("Press Enter to create a new substitute.", joined)
        self.assertGreater(len(non_blank), 1,
                           "expected the sentinel prompt to wrap to >1 line")

    def test_hint_block_is_vertically_centred(self):
        # With wrapped lines L and total T, top blank rows == (T - L) // 2.
        lines = self._empty_state_lines("substitute")
        leading_blank = 0
        for ln in lines:
            if ln.strip():
                break
            leading_blank += 1
        non_blank = [ln for ln in lines if ln.strip()]
        expected_top = max(0, (20 - len(non_blank)) // 2)
        self.assertEqual(leading_blank, expected_top)


class TestValidation(unittest.TestCase):
    """Pattern-required error is armed once the user leaves the field
    with an empty buffer; brace warning fires live as soon as the
    pattern contains an unescaped `{` or `}`."""

    def test_pattern_required_not_armed_on_first_focus(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_create_new_entry()
        # Fresh blank entry — no error yet because the user hasn't left
        # the Pattern field.
        self.assertIsNone(_ed._editor_validation_error())

    def test_pattern_required_appears_after_leaving_field(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_create_new_entry()
        # Tab away to Body — the touched flag arms.
        _ed._profile_editor_set_focus(2, field=1)
        self.assertEqual(_ed._editor_validation_error(),
                         "Pattern is required.")

    def test_pattern_required_clears_when_pattern_nonempty(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_create_new_entry()
        _ed._profile_editor_set_focus(2, field=1)
        self.assertIsNotNone(_ed._editor_validation_error())
        # Type a character into Pattern.
        _ed._profile_editor_set_focus(2, field=0)
        _ed._editor_set_pattern("k")
        self.assertIsNone(_ed._editor_validation_error())

    def test_brace_unbalanced_pattern_fires_as_error(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_set_pattern("orc {x")
        self.assertEqual(
            _ed._editor_validation_error(),
            "Unbalanced braces in Pattern.")

    def test_brace_balanced_pattern_no_error(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_set_pattern("orc {x}")
        self.assertIsNone(_ed._editor_validation_error())

    def test_brace_escaped_pattern_no_error(self):
        # `\{` and `\}` are literal braces in tt++ — they don't count.
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_set_pattern(r"k\{x")
        self.assertIsNone(_ed._editor_validation_error())

    def test_brace_unbalanced_body_fires_as_error(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof, focus=2)
        entry = _ed._editor_current_entry()
        entry.body = "kill orc {"
        self.assertEqual(
            _ed._editor_validation_error(),
            "Unbalanced braces in Commands.")

    def test_required_takes_precedence_over_brace(self):
        # Empty pattern + unbalanced body → the required message wins
        # because empty-pattern is the harder block.
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_create_new_entry()
        _ed._profile_editor_set_focus(2, field=1)
        entry = _ed._editor_current_entry()
        entry.body = "kill {"
        self.assertEqual(_ed._editor_validation_error(),
                         "Pattern is required.")


class TestBraceBalancedHelper(unittest.TestCase):
    """Unit tests for the brace-balance primitive used by the editor's
    inline validation. The helper also handles `\\X` escapes — `\\{`
    and `\\}` do not count toward the depth."""

    def test_empty_string_is_balanced(self):
        self.assertTrue(profile_editor._braces_balanced(""))

    def test_simple_pair(self):
        self.assertTrue(profile_editor._braces_balanced("{x}"))

    def test_nested_pairs(self):
        self.assertTrue(profile_editor._braces_balanced("{a{b}c}"))

    def test_open_only(self):
        self.assertFalse(profile_editor._braces_balanced("{abc"))

    def test_close_only(self):
        self.assertFalse(profile_editor._braces_balanced("abc}"))

    def test_close_before_open(self):
        self.assertFalse(profile_editor._braces_balanced("}abc{"))

    def test_escaped_open_does_not_count(self):
        self.assertTrue(profile_editor._braces_balanced(r"\{x"))

    def test_escaped_close_does_not_count(self):
        self.assertTrue(profile_editor._braces_balanced(r"x\}"))

    def test_double_escape_then_brace_counts(self):
        # `\\` is `\` literal; the following `{` is unescaped.
        self.assertFalse(profile_editor._braces_balanced(r"\\{"))


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
        self.assertEqual(_ed._editor_pattern_cursor, 4)
        _ed._editor_pattern_move_left()
        self.assertEqual(_ed._editor_pattern_cursor, 3)
        _ed._editor_pattern_move_left()
        _ed._editor_pattern_move_left()
        _ed._editor_pattern_move_left()
        self.assertEqual(_ed._editor_pattern_cursor, 0)
        # No fall-through past start of buffer.
        _ed._editor_pattern_move_left()
        self.assertEqual(_ed._editor_pattern_cursor, 0)
        # Right walks back across the buffer.
        _ed._editor_pattern_move_right()
        self.assertEqual(_ed._editor_pattern_cursor, 1)

    def test_insert_at_cursor_in_middle(self):
        prof, _src, _td = _make_profile("#alias {kill} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_pattern_cursor = 2   # between 'i' and 'l'
        _ed._editor_pattern_insert_char("X")
        self.assertEqual(_ed._editor_current_entry().pattern, "kiXll")
        self.assertEqual(_ed._editor_pattern_cursor, 3)

    def test_backspace_at_cursor_in_middle(self):
        prof, _src, _td = _make_profile("#alias {kill} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_pattern_cursor = 3   # between 'l' and 'l'
        _ed._editor_pattern_backspace()
        self.assertEqual(_ed._editor_current_entry().pattern, "kil")
        self.assertEqual(_ed._editor_pattern_cursor, 2)


class TestBodyCursorMovement(unittest.TestCase):
    """Body cursor is a (line, col) pair. ←/→ traverse line boundaries;
    ↑/↓ preserve column as far as the destination line allows."""

    def test_left_at_start_of_line_wraps_to_prev_line_end(self):
        prof, _src, _td = _make_profile("#alias {k} {abc\ndef}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 1
        _ed._editor_body_col  = 0
        _ed._editor_body_move_left()
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col,  3)

    def test_right_at_end_of_line_wraps_to_next_line_start(self):
        prof, _src, _td = _make_profile("#alias {k} {abc\ndef}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 0
        _ed._editor_body_col  = 3
        _ed._editor_body_move_right()
        self.assertEqual(_ed._editor_body_line, 1)
        self.assertEqual(_ed._editor_body_col,  0)

    def test_up_returns_false_at_top_edge(self):
        # `_editor_body_move_line` returns False at the buffer edge so
        # the keybind can fall through to focus the Pattern field.
        prof, _src, _td = _make_profile("#alias {k} {only line}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 0
        self.assertFalse(_ed._editor_body_move_line(-1))

    def test_up_in_multi_line_preserves_column(self):
        prof, _src, _td = _make_profile("#alias {k} {abcdef\nghi}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 1
        _ed._editor_body_col  = 3   # end of "ghi"
        self.assertTrue(_ed._editor_body_move_line(-1))
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col,  3)   # preserved

    def test_up_clamps_column_to_shorter_line(self):
        prof, _src, _td = _make_profile("#alias {k} {ab\nabcdef}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 1
        _ed._editor_body_col  = 5
        self.assertTrue(_ed._editor_body_move_line(-1))
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col,  2)   # clamped to len(ab)

    def test_body_insert_at_cursor_splits_line(self):
        prof, _src, _td = _make_profile("#alias {k} {abc}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 0
        _ed._editor_body_col  = 2   # between 'b' and 'c'
        _ed._editor_body_insert_char("X")
        self.assertEqual(_ed._editor_current_entry().body, "abXc")
        self.assertEqual(_ed._editor_body_col, 3)

    def test_body_backspace_at_start_of_line_joins(self):
        prof, _src, _td = _make_profile("#alias {k} {abc\ndef}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_line = 1
        _ed._editor_body_col  = 0
        _ed._editor_body_backspace()
        self.assertEqual(_ed._editor_current_entry().body, "abcdef")
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col,  3)


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
            for tab in range(len(profile_editor._PROFILE_EDITOR_TABS)):
                _ed._profile_editor_set_tab(tab)
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), expected)

    def test_each_tab_lists_its_kind(self):
        # Phase 6.3: tabs are sorted alphabetically by label —
        # ACTIONS, ALIASES, HIGHLIGHTS, MACROS, SUBSTITUTES.
        prof, _src, _td = _make_profile(self.MIXED_PROFILE)
        _reset_editor_state(prof)
        expected_kinds = [
            ("Actions",     "action"),
            ("Aliases",     "alias"),
            ("Highlights",  "highlight"),
            ("Macros",      "macro"),
            ("Substitutes", "substitute"),
        ]
        for i, (label, kind) in enumerate(expected_kinds):
            _ed._profile_editor_set_tab(i)
            self.assertEqual(_ed._profile_editor_active_kind(), kind,
                             f"tab {label}")

    def test_list_header_labels_follow_active_kind(self):
        prof, _src, _td = _make_profile(self.MIXED_PROFILE)
        _reset_editor_state(prof)
        # Substitutes header reads "Text" + "New text".
        _ed._profile_editor_set_tab(_tab_index("substitute"))
        frags = _ed._editor_list_header_frag(visible_rows=5)
        joined = "".join(f[1] for f in frags)
        self.assertIn("Text",      joined)
        self.assertIn("New text",  joined)
        # Highlights header reads "Pattern" + "Color".
        _ed._profile_editor_set_tab(_tab_index("highlight"))
        frags = _ed._editor_list_header_frag(visible_rows=5)
        joined = "".join(f[1] for f in frags)
        self.assertIn("Color",     joined)


class TestPhase5MacrosTab(unittest.TestCase):
    """Phase 5 — the Macros tab renders the Key (press-to-bind) cell
    + Commands editor and shows readable key names in the list."""

    def test_detail_panel_shows_key_cell(self):
        prof, _src, _td = _make_profile("#macro {\\eOp} {flee}\n")
        _reset_editor_state(prof, kind="macro")
        entry = _ed._editor_current_entry()
        rows = _ed._editor_detail_lines(entry, total_lines=18)
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
        _reset_editor_state(prof, kind="macro")
        entry = prof.entries_of("macro")[0]
        frags = _ed._editor_list_row_text(
            entry, is_cursor=False, is_hover=False)
        joined = "".join(f[1] for f in frags)
        self.assertIn("Numpad 0", joined)
        self.assertNotIn("\\eOp", joined)

    def test_list_row_custom_escape(self):
        prof, _src, _td = _make_profile("#macro {abc} {flee}\n")
        _reset_editor_state(prof, kind="macro")
        entry = prof.entries_of("macro")[0]
        frags = _ed._editor_list_row_text(
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
        _reset_editor_state(prof, kind="macro")
        before = len(prof.entries_of("macro"))
        _ed._editor_create_new_entry()
        self.assertEqual(len(prof.entries_of("macro")), before + 1)
        entry = prof.entries_of("macro")[-1]
        self.assertEqual(entry.pattern, "")
        self.assertTrue(_test_host._overlay_active,
                        "push_overlay_frame() should have been called")
        self.assertTrue(_ed._editor_keybind_just_created)
        # Clean up to avoid leaking the pushed frame state into other tests.
        _ed._editor_keybind_cancel()

    def test_cancel_after_create_drops_entry(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, kind="macro")
        _ed._editor_create_new_entry()
        self.assertEqual(len(prof.entries_of("macro")), 1)
        _ed._editor_keybind_cancel()
        self.assertEqual(len(prof.entries_of("macro")), 0)
        self.assertFalse(_ed._editor_keybind_just_created)


class TestPhase5MacroSaveDropsEmpty(unittest.TestCase):
    """Phase 3's drop-empty-pattern rule applies uniformly to macros:
    an abandoned create (empty pattern) survives ESC out of the editor
    only if the save path also drops it."""

    def test_abandoned_macro_is_not_serialised(self):
        prof, _src, td = _make_profile("")
        _reset_editor_state(prof, kind="macro")
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
        _reset_editor_state(prof, kind="alias")
        _ed._editor_create_new_entry()
        e = _ed._editor_current_entry()
        self.assertEqual(e.pattern, "")
        self.assertEqual(e.body,    "")

    def test_new_highlight_defaults_to_light_yellow(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, kind="highlight")
        _ed._editor_create_new_entry()
        e = _ed._editor_current_entry()
        self.assertEqual(e.kind, "highlight")
        # New entries default to "light yellow" (per DETAIL_NEW_DEFAULTS).
        self.assertEqual(e.body, "light yellow")
        # Text palette cursor parks on Yellow (row 2, col 1) AND that
        # swatch is the active selection.
        self.assertEqual(_ed._editor_hl_text_row, 2)
        self.assertEqual(_ed._editor_hl_text_col, 1)
        self.assertEqual(_ed._editor_hl_text_sel, (2, 1))
        # No background selection.
        self.assertIsNone(_ed._editor_hl_bg_sel)

    def test_new_substitute_has_empty_body(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof, kind="substitute")
        _ed._editor_create_new_entry()
        e = _ed._editor_current_entry()
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
        _reset_editor_state(prof, focus=2, kind="highlight")
        _ed._editor_detail_field = 2   # Text grid
        return prof

    # --- parsing & serialising ------------------------------------
    def test_parse_simple_color(self):
        styles, tc, bg = profile_editor._hl_parse_body("red")
        self.assertEqual(styles, set())
        self.assertEqual(tc, "red")
        self.assertIsNone(bg)

    def test_parse_light_form_normalised(self):
        styles, tc, bg = profile_editor._hl_parse_body("light yellow")
        self.assertEqual(tc, "Yellow")
        self.assertIsNone(bg)

    def test_parse_styles_text_and_bg(self):
        styles, tc, bg = profile_editor._hl_parse_body(
            "underscore Red b green")
        self.assertEqual(styles, {"underscore"})
        self.assertEqual(tc, "Red")
        self.assertEqual(bg, "green")

    def test_parse_multiple_styles(self):
        styles, tc, bg = profile_editor._hl_parse_body(
            "reverse blink Yellow")
        self.assertEqual(styles, {"reverse", "blink"})
        self.assertEqual(tc, "Yellow")
        self.assertIsNone(bg)

    def test_parse_rejects_unknown_token(self):
        # `<faa>` is a custom VT100 form — parser punts (no Custom slot
        # in Phase 6.2; the original body simply persists).
        self.assertIsNone(profile_editor._hl_parse_body("<faa>"))

    def test_parse_rejects_bold_token(self):
        # Phase 6.3: `bold` was dropped from the supported style set —
        # tt++ doesn't list it as a `#highlight` modifier. A persisted
        # body containing `bold` falls through as unrecognised so the
        # original `_raw` survives on save rather than dropping data.
        self.assertIsNone(profile_editor._hl_parse_body("bold red"))

    def test_serialize_round_trip(self):
        body = "underscore Red b green"
        styles, tc, bg = profile_editor._hl_parse_body(body)
        self.assertEqual(
            profile_editor._hl_serialize(styles, tc, bg),
            body,
        )

    def test_serialize_omits_b_when_no_bg(self):
        self.assertEqual(
            profile_editor._hl_serialize({"reverse"}, "Yellow", None),
            "reverse Yellow",
        )

    def test_serialize_only_color(self):
        self.assertEqual(
            profile_editor._hl_serialize(set(), "red", None),
            "red",
        )

    def test_serialize_skips_dropped_bold(self):
        # Phase 6.3: `bold` is no longer in `_HL_STYLE_TOKENS`, so the
        # serializer ignores it even if it sneaks into the styles set.
        # The remaining stable order is underscore < blink < reverse.
        self.assertEqual(
            profile_editor._hl_serialize({"bold", "blink"}, "red", None),
            "blink red",
        )

    # --- cursor + selection on load -------------------------------
    def test_cursor_and_selection_land_on_text_swatch(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        # red is text row 0 col 0; selection mirrors cursor.
        self.assertEqual(_ed._editor_hl_text_row, 0)
        self.assertEqual(_ed._editor_hl_text_col, 0)
        self.assertEqual(_ed._editor_hl_text_sel, (0, 0))
        # No BG selection — cursor parks at (0, 0).
        self.assertIsNone(_ed._editor_hl_bg_sel)
        self.assertEqual(_ed._editor_hl_bg_row, 0)

    def test_cursor_lands_on_light_variant(self):
        self._setup_highlight("#highlight {Orc} {Yellow}\n")
        self.assertEqual(
            (_ed._editor_hl_text_row, _ed._editor_hl_text_col),
            (2, 1),
        )
        self.assertEqual(_ed._editor_hl_text_sel, (2, 1))

    def test_cursor_for_styles_text_bg(self):
        self._setup_highlight(
            "#highlight {Orc} {underscore Red b green}\n")
        self.assertEqual(
            (_ed._editor_hl_text_row, _ed._editor_hl_text_col),
            (0, 1),
        )
        self.assertEqual(_ed._editor_hl_text_sel, (0, 1))
        self.assertEqual(
            (_ed._editor_hl_bg_row, _ed._editor_hl_bg_col),
            (1, 0),
        )
        self.assertEqual(_ed._editor_hl_bg_sel, (1, 0))

    def test_unparseable_body_leaves_body_untouched(self):
        # No more Custom slot — the body persists verbatim, cursor parks
        # at (0,0) with no swatch selected on either dimension.
        self._setup_highlight("#highlight {Snowy} {<faa>}\n")
        entry = _ed._editor_current_entry()
        self.assertEqual(entry.body, "<faa>")
        self.assertIsNone(_ed._editor_hl_text_sel)
        self.assertIsNone(_ed._editor_hl_bg_sel)
        self.assertEqual(
            (_ed._editor_hl_text_row, _ed._editor_hl_text_col),
            (0, 0))

    # --- selection toggling drives the body -----------------------
    def test_cursor_move_does_not_change_body(self):
        # Phase 6.2: cursor is decoupled from selection — moving the
        # cursor must not rewrite entry.body.
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = _ed._editor_current_entry()
        _ed._editor_hl_set_text_cursor(2, 0)   # yellow under cursor
        self.assertEqual(entry.body, "red")        # but body unchanged
        # The selection is still red.
        self.assertEqual(_ed._editor_hl_text_sel, (0, 0))

    def test_toggle_text_selection_at_cursor_updates_body(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = _ed._editor_current_entry()
        _ed._editor_hl_set_text_cursor(2, 1)        # Yellow
        _ed._editor_hl_toggle_text_selection_at_cursor()
        self.assertEqual(entry.body, "Yellow")
        self.assertEqual(_ed._editor_hl_text_sel, (2, 1))

    def test_toggle_text_selection_off_clears_color(self):
        # When cursor sits on the currently-selected swatch, toggling
        # deselects (no text colour in the body).
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = _ed._editor_current_entry()
        # Cursor parks on the selected swatch on load.
        _ed._editor_hl_toggle_text_selection_at_cursor()
        self.assertIsNone(_ed._editor_hl_text_sel)
        self.assertEqual(entry.body, "")  # no color, no styles

    def test_toggle_bg_selection_adds_b_clause(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = _ed._editor_current_entry()
        _ed._editor_detail_field = 3
        _ed._editor_hl_set_bg_cursor(1, 0)        # green
        _ed._editor_hl_toggle_bg_selection_at_cursor()
        self.assertEqual(entry.body, "red b green")
        # Toggling the same swatch off drops the b-clause.
        _ed._editor_hl_toggle_bg_selection_at_cursor()
        self.assertEqual(entry.body, "red")

    def test_style_toggle_adds_modifier(self):
        self._setup_highlight("#highlight {Orc} {red}\n")
        entry = _ed._editor_current_entry()
        _ed._editor_hl_toggle_style("underscore")
        self.assertEqual(entry.body, "underscore red")
        _ed._editor_hl_toggle_style("blink")
        self.assertEqual(entry.body, "underscore blink red")
        _ed._editor_hl_toggle_style("underscore")
        self.assertEqual(entry.body, "blink red")

    def test_editing_text_preserves_styles_and_bg(self):
        self._setup_highlight(
            "#highlight {Orc} {underscore Red b green}\n")
        entry = _ed._editor_current_entry()
        # Move cursor to blue (row 3 col 0) and toggle selection there.
        _ed._editor_hl_set_text_cursor(3, 0)
        _ed._editor_hl_toggle_text_selection_at_cursor()
        self.assertEqual(entry.body, "underscore blue b green")

    def test_editing_bg_preserves_text_and_styles(self):
        self._setup_highlight(
            "#highlight {Orc} {underscore Red b green}\n")
        entry = _ed._editor_current_entry()
        _ed._editor_detail_field = 3
        _ed._editor_hl_set_bg_cursor(4, 1)        # Magenta
        _ed._editor_hl_toggle_bg_selection_at_cursor()
        self.assertEqual(entry.body, "underscore Red b Magenta")


class TestPhase4HighlightListColorColumn(unittest.TestCase):
    """The Highlights list panel renders the `Color` column in the
    swatch's own colour for palette values; custom values render in
    default text style."""

    def test_palette_value_uses_color_style(self):
        prof, _src, _td = _make_profile(
            "#highlight {Orc} {light yellow}\n")
        _reset_editor_state(prof, kind="highlight")
        entry = _ed._editor_current_entry()
        frags = _ed._editor_list_row_text(entry, False, False)
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
        _reset_editor_state(prof, kind="highlight")
        entry = _ed._editor_current_entry()
        frags = _ed._editor_list_row_text(entry, False, False)
        self.assertEqual(len(frags), 1)
        style, _text = frags[0]
        self.assertEqual(style, launcher.C_ITEM)


class TestListBodyPreview(unittest.TestCase):
    """Pure-function tests for `_list_body_preview` — appends `…`
    whenever the list-view body cell does not show the body in full
    (truncated first line OR additional non-blank content follows)."""

    def test_single_line_fits_no_ellipsis(self):
        self.assertEqual(
            profile_editor._list_body_preview("kill orc", 20),
            "kill orc",
        )

    def test_truncated_line_gets_ellipsis(self):
        # 25 chars, column 10 → 9 chars + `…`.
        body = "abcdefghijklmnopqrstuvwxy"
        out = profile_editor._list_body_preview(body, 10)
        self.assertEqual(out, "abcdefghi…")
        self.assertEqual(len(out), 10)

    def test_multiline_first_fits_gets_ellipsis(self):
        # Spec example: `testcommand1;\ntestcommand2` previews as
        # `testcommand1;…` because more non-blank content follows.
        out = profile_editor._list_body_preview(
            "testcommand1;\ntestcommand2", 28)
        self.assertEqual(out, "testcommand1;…")

    def test_multiline_first_exactly_fills_column(self):
        # First line is exactly column-wide; trailing `…` must replace
        # the last char so the cell stays within the column.
        body = "x" * 10 + "\nmore"
        out = profile_editor._list_body_preview(body, 10)
        self.assertEqual(out, "x" * 9 + "…")
        self.assertEqual(len(out), 10)

    def test_blank_only_extras_no_ellipsis(self):
        # Trailing blank/whitespace-only lines do not count as "more".
        self.assertEqual(
            profile_editor._list_body_preview("hello\n   \n\n", 20),
            "hello",
        )

    def test_leading_blanks_skipped(self):
        # Phase 6.2 behaviour: leading blank lines are skipped.
        self.assertEqual(
            profile_editor._list_body_preview("\n\nhello", 20),
            "hello",
        )

    def test_empty_body(self):
        self.assertEqual(profile_editor._list_body_preview("", 20), "")
        self.assertEqual(profile_editor._list_body_preview(None, 20), "")


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
    """Phase 6 — lite/editor mode toggle. The two views are live-bound
    to the same in-memory Profile: lite → editor serialises the items
    into the text buffer; editor → lite parses the buffer back."""

    def _setup_in_lite_mode(self, source=""):
        prof, _src, _td = _make_profile(source)
        _reset_editor_state(prof)
        _ed._editor_mode           = "lite"
        _ed._editor_toggle_focused = False
        _ed._editor_toggle_hover   = None
        _ed._editor_buffer_text    = ""
        _ed._editor_buffer_cursor  = 0
        _ed._editor_buffer_scroll  = 0
        return prof

    def test_default_mode_is_lite_on_open(self):
        # No call to _enter_profile_editor here — the test harness sets
        # lite mode directly, mirroring the editor-state reset.
        prof = self._setup_in_lite_mode("#alias {k} {kill}\n")
        self.assertEqual(_ed._editor_mode, "lite")
        # Buffer text is empty until the first flip.
        self.assertEqual(_ed._editor_buffer_text, "")

    def test_flip_to_editor_serialises_profile(self):
        source = "#alias {k} {kill %1}\n#var {x} {y}\n"
        # Phase 6.2: parse → sort means the buffer reflects the canonical
        # grouped form, not the source verbatim.
        expected_buffer = "#alias {k} {kill %1}\n\n#var {x} {y}\n"
        prof = self._setup_in_lite_mode(source)
        _ed._editor_flip_mode()
        self.assertEqual(_ed._editor_mode, "editor")
        self.assertEqual(_ed._editor_buffer_text, expected_buffer)
        # Cursor lands at offset 0 on flip.
        self.assertEqual(_ed._editor_buffer_cursor, 0)
        self.assertEqual(_ed._editor_buffer_scroll, 0)

    def test_flip_back_to_lite_parses_buffer(self):
        # User edits the buffer in editor mode; flipping back into lite
        # rebuilds the Profile from the buffer text.
        prof = self._setup_in_lite_mode("#alias {k} {kill}\n")
        _ed._editor_flip_mode()  # → editor
        # Append a fresh entry through the buffer-mutation primitives.
        _ed._editor_buffer_cursor = len(_ed._editor_buffer_text)
        for ch in "#alias {ws} {wake;stand}\n":
            _ed._editor_buffer_insert(ch)
        _ed._editor_flip_mode()  # → lite
        self.assertEqual(_ed._editor_mode, "lite")
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
            _ed._editor_mode = "lite"
            _ed._editor_buffer_text = ""
            _ed._editor_buffer_cursor = 0
            _ed._editor_buffer_scroll = 0
            _ed._editor_toggle_focused = False
            _ed._editor_toggle_hover = None
            _ed._editor_flip_mode()
            self.assertEqual(_ed._editor_buffer_text, expected)
            _ed._editor_flip_mode()
            prof.path = dst
            profile_io.save_profile(prof)
            self.assertEqual(dst.read_text(), expected)

    def test_edits_survive_flip_round_trip(self):
        # Edit in lite mode → flip to editor → flip back to lite — the
        # lite-mode edit must persist (parser preserves it as the same
        # canonical Entry).
        prof = self._setup_in_lite_mode("#alias {k} {kill}\n")
        # Edit through the lite-mode helper.
        alias_k = prof.entries_of("alias")[0]
        alias_k.body = "kill orc"
        # Flip to editor and back.
        _ed._editor_flip_mode()
        self.assertIn("kill orc", _ed._editor_buffer_text)
        _ed._editor_flip_mode()
        self.assertEqual(prof.entries_of("alias")[0].body, "kill orc")


class TestEditorModeBufferCursor(unittest.TestCase):
    """Editor-mode buffer cursor model. Cursor is an absolute offset
    into `_editor_buffer_text`; helpers convert to `(line, col)` and
    the line-starts table backs visual layout / scroll-into-view."""

    def _setup_buffer(self, text):
        # Drop into editor mode with `text` as the buffer content.
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode           = "editor"
        _ed._editor_toggle_focused = False
        _ed._editor_buffer_text    = text
        _ed._editor_buffer_cursor  = 0
        _ed._editor_buffer_scroll  = 0

    def test_cursor_to_line_col_first_line(self):
        self._setup_buffer("hello\nworld\n")
        _ed._editor_buffer_cursor = 3
        self.assertEqual(_ed._editor_buffer_cursor_to_line_col(),
                         (0, 3))

    def test_cursor_to_line_col_second_line(self):
        self._setup_buffer("hello\nworld\n")
        _ed._editor_buffer_cursor = 8   # 6 (start of "world") + 2
        self.assertEqual(_ed._editor_buffer_cursor_to_line_col(),
                         (1, 2))

    def test_insert_at_cursor_advances_offset(self):
        self._setup_buffer("ab")
        _ed._editor_buffer_cursor = 1
        _ed._editor_buffer_insert("X")
        self.assertEqual(_ed._editor_buffer_text, "aXb")
        self.assertEqual(_ed._editor_buffer_cursor, 2)

    def test_backspace_at_offset(self):
        self._setup_buffer("abc")
        _ed._editor_buffer_cursor = 2
        _ed._editor_buffer_backspace()
        self.assertEqual(_ed._editor_buffer_text, "ac")
        self.assertEqual(_ed._editor_buffer_cursor, 1)

    def test_backspace_at_start_is_noop(self):
        self._setup_buffer("abc")
        _ed._editor_buffer_cursor = 0
        _ed._editor_buffer_backspace()
        self.assertEqual(_ed._editor_buffer_text, "abc")

    def test_delete_at_offset(self):
        self._setup_buffer("abc")
        _ed._editor_buffer_cursor = 1
        _ed._editor_buffer_delete()
        self.assertEqual(_ed._editor_buffer_text, "ac")
        # Cursor stays put — delete consumes the character to the right.
        self.assertEqual(_ed._editor_buffer_cursor, 1)

    def test_delete_at_end_is_noop(self):
        self._setup_buffer("abc")
        _ed._editor_buffer_cursor = 3
        _ed._editor_buffer_delete()
        self.assertEqual(_ed._editor_buffer_text, "abc")

    def test_set_cursor_from_line_col_clamps_to_line_length(self):
        self._setup_buffer("ab\nlonger line\n")
        _ed._editor_buffer_set_cursor_from_line_col(0, 99)
        # Line 0 is "ab" (length 2) — col clamps to 2.
        self.assertEqual(_ed._editor_buffer_cursor, 2)

    def test_line_count_handles_trailing_newline(self):
        # Vim-style line count: a trailing \n creates an empty phantom
        # line so the cursor at end-of-buffer has a real (line, col)
        # mapping.
        self._setup_buffer("a\nb\n")
        self.assertEqual(_ed._editor_buffer_line_count(), 3)

    def test_line_count_no_trailing_newline(self):
        self._setup_buffer("a\nb")
        self.assertEqual(_ed._editor_buffer_line_count(), 2)


class TestEditorModeToggle(unittest.TestCase):
    """Toggle-row focus + activation. Enter/Space flips mode, click on
    the inactive block flips mode, click on the active block is a
    no-op."""

    def _setup(self):
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof)
        _ed._editor_mode           = "lite"
        _ed._editor_toggle_focused = False
        _ed._editor_toggle_hover   = None
        _ed._editor_buffer_text    = ""
        _ed._editor_buffer_cursor  = 0
        _ed._editor_buffer_scroll  = 0
        return prof

    def test_focus_toggle_sets_flag(self):
        self._setup()
        _ed._editor_focus_toggle()
        self.assertTrue(_ed._editor_toggle_focused)

    def test_setting_lite_focus_clears_toggle_focus(self):
        self._setup()
        _ed._editor_focus_toggle()
        _ed._profile_editor_set_focus(1)
        self.assertFalse(_ed._editor_toggle_focused)

    def test_flip_mode_lite_to_editor_serialises(self):
        prof = self._setup()
        _ed._editor_flip_mode()
        self.assertEqual(_ed._editor_mode, "editor")
        self.assertEqual(_ed._editor_buffer_text,
                         "#alias {k} {kill}\n")

    def test_button_style_inactive_when_other_mode(self):
        self._setup()
        # mode = lite — the EDITOR button is inactive.
        self.assertEqual(
            _ed._editor_toggle_button_style("editor"),
            launcher.C_BUTTON_INACTIVE,
        )

    def test_button_style_active_focused_amber(self):
        self._setup()
        _ed._editor_focus_toggle()
        # mode = lite, toggle focused → LITE is active-focused.
        self.assertEqual(
            _ed._editor_toggle_button_style("lite"),
            launcher.C_BUTTON_ACTIVE_FOCUSED,
        )

    def test_button_style_active_unfocused_grey(self):
        self._setup()
        # mode = lite, toggle NOT focused → LITE is active-unfocused.
        self.assertEqual(
            _ed._editor_toggle_button_style("lite"),
            launcher.C_BUTTON_ACTIVE_UNFOCUSED,
        )

    def test_button_hover_on_inactive_previews_unfocused(self):
        self._setup()
        # mode = lite — hover on EDITOR previews active-unfocused.
        _ed._editor_toggle_hover = "editor"
        self.assertEqual(
            _ed._editor_toggle_button_style("editor"),
            launcher.C_BUTTON_ACTIVE_UNFOCUSED,
        )


class TestEditorModeBraceAssistance(unittest.TestCase):
    """Phase B — `{` auto-close + `}` overtype + `→` step-over + Backspace
    pair-delete, plus the brace-balance footer count. Logic lives in
    `_editor_buffer_open_brace` / `_editor_buffer_close_brace` /
    `_editor_buffer_backspace_pair` / `_editor_buffer_step_over_pending_closer`,
    not in `_editor_buffer_insert`, so paste paths can never trigger
    auto-close."""

    def _setup_buffer(self, text, cursor=0):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = cursor
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []

    # --- auto-close + guard ----------------------------------------
    def test_open_brace_at_end_auto_closes(self):
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_buffer_text, "abc{}")
        # Cursor lands between the two braces.
        self.assertEqual(_ed._editor_buffer_cursor, 4)
        self.assertEqual(_ed._editor_pending_closers, [4])

    def test_open_brace_before_whitespace_auto_closes(self):
        self._setup_buffer("ab cd", cursor=2)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_buffer_text, "ab{} cd")
        self.assertEqual(_ed._editor_buffer_cursor, 3)
        self.assertEqual(_ed._editor_pending_closers, [3])

    def test_open_brace_before_newline_auto_closes(self):
        self._setup_buffer("ab\ncd", cursor=2)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_buffer_text, "ab{}\ncd")
        self.assertEqual(_ed._editor_buffer_cursor, 3)

    def test_open_brace_before_close_brace_auto_closes(self):
        # Guard explicitly allows `}` as the next char — nested braces
        # should still get an inner pair. Only the newly auto-inserted
        # closer is tracked; the pre-existing `}` was not created by
        # auto-close so it never enters the list.
        self._setup_buffer("{}", cursor=1)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_buffer_text, "{{}}")
        self.assertEqual(_ed._editor_buffer_cursor, 2)
        self.assertEqual(_ed._editor_pending_closers, [2])

    def test_open_brace_before_non_whitespace_inserts_literal(self):
        # Guard rejects: next char is a regular letter, so no auto-close.
        self._setup_buffer("abc", cursor=1)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_buffer_text, "a{bc")
        self.assertEqual(_ed._editor_buffer_cursor, 2)
        self.assertEqual(_ed._editor_pending_closers, [])

    # --- `}` overtype ----------------------------------------------
    def test_close_brace_overtypes_pending_closer(self):
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_open_brace()       # → "abc{}", cur=4
        _ed._editor_buffer_close_brace()      # should overtype
        self.assertEqual(_ed._editor_buffer_text, "abc{}")
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_close_brace_without_pending_inserts_literal(self):
        # No tentative `}` tracked → typing `}` is a plain insert.
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_close_brace()
        self.assertEqual(_ed._editor_buffer_text, "abc}")
        self.assertEqual(_ed._editor_buffer_cursor, 4)

    def test_close_brace_at_non_pending_close_inserts_literal(self):
        # A `}` is at cursor, but its offset is NOT in the pending
        # list — treat as a regular insert.
        self._setup_buffer("ab}c", cursor=2)
        _ed._editor_buffer_close_brace()
        self.assertEqual(_ed._editor_buffer_text, "ab}}c")
        self.assertEqual(_ed._editor_buffer_cursor, 3)

    # --- `→` step-over ---------------------------------------------
    def test_right_arrow_steps_over_pending_closer(self):
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_open_brace()       # → "abc{}", cur=4, pend=[4]
        # Simulate `→`: advance cursor, drop pending entries behind it.
        _ed._editor_buffer_cursor = 5
        _ed._editor_buffer_step_over_pending_closer()
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_step_over_preserves_offsets_ahead_of_cursor(self):
        # Two nested auto-closes; stepping over the inner closer must
        # leave the outer one tracked.
        self._setup_buffer("", cursor=0)
        _ed._editor_pending_closers = [3, 5]   # outer, inner sentinels
        _ed._editor_buffer_cursor = 4
        _ed._editor_buffer_step_over_pending_closer()
        self.assertEqual(_ed._editor_pending_closers, [5])

    # --- Backspace pair-delete -------------------------------------
    def test_backspace_after_auto_close_removes_both(self):
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_open_brace()       # → "abc{}", cur=4
        _ed._editor_buffer_backspace_pair()
        self.assertEqual(_ed._editor_buffer_text, "abc")
        self.assertEqual(_ed._editor_buffer_cursor, 3)
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_backspace_without_pending_does_normal_delete(self):
        # `{}` exists in the buffer but the closer offset is NOT in the
        # pending list — backspace must NOT pair-delete the `}`.
        self._setup_buffer("a{}b", cursor=2)
        _ed._editor_buffer_backspace_pair()
        self.assertEqual(_ed._editor_buffer_text, "a}b")
        self.assertEqual(_ed._editor_buffer_cursor, 1)

    # --- Offset bookkeeping ----------------------------------------
    def test_insert_shifts_pending_offsets_right(self):
        # Insert a printable between the cursor and an existing tentative
        # closer: the closer's tracked offset shifts by the insert
        # length.
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_open_brace()       # → "abc{}", cur=4, pend=[4]
        _ed._editor_buffer_insert("X")        # → "abc{X}", cur=5
        self.assertEqual(_ed._editor_buffer_text, "abc{X}")
        self.assertEqual(_ed._editor_pending_closers, [5])
        # Subsequent overtype still steps over the (now shifted) closer.
        _ed._editor_buffer_close_brace()
        self.assertEqual(_ed._editor_buffer_text, "abc{X}")
        self.assertEqual(_ed._editor_buffer_cursor, 6)

    def test_delete_drops_pending_offset_pointing_into_range(self):
        # A forward-delete that consumes the tentative `}` must drop
        # its offset from the pending list, not silently keep a stale
        # entry pointing at the next character.
        self._setup_buffer("", cursor=0)
        _ed._editor_buffer_open_brace()       # → "{}", cur=1, pend=[1]
        _ed._editor_buffer_delete()           # remove the `}`
        self.assertEqual(_ed._editor_buffer_text, "{")
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_delete_before_pending_shifts_offset_left(self):
        # Delete a character that sits BEFORE the tentative closer
        # shifts the closer's tracked offset left by one.
        self._setup_buffer("abc", cursor=3)
        _ed._editor_buffer_open_brace()       # → "abc{}", cur=4, pend=[4]
        _ed._editor_buffer_cursor = 0
        _ed._editor_buffer_delete()           # drops "a", text="bc{}"
        self.assertEqual(_ed._editor_buffer_text, "bc{}")
        self.assertEqual(_ed._editor_pending_closers, [3])

    # --- Balance count ---------------------------------------------
    def test_balance_balanced_returns_zero(self):
        self._setup_buffer("{a{b}c}")
        self.assertEqual(_ed._editor_buffer_brace_balance(), (0, 0))
        self.assertEqual(_ed._editor_brace_balance_text(), "")

    def test_balance_unclosed(self):
        self._setup_buffer("{a{b}")
        self.assertEqual(_ed._editor_buffer_brace_balance(), (1, 0))
        self.assertIn("unclosed", _ed._editor_brace_balance_text())

    def test_balance_stray_close(self):
        # Depth goes negative on the first `}`, so it's a stray.
        self._setup_buffer("a}b")
        self.assertEqual(_ed._editor_buffer_brace_balance(), (0, 1))
        self.assertIn("stray", _ed._editor_brace_balance_text())

    def test_balance_both_unclosed_and_stray(self):
        self._setup_buffer("} {")
        self.assertEqual(_ed._editor_buffer_brace_balance(), (1, 1))
        text = _ed._editor_brace_balance_text()
        self.assertIn("unclosed", text)
        self.assertIn("stray", text)

    def test_balance_escaped_brace_does_not_count(self):
        # `\{` is a `code` span, not a `brace` span — it must not
        # contribute to the balance.
        self._setup_buffer(r"\{abc")
        self.assertEqual(_ed._editor_buffer_brace_balance(), (0, 0))

    def test_balance_var_expansion_brace_does_not_count(self):
        # The braces inside `${...}` are part of the `var` span and
        # never reported as structural.
        self._setup_buffer("${foo}")
        self.assertEqual(_ed._editor_buffer_brace_balance(), (0, 0))


class TestEditorModeBraceMatch(unittest.TestCase):
    """Matching-brace highlight positions. The renderer paints both
    cells with C_SYN_BRACE_MATCH when the cursor sits adjacent to a
    structural brace and a partner is found."""

    def _setup_buffer(self, text, cursor=0):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = cursor
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []

    def test_cursor_at_open_brace_finds_partner(self):
        self._setup_buffer("{a{b}c}", cursor=0)
        self.assertEqual(_ed._editor_brace_match_positions(), (0, 6))

    def test_cursor_after_close_brace_finds_partner(self):
        self._setup_buffer("{a}", cursor=3)
        self.assertEqual(_ed._editor_brace_match_positions(), (0, 2))

    def test_cursor_between_paired_braces_matches_open(self):
        # cursor=1: text[0]='{', text[1]='}'. Spec: prefer cursor-1
        # candidate first → match the `{` and find `}` as partner.
        self._setup_buffer("{}", cursor=1)
        self.assertEqual(_ed._editor_brace_match_positions(), (0, 1))

    def test_no_match_when_cursor_not_adjacent_to_brace(self):
        self._setup_buffer("{abc}", cursor=2)   # between 'a' and 'b'
        self.assertIsNone(_ed._editor_brace_match_positions())

    def test_unbalanced_returns_none(self):
        self._setup_buffer("{ab", cursor=0)
        self.assertIsNone(_ed._editor_brace_match_positions())

    def test_escaped_brace_is_not_structural(self):
        # `\{` is part of a `code` span, not `brace` — the cursor
        # adjacent to it has nothing to match.
        self._setup_buffer(r"\{abc", cursor=2)
        self.assertIsNone(_ed._editor_brace_match_positions())


class TestEditorModePendingClearedOnNonEditingActions(unittest.TestCase):
    """Lifetime: any editor action other than printable insert,
    Backspace/Delete, `}` overtype, and `→` clears
    `_editor_pending_closers`."""

    def _setup_with_pending(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = "abc{}"
        _ed._editor_buffer_cursor    = 4
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = [4]

    def test_enter_profile_editor_resets_pending(self):
        # Creating a new ProfileEditor always starts with empty pending closers,
        # regardless of what the previous editor state held.
        prof, _src, _td = _make_profile("")
        ed = profile_editor.ProfileEditor(
            path=prof.path,
            profile=profile_io.load_profile(prof.path),
            on_exit=lambda p: None,
            host=_test_host,
        )
        self.assertEqual(ed._editor_pending_closers, [])

    def test_flip_mode_clears_pending(self):
        self._setup_with_pending()
        _ed._editor_flip_mode()        # editor → lite
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_helper_clear_pending_is_idempotent(self):
        self._setup_with_pending()
        _ed._editor_clear_pending_closers()
        self.assertEqual(_ed._editor_pending_closers, [])
        _ed._editor_clear_pending_closers()
        self.assertEqual(_ed._editor_pending_closers, [])


class TestProfileEditorClipboardEditorMode(unittest.TestCase):
    """Phase C — clipboard in the Editor-mode text buffer. Shared
    `_editor_clipboard` register; OSC 52 write rides along but is a
    no-op in tests (`_app is None`)."""

    def _setup_buffer(self, text, cursor=0):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = cursor
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []
        _ed._editor_clipboard        = ""

    def test_copy_selection_writes_register(self):
        self._setup_buffer("abcdef", cursor=4)
        _ed._editor_buffer_anchor = 1   # selection "bcd"
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "bcd")
        # Cursor and buffer unchanged.
        self.assertEqual(_ed._editor_buffer_text, "abcdef")
        self.assertEqual(_ed._editor_buffer_cursor, 4)

    def test_copy_without_selection_copies_line_with_newline(self):
        self._setup_buffer("aa\nbb\ncc\n", cursor=4)   # mid line 1 ("bb")
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "bb\n")

    def test_copy_last_line_without_trailing_newline_adds_one(self):
        # Line-copy semantics include a trailing newline even when the
        # last line is unterminated.
        self._setup_buffer("xx\nyy", cursor=4)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "yy\n")

    def test_cut_selection_deletes_and_copies(self):
        self._setup_buffer("abcdef", cursor=4)
        _ed._editor_buffer_anchor = 1
        _ed._editor_buffer_cut()
        self.assertEqual(_ed._editor_clipboard, "bcd")
        self.assertEqual(_ed._editor_buffer_text, "aef")
        self.assertEqual(_ed._editor_buffer_cursor, 1)
        self.assertIsNone(_ed._editor_buffer_anchor)

    def test_cut_without_selection_drops_line_with_trailing_newline(self):
        # The cursor's line is `bb\n`; both go.
        self._setup_buffer("aa\nbb\ncc\n", cursor=4)
        _ed._editor_buffer_cut()
        self.assertEqual(_ed._editor_clipboard, "bb\n")
        self.assertEqual(_ed._editor_buffer_text, "aa\ncc\n")

    def test_cut_last_line_eats_preceding_newline(self):
        # Last line has no trailing `\n` — to avoid leaving a blank
        # line, the cut consumes the preceding `\n` instead.
        self._setup_buffer("aa\nyy", cursor=4)
        _ed._editor_buffer_cut()
        self.assertEqual(_ed._editor_clipboard, "yy\n")
        self.assertEqual(_ed._editor_buffer_text, "aa")

    def test_paste_inserts_register_at_cursor(self):
        self._setup_buffer("ace", cursor=1)
        _ed._editor_clipboard = "bd"
        _ed._editor_buffer_paste()
        self.assertEqual(_ed._editor_buffer_text, "abdce")
        self.assertEqual(_ed._editor_buffer_cursor, 3)

    def test_paste_over_selection_replaces_it(self):
        self._setup_buffer("abcdef", cursor=4)
        _ed._editor_buffer_anchor = 1   # selection "bcd"
        _ed._editor_clipboard = "XYZ"
        _ed._editor_buffer_paste()
        self.assertEqual(_ed._editor_buffer_text, "aXYZef")
        self.assertEqual(_ed._editor_buffer_cursor, 4)
        self.assertIsNone(_ed._editor_buffer_anchor)

    def test_bracketed_paste_normalises_crlf(self):
        self._setup_buffer("", cursor=0)
        _ed._editor_buffer_bracketed_paste("one\r\ntwo\rthree")
        self.assertEqual(_ed._editor_buffer_text, "one\ntwo\nthree")

    def test_bracketed_paste_multi_line_inserts_inline(self):
        self._setup_buffer("ab", cursor=2)
        _ed._editor_buffer_bracketed_paste("XX\nYY")
        self.assertEqual(_ed._editor_buffer_text, "abXX\nYY")
        # Cursor lands after the last inserted character.
        self.assertEqual(_ed._editor_buffer_cursor,
                         len("abXX\nYY"))

    def test_cut_clears_pending_closers(self):
        self._setup_buffer("ab{}", cursor=3)
        _ed._editor_pending_closers = [3]
        _ed._editor_buffer_anchor = 2   # selection "{"
        _ed._editor_buffer_cut()
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_paste_clears_pending_closers(self):
        self._setup_buffer("ab{}", cursor=3)
        _ed._editor_pending_closers = [3]
        _ed._editor_clipboard = "Z"
        _ed._editor_buffer_paste()
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_bracketed_paste_clears_pending_closers(self):
        self._setup_buffer("ab{}", cursor=3)
        _ed._editor_pending_closers = [3]
        _ed._editor_buffer_bracketed_paste("Z")
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_copy_leaves_pending_closers_intact(self):
        self._setup_buffer("ab{}", cursor=3)
        _ed._editor_pending_closers = [3]
        _ed._editor_buffer_anchor = 2
        _ed._editor_buffer_copy()
        # Copy is non-mutating — pending closers untouched.
        self.assertEqual(_ed._editor_pending_closers, [3])


class TestProfileEditorClipboardLitePattern(unittest.TestCase):
    """Phase C — clipboard in the Lite Pattern field. Single-line, so
    bracketed paste flattens newlines to spaces."""

    def _setup(self, pattern, cursor=0):
        prof, _src, _td = _make_profile(f"#alias {{{pattern}}} {{body}}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 0
        _ed._editor_pattern_cursor  = cursor
        _ed._editor_pattern_anchor  = None
        _ed._editor_clipboard       = ""

    def test_copy_selection_writes_register(self):
        self._setup("abcdef", cursor=5)
        _ed._editor_pattern_anchor = 2   # selection "cde"
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "cde")

    def test_copy_without_selection_copies_whole_pattern_with_newline(self):
        self._setup("abcdef", cursor=3)
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "abcdef\n")

    def test_copy_empty_pattern_is_noop(self):
        self._setup("ab", cursor=2)
        _ed._editor_set_pattern("")     # blank Pattern
        _ed._editor_pattern_cursor = 0
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "")

    def test_cut_selection_deletes_and_copies(self):
        self._setup("abcdef", cursor=5)
        _ed._editor_pattern_anchor = 2
        _ed._editor_pattern_cut()
        self.assertEqual(_ed._editor_clipboard, "cde")
        self.assertEqual(_ed._editor_current_entry().pattern, "abf")
        self.assertEqual(_ed._editor_pattern_cursor, 2)

    def test_cut_without_selection_clears_pattern(self):
        self._setup("abcdef", cursor=3)
        _ed._editor_pattern_cut()
        self.assertEqual(_ed._editor_clipboard, "abcdef\n")
        self.assertEqual(_ed._editor_current_entry().pattern, "")
        self.assertEqual(_ed._editor_pattern_cursor, 0)

    def test_paste_inserts_register_at_cursor(self):
        self._setup("abc", cursor=2)
        _ed._editor_clipboard = "XY"
        _ed._editor_pattern_paste()
        self.assertEqual(_ed._editor_current_entry().pattern, "abXYc")
        self.assertEqual(_ed._editor_pattern_cursor, 4)

    def test_paste_over_selection_replaces_it(self):
        self._setup("abcdef", cursor=5)
        _ed._editor_pattern_anchor = 2   # selection "cde"
        _ed._editor_clipboard = "XYZ"
        _ed._editor_pattern_paste()
        self.assertEqual(_ed._editor_current_entry().pattern, "abXYZf")
        self.assertEqual(_ed._editor_pattern_cursor, 5)

    def test_paste_flattens_register_newlines_to_spaces(self):
        # Register populated from a multi-line source — Pattern is
        # single-line, so newlines flatten.
        self._setup("ab", cursor=2)
        _ed._editor_clipboard = "X\nY\nZ"
        _ed._editor_pattern_paste()
        self.assertEqual(_ed._editor_current_entry().pattern,
                         "abX Y Z")

    def test_bracketed_paste_flattens_newlines(self):
        self._setup("ab", cursor=2)
        _ed._editor_pattern_bracketed_paste("one\r\ntwo\rthree")
        # \r\n and \r normalised to \n, then flattened to spaces.
        self.assertEqual(_ed._editor_current_entry().pattern,
                         "abone two three")


class TestProfileEditorClipboardLiteBody(unittest.TestCase):
    """Phase C — clipboard in the Lite Body field. Multi-line; paste
    preserves embedded newlines."""

    def _setup(self, body, line=0, col=0):
        prof, _src, _td = _make_profile(f"#alias {{k}} {{{body}}}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field        = 1
        _ed._editor_body_line           = line
        _ed._editor_body_col            = col
        _ed._editor_body_anchor_line    = None
        _ed._editor_body_anchor_col     = None
        _ed._editor_clipboard           = ""

    def test_copy_single_line_selection(self):
        self._setup("abcdef", line=0, col=5)
        _ed._editor_body_anchor_line = 0
        _ed._editor_body_anchor_col  = 2   # selection "cde"
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "cde")

    def test_copy_multi_line_selection(self):
        # Body splits on `\n`, so seed with explicit newlines.
        prof, _src, _td = _make_profile("#alias {k} {a}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field        = 1
        _ed._editor_current_entry().body = "one\ntwo\nthree"
        _ed._editor_body_line       = 2
        _ed._editor_body_col        = 2     # middle of "three"
        _ed._editor_body_anchor_line = 0
        _ed._editor_body_anchor_col  = 1    # middle of "one"
        _ed._editor_clipboard       = ""
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "ne\ntwo\nth")

    def test_copy_without_selection_copies_current_line_with_newline(self):
        prof, _src, _td = _make_profile("#alias {k} {a}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_current_entry().body = "one\ntwo\nthree"
        _ed._editor_body_line    = 1   # "two"
        _ed._editor_body_col     = 0
        _ed._editor_clipboard    = ""
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "two\n")

    def test_cut_selection_deletes_and_copies(self):
        self._setup("abcdef", line=0, col=5)
        _ed._editor_body_anchor_line = 0
        _ed._editor_body_anchor_col  = 2
        _ed._editor_body_cut()
        self.assertEqual(_ed._editor_clipboard, "cde")
        self.assertEqual(_ed._editor_current_entry().body, "abf")

    def test_cut_without_selection_drops_line(self):
        prof, _src, _td = _make_profile("#alias {k} {a}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_current_entry().body = "one\ntwo\nthree"
        _ed._editor_body_line    = 1   # "two"
        _ed._editor_body_col     = 0
        _ed._editor_clipboard    = ""
        _ed._editor_body_cut()
        self.assertEqual(_ed._editor_clipboard, "two\n")
        # Body re-joined with the surviving lines.
        self.assertEqual(_ed._editor_current_entry().body, "one\nthree")

    def test_paste_inserts_at_cursor(self):
        self._setup("abc", line=0, col=2)
        _ed._editor_clipboard = "XY"
        _ed._editor_body_paste()
        self.assertEqual(_ed._editor_current_entry().body, "abXYc")
        self.assertEqual(_ed._editor_body_col, 4)

    def test_paste_preserves_embedded_newlines(self):
        self._setup("abc", line=0, col=2)
        _ed._editor_clipboard = "X\nY"
        _ed._editor_body_paste()
        # Body is multi-line — paste splits the line at the cursor.
        # Stored body joins lines with `\n`.
        self.assertEqual(_ed._editor_current_entry().body, "abX\nYc")
        self.assertEqual(_ed._editor_body_line, 1)
        self.assertEqual(_ed._editor_body_col,  1)

    def test_paste_over_selection_replaces_it(self):
        self._setup("abcdef", line=0, col=5)
        _ed._editor_body_anchor_line = 0
        _ed._editor_body_anchor_col  = 2
        _ed._editor_clipboard = "Z"
        _ed._editor_body_paste()
        self.assertEqual(_ed._editor_current_entry().body, "abZf")

    def test_bracketed_paste_keeps_newlines(self):
        self._setup("ab", line=0, col=2)
        _ed._editor_body_bracketed_paste("one\r\ntwo")
        # \r\n normalised to \n; preserved in Body as a `\n` separator.
        self.assertEqual(_ed._editor_current_entry().body, "abone\ntwo")


class TestProfileEditorCopyCutFlash(unittest.TestCase):
    """Transient `Copied` / `Cut` confirmation flash in the profile-editor
    footer. Set on a successful c-c / c-x, never on c-v. Cleared on the
    1.5 s timer (or explicit `_editor_clear_flash`). Suppressed in no-op
    contexts — palette / macro Key / kind buttons / list — because the
    lite-mode dispatcher returns False before the flash call runs."""

    def setUp(self):
        # `_app_loop is None` in tests: the setter writes the text and
        # style but skips scheduling — exactly what we want here.
        _ed._editor_clear_flash()

    def tearDown(self):
        _ed._editor_clear_flash()

    # --- Editor-mode buffer ------------------------------------------
    def test_editor_buffer_copy_sets_flash_copied(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = "abc"
        _ed._editor_buffer_cursor    = 1
        _ed._editor_buffer_anchor    = None
        _ed._editor_clipboard        = ""
        _ed._kb_peditor_buffer_copy(None)
        self.assertEqual(_ed._editor_flash_text, "Copied")

    def test_editor_buffer_cut_sets_flash_cut(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = "abc"
        _ed._editor_buffer_cursor    = 1
        _ed._editor_buffer_anchor    = None
        _ed._editor_clipboard        = ""
        _ed._kb_peditor_buffer_cut(None)
        self.assertEqual(_ed._editor_flash_text, "Cut")

    def test_editor_buffer_paste_does_not_flash(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = "abc"
        _ed._editor_buffer_cursor    = 1
        _ed._editor_buffer_anchor    = None
        _ed._editor_clipboard        = "X"
        _ed._kb_peditor_buffer_paste(None)
        self.assertIsNone(_ed._editor_flash_text)

    def test_editor_bracketed_paste_does_not_flash(self):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = ""
        _ed._editor_buffer_cursor    = 0
        _ed._editor_buffer_anchor    = None
        # Synthesise a minimal bracketed-paste event stub.
        class _Ev:
            data = "hello"
        _ed._kb_peditor_buffer_bracketed_paste(_Ev())
        self.assertIsNone(_ed._editor_flash_text)

    # --- Lite Pattern -----------------------------------------------
    def test_lite_pattern_copy_sets_flash_copied(self):
        prof, _src, _td = _make_profile("#alias {abc} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 0
        _ed._editor_pattern_cursor  = 0
        _ed._editor_pattern_anchor  = None
        _ed._editor_clipboard       = ""
        _ed._kb_peditor_lite_copy(None)
        self.assertEqual(_ed._editor_flash_text, "Copied")

    def test_lite_pattern_cut_sets_flash_cut(self):
        prof, _src, _td = _make_profile("#alias {abc} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 0
        _ed._editor_pattern_cursor  = 0
        _ed._editor_pattern_anchor  = None
        _ed._editor_clipboard       = ""
        _ed._kb_peditor_lite_cut(None)
        self.assertEqual(_ed._editor_flash_text, "Cut")

    # --- Lite Body --------------------------------------------------
    def test_lite_body_copy_sets_flash_copied(self):
        prof, _src, _td = _make_profile("#alias {k} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 1
        _ed._editor_body_line       = 0
        _ed._editor_body_col        = 0
        _ed._editor_body_anchor_line = None
        _ed._editor_body_anchor_col  = None
        _ed._editor_clipboard       = ""
        _ed._kb_peditor_lite_copy(None)
        self.assertEqual(_ed._editor_flash_text, "Copied")

    def test_lite_body_cut_sets_flash_cut(self):
        prof, _src, _td = _make_profile("#alias {k} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 1
        _ed._editor_body_line       = 0
        _ed._editor_body_col        = 0
        _ed._editor_body_anchor_line = None
        _ed._editor_body_anchor_col  = None
        _ed._editor_clipboard       = ""
        _ed._kb_peditor_lite_cut(None)
        self.assertEqual(_ed._editor_flash_text, "Cut")

    def test_lite_paste_does_not_flash(self):
        prof, _src, _td = _make_profile("#alias {abc} {body}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 0
        _ed._editor_pattern_cursor  = 0
        _ed._editor_pattern_anchor  = None
        _ed._editor_clipboard       = "X"
        _ed._kb_peditor_lite_paste(None)
        self.assertIsNone(_ed._editor_flash_text)

    # --- No-op contexts (lite mode) ---------------------------------
    def test_lite_copy_in_list_focus_does_not_flash(self):
        # `_editor_focus = 1` → list. Dispatcher returns False, no flash.
        prof, _src, _td = _make_profile("#alias {abc} {body}\n")
        _reset_editor_state(prof, focus=1)
        _ed._kb_peditor_lite_copy(None)
        self.assertIsNone(_ed._editor_flash_text)

    def test_lite_copy_in_kind_focus_does_not_flash(self):
        prof, _src, _td = _make_profile("#alias {abc} {body}\n")
        _reset_editor_state(prof, focus=0)
        _ed._kb_peditor_lite_copy(None)
        self.assertIsNone(_ed._editor_flash_text)

    def test_lite_copy_in_palette_focus_does_not_flash(self):
        # Highlights tab, detail_field = 2 (Text palette) — palette focus.
        prof, _src, _td = _make_profile("#highlight {abc} {white}\n")
        _reset_editor_state(prof, focus=2, kind="highlight")
        _ed._editor_detail_field = 2
        _ed._kb_peditor_lite_copy(None)
        self.assertIsNone(_ed._editor_flash_text)

    def test_lite_copy_in_macro_key_focus_does_not_flash(self):
        # Macros tab, detail_field = 0 → macro Key cell.
        prof, _src, _td = _make_profile("#macro {\\eOP} {body}\n")
        _reset_editor_state(prof, focus=2, kind="macro")
        _ed._editor_detail_field = 0
        _ed._kb_peditor_lite_copy(None)
        self.assertIsNone(_ed._editor_flash_text)

    # --- Clearing ---------------------------------------------------
    def test_clear_flash_resets_text_and_style(self):
        _ed._editor_flash("Copied")
        self.assertEqual(_ed._editor_flash_text, "Copied")
        _ed._editor_clear_flash()
        self.assertIsNone(_ed._editor_flash_text)
        self.assertEqual(_ed._editor_flash_style, "")
        self.assertIsNone(_ed._editor_flash_handle)


class TestClipboardCtrlCFilter(unittest.TestCase):
    """Phase C — the global `c-c` quit must NOT fire inside the
    profile_editor frame. ESC is the documented editor exit."""

    def test_global_c_c_quit_filter_evaluates_per_frame(self):
        # The handler is registered with `filter=~_in_frame("profile_editor")`.
        # We can't easily introspect the bound filter, but the same
        # `_in_frame` helper is module-public — confirm it flips state
        # as the frame changes.
        cond = launcher._in_frame("profile_editor")
        # Force a sane terminal size so `_size_ok()` is True in tests.
        prev_frame = launcher._current_frame
        try:
            launcher._current_frame = "profile_editor"
            self.assertTrue(cond())
            launcher._current_frame = "main"
            self.assertFalse(cond())
        finally:
            launcher._current_frame = prev_frame


class TestEditorModeUndoRedo(unittest.TestCase):
    """Phase D — snapshot-based undo/redo for the Editor-mode text
    buffer. Single-character typing coalesces; paste / cut / auto-close
    / overtype / pair-delete / newline each form their own undoable
    unit; a cursor move (or any focus / mode change) forces a
    coalescing boundary. See ADR 0091."""

    def _setup(self, text="", cursor=0):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = cursor
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []
        _ed._editor_clipboard        = ""
        _ed._editor_undo_reset()

    # Helpers that mirror the relevant key-handler flow without
    # invoking prompt_toolkit's key parser. Each pairs the kind label
    # the live handler passes with the matching buffer mutator.
    def _type(self, s):
        for ch in s:
            kind = None if _ed._editor_buffer_anchor is not None else "insert"
            _ed._editor_undo_record(kind)
            _ed._editor_buffer_insert(ch)

    def _backspace(self):
        # Mimics the `backspace` key handler, which delegates to
        # `_editor_buffer_backspace_pair` (records the transaction
        # internally — pair-delete is atomic, plain backspace coalesces).
        _ed._editor_buffer_backspace_pair()

    def _delete(self):
        kind = None if _ed._editor_buffer_anchor is not None else "delete"
        _ed._editor_undo_record(kind)
        _ed._editor_buffer_delete()

    def _move_cursor(self, new_pos):
        # Cursor moves close any open coalescing run. We bypass the
        # line/col helpers and write the offset directly for terseness.
        _ed._editor_undo_close()
        _ed._editor_buffer_cursor = new_pos
        _ed._editor_buffer_clear_selection()

    def _enter(self):
        _ed._editor_undo_record(None)
        _ed._editor_buffer_insert("\n")

    # --- Coalesced typing -------------------------------------------
    def test_typing_a_word_undoes_in_one_step(self):
        self._setup()
        self._type("hello")
        self.assertEqual(_ed._editor_buffer_text, "hello")
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "")
        self.assertEqual(_ed._editor_buffer_cursor, 0)

    def test_redo_restores_typed_word(self):
        self._setup()
        self._type("hello")
        _ed._editor_undo()
        _ed._editor_redo()
        self.assertEqual(_ed._editor_buffer_text, "hello")
        self.assertEqual(_ed._editor_buffer_cursor, 5)

    # --- Cursor-move boundary ---------------------------------------
    def test_cursor_move_splits_typing_run(self):
        self._setup(text="abc", cursor=3)
        self._type("XY")            # run 1
        self.assertEqual(_ed._editor_buffer_text, "abcXY")
        self._move_cursor(0)
        self._type("Z")             # run 2 — fresh transaction
        self.assertEqual(_ed._editor_buffer_text, "ZabcXY")
        _ed._editor_undo()     # undo only the "Z" run
        self.assertEqual(_ed._editor_buffer_text, "abcXY")
        _ed._editor_undo()     # undo the "XY" run
        self.assertEqual(_ed._editor_buffer_text, "abc")

    # --- Insert ↔ delete boundary -----------------------------------
    def test_insert_then_delete_each_own_transaction(self):
        self._setup()
        self._type("ab")
        self._backspace()           # type-switch forces a boundary
        self.assertEqual(_ed._editor_buffer_text, "a")
        _ed._editor_undo()     # undo the delete
        self.assertEqual(_ed._editor_buffer_text, "ab")
        _ed._editor_undo()     # undo the typing run
        self.assertEqual(_ed._editor_buffer_text, "")

    def test_backspace_then_insert_each_own_transaction(self):
        self._setup(text="abc", cursor=3)
        self._backspace()
        self._backspace()           # coalesces with the previous backspace
        self.assertEqual(_ed._editor_buffer_text, "a")
        self._type("Z")
        self.assertEqual(_ed._editor_buffer_text, "aZ")
        _ed._editor_undo()     # undo the insert
        self.assertEqual(_ed._editor_buffer_text, "a")
        _ed._editor_undo()     # undo the coalesced delete run
        self.assertEqual(_ed._editor_buffer_text, "abc")

    # --- Paste / cut / bracketed paste are atomic units -------------
    def test_paste_is_atomic(self):
        self._setup(text="ab", cursor=2)
        _ed._editor_clipboard = "XYZ"
        _ed._editor_buffer_paste()
        self.assertEqual(_ed._editor_buffer_text, "abXYZ")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "ab")
        self.assertEqual(_ed._editor_buffer_cursor, 2)

    def test_cut_selection_is_atomic(self):
        self._setup(text="abcdef", cursor=4)
        _ed._editor_buffer_anchor = 1   # selection "bcd"
        _ed._editor_buffer_cut()
        self.assertEqual(_ed._editor_buffer_text, "aef")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "abcdef")

    def test_cut_line_is_atomic(self):
        self._setup(text="aa\nbb\ncc\n", cursor=4)   # mid "bb"
        _ed._editor_buffer_cut()
        self.assertEqual(_ed._editor_buffer_text, "aa\ncc\n")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "aa\nbb\ncc\n")

    def test_bracketed_paste_is_atomic(self):
        self._setup(text="ab", cursor=2)
        _ed._editor_buffer_bracketed_paste("XX\nYY")
        self.assertEqual(_ed._editor_buffer_text, "abXX\nYY")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "ab")

    # --- Auto-close `{}` as a single unit ---------------------------
    def test_autoclose_brace_is_atomic(self):
        self._setup(text="abc", cursor=3)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_buffer_text, "abc{}")
        self.assertEqual(_ed._editor_buffer_cursor, 4)
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "abc")
        self.assertEqual(_ed._editor_buffer_cursor, 3)

    def test_autoclose_then_typed_word_two_undos(self):
        # Typing inside the auto-closed pair is a separate insert run;
        # two undos peel back: first the typed word, then the `{}`.
        self._setup(text="abc", cursor=3)
        _ed._editor_buffer_open_brace()    # → "abc{}", cur=4
        self._type("Xy")                         # → "abc{Xy}"
        self.assertEqual(_ed._editor_buffer_text, "abc{Xy}")
        _ed._editor_undo()                  # undo typing
        self.assertEqual(_ed._editor_buffer_text, "abc{}")
        _ed._editor_undo()                  # undo auto-close
        self.assertEqual(_ed._editor_buffer_text, "abc")

    # --- Pair-delete and overtype are atomic ------------------------
    def test_pair_delete_is_atomic(self):
        self._setup(text="abc", cursor=3)
        _ed._editor_buffer_open_brace()    # → "abc{}", pending=[4]
        _ed._editor_buffer_backspace_pair()
        self.assertEqual(_ed._editor_buffer_text, "abc")
        # Two atomic transactions → two undos.
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "abc{}")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "abc")

    # --- Newline forces a boundary ----------------------------------
    def test_newline_forces_boundary(self):
        self._setup()
        self._type("ab")
        self._enter()
        self._type("cd")
        self.assertEqual(_ed._editor_buffer_text, "ab\ncd")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "ab\n")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "ab")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "")

    # --- Empty-stack no-op ------------------------------------------
    def test_undo_on_empty_stack_is_noop(self):
        self._setup(text="abc", cursor=1)
        # Stack is empty after _setup → _editor_undo_reset.
        self.assertEqual(_ed._editor_undo_stack, [])
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "abc")
        self.assertEqual(_ed._editor_buffer_cursor, 1)

    def test_redo_on_empty_stack_is_noop(self):
        self._setup(text="abc", cursor=1)
        _ed._editor_redo()
        self.assertEqual(_ed._editor_buffer_text, "abc")
        self.assertEqual(_ed._editor_buffer_cursor, 1)

    def test_undo_past_history_eventually_noop(self):
        # Type one transaction, undo it, undo again — second undo is
        # a no-op (stack already drained).
        self._setup()
        self._type("hi")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "")
        self.assertEqual(_ed._editor_undo_stack, [])
        _ed._editor_undo()      # no-op
        self.assertEqual(_ed._editor_buffer_text, "")

    # --- Redo cleared by a new edit ---------------------------------
    def test_new_edit_clears_redo_stack(self):
        self._setup()
        self._type("ab")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "")
        # Redo stack has the just-undone transaction.
        self.assertEqual(len(_ed._editor_redo_stack), 1)
        # A fresh edit invalidates the redo future.
        self._type("XY")
        self.assertEqual(_ed._editor_redo_stack, [])
        # A subsequent redo is now a no-op.
        before = _ed._editor_buffer_text
        _ed._editor_redo()
        self.assertEqual(_ed._editor_buffer_text, before)

    # --- Stack reset on mode flip -----------------------------------
    def test_undo_state_resets_on_mode_flip(self):
        # Round-trip through a real flip from lite → editor → lite.
        prof, _src, _td = _make_profile("#alias {k} {kill}\n")
        _reset_editor_state(prof)
        _ed._editor_mode             = "lite"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = ""
        _ed._editor_buffer_cursor    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []
        _ed._editor_undo_reset()
        _ed._editor_flip_mode()   # lite → editor
        self.assertEqual(_ed._editor_undo_stack, [])
        self.assertEqual(_ed._editor_redo_stack, [])
        # Build a transaction and an entry on the redo stack.
        self._type("X")
        self.assertGreater(len(_ed._editor_undo_stack), 0)
        _ed._editor_undo()
        self.assertGreater(len(_ed._editor_redo_stack), 0)
        # Flipping back to lite wipes both stacks.
        _ed._editor_flip_mode()   # editor → lite
        self.assertEqual(_ed._editor_undo_stack, [])
        self.assertEqual(_ed._editor_redo_stack, [])

    def test_undo_state_resets_on_enter_profile_editor(self):
        # Seed stacks with some entries, then re-enter the editor —
        # state must be wiped so undo can't reach the previous frame.
        self._setup()
        self._type("abc")
        self.assertGreater(len(_ed._editor_undo_stack), 0)
        # `_enter_profile_editor` calls `_editor_undo_reset` after
        # clearing the buffer; we exercise the reset directly here
        # because the full enter-path needs a valid file on disk.
        _ed._editor_undo_reset()
        self.assertEqual(_ed._editor_undo_stack, [])
        self.assertEqual(_ed._editor_redo_stack, [])

    # --- Post-undo invariants ---------------------------------------
    def test_undo_clears_pending_closers(self):
        self._setup(text="abc", cursor=3)
        _ed._editor_buffer_open_brace()
        self.assertEqual(_ed._editor_pending_closers, [4])
        _ed._editor_undo()
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_undo_restores_anchor(self):
        # Selection-replace through a type captures the anchor in the
        # snapshot; undo brings the selection back.
        self._setup(text="abcdef", cursor=4)
        _ed._editor_buffer_anchor = 1   # selection "bcd"
        self._type("X")
        self.assertEqual(_ed._editor_buffer_text, "aXef")
        self.assertIsNone(_ed._editor_buffer_anchor)
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "abcdef")
        self.assertEqual(_ed._editor_buffer_cursor, 4)
        self.assertEqual(_ed._editor_buffer_anchor, 1)

    # --- Stack-depth cap --------------------------------------------
    def test_undo_stack_respects_max_depth(self):
        self._setup()
        cap = profile_editor._EDITOR_UNDO_MAX_DEPTH
        # Each `_enter` is an atomic transaction → one stack entry per call.
        for _ in range(cap + 25):
            self._enter()
        self.assertLessEqual(len(_ed._editor_undo_stack), cap)


class TestEditorModeMoveLine(unittest.TestCase):
    """Phase E — Alt+↑/↓ swaps the cursor's logical line with its
    neighbour. The cursor follows the moved line with its column
    preserved (clamped to the new line's length). Newline structure is
    preserved by swapping line bodies in place, so moving the last
    line — which may lack a trailing `\\n` — does not corrupt the
    buffer. The move is recorded as a single atomic undo transaction
    and clears `_editor_pending_closers`."""

    def _setup(self, text="", cursor=0):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = cursor
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []
        _ed._editor_clipboard        = ""
        _ed._editor_undo_reset()

    # --- Basic swap behaviour --------------------------------------
    def test_move_up_swaps_lines(self):
        self._setup(text="aaa\nbbb\nccc\n", cursor=4)   # start of line 1
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa\nccc\n")

    def test_move_down_swaps_lines(self):
        self._setup(text="aaa\nbbb\nccc\n", cursor=0)   # start of line 0
        self.assertTrue(_ed._editor_buffer_move_line(+1))
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa\nccc\n")

    # --- No-op at the buffer ends ----------------------------------
    def test_move_up_at_top_is_noop(self):
        self._setup(text="aaa\nbbb\n", cursor=1)        # line 0
        self.assertFalse(_ed._editor_buffer_move_line(-1))
        self.assertEqual(_ed._editor_buffer_text, "aaa\nbbb\n")
        self.assertEqual(_ed._editor_buffer_cursor, 1)
        # No undo entry on a no-op move.
        self.assertEqual(_ed._editor_undo_stack, [])

    def test_move_down_at_bottom_is_noop(self):
        self._setup(text="aaa\nbbb", cursor=5)          # mid line 1 (last)
        self.assertFalse(_ed._editor_buffer_move_line(+1))
        self.assertEqual(_ed._editor_buffer_text, "aaa\nbbb")
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        self.assertEqual(_ed._editor_undo_stack, [])

    def test_single_line_buffer_both_directions_are_noop(self):
        self._setup(text="solo", cursor=2)
        self.assertFalse(_ed._editor_buffer_move_line(-1))
        self.assertFalse(_ed._editor_buffer_move_line(+1))
        self.assertEqual(_ed._editor_buffer_text, "solo")

    # --- Cursor + column follow the moved line ---------------------
    def test_cursor_follows_moved_line_up(self):
        # Column 2 on line 1; after move-up, cursor on line 0, col 2.
        self._setup(text="aaaa\nbbbb\ncccc\n", cursor=7)    # line 1, col 2
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        line, col = _ed._editor_buffer_cursor_to_line_col()
        self.assertEqual((line, col), (0, 2))

    def test_cursor_follows_moved_line_down(self):
        self._setup(text="aaaa\nbbbb\ncccc\n", cursor=2)    # line 0, col 2
        self.assertTrue(_ed._editor_buffer_move_line(+1))
        line, col = _ed._editor_buffer_cursor_to_line_col()
        self.assertEqual((line, col), (1, 2))

    def test_column_preserved_when_destination_line_is_shorter(self):
        # Cursor on a long line, neighbour is shorter. Since the moved
        # line's text travels with it, the cursor stays at the same
        # column without truncation — the move never widens the gap.
        self._setup(text="a\nbbbb\ncc\n", cursor=6)         # line 1, col 4
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        # Line 1 ("bbbb") is now at position 0; cursor still at col 4.
        self.assertEqual(_ed._editor_buffer_text, "bbbb\na\ncc\n")
        line, col = _ed._editor_buffer_cursor_to_line_col()
        self.assertEqual((line, col), (0, 4))

    # --- Trailing-newline edge -------------------------------------
    def test_last_line_without_trailing_newline_move_up(self):
        # The last line has no trailing `\n`. Move-up must preserve
        # the trailing-no-newline shape (still 2 lines, last has no nl).
        self._setup(text="aaa\nbbb", cursor=4)              # line 1, col 0
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa")
        self.assertEqual(_ed._editor_buffer_line_count(), 2)
        self.assertFalse(_ed._editor_buffer_text.endswith("\n"))
        line, col = _ed._editor_buffer_cursor_to_line_col()
        self.assertEqual((line, col), (0, 0))

    def test_move_down_into_last_line_position_preserves_shape(self):
        # Moving line 0 down so it becomes the (newline-less) last line.
        self._setup(text="aaa\nbbb", cursor=0)
        self.assertTrue(_ed._editor_buffer_move_line(+1))
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa")
        self.assertFalse(_ed._editor_buffer_text.endswith("\n"))
        line, col = _ed._editor_buffer_cursor_to_line_col()
        self.assertEqual((line, col), (1, 0))

    def test_move_last_line_up_then_down_round_trips(self):
        self._setup(text="aaa\nbbb", cursor=4)
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa")
        self.assertTrue(_ed._editor_buffer_move_line(+1))
        self.assertEqual(_ed._editor_buffer_text, "aaa\nbbb")

    # --- Undo: a move is one transaction ---------------------------
    def test_move_is_one_undo_transaction(self):
        self._setup(text="aaa\nbbb\nccc\n", cursor=4)
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa\nccc\n")
        _ed._editor_undo()
        self.assertEqual(_ed._editor_buffer_text, "aaa\nbbb\nccc\n")
        self.assertEqual(_ed._editor_buffer_cursor, 4)

    def test_move_round_trip_with_redo(self):
        self._setup(text="aaa\nbbb\nccc\n", cursor=4)
        _ed._editor_buffer_move_line(-1)
        _ed._editor_undo()
        _ed._editor_redo()
        self.assertEqual(_ed._editor_buffer_text, "bbb\naaa\nccc\n")

    def test_move_clears_pending_closers(self):
        self._setup(text="aaa\nbbb\nccc\n", cursor=4)
        _ed._editor_pending_closers = [10]
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        self.assertEqual(_ed._editor_pending_closers, [])

    def test_move_clears_active_selection(self):
        # Selection is dropped: multi-line block move is out of scope.
        self._setup(text="aaa\nbbb\nccc\n", cursor=4)
        _ed._editor_buffer_anchor = 6              # selection within line 1
        self.assertTrue(_ed._editor_buffer_move_line(-1))
        self.assertIsNone(_ed._editor_buffer_anchor)


class TestEditorModeLineColIndicator(unittest.TestCase):
    """Phase E — `Ln L, Col C` is 1-indexed and tracks the cursor."""

    def _setup(self, text="", cursor=0):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = cursor
        _ed._editor_buffer_anchor    = None

    def test_empty_buffer_reports_ln1_col1(self):
        self._setup()
        self.assertEqual(_ed._editor_line_col_text(),
                         "Ln 1, Col 1")

    def test_first_line_offset_reports_ln1_col_n_plus_1(self):
        # Cursor in the middle of the first line — col is 1-indexed.
        self._setup(text="abcdef", cursor=3)
        self.assertEqual(_ed._editor_line_col_text(),
                         "Ln 1, Col 4")

    def test_second_line_reports_ln2(self):
        self._setup(text="aaa\nbbb", cursor=5)            # line 1, col 1
        self.assertEqual(_ed._editor_line_col_text(),
                         "Ln 2, Col 2")

    def test_end_of_buffer_with_trailing_newline_reports_phantom_line(self):
        # Trailing `\n` creates a phantom empty line; cursor at end
        # lands on its start → 1-indexed Ln 3, Col 1.
        self._setup(text="aa\nbb\n", cursor=6)
        self.assertEqual(_ed._editor_line_col_text(),
                         "Ln 3, Col 1")

    def test_tracks_cursor_after_move(self):
        self._setup(text="aaa\nbbb\nccc\n", cursor=0)
        self.assertEqual(_ed._editor_line_col_text(),
                         "Ln 1, Col 1")
        _ed._editor_buffer_cursor = 4               # start of line 1
        self.assertEqual(_ed._editor_line_col_text(),
                         "Ln 2, Col 1")


# ---------------------------------------------------------------------------
# Phase F — double/triple-click word and line selection
# ---------------------------------------------------------------------------
# prompt_toolkit ships only MOUSE_DOWN/UP/MOVE; click counts are rebuilt by
# `_editor_click_tick` from a `(t, x, y)` history. Tests drive both the
# tracker and the wired-in row/field click handlers with a stub event +
# an injected monotonic clock.

import time  # noqa: E402  — used by tearDown to restore the real clock

from prompt_toolkit.data_structures import Point  # noqa: E402
from prompt_toolkit.mouse_events import MouseEventType  # noqa: E402


class _MouseEv:
    """Minimal prompt_toolkit MouseEvent stand-in: only `position` and
    `event_type` are read by the editor's click handlers."""

    def __init__(self, x, y, event_type=None):
        self.position   = Point(x=x, y=y)
        self.event_type = (event_type if event_type is not None
                           else MouseEventType.MOUSE_DOWN)


class _FakeClock:
    """Injectable monotonic clock — every read returns the current `t`."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _reset_click_state(clock=None):
    global _ed, _test_click_clock
    _test_click_clock = clock  # persist so _reset_editor_state can apply it
    if _ed is None:
        # Create a minimal editor instance so click state can be set.
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
    _ed._editor_click_count   = 0
    _ed._editor_click_last_t  = 0.0
    _ed._editor_click_last_xy = (-1, -1)
    if clock is not None:
        _ed._editor_click_now = clock


class TestEditorClickCount(unittest.TestCase):
    """`_editor_click_tick` cycles 1 → 2 → 3 → 1 within the click window
    at the same `(x, y)`; otherwise resets to 1."""

    def setUp(self):
        self.clock = _FakeClock()
        _reset_click_state(self.clock)

    def tearDown(self):
        _reset_click_state(time.monotonic)

    def test_first_click_is_one(self):
        self.assertEqual(
            _ed._editor_click_tick(_MouseEv(10, 5)), 1)

    def test_rapid_repeat_at_same_xy_increments(self):
        ev = _MouseEv(10, 5)
        self.assertEqual(_ed._editor_click_tick(ev), 1)
        self.clock.advance(0.1)
        self.assertEqual(_ed._editor_click_tick(ev), 2)
        self.clock.advance(0.1)
        self.assertEqual(_ed._editor_click_tick(ev), 3)

    def test_fourth_rapid_click_cycles_to_one(self):
        ev = _MouseEv(10, 5)
        for expected in (1, 2, 3, 1):
            self.assertEqual(_ed._editor_click_tick(ev), expected)
            self.clock.advance(0.1)

    def test_slow_second_click_resets_to_one(self):
        # A click outside the window resets the count even at the same xy.
        ev = _MouseEv(10, 5)
        self.assertEqual(_ed._editor_click_tick(ev), 1)
        self.clock.advance(0.5)                                  # > 0.4 s
        self.assertEqual(_ed._editor_click_tick(ev), 1)

    def test_different_xy_resets_to_one(self):
        self.assertEqual(_ed._editor_click_tick(_MouseEv(10, 5)), 1)
        self.clock.advance(0.1)
        self.assertEqual(_ed._editor_click_tick(_MouseEv(11, 5)), 1)
        self.clock.advance(0.1)
        self.assertEqual(_ed._editor_click_tick(_MouseEv(11, 6)), 1)


class TestEditorWordBounds(unittest.TestCase):
    """`_editor_word_bounds` classifies word-chars (alnum + `_`),
    whitespace (space/tab), and `other` (punctuation), and extends the
    run in both directions over the same class."""

    def test_word_char_run(self):
        self.assertEqual(_ed._editor_word_bounds("foo bar", 1),
                         (0, 3))

    def test_word_includes_underscore_and_digits(self):
        # "ab_42c" is one same-class run; whitespace at col 6 is the boundary.
        self.assertEqual(_ed._editor_word_bounds("ab_42c x", 3),
                         (0, 6))

    def test_whitespace_run(self):
        # Three spaces in a row → ws class.
        self.assertEqual(_ed._editor_word_bounds("a   b", 2),
                         (1, 4))

    def test_punctuation_run(self):
        # `!!!` is an "other" run that the boundary walk groups together.
        self.assertEqual(_ed._editor_word_bounds("hi!!!there", 3),
                         (2, 5))

    def test_punctuation_does_not_merge_with_word(self):
        # `,` is `other`; `word` is the surrounding letters. Class change
        # stops the walk.
        self.assertEqual(_ed._editor_word_bounds("hi,bye", 0),
                         (0, 2))
        self.assertEqual(_ed._editor_word_bounds("hi,bye", 2),
                         (2, 3))
        self.assertEqual(_ed._editor_word_bounds("hi,bye", 3),
                         (3, 6))

    def test_past_end_of_line_returns_none(self):
        self.assertIsNone(_ed._editor_word_bounds("hi", 2))
        self.assertIsNone(_ed._editor_word_bounds("", 0))

    # --- Regression: run boundary must be end-exclusive on the right ---
    # Earlier the visual highlight bled one cell past the run because the
    # cursor cell at `e` was painted alongside `[s, e)`. The bounds
    # contract is unchanged — `text[s:e]` is exactly the run.
    def test_word_run_inside_braces(self):
        self.assertEqual(_ed._editor_word_bounds("{word}", 1),
                         (1, 5))
        self.assertEqual(_ed._editor_word_bounds("{word}", 4),
                         (1, 5))

    def test_word_run_inside_quoted_dollar(self):
        # `"` and `$` are `other`; the word run is just `abody`.
        self.assertEqual(_ed._editor_word_bounds('"$abody"', 2),
                         (2, 7))
        self.assertEqual(_ed._editor_word_bounds('"$abody"', 6),
                         (2, 7))

    def test_word_run_before_trailing_space(self):
        # `{#if {` — clicking `if` stops at the space; the run is just
        # `if`, not `if ` (whitespace is a different class).
        self.assertEqual(_ed._editor_word_bounds("{#if {", 2),
                         (2, 4))
        self.assertEqual(_ed._editor_word_bounds("{#if {", 3),
                         (2, 4))

    def test_left_edge_stops_at_class_change(self):
        # `{` is `other`; the `word` run starts at the `w` — left walk
        # must not pull `{` into the run.
        self.assertEqual(_ed._editor_word_bounds("{word}", 1),
                         (1, 5))


class TestEditorBufferDoubleTripleClick(unittest.TestCase):
    """The editor-mode buffer row click handler: count 1 positions the
    cursor, count 2 selects the word, count 3 selects the logical line
    including its trailing `\\n`. Clipboard copy reads the selected
    text."""

    def setUp(self):
        self.clock = _FakeClock()
        _reset_click_state(self.clock)

    def tearDown(self):
        _reset_click_state(time.monotonic)

    def _setup_buffer(self, text):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = text
        _ed._editor_buffer_cursor    = 0
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None
        _ed._editor_pending_closers  = []
        _ed._editor_clipboard        = ""

    def _row_handler(self, logical_line, line_len):
        # content_x_offset=0 and wrap_start=0 — ev.position.x is then the
        # absolute column directly. line_len = len(line_text) for the
        # clicked logical line.
        return _ed._editor_buffer_row_click_handler(
            logical_line, wrap_start=0, content_x_offset=0,
            line_len=line_len)

    def test_single_click_positions_cursor_and_clears_selection(self):
        self._setup_buffer("hello world")
        h = self._row_handler(0, len("hello world"))
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_buffer_cursor, 2)
        self.assertIsNone(_ed._editor_buffer_anchor)

    def test_double_click_selects_word(self):
        self._setup_buffer("hello world")
        h = self._row_handler(0, len("hello world"))
        h(_MouseEv(2, 0))                      # count 1 at col 2
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))                      # count 2 at col 2
        self.assertEqual(_ed._editor_buffer_anchor, 0)
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        # Clipboard copy reads the selected word.
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "hello")

    def test_double_click_whitespace_selects_run(self):
        self._setup_buffer("a    b")
        h = self._row_handler(0, len("a    b"))
        h(_MouseEv(3, 0))
        self.clock.advance(0.1)
        h(_MouseEv(3, 0))
        self.assertEqual(_ed._editor_buffer_anchor, 1)
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "    ")

    def test_double_click_punctuation_selects_run(self):
        self._setup_buffer("hi!!!there")
        h = self._row_handler(0, len("hi!!!there"))
        h(_MouseEv(3, 0))
        self.clock.advance(0.1)
        h(_MouseEv(3, 0))
        self.assertEqual(_ed._editor_buffer_anchor, 2)
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "!!!")

    # Regression: the run's right edge must not absorb the first
    # out-of-class character. Earlier the cursor cell at `e` was painted
    # alongside `[s, e)`, so visually `{word}` looked like `word}`.
    def test_double_click_word_inside_braces(self):
        self._setup_buffer("{word}")
        h = self._row_handler(0, len("{word}"))
        h(_MouseEv(2, 0))                      # over `o` in `word`
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_buffer_anchor, 1)
        self.assertEqual(_ed._editor_buffer_cursor, 5)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "word")

    def test_double_click_word_after_dollar_quoted(self):
        self._setup_buffer('"$abody"')
        h = self._row_handler(0, len('"$abody"'))
        h(_MouseEv(3, 0))                      # over `b` in `abody`
        self.clock.advance(0.1)
        h(_MouseEv(3, 0))
        self.assertEqual(_ed._editor_buffer_anchor, 2)
        self.assertEqual(_ed._editor_buffer_cursor, 7)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "abody")

    def test_double_click_if_before_trailing_space(self):
        self._setup_buffer("{#if {")
        h = self._row_handler(0, len("{#if {"))
        h(_MouseEv(2, 0))                      # over `i` in `if`
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_buffer_anchor, 2)
        self.assertEqual(_ed._editor_buffer_cursor, 4)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "if")

    def test_double_click_does_not_cross_line_boundary(self):
        self._setup_buffer("foo\nbar")
        # Click on line 1, col 1 (the `a` in `bar`) — line 0's content is
        # exclusive of the trailing `\n`, so the word selection on line 1
        # must stay within line 1.
        h = self._row_handler(1, len("bar"))
        h(_MouseEv(1, 0))
        self.clock.advance(0.1)
        h(_MouseEv(1, 0))
        # Line 1 starts at offset 4 (after "foo\n"); word "bar" occupies
        # offsets 4..7.
        self.assertEqual(_ed._editor_buffer_anchor, 4)
        self.assertEqual(_ed._editor_buffer_cursor, 7)

    def test_double_click_past_eol_selects_nothing(self):
        self._setup_buffer("hi")
        h = self._row_handler(0, len("hi"))
        h(_MouseEv(10, 0))                     # well past EOL → clamps to 2
        self.clock.advance(0.1)
        h(_MouseEv(10, 0))
        self.assertIsNone(_ed._editor_buffer_anchor)
        self.assertEqual(_ed._editor_buffer_cursor, 2)

    def test_triple_click_selects_line_text_only(self):
        self._setup_buffer("foo\nbar\nbaz\n")
        h = self._row_handler(1, len("bar"))
        h(_MouseEv(1, 0))
        self.clock.advance(0.1)
        h(_MouseEv(1, 0))                      # count 2
        self.clock.advance(0.1)
        h(_MouseEv(1, 0))                      # count 3
        # Line 1 spans offsets 4..7 ("bar"); the `\n` at 7 is excluded
        # so the highlight stops at end-of-line.
        self.assertEqual(_ed._editor_buffer_anchor, 4)
        self.assertEqual(_ed._editor_buffer_cursor, 7)
        _ed._editor_buffer_copy()
        self.assertEqual(_ed._editor_clipboard, "bar")

    def test_triple_click_last_line_without_trailing_newline(self):
        self._setup_buffer("foo\nbar")
        h = self._row_handler(1, len("bar"))
        h(_MouseEv(1, 0))
        self.clock.advance(0.1)
        h(_MouseEv(1, 0))
        self.clock.advance(0.1)
        h(_MouseEv(1, 0))
        # Last line — selection is just the line text, no \n.
        self.assertEqual(_ed._editor_buffer_anchor, 4)
        self.assertEqual(_ed._editor_buffer_cursor, 7)

    def test_fourth_rapid_click_cycles_to_single_click(self):
        self._setup_buffer("hello world")
        h = self._row_handler(0, len("hello world"))
        for _ in range(4):
            h(_MouseEv(2, 0))
            self.clock.advance(0.1)
        # After the 4th rapid click we're back to count 1 — cursor lands,
        # selection cleared.
        self.assertIsNone(_ed._editor_buffer_anchor)
        self.assertEqual(_ed._editor_buffer_cursor, 2)

    def test_slow_second_click_does_not_upgrade_to_double(self):
        self._setup_buffer("hello world")
        h = self._row_handler(0, len("hello world"))
        h(_MouseEv(2, 0))
        self.clock.advance(0.5)                # > 0.4 s window
        h(_MouseEv(2, 0))
        self.assertIsNone(_ed._editor_buffer_anchor)


class TestEditorLitePatternDoubleTripleClick(unittest.TestCase):
    """Lite-mode Pattern field click handler: double-click selects the
    word; triple-click selects the whole single-line field."""

    def setUp(self):
        self.clock = _FakeClock()
        _reset_click_state(self.clock)

    def tearDown(self):
        _reset_click_state(time.monotonic)

    def _setup(self, pattern):
        prof, _src, _td = _make_profile(
            f"#alias {{{pattern}}} {{body}}\n")
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field    = 0
        _ed._editor_pattern_cursor  = 0
        _ed._editor_pattern_anchor  = None
        _ed._editor_clipboard       = ""

    def _handler(self, visible_col):
        return _ed._editor_make_field_click_handler(
            "pattern", visible_col=visible_col, line_idx=None, start=0)

    def test_single_click_positions_cursor_and_clears_selection(self):
        self._setup("hello world")
        self._handler(2)(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_pattern_cursor, 2)
        self.assertIsNone(_ed._editor_pattern_anchor)

    def test_double_click_selects_word(self):
        self._setup("hello world")
        h = self._handler(7)                    # col 7 → inside "world"
        h(_MouseEv(7, 0))                       # count 1
        self.clock.advance(0.1)
        h(_MouseEv(7, 0))                       # count 2
        self.assertEqual(_ed._editor_pattern_anchor, 6)
        self.assertEqual(_ed._editor_pattern_cursor, 11)
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "world")

    def test_double_click_punctuation_run(self):
        self._setup("ab!!cd")
        h = self._handler(3)
        h(_MouseEv(3, 0))
        self.clock.advance(0.1)
        h(_MouseEv(3, 0))
        self.assertEqual(_ed._editor_pattern_anchor, 2)
        self.assertEqual(_ed._editor_pattern_cursor, 4)

    # Regression: same-class run stops at the first out-of-class char on
    # the right — `word}` / `abody"` / `if ` were over-selecting. The
    # raw `#alias` source can't carry literal braces in the pattern, so
    # set them directly on the entry after a benign setup.
    def test_double_click_word_inside_braces(self):
        self._setup("placeholder")
        _ed._editor_current_entry().pattern = "{word}"
        h = self._handler(2)
        h(_MouseEv(2, 0))
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_pattern_anchor, 1)
        self.assertEqual(_ed._editor_pattern_cursor, 5)
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "word")

    def test_double_click_if_before_trailing_space(self):
        self._setup("placeholder")
        _ed._editor_current_entry().pattern = "{#if {"
        h = self._handler(2)
        h(_MouseEv(2, 0))
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_pattern_anchor, 2)
        self.assertEqual(_ed._editor_pattern_cursor, 4)
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "if")

    def test_double_click_past_end_selects_nothing(self):
        self._setup("hi")
        h = self._handler(5)
        h(_MouseEv(5, 0))
        self.clock.advance(0.1)
        h(_MouseEv(5, 0))
        self.assertIsNone(_ed._editor_pattern_anchor)
        self.assertEqual(_ed._editor_pattern_cursor, 2)

    def test_triple_click_selects_whole_field(self):
        self._setup("hello world")
        h = self._handler(7)
        h(_MouseEv(7, 0))
        self.clock.advance(0.1)
        h(_MouseEv(7, 0))
        self.clock.advance(0.1)
        h(_MouseEv(7, 0))
        self.assertEqual(_ed._editor_pattern_anchor, 0)
        self.assertEqual(_ed._editor_pattern_cursor,
                         len("hello world"))
        _ed._editor_pattern_copy()
        self.assertEqual(_ed._editor_clipboard, "hello world")

    def test_click_count_resets_outside_window(self):
        self._setup("hello world")
        h = self._handler(7)
        h(_MouseEv(7, 0))
        self.clock.advance(0.5)                 # outside window
        h(_MouseEv(7, 0))
        # No upgrade — still single click, no selection.
        self.assertIsNone(_ed._editor_pattern_anchor)


class TestEditorLiteBodyDoubleTripleClick(unittest.TestCase):
    """Lite-mode Body field click handler: double-click selects the
    word, triple-click selects the logical line (incl. trailing `\\n`
    except on the unterminated last line)."""

    def setUp(self):
        self.clock = _FakeClock()
        _reset_click_state(self.clock)

    def tearDown(self):
        _reset_click_state(time.monotonic)

    def _setup(self, body):
        # Use #action so a multi-line body is wrapped in `{...}` cleanly;
        # `\n` literal becomes a literal newline through profile_io.
        body_lit = body.replace("\n", "\\n")
        prof, _src, _td = _make_profile(
            f"#action {{pat}} {{{body_lit}}}\n")
        _reset_editor_state(prof, focus=2, kind="action")
        # Backfill the body — `\\n` in the source survives parsing as a
        # literal `\n` pair; replace with actual newlines so the Body
        # selection paths see a multi-line body.
        entry = _ed._editor_current_entry()
        entry.body = body
        _ed._editor_detail_field    = 1
        _ed._editor_body_line       = 0
        _ed._editor_body_col        = 0
        _ed._editor_body_anchor_line = None
        _ed._editor_body_anchor_col  = None
        _ed._editor_clipboard       = ""

    def _handler(self, visible_col, line_idx):
        return _ed._editor_make_field_click_handler(
            "body", visible_col=visible_col, line_idx=line_idx, start=0)

    def test_single_click_positions_cursor_and_clears_selection(self):
        self._setup("hello world")
        self._handler(2, 0)(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col, 2)
        self.assertIsNone(_ed._editor_body_anchor_line)

    def test_double_click_selects_word(self):
        self._setup("alpha bravo charlie")
        h = self._handler(8, 0)                 # col 8 → inside "bravo"
        h(_MouseEv(8, 0))
        self.clock.advance(0.1)
        h(_MouseEv(8, 0))
        self.assertEqual(_ed._editor_body_anchor_line, 0)
        self.assertEqual(_ed._editor_body_anchor_col, 6)
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col, 11)
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "bravo")

    def test_double_click_does_not_cross_line_boundary(self):
        self._setup("foo bar\nbaz qux")
        h = self._handler(0, 1)                 # col 0 of line 1 → "baz"
        h(_MouseEv(0, 1))
        self.clock.advance(0.1)
        h(_MouseEv(0, 1))
        self.assertEqual(
            (_ed._editor_body_anchor_line,
             _ed._editor_body_anchor_col), (1, 0))
        self.assertEqual(
            (_ed._editor_body_line, _ed._editor_body_col),
            (1, 3))

    def test_double_click_whitespace_run(self):
        self._setup("a   b")
        h = self._handler(2, 0)
        h(_MouseEv(2, 0))
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_body_anchor_col, 1)
        self.assertEqual(_ed._editor_body_col, 4)

    # Regression: run's right edge is end-exclusive — the cell at `e` is
    # NOT part of the selection, even when the cursor lands there. The
    # raw `#action` source can't carry literal braces in the body, so
    # set them directly on the entry after a benign setup.
    def test_double_click_word_inside_braces(self):
        self._setup("placeholder")
        _ed._editor_current_entry().body = "{word}"
        h = self._handler(2, 0)
        h(_MouseEv(2, 0))
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_body_anchor_col, 1)
        self.assertEqual(_ed._editor_body_col, 5)
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "word")

    def test_double_click_if_before_trailing_space(self):
        self._setup("placeholder")
        _ed._editor_current_entry().body = "{#if {"
        h = self._handler(2, 0)
        h(_MouseEv(2, 0))
        self.clock.advance(0.1)
        h(_MouseEv(2, 0))
        self.assertEqual(_ed._editor_body_anchor_col, 2)
        self.assertEqual(_ed._editor_body_col, 4)
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "if")

    def test_double_click_past_eol_selects_nothing(self):
        self._setup("hi\nyo")
        h = self._handler(10, 0)
        h(_MouseEv(10, 0))
        self.clock.advance(0.1)
        h(_MouseEv(10, 0))
        self.assertIsNone(_ed._editor_body_anchor_line)
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col, 2)

    def test_triple_click_selects_line_text_only(self):
        self._setup("foo\nbar\nbaz")
        h = self._handler(1, 1)                 # line 1 has a trailing \n
        h(_MouseEv(1, 1))
        self.clock.advance(0.1)
        h(_MouseEv(1, 1))
        self.clock.advance(0.1)
        h(_MouseEv(1, 1))
        # Anchor at (1, 0), cursor at (1, 3) — selection stops at the
        # last text char so the highlight doesn't bleed into line 2.
        self.assertEqual(
            (_ed._editor_body_anchor_line,
             _ed._editor_body_anchor_col), (1, 0))
        self.assertEqual(
            (_ed._editor_body_line, _ed._editor_body_col),
            (1, 3))
        _ed._editor_body_copy()
        self.assertEqual(_ed._editor_clipboard, "bar")

    def test_triple_click_last_line_without_newline(self):
        self._setup("foo\nbar")
        h = self._handler(1, 1)                 # last line, no trailing \n
        h(_MouseEv(1, 1))
        self.clock.advance(0.1)
        h(_MouseEv(1, 1))
        self.clock.advance(0.1)
        h(_MouseEv(1, 1))
        # Selection ends at line-end, no phantom newline crossed.
        self.assertEqual(
            (_ed._editor_body_anchor_line,
             _ed._editor_body_anchor_col), (1, 0))
        self.assertEqual(
            (_ed._editor_body_line, _ed._editor_body_col),
            (1, len("bar")))

    def test_fourth_rapid_click_cycles_to_single(self):
        self._setup("hello world")
        h = self._handler(2, 0)
        for _ in range(4):
            h(_MouseEv(2, 0))
            self.clock.advance(0.1)
        self.assertIsNone(_ed._editor_body_anchor_line)
        self.assertEqual(_ed._editor_body_col, 2)


class TestEditorWheelScroll(unittest.TestCase):
    """Phase G: mouse-wheel scrolling.

    Three independent surfaces — editor-mode buffer, lite-mode entry list,
    lite-mode Body field (when overflowing the 10-row cap) — each move
    ±3 rows/tick under SCROLL_UP / SCROLL_DOWN, clamp to their bounds,
    and never move their associated cursor. Wheel over a non-overflowing
    region is a no-op."""

    def setUp(self):
        # Fix terminal size so body_h / list_visible / max_scroll are
        # deterministic across host environments.
        self._real_get_terminal_size = launcher.shutil.get_terminal_size
        launcher.shutil.get_terminal_size = lambda: os.terminal_size((80, 30))

    def tearDown(self):
        launcher.shutil.get_terminal_size = self._real_get_terminal_size

    # ------------------------------------------------------------------
    # Editor-mode buffer
    # ------------------------------------------------------------------
    def _setup_buffer(self, line_count):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode            = "editor"
        _ed._editor_toggle_focused  = False
        _ed._editor_buffer_text     = "\n".join(
            f"line{i}" for i in range(line_count))
        _ed._editor_buffer_cursor   = 0
        _ed._editor_buffer_scroll   = 0
        _ed._editor_buffer_anchor   = None

    def _row_handler(self):
        # Per-row click handler used by editor-mode buffer rows. Args mirror
        # the live render call site; for wheel events only the event_type
        # branch is exercised.
        return _ed._editor_buffer_row_click_handler(
            logical_line=0, wrap_start=0, content_x_offset=0, line_len=5)

    def test_buffer_wheel_down_scrolls_by_three(self):
        self._setup_buffer(50)
        h = self._row_handler()
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 3)

    def test_buffer_wheel_up_scrolls_by_three(self):
        self._setup_buffer(50)
        _ed._editor_buffer_scroll = 10
        h = self._row_handler()
        h(_MouseEv(0, 0, MouseEventType.SCROLL_UP))
        self.assertEqual(_ed._editor_buffer_scroll, 7)

    def test_buffer_wheel_clamps_at_top(self):
        self._setup_buffer(50)
        _ed._editor_buffer_scroll = 2
        h = self._row_handler()
        h(_MouseEv(0, 0, MouseEventType.SCROLL_UP))
        self.assertEqual(_ed._editor_buffer_scroll, 0)
        h(_MouseEv(0, 0, MouseEventType.SCROLL_UP))
        self.assertEqual(_ed._editor_buffer_scroll, 0)

    def test_buffer_wheel_clamps_at_bottom(self):
        self._setup_buffer(50)
        cols = launcher._term_cols()
        _wrap_w, total, _l2v = _ed._editor_buffer_visual_layout(cols)
        viewport_h = _ed._editor_body_h()
        mx = max(0, total - viewport_h)
        _ed._editor_buffer_scroll = mx - 1
        h = self._row_handler()
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, mx)
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, mx)

    def test_buffer_wheel_does_not_move_cursor(self):
        self._setup_buffer(50)
        _ed._editor_buffer_cursor = 7
        h = self._row_handler()
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 6)
        self.assertEqual(_ed._editor_buffer_cursor, 7)

    def test_buffer_wheel_noop_when_no_overflow(self):
        # 3 short lines and a viewport ≥ 15 rows → nothing to scroll.
        self._setup_buffer(3)
        h = self._row_handler()
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 0)

    def test_buffer_scrollbar_handler_also_scrolls(self):
        # The scrollbar cell handler must accept SCROLL events too — wheel
        # on the bar should behave the same as wheel on the content area.
        self._setup_buffer(50)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=0, sb_top=0, sb_thumb_h=2, total=50, viewport_h=15)
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 3)

    def test_buffer_chrome_wheel_handler_scrolls(self):
        # The line-number cells route wheel events through the dedicated
        # chrome handler.
        self._setup_buffer(50)
        _ed._editor_buffer_chrome_wheel_handler(
            _MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 3)

    # ------------------------------------------------------------------
    # Lite-mode entry list
    # ------------------------------------------------------------------
    def _setup_list(self, n_entries):
        body = "\n".join(
            f"#alias {{a{i:02d}}} {{cmd{i}}}" for i in range(n_entries))
        prof, _src, _td = _make_profile(body)
        _reset_editor_state(prof, focus=1)
        _ed._editor_list_sb = launcher.Scrollbar(
            _ed._profile_editor_display_total(),
            _ed._editor_list_visible(),
            _ed._editor_list_visible(),
        )
        _ed._editor_list_scroll = 0
        _ed._editor_list_cursor = 0
        return prof

    def test_list_wheel_down_scrolls_by_three(self):
        self._setup_list(60)
        _ed._editor_list_wheel(3)
        self.assertEqual(_ed._editor_list_scroll, 3)
        self.assertEqual(_ed._editor_list_sb.scroll_offset, 3)

    def test_list_wheel_up_clamps_at_zero(self):
        self._setup_list(60)
        _ed._editor_list_scroll = 2
        _ed._editor_list_sb.scroll_to(2)
        _ed._editor_list_wheel(-3)
        self.assertEqual(_ed._editor_list_scroll, 0)

    def test_list_wheel_clamps_at_bottom(self):
        self._setup_list(60)
        total = _ed._profile_editor_display_total()
        visible = _ed._editor_list_visible()
        mx = max(0, total - visible)
        _ed._editor_list_scroll = mx - 1
        _ed._editor_list_sb.scroll_to(mx - 1)
        _ed._editor_list_wheel(3)
        self.assertEqual(_ed._editor_list_scroll, mx)
        _ed._editor_list_wheel(3)
        self.assertEqual(_ed._editor_list_scroll, mx)

    def test_list_wheel_does_not_move_cursor(self):
        self._setup_list(60)
        _ed._editor_list_cursor = 4
        _ed._editor_list_wheel(3)
        _ed._editor_list_wheel(3)
        self.assertEqual(_ed._editor_list_scroll, 6)
        self.assertEqual(_ed._editor_list_cursor, 4)

    def test_list_wheel_noop_when_no_overflow(self):
        # Two entries + sentinel → 3 rows, list_visible is ~28. No scroll.
        self._setup_list(2)
        _ed._editor_list_wheel(3)
        self.assertEqual(_ed._editor_list_scroll, 0)

    # ------------------------------------------------------------------
    # Lite-mode Body field
    # ------------------------------------------------------------------
    def _setup_body(self, body_line_count):
        prof, _src, _td = _make_profile("#alias {p} {one-liner}\n")
        # Mutate the entry's body to span `body_line_count` lines. Going
        # through the source-parse path would require literal newlines
        # inside the brace group, which is fiddlier; setting the body
        # directly is the same surface the live editor mutates.
        entry = prof.entries_of("alias")[0]
        entry.body = "\n".join(f"line{i}" for i in range(body_line_count))
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1     # body field
        _ed._editor_body_scroll  = 0
        _ed._editor_body_line    = 0
        _ed._editor_body_col     = 0
        return prof

    def test_body_wheel_down_scrolls_by_three(self):
        self._setup_body(20)
        _ed._editor_body_wheel(3)
        self.assertEqual(_ed._editor_body_scroll, 3)

    def test_body_wheel_up_clamps_at_zero(self):
        self._setup_body(20)
        _ed._editor_body_scroll = 2
        _ed._editor_body_wheel(-3)
        self.assertEqual(_ed._editor_body_scroll, 0)

    def test_body_wheel_clamps_at_bottom(self):
        self._setup_body(20)
        mx = 20 - profile_editor._EDITOR_BODY_CAP_ROWS    # 10
        _ed._editor_body_scroll = mx - 1
        _ed._editor_body_wheel(3)
        self.assertEqual(_ed._editor_body_scroll, mx)
        _ed._editor_body_wheel(3)
        self.assertEqual(_ed._editor_body_scroll, mx)

    def test_body_wheel_noop_when_no_overflow(self):
        self._setup_body(5)
        _ed._editor_body_wheel(3)
        self.assertEqual(_ed._editor_body_scroll, 0)

    def test_body_wheel_does_not_move_body_cursor(self):
        self._setup_body(20)
        _ed._editor_body_line = 4
        _ed._editor_body_col  = 2
        _ed._editor_body_wheel(3)
        _ed._editor_body_wheel(3)
        self.assertEqual(_ed._editor_body_scroll, 6)
        self.assertEqual(_ed._editor_body_line, 4)
        self.assertEqual(_ed._editor_body_col, 2)

    def test_body_field_click_handler_routes_wheel(self):
        # Per-cell body handler must forward SCROLL_UP / SCROLL_DOWN to
        # the body wheel helper.
        self._setup_body(20)
        h = _ed._editor_make_field_click_handler(
            "body", visible_col=0, line_idx=0, start=0)
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_body_scroll, 3)
        self.assertEqual(_ed._editor_body_line, 0)
        self.assertEqual(_ed._editor_body_col, 0)

    def test_body_focus_handler_routes_wheel(self):
        # Wheel landing on the body's chrome (label, top/bottom border, or
        # the vertical `│` bars) routes through the focus handler.
        self._setup_body(20)
        h = _ed._editor_make_field_focus_handler("body")
        h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        self.assertEqual(_ed._editor_body_scroll, 3)

    def test_pattern_field_click_handler_ignores_wheel(self):
        # Pattern is single-line: wheel must NOT scroll the body.
        self._setup_body(20)
        h = _ed._editor_make_field_click_handler(
            "pattern", visible_col=0, line_idx=None, start=0)
        result = h(_MouseEv(0, 0, MouseEventType.SCROLL_DOWN))
        # Handler returns NotImplemented for unhandled events so the parent
        # control falls through; body scroll must not have moved.
        self.assertIs(result, NotImplemented)
        self.assertEqual(_ed._editor_body_scroll, 0)


class TestEditorScrollbarAutoScroll(unittest.TestCase):
    """Phase H: click-and-hold auto-scroll on the three profile-editor
    scrollbars (Editor-mode buffer, lite-mode entry list, lite-mode Body).

    Auto-scroll is bounded by a TARGET (the held track row) and
    self-terminates once the thumb covers that row or no further scroll
    is possible — see ADR 0092. Tests drive `_autoscroll_tick` directly
    so they exercise the timer mechanism without sleeping for the
    initial delay or repeat interval."""

    def setUp(self):
        self._real_get_terminal_size = launcher.shutil.get_terminal_size
        launcher.shutil.get_terminal_size = lambda: os.terminal_size((80, 30))
        _ed._autoscroll_disarm()

    def tearDown(self):
        launcher.shutil.get_terminal_size = self._real_get_terminal_size
        _ed._autoscroll_disarm()

    # The arm path schedules a real asyncio timer when `_app_loop` is
    # live; in unit tests it is None, so `_autoscroll_handle` stays None
    # and tests can call `_autoscroll_tick` directly with no setup.

    # ------------------------------------------------------------------
    # Editor-mode buffer scrollbar
    # ------------------------------------------------------------------
    def _setup_buffer(self, line_count):
        prof, _src, _td = _make_profile("")
        _reset_editor_state(prof)
        _ed._editor_mode             = "editor"
        _ed._editor_toggle_focused   = False
        _ed._editor_buffer_text      = "\n".join(
            f"line{i}" for i in range(line_count))
        _ed._editor_buffer_cursor    = 0
        _ed._editor_buffer_scroll    = 0
        _ed._editor_buffer_anchor    = None

    def test_buffer_arm_performs_immediate_step(self):
        # MOUSE_DOWN below the thumb pages by one viewport AND arms.
        self._setup_buffer(100)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=5, total=100, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 24)
        self.assertTrue(_ed._autoscroll_armed())

    def test_buffer_tick_pages_toward_target(self):
        # Each tick pages one viewport toward the held row.
        self._setup_buffer(200)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=3, total=200, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 24)
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_buffer_scroll, 48)
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_buffer_scroll, 72)

    def test_buffer_tick_self_terminates_at_target_without_mouseup(self):
        # Holding the bottom row pages until the thumb covers it, then
        # the step_fn returns False and disarms — MOUSE_UP not needed.
        self._setup_buffer(100)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=6, total=100, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        for _ in range(20):
            if not _ed._autoscroll_armed():
                break
            _ed._autoscroll_tick()
        self.assertFalse(_ed._autoscroll_armed())
        # body_h=24, total_visual=100 → max_scroll=76.
        self.assertEqual(_ed._editor_buffer_scroll, 76)

    def test_buffer_tick_clamps_at_bottom_then_disarms(self):
        # Small buffer: one immediate step reaches max_scroll; the next
        # tick sees no further movement possible and disarms.
        self._setup_buffer(30)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=18, total=30, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        # max_scroll = 30 - 24 = 6.
        self.assertEqual(_ed._editor_buffer_scroll, 6)
        _ed._autoscroll_tick()
        self.assertFalse(_ed._autoscroll_armed())
        self.assertEqual(_ed._editor_buffer_scroll, 6)

    def test_buffer_mouseup_disarms_early(self):
        self._setup_buffer(100)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=5, total=100, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        self.assertTrue(_ed._autoscroll_armed())
        h(_MouseEv(0, 0, MouseEventType.MOUSE_UP))
        self.assertFalse(_ed._autoscroll_armed())

    def test_buffer_disarm_explicit_cancels_further_ticks(self):
        # _autoscroll_disarm() prevents subsequent ticks from running.
        self._setup_buffer(100)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=5, total=100, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        _ed._autoscroll_disarm()
        before = _ed._editor_buffer_scroll
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_buffer_scroll, before)

    def test_buffer_thumb_click_does_not_arm(self):
        # Click on the thumb is a no-op and must not arm auto-scroll.
        self._setup_buffer(100)
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=2, sb_top=0, sb_thumb_h=5, total=100, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        self.assertEqual(_ed._editor_buffer_scroll, 0)
        self.assertFalse(_ed._autoscroll_armed())

    def test_buffer_autoscroll_tick_does_not_move_cursor(self):
        # Phase G decoupling: scrollbar moves only the viewport, not the
        # cursor. Auto-scroll ticks inherit that — `_editor_buffer_cursor`
        # is untouched even after several ticks pull the viewport away.
        self._setup_buffer(100)
        _ed._editor_buffer_cursor = 7
        h = _ed._editor_buffer_scrollbar_click_handler(
            vrow=23, sb_top=0, sb_thumb_h=5, total=100, viewport_h=24)
        h(_MouseEv(0, 0, MouseEventType.MOUSE_DOWN))
        _ed._autoscroll_tick()
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_buffer_cursor, 7)

    # ------------------------------------------------------------------
    # Lite-mode entry-list scrollbar
    # ------------------------------------------------------------------
    def _setup_list(self, n_entries):
        body = "\n".join(
            f"#alias {{a{i:02d}}} {{cmd{i}}}" for i in range(n_entries))
        prof, _src, _td = _make_profile(body)
        _reset_editor_state(prof, focus=1)
        _ed._editor_list_sb = launcher.Scrollbar(
            _ed._profile_editor_display_total(),
            _ed._editor_list_visible(),
            _ed._editor_list_visible(),
        )
        _ed._editor_list_scroll = 0
        _ed._editor_list_cursor = 0

    def test_list_step_pages_toward_target_and_self_terminates(self):
        # Drive the list step_fn directly: arm with the bottom row of the
        # bar as the held target. Each tick pages by `_editor_list_visible`
        # toward it; the loop stops once the thumb covers the target row.
        self._setup_list(100)
        visible = _ed._editor_list_visible()
        total = _ed._profile_editor_display_total()
        max_scroll = max(0, total - visible)
        target = visible - 1   # bottom track row
        _ed._autoscroll_arm(
            _ed._editor_list_autoscroll_step, target)
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_list_scroll, visible)
        for _ in range(20):
            if not _ed._autoscroll_armed():
                break
            _ed._autoscroll_tick()
        self.assertFalse(_ed._autoscroll_armed())
        self.assertEqual(_ed._editor_list_scroll, max_scroll)

    def test_list_autoscroll_tick_does_not_move_cursor(self):
        self._setup_list(100)
        _ed._editor_list_cursor = 3
        visible = _ed._editor_list_visible()
        _ed._autoscroll_arm(
            _ed._editor_list_autoscroll_step, visible - 1)
        _ed._autoscroll_tick()
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_list_cursor, 3)

    # ------------------------------------------------------------------
    # Lite-mode Body-field scrollbar
    # ------------------------------------------------------------------
    def _setup_body(self, body_line_count):
        prof, _src, _td = _make_profile("#alias {p} {one-liner}\n")
        entry = prof.entries_of("alias")[0]
        entry.body = "\n".join(f"line{i}" for i in range(body_line_count))
        _reset_editor_state(prof, focus=2)
        _ed._editor_detail_field = 1
        _ed._editor_body_scroll  = 0
        _ed._editor_body_line    = 0
        _ed._editor_body_col     = 0

    def test_body_step_pages_toward_target_and_self_terminates(self):
        # cap=10 → page-step is 10 lines. Hold the bottom track row;
        # each tick pages by cap until the thumb covers it.
        self._setup_body(50)
        cap = profile_editor._EDITOR_BODY_CAP_ROWS
        _ed._autoscroll_arm(
            _ed._editor_body_autoscroll_step, cap - 1)
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_body_scroll, cap)
        for _ in range(20):
            if not _ed._autoscroll_armed():
                break
            _ed._autoscroll_tick()
        self.assertFalse(_ed._autoscroll_armed())
        self.assertEqual(_ed._editor_body_scroll, 50 - cap)

    def test_body_step_noop_when_no_overflow(self):
        # 5 lines fits inside the cap → step_fn returns False on first tick.
        self._setup_body(5)
        _ed._autoscroll_arm(
            _ed._editor_body_autoscroll_step,
            profile_editor._EDITOR_BODY_CAP_ROWS - 1)
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_body_scroll, 0)
        self.assertFalse(_ed._autoscroll_armed())

    def test_body_autoscroll_tick_does_not_move_cursor(self):
        self._setup_body(50)
        _ed._editor_body_line = 4
        _ed._editor_body_col  = 2
        _ed._autoscroll_arm(
            _ed._editor_body_autoscroll_step,
            profile_editor._EDITOR_BODY_CAP_ROWS - 1)
        _ed._autoscroll_tick()
        _ed._autoscroll_tick()
        self.assertEqual(_ed._editor_body_line, 4)
        self.assertEqual(_ed._editor_body_col, 2)


if __name__ == "__main__":
    unittest.main()
