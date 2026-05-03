# ADR 0034 — Clock renderer-side countdown

**Status:** Accepted  
**Date:** 2026-05-03

## Context

The input-pane menu bar displayed a clock countdown (`time_remaining`) that was
pre-formatted as a string by `lua/core/clock.lua` and written into
`bridge/status.state` on every Lua tick. The data path was:

```
4 Hz tt++ ticker → Lua → atomic write → 250 ms mtime poll → renderer
```

This introduced variable phase between the wall-clock second boundary and when
the rendered value changed. The mtime poll fires at an arbitrary offset relative
to the second boundary, so any write that lands just after a poll fires won't
display until the next poll ~250 ms later. Combined with the 4 Hz Lua ticker
(which itself has phase relative to real seconds), the displayed counter could
skip a second (~700 ms between decrements) or hold for two (~1300 ms). This
was visible to the user as an unsteady clock.

## Decision

Move the countdown computation into the renderer. Lua publishes a target epoch
(`time_transition_at`) and precision flag (`time_precision`) instead of a
pre-formatted countdown string. The renderer computes:

```python
remaining = max(0.0, time_transition_at - time.time())
```

and formats per precision. A new async task (`_clock_tick`) wakes just after
each wall-clock second boundary and calls `app.invalidate()`, ensuring the
countdown decrements at exactly 1 Hz with uniform cadence.

### Schema change (`bridge/status.state`)

Dropped: `time_remaining`  
Added: `time_transition_at` (unix epoch int), `time_precision` (`"MINUTE"`/`"HOUR"`)  
Unchanged: `time_period`

### `next_transition()` API change (`lua/core/clock.lua`)

Old return shape: `{ period, remaining }` (remaining was a pre-formatted string)  
New return shape: `{ period, at, precision }` (at is a unix epoch integer)

`bridge/status.state` is gitignored and regenerated each session; no migration
path is needed.

## Rationale

Renderer-side compute eliminates phase wobble. `time.time()` drives both the
sleep target in `_clock_tick` and the displayed countdown, so they are always
coherent — the displayed second decrements at the same instant the sleep fires.

The pattern mirrors the buffs blink fix (ADR 0033): the blink state was moved
from Lua into a renderer-side timer for the same reason. `_clock_tick` is
structurally identical to the `_blink_tick` in `bridge/buffs_pane.py`.

The 250 ms mtime poll is retained. Its role for clock updates narrows to picking
up changes in the transition target itself (rare: only on day/night flips or
precision upgrades). It continues to handle all other menu fields unchanged.

## Consequences

- At MINUTE precision the clock decrements once per real second with visibly
  uniform cadence; HOUR precision (`~N`) behaviour is unchanged.
- `next_transition()` is an internal API; low-impact change.
- `_clock_tick` keeps firing even when `status.state` hasn't changed (e.g. at
  HOUR precision where the target is hours away).

## Rejected alternatives

**Boundary-aligned invalidate without schema change.** Half-fix: the file-poll
lag remains in the path. A write that lands just after a boundary still shows
stale until the next boundary tick.

**Tighten the mtime poll to ~50 ms.** Reduces average lag but doesn't fix the
variable-phase root cause; also increases CPU wake-ups by 5×.

**Dedicated `bridge/clock.state` for the transition target.** No benefit over
reusing `status.state`; would add a third state file to the input-pane poll
loop.
