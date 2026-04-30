# 0030 — Right-column pane heights are tmux-managed

**Status:** Accepted
**Date:** 2026-04-30

## Context

ADR 0029 moved the input pane to a window-level full-width `vsplit` (`-f`)
below the top container. With that topology, `tmux resize-pane -y N` on a
right-column pane that has no vertical sibling inside the right column
resizes the outer `hsplit` boundary — moving the top container's bottom edge
and pushing the input row up. The apply-layout-as-height-authority model
(ADR 0004, ADR 0005) is therefore incompatible with the new topology when
fewer than two right-column panes are open.

Two recovery options were considered:

- **(a)** Make height authority conditional on the right column having multiple
  panes. Fall back to no-op when a single pane is open.
- **(b)** Drop height authority entirely. Let tmux manage right-column heights
  as it does for any normal `vsplit`; `apply_layout.sh` keeps only the input
  pin and the width-floor enforcement.

## Decision

Option **(b)**. `apply_layout.sh` is reduced to two responsibilities:

1. Pin the input pane to 1 row on every call.
2. Enforce the 29-col right-column width floor when status is open.

`on_pane_resize.sh` persists `ui_width` only; vertical drag detection and
`ui_height` / `comm_height` persistence are removed. `open_pane.sh` no
longer force-sizes status on creation. `tmux_start.sh` writes only
`ui_width` and `window_cols` to a fresh `layout.conf`. The keys
`status_height`, `ui_height`, and `comm_height` are dropped from `layout.conf`;
stale keys in existing files are ignored (no migration needed).

Right-column pane heights are freely resizable by the user, with no snap-back
and no persistence across sessions.

## Consequences

- Input never moves except on terminal resize (window-level pin is always
  correct regardless of right-column pane count).
- Right-column heights on cold start are tmux's equal-share default across
  siblings — visually less predictable than the old authored defaults, but
  consistent: users build muscle memory around one drag from a known baseline.
- The Phase 2 affects-tracker dynamic-height path becomes a direct
  `tmux resize-pane -y N -t status` call from Lua, gated on the right column
  having more than one pane (single-pane case is skipped — status fills the
  column anyway). No `layout.conf` write, no `apply_layout.sh` round-trip.
- A class of snap-back vs. drag-intent bugs is eliminated entirely rather than
  papered over.

## Alternatives considered

**Option (a) — conditional authority.** Guard the height-resize block on
`ACTIVE_COUNT > 1`. Correct for two-or-more panes, but adds branching and
keeps the snap-back / drag-intent tension alive for the multi-pane case.
More complex than option (b) with no clear win. Rejected.

**Re-introduce height authority via the inner right-column `vsplit`** (resize
the container, not individual panes). Still requires two-or-more panes to
work; no advantage over option (b) for the single-pane case. Rejected.

## ADR relationships

Supersedes ADR 0004 and ADR 0005 (height authority removed entirely).
ADR 0006 (column ordering: status → ui → dev) remains Accepted; its ordering
decision is unchanged. ADR 0006's apply-order and drag-detection
implementation notes are obsoleted by this decision.
