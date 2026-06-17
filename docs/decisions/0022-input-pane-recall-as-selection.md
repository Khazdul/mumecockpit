# ADR 0022 — Input Pane: Recall State as Native Selection

**Status:** Accepted  
**Date:** 2026-04-29

## Context

The input pane had two parallel visual languages for "this text is
selected / ready to be overwritten":

1. A custom `HighlightRecalled` processor that rendered the buffer
   black-on-white when an `is_recalled` flag was set.
2. prompt_toolkit's own `SelectionState`, used when the player made
   an ad-hoc Shift+arrow selection.

These two mechanisms were independent and visually inconsistent.
The custom highlight showed inverted colours; native selection showed
whatever the terminal uses for selected text. Both could exist
simultaneously with no reconciliation.

Additionally, Ctrl+C raised `KeyboardInterrupt` and exited the app —
a crash on a key players reflexively reach for. Ctrl+X and Ctrl+V were
forwarded to tt++, where they had no bindings, and were effectively
dead keys.

## Decision

**Model recall state as prompt_toolkit's whole-buffer selection.**

A buffer is "recalled" when `buf.selection_state` spans 0..len(text).
There is no separate `is_recalled` flag, no `HighlightRecalled`
processor, and no per-key printable/backspace/arrow handlers to clear
the flag. prompt_toolkit's default key handling replaces/deletes/deselects
as expected.

Two buffer-set helpers replace the old single helper:
- `_set_buffer_text(buf, text)` — sets text, no selection (draft restore,
  clear).
- `_set_buffer_text_selected(buf, text)` — sets text and selects the whole
  buffer via `SelectionState` (Enter refill, history nav, Shift+Home/End,
  Ctrl+A).

The `_is_fully_selected(buf)` predicate replaces every `is_recalled` read.

**Bind Ctrl+C / Ctrl+X / Ctrl+V to clipboard operations.**

- Ctrl+C copies the current selection via OSC 52 (no-op if no selection).
  Does not exit the pane.
- Ctrl+X cuts (copy + delete selection). No-op if no selection.
- Ctrl+V pastes via `pyperclip`, replacing the current selection if any.
- Ctrl+D is bound as a no-op (prevent EOFError exit).
- Ctrl+X and Ctrl+V are removed from `FORWARDED_KEYS`.

## Trade-offs

**Accepted:**
- Less style control over recall highlight — appearance is whatever the
  terminal renders for selected text, not a custom colour. This is
  actually a benefit: Shift+arrow selection, history nav, and post-Enter
  refill all look identical, which is visually coherent.
- `pyperclip` added as a dependency for the paste read path. On WSL it
  spawns `powershell.exe` on first use (~200–500 ms). Acceptable for a
  one-off paste action.

**Gained:**
- Ctrl+C copies the recalled (selected) buffer immediately after Enter —
  no extra step to grab the just-sent command.
- Shift+arrow selection and the recall state are the same thing; no
  split-state confusion.
- ~80 lines removed: `HighlightRecalled`, `is_recalled`, `_exit_recall_state`,
  the `_PRINTABLE` loop, and the four per-key arrow/backspace/delete handlers.

## Rejected alternative

**Keep `HighlightRecalled` and add Ctrl+Shift+C/X/V for clipboard.**

Rejected because:
- Ctrl+C reflexively crashing the input pane was unacceptable regardless
  of whether clipboard was added.
- Two visual languages (custom colour for recall, terminal colour for
  shift-select) would persist.
- Ctrl+Shift+C is not reliably distinguishable from Ctrl+C in many
  terminals (modifier encoding varies by terminal).

## Consequences

- `bridge/input_pane.py`: no `HighlightRecalled`, no `is_recalled`,
  no `_exit_recall_state`. Printable char and arrow key default handling
  is delegated to prompt_toolkit.
- `docs/input-pane.md`: "Recall highlighting" section rewritten as
  "Recall state = whole-buffer selection"; clipboard section added;
  forwarded Ctrl+letter list updated.
- `pyperclip` must be installed alongside `prompt_toolkit`.

## Amendment — 2026-06-17 (Shift+Home/End now cursor-relative)

The Decision's grouping of Shift+Home/End with Ctrl+A as whole-buffer
recall-entry (the `_set_buffer_text_selected` driver list) is superseded.
Shift+Home / Shift+Up now select cursor→start, and Shift+End / Shift+Down
select cursor→end — a partial selection from the current cursor position,
recomputed on each press. There is no multi-step extension: extending a
selection one character at a time stays on native Shift+Left / Shift+Right.
Ctrl+A retains whole-buffer select, and recall state (whole-buffer selection)
is now entered only by the post-Enter refill, history navigation, and Ctrl+A.

Rationale: the select-all-on-Shift+Home behaviour was non-standard;
cursor-relative selection matches conventional editors.

See `docs/input-pane.md` ("Recall state = whole-buffer selection" section)
for the current authority on Shift-selection semantics. The rest of this ADR
— recall state modelled as native `SelectionState`, and the Ctrl+C / X / V
clipboard bindings — stands.
