# 0072 — Equalize-before-split fallback for runtime pane opens

**Status:** Accepted
**Date:** 2026-05-13

## Context

`bridge/launcher/open_pane.sh` consulted `rc_target_can_be_split`
on the predecessor before splitting and refused the split when the
predecessor's body was below the gate threshold. This prevented
tmux's "no space" recovery from displacing the input row.

In practice the gate fired surprisingly often after a user had
dragged some panes very small — a toggle that should have succeeded
geometrically failed silently. ADR 0055's contract ("exit 0 on
gate refusal") meant the caller had no signal to act on, and
toggle_pane.sh --persist had already written show_X=1 to
startup.conf, leaving the menu bar's button state out of sync with
reality.

## Decision

When `rc_target_can_be_split` would refuse, fall back to
`bridge/layout/equalize_right_column.sh` to redistribute current
right-column panes to fair share, then re-check the gate. If it
passes, proceed. If it still refuses, the terminal is genuinely too
short — emit a UI-visible amber WARN and exit 1.

`toggle_pane.sh` persists show_<pane>=1 to startup.conf only after
open_pane.sh returns 0. A non-zero return leaves startup.conf
unchanged so the menu bar reflects reality.

`open_pane.sh` gains a `--batch` flag that suppresses the post-split
apply_desired_heights.sh call. Cold-start (Phase 3) and narrow-
restore loops pass `--batch` because they apply once at the end of
the loop. Interactive toggle paths get the per-call settle so the
new pane lands at its algorithmic ALLOC.

## Consequences

- Toggle reliability: a pane the user asks for opens whenever there's
  any feasible way to fit it, without destroying scrollback.
- No scrollback loss: kill-and-rebuild was considered and rejected.
  ui, comm, and dev are scroll-buffers with user-visible content.
- State consistency: startup.conf and the menu bar always reflect
  actual right-column state.
- ADR 0055's "exit 0 on gate refusal" contract is replaced for the
  height-gate path. The count-gate (rc_fits_one_more) and narrow-
  collapse sentinel paths keep existing behavior.

## Alternatives considered

**Kill all right-column panes and rebuild via the cold-start
algorithm.** Always succeeds when geometrically feasible and offers
one mental model. Rejected — kills scrollback in ui, comm, and dev
panes. The tear-down-rebuild is also visibly jarring.

**Pre-resize only the target.** Borrow rows from one specific
neighbor. Simpler but the donor choice is arbitrary. Equalize is the
principled fair-share answer and reuses an already-tested helper.

**Louder log line with silent failure preserved.** Doesn't fix the
UX — users don't read logs/ui.log mid-play.

## Relation to other ADRs

- Refines ADR 0055 — the height-gate's exit-0 contract is replaced
  by exit 1 on unrecoverable failure.
- Depends on equalize_right_column.sh from ADR 0071.
