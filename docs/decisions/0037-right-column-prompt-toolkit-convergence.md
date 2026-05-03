# 0037 — All right-column panes use prompt_toolkit

**Status:** Accepted
**Date:** 2026-05-03
**Supersedes:** 0033

## Context

ADR 0033 recorded that the buffs pane was built on `prompt_toolkit` while the
status pane remained an ANSI cursor-home renderer, and concluded that the split
was acceptable because each pane's content shape drove the rendering choice. The
UI pane was still a `tail -f` bash subshell.

The right column therefore used three rendering models simultaneously:

- **Status pane** — ANSI flicker-free loop.
- **Buffs pane** — `prompt_toolkit` (async invalidate, tick-driven).
- **Comm pane** — `prompt_toolkit` (async invalidate, scroll, mouse header).
- **UI pane** — `tail -f` bash subshell (no scroll, no ANSI rendering state).

## Decision

All four right-column panes (status, buffs, comm, ui) are `prompt_toolkit`
full-screen Applications.

- `bridge/status_pane.py` — migrated from ANSI loop in Phase 1.
- `bridge/buffs_pane.py` — already `prompt_toolkit`; scroll anchor flipped to
  top in Phase 2.
- `bridge/comm_pane.py` — unchanged reference implementation.
- `bridge/ui_pane.py` — new file created in Phase 3; replaces `tail -f` subshell.

The `tail -f` bash wrapper in `bridge/open_pane.sh` and `bridge/tmux_start.sh`
is replaced by `python3 $MUME/bridge/ui_pane.py`, matching the spawn pattern of
the other three panes.

## Rationale

1. **Uniform scroll and indicator semantics.** All panes that can overflow now
   use the same `ConditionalContainer` overflow indicator in `fg:#d4a04e italic`
   amber. Comm and UI use anchor-bottom with `↓ N newer messages`. Buffs uses
   anchor-top with `↑ N rows above` / `↓ N more rows`. Status uses anchor-top
   with `↓ N more rows` (passive, not clickable — content is fixed-position
   and scrolling has no semantic value).

2. **Eliminated the dual rendering model.** The ANSI cursor-home loop in the
   status pane and the raw `tail -f` in the UI pane each required separate
   mental models for resize handling, cursor hiding, and terminal interaction.
   `prompt_toolkit` handles all of these uniformly across all four panes.

3. **UI pane gains scrollback.** `tail -f` cannot scroll history. The new
   `ui_pane.py` reads up to 1000 lines at startup, supports wrap-aware
   mouse-wheel scroll, and provides a sticky-bottom live-follow mode identical
   to the comm pane's.

4. **Single dependency.** `prompt_toolkit` is already required for
   `input_pane.py`, `comm_pane.py`, and `buffs_pane.py`. The status and UI
   pane migrations add no new dependencies.

## Consequences

- **Status pane:** exposes only a passive overflow indicator (no scroll) by
  deliberate choice. The status frame is a fixed-height data board; the content
  at the top is always the most important. Scrolling has no semantic value —
  the spec chose anchor-top (top rows always visible) over anchor-bottom.

- **Buffs pane:** scroll anchor flipped from bottom to top for consistency with
  the status pane. Affects are ordered newest-first at the top; the most urgent
  (freshest spells) are always visible. The old sticky-bottom model assumed a
  comm-log mental model which does not fit an affect grid.

- **UI pane:** anchor-bottom live-follow matching the comm pane. Log output is
  append-only and naturally read newest-last, so sticky-bottom is the correct
  default.

- **No Lua changes.** `ui_pane.py` tails `logs/ui.log` directly; no new state
  file, no new serialisation layer.

## Alternatives considered

**Keep `tail -f` for UI pane.** Rejected. No scrollback, no consistent cursor
management, no mouse interaction. The bash subshell survival loop was a workaround
for `tail` exiting on log rotation; `ui_pane.py` handles this correctly via
inode tracking.

**Keep ANSI loop for status pane.** Rejected in Phase 1. The ANSI loop was
simpler for its use case but required a manual SIGWINCH dirty-flag and a
separate rendering path. `prompt_toolkit` handles resize automatically and
reduces the conceptual surface of the right column.

## Relation to ADR 0033

ADR 0033 concluded that the buffs/status split was acceptable by content shape.
This ADR supersedes that conclusion: the convergence benefit — uniform overflow
indicators, shared mental model, single dependency — outweighs the marginal
simplicity of the ANSI loop for the status pane.
