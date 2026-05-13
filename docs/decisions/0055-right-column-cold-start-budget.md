# 0055 — Right-column cold-start budget and runtime open gate

**Status:** Superseded by [ADR 0071](0071-per-pane-desired-heights.md)
**Date:** 2026-05-10

## Note (2026-05-13)

Drop-and-equalize replaced with min-sum-based drop + scale-to-
desired allocation. The runtime open gate (`rc_fits_one_more` /
`rc_target_can_be_split`) is further refined by
[ADR 0072](0072-toggle-equalize-fallback.md).

## Context

Cold-start built the right column by issuing one `split-window -v` per
requested pane in cascade. tmux halves the current pane on each split, so
the deepest pane received a row count proportional to `1 / 2^N`. On a
moderately tall terminal (e.g. 25–30 rows) with all six panes enabled this
either left the deepest pane at 1–2 rows of content (unreadable) or
failed outright with `create pane failed: pane too small`, after which
tmux's recovery placed the new pane on top of the input row — silently
breaking the layout in a way that was hard to diagnose because the
preceding splits had succeeded.

Runtime `cp -*` opens had the same blind-spot: when the right column was
already full, the next split-window call tripped the same recovery and the
new pane landed on top of the input row instead of failing cleanly.

The previous behavior of writing each pane's `show_*` flag aside (so a
narrower terminal could "remember" them) was tempting, but conflicted with
`startup.conf`'s contract: those keys reflect *what the user wants*, not
*what the current terminal can fit*. A wider terminal on the next attach
should restore everything the user asked for.

## Decision

Introduce `bridge/layout/right_column_budget.sh` with a conservative
formula (assumes one title row per pane regardless of `pane-border-status`
state):

    overhead_per_pane = MIN_PER_PANE + TITLE_OVERHEAD = 3 + 1
    max_panes         = (window_height - INPUT_RESERVE) / overhead_per_pane

`bridge/launcher/build_initial_layout.sh` runs a pre-flight skip pass:
build the requested list in visual order, then drop the lowest-priority
survivor (drop order: dev → group → buffs → comm → status → ui) until
`len(requested) ≤ max_panes`. Each skip is logged to `logs/debug.log`.
`startup.conf` is **not** modified — the next attach on a taller terminal
restores everything the user asked for.

Survivors are created uniformly through `open_pane.sh`. The previous inline
`split-window` block that special-cased the `ui + dev` cold-start pair is
deleted; `open_pane.sh`'s "no right column yet" branch handles the first
right-column pane correctly via `split-window -h -t main` and resizes
main to LEFT.

After `input` is created, a single equalize pass divides remaining rows
evenly across the right-column panes (residual goes to the last pane).
This pass runs **once** at cold start; subsequent terminal resizes and
border drags are not stomped (ADR 0030 standing).

`open_pane.sh` consults the same budget on every runtime open path
(`cp -*` aliases, GRP/BUF/COM/CHR buttons, in-game popup, and the
narrow-terminal restore loop in `on_window_resize.sh`). When the next
split would exceed the budget it writes a `logs/ui.log` warning and
exits 0 — no `split-window` is issued.

Skip priority (highest = last to be skipped): ui > status > comm > buffs >
group > dev. ui ranks first because the launcher and the main UI feed live
there; dev last because it's developer-only and rarely opens on tight
terminals.

## Consequences

- Cold-start always produces a layout in which every created pane has
  ≥ 3 content rows + 1 title row, and the input row is preserved.
- Panes that don't fit at cold start are absent for that session but
  remain enabled in `startup.conf` for the next attach.
- Runtime opens past the budget are no-ops with a user-visible warning
  in `logs/ui.log`; tmux's "no space" recovery is never triggered.
- ADR 0053 (split-from-predecessor for kill/reopen symmetry) is
  preserved unchanged — `open_pane.sh`'s per-pane split-target logic is
  untouched.
- ADR 0030 (heights are tmux-managed and user-resizable) is preserved:
  equalize runs exactly once at cold start; user drags afterwards are
  authoritative.

## Alternatives considered

**Preferred-minimum per pane** — let each pane declare a preferred row
count and try to honor it. Two prior attempts failed: row-budget accounting
across the cascade-create path was brittle (tmux's actual split outcome
depends on parent-pane state at the moment of the call), and equalize-on-
overflow leaked into the runtime open path. Rejected.

**Persist heights across sessions** — would let the user "lock in" a
custom right-column distribution. Rejected: ADR 0030 standing
(heights are tmux-managed and user-resizable; persistence would re-stomp
user drags on every attach).

**Modify `startup.conf` when a pane is skipped** — would survive across
restarts but conflates "user preference" with "current terminal fits."
A user who occasionally attaches from a small terminal would lose pane
state they never asked to lose. Rejected.
