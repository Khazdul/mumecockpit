# 0011 — Per-profile JSONL archive for comm history

**Status:** Accepted
**Date:** 2026-04-26

## Context

The comm pipeline previously had two storage layers:

1. **In-RAM ring buffer** (`state.comm.history`, max 500 entries) — lost on
   every `cp -r` (Lua restart) except for a short-lived recovery path via
   `bridge/comm.state`.
2. **`bridge/comm.state` projection** — a JSON snapshot written on every
   event, read back by `comm_state.lua` on load to repopulate history after
   `cp -r`. This capped history recovery at whatever was in RAM when the
   last restart happened; it was not durable across reboots or long gaps, and
   it carried no per-profile separation.

Two problems motivated a third layer:

- **Short retention.** History visible after `cp -r` was limited to the events
  that had arrived since the last brain start, not a meaningful sliding window.
  A player who disconnects for a few hours returns to an empty comm pane.
- **Profile leakage.** `bridge/comm.state` mixed history from whichever profile
  was active. Switching profiles via the launcher could present a different
  character's communication log to the new session.

## Decision

Add `lua/core/comm_store.lua` — a third comm-pipeline layer that persists
messages to a per-profile JSONL file at:

```
logs/comm_archive/<profile>.jsonl
```

- **Profile** is resolved at startup from `bridge/startup.conf` (`profile=`
  key); falls back to `"default"`.
- **Format:** one JSON object per line, same schema as `state.comm.history`
  entries (`ts`, `channel`, `talker`, `talker_type`, `destination`, `text`).
- **7-day sliding window:** at brain startup, entries with `ts < now - 604800`
  are discarded; the file is atomically rewritten with the pruned set.
- **History seeding:** pruned entries (clamped to `max_size`) replace
  `state.comm.history`; `state.comm.serialize()` is called once so
  `bridge/comm.state` reflects the seeded history before the first pane poll.
- **Append path:** each `Comm.Channel.Text` event appends one JSON line
  (open-append, write, close). No tmp+rename on appends.
- **`max_size` bumped 500 → 1000** to accommodate the larger working set
  that a week of history can produce.

`comm_state.lua` retains ownership of `bridge/comm.state` and channel restore.
History seeding moves entirely to `comm_store.lua`. The two responsibilities are
split at file boundaries so the load-order invariant (alphabetical: `comm_log`
< `comm_state` < `comm_store`) enforces the dependency direction.

## Consequences

- **Archive size is bounded by 7-day activity.** In practice sub-MB. `logs/`
  is gitignored; no repository bloat.
- **Append cost is one line write per event.** No debouncing needed; writes are
  amortised over message arrival rate.
- **Prune cost is O(n) at startup only.** The entire file is read once; all
  subsequent writes in a session are appends.
- **Profile isolation is exact.** Switching profiles via the launcher starts a
  fresh brain process that reads only the new profile's archive. No cross-
  profile leakage.
- **Partial writes are self-healing.** A truncated final line in the archive
  (e.g. from a power loss mid-append) is silently skipped on the next startup
  read; the rest of the file is unaffected.
- **`bridge/comm.state` remains the pane contract.** `comm_pane.py` is
  unchanged; it still polls `comm.state` every 250 ms. The archive is Lua-
  internal.

## Alternatives considered

**Single JSON array per profile.** Storing the entire history as one JSON array
would require reading and rewriting the whole file on every append (O(n) per
event) or maintaining a debounce timer. Rejected: JSONL gives O(1) appends with
no debouncing complexity.

**SQLite.** Full query capability, atomic transactions. Rejected: overkill for
an append-only log with a single reader, and adds a dependency not present
elsewhere in the stack.

**No per-profile separation (current behaviour).** Keeps `bridge/comm.state` as
the sole persistence layer. Rejected: profile leakage across sessions is
confusing, and the comm pane returning empty after a reconnect degrades UX for
players who rely on narrate/tell context.

**Debounced batch write.** Buffer events in RAM and flush every N seconds.
Reduces I/O but risks losing the tail on unexpected exits. Rejected: the per-
event append cost is negligible, and no-loss semantics are more important than
marginal I/O savings on a local filesystem.
