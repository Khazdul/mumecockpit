# 0065 — Run-stats aggregation lives in Python

**Status:** Accepted
**Date:** 2026-05-12

## Context

The in-game popup's Statistics frame needs aggregated run data:
top kills (by count and by total XP), top player kills, allies,
achievements, level span, run duration, current-level XP progress,
and XP/h + TP/h sparkline buckets. None of that aggregate shape is
already on hand: `state.run` (owned by `lua/core/run_state.lua`)
holds only the running totals the status pane consumes (XP gained
since run start, TP gained, last kill name) plus the in-memory
kill list — not grouped, not sorted, not time-bucketed.

The canonical source for everything the Statistics frame needs is
the per-run JSONL stream written by `lua/core/run_log.lua` to
`data/runs/<character>/current.jsonl` while a run is active, and
archived to `<run_id>.jsonl` on run end. See [ADR 0044](0044-run-event-log-jsonl.md)
for the schema, [ADR 0056](0056-previous-run-id-linking.md) for the
linking, and [docs/runs.md](../runs.md) for the event catalogue.

Two reasonable homes for the aggregation logic:

(a) **Lua-side.** Extend `state.run` with grouped/sorted fields
    and add a `run_state_writer.lua` that serialises a richer
    snapshot to `bridge/runtime/run.state`. The popup then reads
    that file the same way the status pane reads `status.state`.

(b) **Python-side.** A pure library at
    `bridge/launcher/run_stats.py` that reads
    `data/runs/<character>/current.jsonl` (and, later, archived
    runs) directly and returns a `RunStats` dataclass. The popup
    imports it; a future launcher run-browser imports the same
    function with a different run-id.

The launcher run-browser is on the roadmap — a page that lets the
player walk back through archived runs, view the same Statistics
shape per run, and compare. That page lives in the launcher
(pre-tmux bash + Python helpers), not in a tt++/Lua context.

## Decision

**Python-side.** Aggregation lives in `bridge/launcher/run_stats.py`.
The popup's Statistics frame imports `load_current_run_stats` and
calls it on push + on every live tick + on R-key refresh. The
future launcher run-browser will call `aggregate(run_id)` against
archived JSONL files.

`state.run` is unchanged. It continues to serve the status pane
(running totals, last kill highlight) as before. No new Lua
collectors, no new `bridge/runtime/run.state` file.

The aggregator is a pure library: no UI, no tmux, no Lua, no
mutation of any runtime files. It reads the JSONL the same way
`lua/core/run_log.lua` writes it.

## Consequences

- **Gained.** A single source of aggregation logic for both the
  in-game Statistics frame and the future launcher run-browser.
  When the schema grows a new event type, one Python file changes
  and both surfaces pick it up. No new always-on Lua collectors,
  no new serializer feeding a snapshot file, no Lua/Python
  drift across two readers of the same JSONL.
- **Lost.** A deviation from architecture.md design principle 5
  ("Single source of truth — Lua owns all game state") on the
  read side. The principle still holds for *writes* — `run_log.lua`
  is the only writer of run JSONL, and `state.run` remains the
  only in-memory representation Lua scripts consume. What
  `run_stats.py` adds is a derived view computed at read time
  outside Lua. That is acceptable because (i) the JSONL is the
  durable contract Lua owns, (ii) the derived view is read-only,
  and (iii) the alternative (b) duplicates the derivation in
  Python anyway for the launcher run-browser, which has no Lua
  available.
- **Cost.** Per-tick JSONL re-read on the Statistics frame. For a
  typical run (≤ a few thousand events on a multi-hour session)
  this is a millisecond-scale read on local disk; the popup tick
  runs every 60 s so the cost is irrelevant. If a very long run
  ever shows up on the cost radar, a tail-incremental aggregator
  (remember the last offset, re-fold only new lines) is a
  drop-in upgrade — the aggregate dataclass shape stays the same.
- **Re-reads pick up writes naturally.** The aggregator reads the
  file fresh on each call; live updates from `run_log.lua` are
  visible on the next tick without any file-watcher or
  invalidation plumbing.

## Alternatives considered

**Lua-side aggregator + `bridge/runtime/run.state`.** Extend
`state.run` to hold the grouped/sorted/bucketed shape and add a
serializer in `lua/core/` that emits a `run.state` file the popup
polls.

Rejected. The launcher run-browser cannot consume
`bridge/runtime/run.state` — that file describes the *currently
active* run on the live brain, and the launcher runs pre-tmux with
no Lua available. To support archived runs the launcher would need
its own Python reader of the JSONL — so either there would be two
implementations of the same aggregation (Lua for live, Python for
archived) drifting over time, or the Lua aggregator would have to
be ported to Python anyway. Picking Python from the start
collapses both surfaces onto one implementation.

**Hybrid: Lua aggregates live, Python aggregates archived, shared
schema doc.** Same Python port problem, just deferred. Doubles the
test surface and creates a class of "the popup shows X but the
run-browser shows Y for the same archived run" bugs.

**Aggregate on demand inside the popup itself, no library.** Inline
the JSONL parsing into `ingame_menu.py`. Rejected — the launcher
run-browser would have nowhere to import from, and a one-shot
inline parser would inevitably grow into a library anyway.

## Relation to other ADRs

- **Builds on [ADR 0044](0044-run-event-log-jsonl.md)** — the
  JSONL schema and lifecycle this aggregator consumes.
- **Builds on [ADR 0056](0056-previous-run-id-linking.md)** —
  links between consecutive runs are read by the aggregator's
  archived-run path for the future launcher run-browser.
- **Diverges from [ADR 0003](0003-gmcp-driven-mume-connection-state.md)
  for read-side aggregation only.** GMCP remains the source of
  truth for in-memory state (`state.run` is populated from
  `Char.Vitals` + per-kill GMCP events); the aggregator only
  derives a presentational view from the JSONL that `run_log.lua`
  writes. No GMCP module, no `state.*` namespace, no Lua
  ownership change.
- **Supplements [ADR 0062](0062-popup-menu-prompt-toolkit.md)** —
  the Statistics frame is a consumer of this aggregator; the
  popup-side rendering contract (focus-on-push) is recorded
  separately in [ADR 0066](0066-popup-frame-focus-on-push.md).
