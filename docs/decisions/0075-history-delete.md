# 0075 — History session delete bypasses the saved flag

**Status:** Accepted
**Date:** 2026-05-15

## Context

The launcher History view (ADR 0073) lets the player save sessions
(ADR 0074) so they survive the 14-day retention sweep. Until now,
removing a session from disk was either an automatic side-effect of
the sweep (unsaved → deleted on age) or a manual `rm` from a shell.
There was no in-launcher path to delete a session — saved or
otherwise.

Two things need deciding:

1. Does the Delete action respect `summary.saved`?
2. How do we mediate the risk that one keystroke can destroy hours
   of capture?

Letting Delete bypass `saved` is the simple answer; gating it on
unsaved would force the player to "un-save → delete" through the
launcher, but no un-save UI exists, so the practical effect of
gating would be "saved sessions are undeletable from the launcher".

## Decision

**Delete is always available when a row is selected.** It does not
check `summary.saved`. The `saved` flag's role narrows to "protected
from the automatic retention sweep"; explicit player-initiated delete
is always honoured.

**Mandatory confirmation via `history_delete_confirm`.** Activating
Delete pushes a centred modal that surfaces the session's identity
(character, date/time/duration, run count) and — when applicable —
its saved/rating status painted `C_ACCENT` (gold). The frame mirrors
the existing `exit_confirm` / `update_result` pattern: `Y` confirms,
any other key (including `ESC`) cancels.

**Per-file best-effort removal.** `_history_delete_session()` walks
the chain's `run_ids` and removes the `.jsonl`, `.log`, and
`.meta.json` triplet for each. Per-file `OSError` is swallowed (same
defensive style as the retention sweep); no rollback on partial
failure.

## Consequences

- **Gained.** Saved sessions are deletable without leaving the
  launcher. The UI surfaces a session's saved status at the moment
  of destruction, so the player sees what they're about to lose.
- **Gained.** `saved` semantics are now crisp: "protected from
  retention", not "immutable". One concern, one rule.
- **Lost.** No un-delete. A confirmed Delete is final at the
  filesystem layer; restoration requires a backup outside Cockpit.
- **Cost.** A second confirm-style frame for History (alongside
  `history_rate`). Same focus-on-push contract (ADR 0066), same
  module-level summary handle pattern.
- **Risk.** A misaimed `Y` after pushing the frame deletes the row.
  Mitigated by the explicit `Y` requirement (no `Enter`/`Space`
  shortcut), the visible saved/rating warning, and the two-line
  "cannot be undone" body copy.

## Alternatives considered

**Block delete on saved sessions.** Rejected. With no un-save UI,
this would create an asymmetry — unsaved rows are deletable, saved
rows are stuck — that fails the principle of least surprise. The
player owns their data; refusing the action just hides it behind a
shell command.

**Soft-delete to a trash directory.** Rejected. Adds a restoration
UX that nobody asked for, plus a second sweep policy ("how long do
we keep trash?"), plus an extra filesystem surface for retention to
reason about. Out of scope for the History delete prompt.

**Inline confirmation (no separate frame).** Rejected. The History
frame is already busy (filter pills, table, Options column, feedback
row). A modal pulls the player out of the table cursor flow and
makes the confirm a deliberate context switch, which is what we
want for a destructive action.

## Relation to other ADRs

- **Builds on [ADR 0066](0066-popup-frame-focus-on-push.md)** — the
  confirm frame is a single focusable Window registered in
  `_focus_current_frame()` so key handlers route correctly.
- **Builds on [ADR 0073](0073-statistics-rendering-duplicated.md)** —
  Delete is one more action on the History Options widget, anchored
  to `_history_table_cursor` like every other row-targeted action.
- **Narrows [ADR 0074](0074-run-retention-and-saved-meta.md)** —
  the `saved` flag now only guards the retention sweep, not all
  destructive paths. Explicit player deletion ignores it.
