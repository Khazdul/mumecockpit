# 0071 — Per-pane desired heights with adaptive cold-start allocation

**Status:** Accepted — Phase 2 allocation amended by [ADR 0137](0137-character-pane-height-reservation.md) (2026-06-14): the status/character pane is reserved its desired height before the other panes scale proportionally. The body below is unchanged.
**Date:** 2026-05-13

## Context

The right-column layout system has been through:

- ADR 0004/0005 — height authority via apply_layout.sh. Drag and
  toggle bugs.
- ADR 0030 — dropped height authority; heights tmux-managed and
  freely resizable. Solved the bugs but cold-start always started
  from equal-share — preferred layouts could not persist across
  restarts.
- ADR 0055 — cold-start budget with uniform MIN_PER_PANE=2 and
  drop-and-equalize. Protected against tmux's "pane too small"
  failures but capped pane counts at typical terminal heights (e.g.,
  4 panes at H≈15) regardless of whether each pane could have used
  less space.

Combined limitation: a user who configured a preferred layout (big
status, big comm, small group) had to drag every restart, and could
not reliably fit 6 panes at heights where geometry should have
allowed it.

## Decision

Right-column pane heights are determined by per-pane desired values
stored in `bridge/runtime/layout.conf`:

    desired_status=6
    desired_buffs=5
    desired_group=5
    desired_comm=10
    desired_ui=5
    desired_dev=5

Values are *content* rows, excluding title overhead. Defaults live
in `bridge/layout/right_column_budget.sh` as DEFAULT_DESIRED. Per-
pane minimums live there as MIN_HEIGHT (status=2, all others=1).

Cold-start runs a two-phase algorithm:

**Phase 1 — survivor selection.** REQUESTED = panes with
show_<pane>=1 in startup.conf. While
sum(MIN_HEIGHT[p] for p in REQUESTED) > rc_available_rows(N), drop
the lowest-priority pane (DROP_ORDER: dev, group, buffs, comm,
status, ui). Logged to debug.log; startup.conf is not modified — a
taller terminal next start restores everything.

**Phase 2 — allocation.** Available rows are computed via:

    rc_available_rows(N) = ROWS - (N - 1) - top_header - 2

where top_header = 1 if show_pane_dividers=1 else 0, and 2 = input
row + divider above. If sum(desired) ≤ available, each pane gets
its desired height; residual goes to the highest-priority survivor
(PRIORITY_ORDER: ui, status, comm, buffs, group, dev). Otherwise,
allocate linearly:

    ALLOC[p] = MIN_HEIGHT[p]
             + (desired[p] - MIN_HEIGHT[p])
               * (available - min_sum) / (desired_sum - min_sum)

with residual to the highest-priority survivor.

**Phase 3 — pane creation.** Panes created in visual order via
`open_pane.sh`, with `bridge/layout/equalize_right_column.sh` run
between splits so intermediate panes stay above tmux's split floor.
After the input pane is created, `pane-border-status` is set to its
final state (before the algorithmic resize, so tmux doesn't steal a
row from the topmost pane afterward), then
`bridge/layout/apply_desired_heights.sh` applies the ALLOC values
via targeted tmux resize-pane calls.

User drags are the configuration mechanism.
`bridge/layout/on_pane_resize.sh` persists current right-column pane
heights to desired_<pane> on every MouseDragEnd1Border event.
Horizontal-only drags (main↔right border) change no heights and the
writes are no-ops.

`cp -reset-heights` deletes the persisted desired_<pane> lines,
appends defaults from DEFAULT_DESIRED, and re-runs
apply_desired_heights.sh without restart.

`bridge/layout/on_window_resize.sh` re-runs apply_desired_heights.sh
after every WINCH event (via the `_reapply_desired_heights` helper)
so the layout responds symmetrically to terminal resizes — heights
restore to algorithmic ALLOC when the terminal grows back.

## Consequences

- Layouts persist across sessions. Drag once, configuration sticks.
- Drop ceiling is no longer artificial: at H=42 all 6 panes fit; at
  smaller terminals, only panes whose individual minimums don't fit
  are dropped.
- Algorithm and runtime gates share a single available-rows formula
  via rc_available_rows(), eliminating prior overhead-accounting
  drift between sites.
- ADR 0030's mid-session promise is preserved: drags during a session
  are not stomped by re-application. Re-application happens only on
  WINCH and explicit cp -reset-heights.

## Alternatives considered

**Uniform MIN_PER_PANE = 1.** Simpler, but treats status (with
2-row progress bars) the same as comm (scrollable text). A 1-row
status is unreadable. Per-pane minimums are the right granularity.

**Tabbed panes (combine two logical panes into one tmux slot with a
tab header).** Would fit more panes in tight terminals. Adds UX and
rendering complexity. Premature; deferred.

**Drag-free configuration via config file or settings UI.** Cleaner
separation of preference from geometry but adds friction. Users
adjust by dragging during play, not by editing config.

**Restore full ADR 0004/0005-style height authority** (apply on
every operation). Would let mid-session toggles snap heights back to
desired. Rejected for the original ADR 0030 reasons — drag detection
becomes brittle, toggles get bug-prone. Mid-session heights stay
free; cold-start and WINCH are the re-application points.

## Relation to other ADRs

- Supersedes ADR 0055 (drop-and-equalize replaced).
- Partially supersedes ADR 0030 — cold-start and WINCH now drive
  heights from desired_<pane>; mid-session free-drag stands.
- ADR 0006 (visual order) unchanged.
- ADR 0029 (input pane full width) unchanged; new accounting in
  rc_available_rows includes the input divider.
