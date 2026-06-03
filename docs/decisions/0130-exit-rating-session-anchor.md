# 0130 — Exit-rating anchors to the session's latest persisted run

**Status:** Accepted
**Date:** 2026-06-03

## Context

ADR 0119 folded run rating/save into the `exit_confirm` frame and anchored it to the
*active* run — `_statistics_character()` + `current_run_id_for()`, both reading live state
(`status.state` character + `current.jsonl`). Two cases break that assumption:

- **Quit-then-exit.** `mark_mume_disconnected()` (ADR 0044) seals the run
  (`current.jsonl` → `<run-id>.jsonl`) and clears `state.char`, nulling
  `status.state.character`. A player who `quit`s in-game and *then* exits via the popup has
  no active run and no live character: the prefill showed 0 and the commit silently
  no-op'd, so a just-finished run couldn't be rated on the way out and its history row never
  updated.
- **Enter-then-exit.** A player who enters MUME but never logs in, then exits, has no run at
  all — yet the active-run assumption gave no basis to *hide* the rating widget.

0119 also made `rating == 0` a pure no-op. That orphans the newest sub-run of an
already-saved continued session: if the chain was saved but the just-played continuation
isn't, the continuation's `.jsonl` expires under the 14-day sweep (ADR 0074), splitting a
saved session.

## Decision

**Anchor exit-rating to the latest run *of this cockpit session*, resolved from disk, not to
live connection state.** `_exit_anchor()`:

- **Connected** — the active run (`current.jsonl`); unchanged fast-path.
- **Disconnected** — `run_stats.most_recent_sealed_run()` (lexicographically-greatest sealed
  `<run-id>.jsonl` across all characters), gated to runs that started during the current
  cockpit session. The gate compares the run-id timestamp against
  `bridge/runtime/.session_start`, a launch epoch `tmux_start.sh` stamps on every "Enter
  MUME". A missing stamp or only-stale runs → `None`.

`_exit_rateable = (_exit_anchor() is not None)` decides the frame: rateable → the star
widget; not rateable → a plain Y/ESC confirmation. The bias is to false-negative — rating an
old run would overwrite it, so it is never offered when in doubt.

**`rating == 0` means inherit, not no-op.** On commit the chain's existing rating
(`run_meta.chain_rating`, the most-recently-saved member) is re-written across the whole
chain — including the just-sealed run — so a continued session stays whole and survives
retention. `0` never downgrades a rated chain and never *creates* a save on an unsaved
chain. `rating > 0` overrides the whole chain.

## Consequences

- Rating works on the way out after an in-game `quit`, and updates the correct history row.
- A stale run from a previous cockpit session can never be shown or overwritten — the
  session gate plus the false-negative bias guarantee it.
- An already-saved continued session stays whole: committing the prefilled rating (or 0)
  re-stamps the newest sub-run, so retention can't split it.
- The exit-rating flow no longer depends on live connection state; it reads the same on-disk
  truth the launcher's `history_rate` flow already used. One model, two surfaces.
- Cost: one runtime file (`.session_start`) and a launch-time stamp in `tmux_start.sh`; the
  rest is the popup consumer. No tt++/Lua/hot-path change.

## Alternatives considered

**A Lua "last sealed run" marker written on disconnect.** Rejected. Three layers (Lua write
+ bash clear + Python read), and it duplicates information already on disk — the sealed
run-id *is* the last run. Deriving from the directory listing plus a cheap launch stamp
keeps the writer untouched and honours ADR 0056's "directory is the source of truth" stance.

**A recency window** (offer the most recent sealed run if sealed within N minutes). Rejected.
Fragile both ways: a long deliberation at the login screen drops a legitimate run; a quick
restart surfaces a prior-session run. A launch-anchored boundary is exact.

**Read the character from `status.state` post-quit.** Rejected — impossible: the disconnect
clear nulls it by design (ADR 0044 / status-pane disconnect clear).

**Keep `rating == 0` a no-op (0119).** Rejected. It silently splits saved continued sessions
at the retention boundary and makes the prefill meaningless — committing an untouched
prefilled rating would drop it.

## Relation to other ADRs

- **Supersedes [ADR 0119](0119-exit-confirm-run-rating.md)** — revises the 0-semantics and
  the anchor; 0119's fold-into-exit decision and the deliberate-`Y` friction guard stand.
- **Builds on [ADR 0044](0044-runs-and-character-scoped-persistence.md)** — run sealing and
  the disconnect clear are the forces motivating the disk-anchored resolution.
- **Builds on [ADR 0056](0056-previous-run-id-linking.md)** — the chain walked for
  save/inherit; reaffirms "directory is the source of truth".
- **Builds on [ADR 0074](0074-run-retention-and-saved-meta.md)** — chain-wholeness for the
  14-day sweep is why 0 inherits rather than no-ops.
