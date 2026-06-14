# 0137 — Character-pane height reservation

**Status:** Accepted
**Date:** 2026-06-14

## Context

ADR 0071 distributes right-column rows in two phases: Phase 1 selects which
panes survive a tight budget, and Phase 2 allocates content rows among the
survivors — each pane its desired height when everything fits, otherwise a
linear scale between its minimum and desired, with the residual dropped into
the highest-priority survivor (`PRIORITY_ORDER`: ui, status, comm, …).

Under a tight budget the linear scale squeezes every pane proportionally,
including the status (character) pane. The character pane's progress bars are
the most height-sensitive content in the column — a couple of rows short and
fields are lost — so squeezing it the same as a scrollable comm or ui pane
gave a poor read exactly when space was scarce.

## Decision

In Phase 2 (`apply_desired_heights.sh`) the status (character) pane is
**reserved its desired height before** the remaining rows are distributed
proportionally among the other panes. The status allocation is set aside
(clamped so the other panes always keep at least their minimums), and the
remaining panes scale via the existing `allocate_set()` rule against
`CONTENT_AVAILABLE − STATUS_ALLOC`. The residual still drops into the
highest-priority *non-status* survivor (`ui`), unchanged.

This bites only under a tight budget: when `Σ desired ≤ budget` every pane
(status included) already gets its desired height, so reserving status first
yields **identical geometry**. The reservation is **skipped** when status was
dropped by Phase 1 survivor selection, or when status is the only requested
pane — in those cases every pane is allocated in a single `allocate_set()`
pass, geometry identical to the unprotected rule.

## Alternatives considered (rejected)

- **Lower comm/ui `DEFAULT_DESIRED`.** A blunt nudge that biases the split
  toward status by shrinking the others' desired values. Rejected: it does
  not *guarantee* the character pane its desired height under a tight budget,
  and it changes the comfortable-budget geometry too.
- **Reorder `PRIORITY_ORDER` alone.** Moving status up the priority order
  only affects who absorbs the *residual*; it gives no protection under the
  proportional linear scale, which is where the character pane actually loses
  rows. Rejected as residual-only.

## Consequences

- Under a tight budget the character pane keeps its desired height and the
  other panes absorb the squeeze; the highest-priority non-status pane (ui)
  still takes the residual.
- When everything fits, geometry is unchanged from ADR 0071.
- The protection is contingent on status surviving Phase 1; a dropped status
  pane reserves nothing.

## Cross-references

- Amends the Phase 2 allocation of
  [ADR 0071](0071-per-pane-desired-heights.md) (see its append-only status
  note).
- [ADR 0136](0136-in-pane-borders.md) — the per-pane frame reservations
  (`rc_frame_extra`) that Phase 2 carves out of the budget before this
  status reservation applies.
