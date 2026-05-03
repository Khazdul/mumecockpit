# 0033 — Buffs pane uses prompt_toolkit, not the ANSI renderer

**Status:** Superseded by 0037
**Date:** 2026-05-03

## Context

The status pane (`bridge/status_pane.py`) is a flicker-free ANSI renderer:
cursor-home + per-line `\e[K` + `\e[J`, no `\e[2J`. The natural inference for
a sibling right-column pane would be the same architecture. The buffs pane was
nevertheless built on `prompt_toolkit`. This ADR records why, so future
contributors do not mistake the inconsistency for an oversight and waste effort
"fixing" it.

## Decision

`bridge/buffs_pane.py` is a `prompt_toolkit` full-screen `Application`.

## Rationale

Three drivers made `prompt_toolkit` the right choice:

1. **Mouse-wheel scroll with sticky bottom.** The comm pane already implements
   row-based scroll via `ListControl(FormattedTextControl)` and a
   `ConditionalContainer` overflow indicator. The buffs pane needs identical
   semantics (scroll offset, sticky bottom on new rows, two indicator
   variants). Reusing the same primitives costs nothing; reimplementing the
   same scroll logic in a raw ANSI loop would be non-trivial and would drift
   from the comm pane over time.

2. **Tick-driven redraw model.** Bar drain and blink are time-driven, not
   event-driven — the grid must redraw on a cadence independent of state
   changes. `prompt_toolkit`'s async `app.invalidate()` model composes
   naturally with two concurrent `asyncio` tasks (mtime poll + blink tick).
   An ANSI renderer would need its own redraw scheduler interleaved with the
   poll loop.

3. **Overflow indicator pattern.** The `↓ N more rows` / `↓ N newer rows`
   indicator is already established in the comm pane via a separate `Window`
   so list `wrap_lines` can never push it off the bottom. Reusing the same
   `ConditionalContainer` pattern keeps both surfaces consistent.

## Consequences

The right column now contains two different rendering models:

- **Status pane** — ANSI (flicker-free cursor-home loop).
- **Buffs pane** — `prompt_toolkit` (async invalidate, tick-driven).
- **Comm pane** — `prompt_toolkit` (async invalidate, scroll).

This is acceptable. Each pane is self-contained, and the split follows content
shape: static-framed data (status) vs tick-driven animation (buffs) vs
scrollable message history (comm). The inconsistency is by content, not
arbitrary.

## Alternatives considered

**ANSI renderer (like status pane).** Rejected. Would require hand-rolling
scroll state, a blink tick scheduler, and the overflow indicator — all already
solved by `prompt_toolkit` primitives used in the comm pane.

**Migrate status pane to `prompt_toolkit` for consistency.** Rejected. The
status pane works correctly, is simpler for its use case (pure static frame,
no scroll, no animation beyond bar fill), and a unified right-column TUI
redesign is already recorded as a separate parked option in ADR 0012. Forcing
consistency here would be scope creep, not improvement.

## Relation to ADR 0012

ADR 0012 parked a unified right-column TUI (single `prompt_toolkit` app
managing all right-column panes). This ADR is narrower — a single-pane
renderer choice — and does not reopen 0012.
