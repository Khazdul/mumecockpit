# 0004 — Right-column layout authority via apply_layout.sh

**Status:** Superseded by 0030
**Date:** 2026-04-25

## Context

Three related bugs emerged from the right-column layout system:

- **Bug 6:** `cp -d` off → on cut 1 row from the status pane. Root cause:
  `open_pane.sh` applied inline ui/dev ratio logic after splitting but never
  restored status to its configured height. Tmux's redistribution from split +
  resize left status 1 row short.

- **Bug 7:** Arbitrary toggle sequences cut rows. Root cause: `toggle_pane.sh`
  `_kill_pane` left freed space distributed by tmux without any authoritative
  restore.

- **Bug 10:** Dragging the status border upward persisted. Root cause:
  `on_pane_resize.sh` only snapped back if the height fell *below* a minimum;
  drags upward were saved to layout.conf and treated as intentional.

The underlying issue: there was no single canonical path to restore right-column
heights. Each caller inlined its own resize logic, creating divergence over time.

## Decision

Introduce `bridge/apply_layout.sh` as the sole path that restores right-column
pane heights from `layout.conf`. It is idempotent and called after every
operation that touches the right column:

- `open_pane.sh` — after opening any right-column pane (ui, dev, status)
- `toggle_pane.sh` — after `_kill_pane` for ui, dev, or status
- `on_window_resize.sh` — replaces the three inline blocks (input pin, ratio, status restore)
- `on_pane_resize.sh` — when status height differs from the configured value

`status_height` (default 12, matching rendered content) is the authoritative
height. Manual drag snaps back in both directions; the configured value is never
overwritten by a drag. `ui_height_ratio` is dropped — ui and dev share whatever
space remains after `status_height` is allocated.

## Consequences

- Status pane stays at exactly `status_height` rows after any toggle sequence,
  terminal resize, or border drag.
- Phase 2 can drive `status_height` dynamically (from affect count in
  `lua/core/status_state.lua`) without touching any callers — only
  `apply_layout.sh` needs to read the updated value.
- `on_pane_resize.sh` no longer persists `status_height` from drag; it is
  always restored to the configured value.
- ui/dev split ratio is no longer persisted or restored across sessions.
  The two panes share remaining space equally on open.

## Alternatives considered

**Inline restore at each call site.** The original approach. Easy to understand
in isolation but drifts: each new caller must remember to restore status, and the
order of operations diverges. Rejected — this is exactly what caused bugs 6 and 7.

**Restore only on pane-resize events.** Would fix bug 10 but not 6 or 7, since
toggles don't fire the resize hook. Rejected as incomplete.
