# 0040 — Comm pane owns line wrapping

**Status:** Accepted
**Date:** 2026-05-04

## Context

`bridge/comm_pane.py` previously set `wrap_lines=True` on the list `Window`,
delegating line wrapping to prompt_toolkit. prompt_toolkit's built-in wrap is a
char-break: it splits at exactly the window width with no regard for word
boundaries. This produced mid-word breaks on every wrapped line (e.g.
`"interesting"` broken as `"interes"` / `"ting"`), which is visually jarring for
chat content.

prompt_toolkit provides no word-wrap option for `FormattedTextControl`.

A secondary problem: `_row_count` estimated the wrapped row count via
`ceil(visible_width / cols)`. This is the same arithmetic prompt_toolkit uses for
char-wrap, so it was consistent with `wrap_lines=True`. Switching to word-wrap
would invalidate that estimate unless `_row_count` is updated to match — if the
two diverge, scroll math (max_offset computation, sticky-bottom, backward-walk
filling) counts the wrong number of rows and the view jumps or leaves blank rows.

## Decision

The renderer owns wrapping via two new helpers:

- `_wrap_fragments(fragments, cols)` — greedy word-boundary wrap of a
  `(style, text)` fragment list into a list of display rows. Each row is itself
  a list of `(style, text)` fragments.
- `_entry_to_rows(entry, cols, channels)` — calls the appropriate render
  function (`_render_quoted_row` or `_render_action_row`) and passes the
  resulting fragments through `_wrap_fragments`. This is the single authority
  for how an entry is laid out.

`_row_count` is rewritten to `return len(_entry_to_rows(...))`. It no longer
contains an independent width-counting path.

`_list_text` calls `_entry_to_rows` per visible entry and joins rows with `\n`
exactly as it previously joined entries. The backward-walk filling loop and
clip-top semantics are structurally unchanged.

`wrap_lines=False` is set on the list `Window`. prompt_toolkit no longer wraps;
every `\n` in the fragment stream produces exactly one display row.

**`_wrap_fragments` algorithm:**

1. `_tokenize_fragments` splits the fragment stream into alternating whitespace
   and non-whitespace tokens, spanning fragment boundaries while preserving
   per-character style. ANSI SGR sequences are zero-width and attached to the
   preceding visible-char accumulator.
2. Greedy fill: each non-whitespace token (with its preceding whitespace, if the
   line is non-empty) is placed on the current line when it fits. When it does
   not fit and the line is non-empty, the pending whitespace is dropped and a new
   line is started (R4 — no leading whitespace on continuation rows).
3. Long-word fallback: if a single non-whitespace token exceeds `cols`, it is
   hard-broken at exactly `cols` visible characters per row, with the original
   style preserved across the break.
4. ANSI SGR sequences inside fragment text are measured as zero-width via the
   existing `_SGR_RE` pattern and kept verbatim in the emitted output, so styles
   survive wrap-induced row breaks.

## Consequences

- **Word-boundary breaks.** No more mid-word splits for normal chat content.
- **Scroll math is exact.** `_row_count` and the renderer share the same wrap
  logic; max_offset, sticky-bottom, and backward-walk filling are all consistent.
- **ANSI-aware width measurement is our responsibility.** `_visual_len` and
  `_split_at_visual` strip/respect `_SGR_RE` for all width calculations.
- **Fragment styles survive splits.** When a hard-break cuts a fragment, the two
  halves keep the original style. When a word-break splits a token that spans
  multiple input fragments, each sub-fragment retains its source style.
- **Long-word fallback is a hard char-break.** A single word wider than `cols`
  is broken at exactly `cols` visible chars per row. This matches the behaviour
  of the previous char-wrap for the pathological case, and is the only sensible
  option when no space exists.
- **R4 is a guaranteed property of `_wrap_fragments`.** Continuation rows never
  begin with a whitespace fragment; the pending whitespace is dropped on wrap.

## Alternatives considered

**Keep `wrap_lines=True` (char-wrap).** Rejected — produces mid-word breaks that
are visually unacceptable for chat content.

**Maintain a separate `_row_count` approximating prompt_toolkit's char-wrap.**
Rejected — any divergence between the count and the actual rendered layout causes
scroll math to produce incorrect offsets. A single delegating path eliminates the
drift risk entirely.

**Implement word-wrap inside prompt_toolkit via a custom control.** Rejected —
substantially more complex integration surface; the fragment-list model of
`FormattedTextControl` is already the right interface for our needs.
