# 0027 — Drop-driven affect expiry with 2.5× safety timeout

**Status:** Accepted
**Date:** 2026-04-29

## Context

The tick prune at `expires_at` evicted affect entries before `affect_down`
could fire and record the actual duration. This created a self-reinforcing
under-prediction loop: short samples (entries pruned early) drove
`expected_duration` below reality, which set `expires_at` even earlier,
which caused even earlier pruning, preventing longer samples from ever being
recorded.

Affects with a `dropString_*` in the data table have a reliable in-game
expiry signal. The only reason to tick-prune them is as a guard against
missed drops — not as the primary expiry mechanism.

## Decision

For affects with a configured `dropString_1` or `dropString_2`, the drop
message is the sole expiry source. The tick keeps overrun entries
(`expires_at <= now`) alive so that `affect_down` can record the true
observed duration. The tick acts only as a 2.5× safety net: if
`now - started_at >= floor(2.5 × expected_duration)` the entry is silently
pruned with no ring-buffer sample and no `affect_ui` "down" line.

Affects without a drop string keep the previous behaviour: tick-prune at
`expires_at`, no sample recorded.

`status_state.lua` no longer clamps `remaining_seconds` to 0; negative values
signal overrun. The status pane renders overrun cells with `!` in place of `Xm`.

## Consequences

- Observed durations that exceed the current `expected_duration` are now
  captured, breaking the under-prediction loop.
- Status pane shows `!` for any affect in overrun, giving the player a visual
  cue that the drop is imminent.
- Overrun entries that survive a disconnect are expired by `_load_active`'s
  `expires_at <= now` guard on the next login — desired, since we have no
  signal whether the drop fired during downtime.

## Alternatives considered

**Record sample at tick prune.** The tick never has a confirmed drop, so the
prune time is not the true duration — it perpetuates the under-prediction even
if the value improves. Rejected.

**No safety net.** A missed drop (server bug, ANSI colour variant, pattern
miss) would leak the entry in memory indefinitely. Rejected.

**2× multiplier.** Still cuts legitimate long-tail samples — some affects run
20–30 % over mean. 2.5× gives comfortable clearance while still bounding the
worst-case leak. Rejected.

**Explicit `overrun` boolean field in the state entry.** Adds schema surface
for a signal already carried by `remaining_seconds <= 0`. Negative
`remaining_seconds` is unambiguous and the renderer already reads the field.
Rejected.
