# 0091 — Profile editor undo: coalescing policy

**Status:** Accepted
**Date:** 2026-05-22

## Context

Phase D of the profile-editor rework added undo / redo to the
Editor-mode text buffer. The data model is the simplest thing that
could work: each undo entry is a whole-buffer snapshot
`(text, cursor, anchor)`. Python strings are immutable, so a snapshot
stores a reference — not a copy — and a few-KB profile's worth of
history is cheap. Two module-level stacks (`_editor_undo_stack`,
`_editor_redo_stack`); the undo stack capped at 200 entries with the
oldest dropped on overflow. Stacks reset on `_enter_profile_editor`
and on every lite ↔ editor flip — undo history never survives leaving
the editor or a mode change.

The interesting question is **what counts as one undoable unit**.
Whole-snapshot history means every keystroke could push a fresh
entry — but that turns a one-undo "rewind the word I just typed" into
five undos, which is the wrong UX. We want a word's worth of typing
to undo in one step, while keeping paste / cut / auto-close as their
own atomic units.

## Decision

**Coalesce consecutive single-character inserts into one undo
transaction. Coalesce consecutive Backspace / Delete keystrokes the
same way. Force a boundary on every other action.**

A boundary (the current run ends, the next edit pushes a fresh
pre-edit snapshot) is forced by any of:

- a newline insert (Enter is its own undoable unit);
- any cursor move — arrow, Home / End, PgUp / PgDn, mouse click;
- switching edit kind — an insert run followed by a delete, or a
  delete run followed by an insert;
- paste (`c-v` or bracketed paste), cut (`c-x`), auto-close `{}`,
  `}` overtype, pair-delete (each its own unit);
- a focus change or lite ↔ editor mode flip.

Implementation: a single `_editor_undo_record(kind)` helper called
before any buffer mutation. `kind ∈ {"insert", "delete", None}`. When
`kind` matches the current open run, no push happens (the pre-edit
snapshot is already on the stack and a redo-clear has already fired).
Otherwise a fresh snapshot is pushed, the redo stack is cleared, and
the run is either marked open (for `"insert"` / `"delete"`) or left
closed (for `None`, the atomic kinds). Cursor-move handlers and
focus-change handlers call `_editor_undo_close()` to force a boundary
without pushing.

## Alternatives considered

### A wall-clock typing timeout (rejected)

"Coalesce keystrokes that arrive within 500 ms of each other." This
is what some text editors do. Rejected because:

- **Non-deterministic.** A test that types four characters needs
  either to sleep between them (slow, fragile) or to mock the clock
  (fiddly). The kind/flag rule has neither problem — its boundary
  behaviour is a pure function of the keystroke sequence.
- **User-surprising under load.** A momentary stall (GC pause, scroll
  blocking on a redraw) silently fragments what should have been one
  undo step. The kind/flag rule's boundaries are explicit and
  predictable — the user can rely on "I moved the cursor, so the
  next undo will stop there."

### Per-character undo with no coalescing (rejected)

Push every keystroke. Simple to implement, but five undos to delete
a five-character word is the wrong UX for a TUI editor. The clean
test-friendliness of the no-coalesce design didn't outweigh the user
cost.

### Diff-based undo (rejected)

Store only the delta (`(start, removed_text, inserted_text)`) per
edit, replay forward / backward. Lower memory, more complexity. The
whole-snapshot approach is simpler and the memory cost is trivial
for a profile file (a few KB × 200 entries = ~1 MB worst case, in
practice far less because Python interns identical strings).

## Consequences

- Typing a word and pressing `c-z` removes the whole word in one
  step; `c-y` restores it. A cursor move splits the typing run, so
  `c-z` then undoes only the text typed after the move.
- Paste, cut, an auto-close `{}` insertion, a `}` overtype, and a
  pair-delete each form their own undoable unit.
- A fresh edit after some undos clears the redo stack — the future
  the user didn't take is gone. Standard editor semantics.
- Undo state is wiped on `_enter_profile_editor` and on every
  lite ↔ editor flip. Lite-mode edits do not flow into the editor's
  undo history (Phase D scope is the editor buffer only; a possible
  later D2 would cover the lite Pattern / Body fields).
- Undo and redo close any open coalescing run, clear
  `_editor_pending_closers` (offsets aren't valid against the
  restored text), and scroll the cursor into view.
- The kind/flag rule is unit-testable end-to-end:
  `test_profile_editor.py:TestEditorModeUndoRedo` covers coalesced
  typing, cursor-move and insert↔delete boundaries, the atomic
  units, redo, redo-cleared-by-new-edit, empty-stack no-ops, and
  the stack reset on flip.

## Future work

A D2 phase could extend snapshot-based undo to the Lite-mode Pattern
and Body fields. The model is different there — each field has its
own cursor / anchor and the body is a list of lines, not a single
string — so the helper API would need a per-field flavour. The
coalescing policy itself transfers unchanged: same kind/flag
boundaries, same atomic units, same no-wall-clock invariant.
