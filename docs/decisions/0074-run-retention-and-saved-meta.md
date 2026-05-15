# 0074 — Run retention with saved-rating meta sidecar

**Status:** Accepted
**Date:** 2026-05-15

## Context

Run logs accumulate without bound. Each play session produces a
`<run-id>.jsonl` plus a paired `<run-id>.log` raw capture under
`data/runs/<character>/`. The `.log` files alone are tens of MB per
multi-hour run, and with the launcher History list (ADR 0073) growing
into a long-tail browser, the on-disk footprint will keep climbing
forever unless we prune.

The natural pairing — automatic retention on most runs, manual keep
for the ones the player cares about — requires two new ingredients:

1. A durable "this one is special" marker per run, set from the
   in-game popup at the end of a session.
2. A retention sweep that respects the marker.

The marker also wants a small rating (0–5) so the player can capture
"that one was epic" alongside "save this for later". That data is not
naturally part of the `run_log` event stream — it is metadata about
the run, set after the run ended, by a human action.

Three design decisions need recording: where the marker lives, who
owns the sweep, and how long the TTL is.

## Decision

### Marker: per-run meta sidecar file

Each saved run gets a sidecar at
`data/runs/<character>/<run-id>.meta.json`:

```json
{"schema": 1, "saved": true, "rating": 3, "saved_ts": 1746644500}
```

**File presence ⇔ saved.** No `"saved": false`. Un-save (a future
feature) deletes the file. The sidecar is paired by run-id with the
`.jsonl` and `.log` triplet.

For an active run the sidecar uses the *computed* run-id (derived from
the first row's `ts`), not the literal `current.jsonl` name. When the
JSONL is sealed it is renamed to `<run-id>.jsonl`; the meta filename
is already correct, so no rename is needed in the seal path.

Producers (the future popup "Save session" flow) write the sidecar
atomically via tmp + `os.rename`.

### Sweep owner: the launcher

The launcher runs a single sweep at boot, before the main menu
renders, via `bridge/launcher/run_retention.py`'s
`prune_expired_runs()`. Wrapped in a broad try/except — retention
failures must never block startup.

Pure library, no UI. Reuses path helpers from `run_stats.py`
(ADR 0065). No scheduling, no recurring task, no in-session pruning.

### TTL: 14 days

Measured from the run-id timestamp (which is `_run_start_ts` at seal
time — deterministic, no JSONL re-read needed). A sealed run older
than 14 days without a `"saved": true` sidecar is deleted along with
its `.log` and any stray `.meta.json`.

### Stitched-chain save granularity

When the popup "Save session" flow lands, it writes one sidecar per
run in the chain (ADR 0056) — not a single session-level sidecar.
Granularity stays at the run level so retention reads one file per
deletion candidate and never needs to walk chains. The "save the
session" UX is implemented in the producer, not in the on-disk
schema.

## Consequences

- **Gained.** Disk footprint bounded by 14 days + whatever the player
  explicitly saves. The on-disk schema is forward-compatible with the
  popup "Save session" flow and a future un-save / re-rate path — the
  retention reader already knows how to read meta files.
- **Gained.** Retention logic lives in one Python module testable
  against a fake `data/runs/`, with a `now` parameter for time
  injection. No Lua-side complexity, no tt++ involvement.
- **Lost.** A run that is silently valuable but unsaved is gone after
  14 days. The 14-day window gives the player two weekly play-cycles
  to mark anything they care about; longer windows just trade disk
  for delayed regret.
- **Cost.** One `os.listdir` per character directory plus per-run
  file ops on boot. With realistic character counts and run counts
  per character the sweep is sub-100ms; it runs once per launcher
  process.
- **Drift risk.** Retention reads `"saved": true` from a file written
  by a separate flow that doesn't exist yet. The contract is
  recorded in `docs/runs.md` and the popup prompt will be built
  against it. If the popup writes a different shape the sweep
  conservatively treats it as unsaved and deletes on age — which is
  loud enough that the bug surfaces immediately.

## Alternatives considered

**Save flag as a JSONL row inside the run log.** Append a
`{"event":"saved", "rating":N, "ts":...}` line to the sealed
`<run-id>.jsonl`. Rejected:

- Mutates a file that the rest of the system treats as append-only
  per-run state (ADR 0044 §"Append-only").
- Forces every retention decision to scan the JSONL for the saved
  marker rather than statting one small sidecar. With a future
  un-save / re-rate flow, mutating the JSONL repeatedly compounds
  the cost.
- Mixes two concerns: in-run gameplay events vs. post-run user
  curation. The sidecar keeps those layered cleanly.

**Per-run-start Lua sweep.** Have `run_log.lua` prune old files at
`run_started` time. Rejected:

- Pulls a retention policy into the latency-sensitive hot path of
  starting a run.
- The launcher already has a guaranteed once-per-cockpit-boot entry
  point; that is the right place for housekeeping.
- A Lua sweep would also need to read JSON meta files from Lua and
  add a fresh persistence surface; Python has `json` in stdlib.

**Unbounded retention (the status quo).** Rejected. Several months
of multi-hour `.log` files in particular blow up the data dir
quickly; the player has no signal that anything is happening until
the disk warning lands.

**Single session-level sidecar** (one meta file per chain). Rejected.
A chain is a consumer-side derived concept; storing the marker at
chain level would make retention walk chains to decide whether any
member is saved. Per-run sidecars keep retention's read model O(1)
per deletion candidate, and the popup's "save the session" UX can
trivially write N sidecars in a loop.

## Relation to other ADRs

- **Builds on [ADR 0044](0044-runs-and-character-scoped-persistence.md)**
  — runs live under `data/runs/<character>/`; sidecars share that
  directory.
- **Builds on [ADR 0056](0056-previous-run-id-linking.md)** — the
  session "Save session" flow saves every run in the stitched chain;
  the chain definition is ADR 0056's `previous_run_id` linkage.
- **Builds on [ADR 0065](0065-run-stats-python-aggregator.md)** —
  retention shares `_DATA_RUNS_DIR` / `_character_dir` / run-id
  helpers with the Python aggregator; same path conventions, same
  filesystem authority.
