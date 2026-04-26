# 0012 — Unified right-column TUI (parked)

**Status:** Parked
**Date:** 2026-04-26

## Context

The right column currently consists of four independent tmux panes: status,
comm, ui, and dev. Their heights are managed by `bridge/apply_layout.sh`, with
`status_height` as the authoritative key (ADR 0004, ADR 0005).

Two visible artefacts occur whenever right-column pane heights change at
runtime (e.g. status growing with affect count):

1. **Comm pane redraws in multiple visible steps** during resize, because the
   Python renderer polls on an interval and may fire mid-transition.
2. **All right-column panes briefly jump** as tmux propagates the new geometry
   top-down through `apply_layout.sh` — panes are resized one at a time, so
   neighbours move before the overall layout settles.

Root cause: tmux has no atomic relayout. There is no mechanism to resize all
panes in a single frame. Any approach that drives `status_height` dynamically
will produce these artefacts as a direct consequence of how tmux applies
geometry changes.

This will become more visible if Phase 2 of the status pane drives
`status_height` from affect count at runtime (see `docs/status-pane.md` →
"Phase 2 — Affects tracker").

## Decision

Park the unified-TUI approach. Mitigate flicker at the status-pane renderer
level — fixed height with overflow handling or compact affect rendering —
rather than restructuring the right column.

### Parked design (recorded for later resumption)

Replace the four right-column tmux panes with a single tmux pane running a
`prompt_toolkit` application that hosts four internal sections (status, comm,
ui, dev) in an `HSplit`. Internal layout changes redraw atomically inside one
process — no tmux resize choreography, no flicker.

**What moves into the TUI:**
- Status renderer (from `bridge/status_pane.py`)
- Comm renderer with mouse-driven channel-filter header (from `bridge/comm_pane.py`)
- `ui.log` tail with scrollback
- `debug.log` tail with scrollback
- Section show/hide state (replaces tmux pane open/close for status/comm/ui/dev)
- Internal divider rendering (replaces tmux `pane-border-status` for the right column)
- Height persistence for sections (replaces `ui_height`, `comm_height`,
  `status_height` in `layout.conf`)

**What stays unchanged:**
- Lua side (`status_state.lua`, `comm_log.lua`, `comm_state.lua`,
  `comm_store.lua`) — same JSON state files, same poll model
- tt++ side
- `ui.log` and `debug.log` on disk
- Outer right-column width (`ui_width`) — still a tmux concern
- Input pane and main game pane

**What simplifies on the bridge side:**
- `bridge/apply_layout.sh` — only outer column width remains
- `bridge/on_pane_resize.sh` — only width-drag detection
- `bridge/on_window_resize.sh` — narrow-collapse handles one pane instead of
  a list
- ADR 0004's right-column layout authority framing is largely superseded for
  height management
- `bridge/toggle_pane.sh` — `cp -u/-m/-c/-d` signal the TUI instead of
  opening/closing tmux panes
- In-game popup Options — reads section visibility from a TUI state file
  instead of probing tmux pane titles

**What needs new design when we resume:**
- IPC for section toggles (signal + state file, or polled config)
- Behaviour when all four sections are hidden (close the outer pane, or keep
  an empty placeholder?)
- Loss of tmux copy-mode for ui and dev sections — either reimplement
  scrollback/copy in the TUI or accept that the log files on disk are the
  fallback
- Section focus model (does any section "have focus", or is mouse the only
  interaction surface?)
- Migration path for `layout.conf` height keys

## Consequences

- The flicker artefact remains visible whenever right-column pane heights
  change at runtime.
- Phase 2 of the status pane (dynamic height from affect count) must mitigate
  flicker at the renderer level — e.g. fixed height with "+N more" overflow,
  or compact one-line affect rendering — rather than relying on the TUI
  restructure.
- ADR 0004 remains the authoritative model for right-column layout.

## Alternatives considered

**Fixed status height with overflow handling.** A "+N more" line or pagination
keeps the pane at a constant row count. Stable layout, no flicker, modest
renderer work. This is the preferred near-term mitigation.

**Compact affect rendering.** One or two fixed rows of short tags. Highest
information density, fully stable layout.

**Affects on demand.** Surface affects only via popup or keybind, not in the
status pane at all. Keeps the status pane at a fixed row count with no new
renderer complexity.

## Revisit triggers

Reconsider this design when one or more apply:

- A second independent reason to restructure the right column appears (e.g.
  cross-pane focus, unified scrollback, richer interactive widgets).
- The renderer-level mitigations prove insufficient as the status pane gains
  more dynamic content.
- A user-facing requirement emerges that tmux-level layout cannot satisfy
  cleanly.
