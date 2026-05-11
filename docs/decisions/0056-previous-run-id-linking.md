# 0056 — previous_run_id links each run to its predecessor

**Status:** Accepted
**Date:** 2026-05-11

## Context

A run is bounded by `mark_mume_connected()` / `mark_mume_disconnected()`
(ADR 0044). A short link-loss + reconnect therefore produces two distinct
runs: the first sealed via the normal `run_end` path or as an orphan, the
second beginning at the next `Char.Name`. The presentation layer (a
future runs browser, aggregate views, the launcher) will often want to
treat these two short runs as one continuous play session.

ADR 0044 rejected a writer-side **grace window** ("if reconnect happens
within N minutes, the new run is the same run") as needless complexity.
That stance still holds for the writer. But the consumer needs *some*
signal to stitch runs back together — otherwise it has to guess from
character name and adjacent timestamps, which is fragile and forces the
heuristic onto every consumer independently.

We considered a real resume — keep `current.jsonl` open across the
disconnect, omit the seal — but that lands in exactly the territory
[ADR 0054](0054-remove-cp-r-full-reload.md) declined: cross-boundary
state rehydration, special cases on every state surface, sticky-GMCP
edges. The cost of doing it right scales with each new pane and module.

## Decision

Each `run_start` row in `current.jsonl` includes an optional
`previous_run_id` field naming the most recent sealed run for the same
character. The field is **absent** (not null, not empty) when no
predecessor exists.

### Resolution rule

At `run_start` write time (first `Char.Vitals` tick), scan
`data/runs/<character>/` and take the lexicographic max of
`<run-id>.jsonl` filenames with the `.jsonl` suffix stripped,
excluding `current.jsonl`. Run-ids are ISO-like
`YYYY-MM-DDTHH-MM-SS`, so lexicographic order equals chronological
order.

Resolution happens **after** orphan sealing (which runs in the
`run_started` handler, before the first Vitals tick). A freshly-sealed
orphan from the immediately preceding login is therefore visible in the
directory listing and correctly becomes the predecessor of the new run
— the link-loss case that motivated this work.

### Schema versioning

`schema` stays at `1`. The version field bumps for required-field or
event-type changes (per docs/runs.md); adding an optional field is
non-breaking, and consumers that don't know about `previous_run_id`
simply ignore it.

## Consequences

- Link-loss + reconnect produces two runs, but the second names the
  first as its predecessor. The consumer can stitch on display without
  the writer holding cross-boundary state.
- The stitching *policy* — how long a gap is "the same session", how to
  render stitched runs, whether to expose a "merged" or "split" view —
  lives entirely in the consumer. The writer just provides the link.
- A character switch (Character A logs out, Character B logs in)
  produces no link: `previous_run_id` is scoped to the same character's
  directory and resolves to nil for B's first run.
- A fresh character (no archive dir yet, or empty after a manual purge)
  writes `run_start` with no `previous_run_id` field. Consumers treat
  absent as "no predecessor", which matches reality.
- The directory scan is O(N) in sealed runs for that character. With
  one run per play session and a manual purge tool (or none),
  N stays small enough that one `ls` per login is negligible. If it
  ever isn't, a sidecar last_run_id file becomes a viable optimisation
  — without changing the on-disk schema, since consumers only read the
  field on the row.

## Alternatives considered

**Resume the prior run across the disconnect** (keep `current.jsonl`
open, omit the seal on the brief disconnect, treat the reconnect as a
continuation). Rejected for the same reason
[ADR 0054](0054-remove-cp-r-full-reload.md) rejected mid-run resume in
the cp -r path: sticky GMCP modules are not re-emitted on reconnect,
so any module reading state at run boundaries (status, buffs, group,
affects, stored_spells) needs special-case rehydration. Each new state
surface adds another "what does resume mean here?" question. The cost
is paid forever; the benefit only ever surfaces at link-loss boundaries.
A link in the row buys the same consumer-visible outcome at zero
state-rehydration cost.

**Grace window in the writer** (within N seconds of the previous seal,
the new login appends to the prior run instead of starting a new one).
Rejected by ADR 0044 already; reaffirmed here. Picking N is policy, not
mechanism, and policy lives in the consumer. The link is the writer's
mechanism contribution; the consumer chooses N — and can choose
differently for different views without a writer change. This ADR is
the chosen lighter-weight alternative to ADR 0044's rejected
"grace window" option.

**Persist a `last_run_id` sidecar** under `data/runs/<character>/` and
read it on the next `run_start` instead of scanning the directory.
Rejected: a second write per seal, a second file that can drift from
the truth (crash between seal-rename and sidecar-write, manual file
moves, restore from backup), and an extra persistence surface to reason
about — all to avoid an `ls` of a directory that is empirically small.
The directory listing is the source of truth; deriving from it on
demand keeps the system robust to crashes and manual file ops.

**Bake the link into the run-id itself** (e.g., a parent-id suffix or
prefix on the sealed filename). Rejected: run-ids are also filesystem
paths and `ls`-sortable timestamps; smuggling a relation into the
filename hurts both. A row field is the right place for row metadata.

## Relation to other ADRs

- Extends [ADR 0044](0044-runs-and-character-scoped-persistence.md)
  with the linking field. ADR 0044's rejected "grace window"
  alternative now points here as the chosen lighter-weight design.
- Honours [ADR 0054](0054-remove-cp-r-full-reload.md)'s stance against
  cross-boundary state rehydration. The link gives consumers a
  stitching primitive without reintroducing the resume problem.
