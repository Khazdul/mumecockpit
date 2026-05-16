# 0079 — Spotlight pre-roll trim; post-roll left unclamped

**Status:** Accepted
**Date:** 2026-05-17

## Context

A spotlight's nominal window is `[event.ts − 10 s, event.ts + 5 s]`
— 10 seconds of pre-roll context before the moment, 5 seconds of
post-roll dwell afterwards
([ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md)
covers why each event gets its own window).

The naive renderer ran into two distinct edges:

1. **Empty pre-rolls.** Events near the start of a run, or events
   that follow a long quiet period (e.g. an achievement triggered
   while idle), can have a nominal 10 s pre-roll containing zero
   `.log` lines. The naive render is a blank viewport with the
   info-box countdown ticking down — feels broken, like playback
   has frozen.

2. **Quiet post-rolls.** Some events have nothing in the `.log`
   for several seconds afterwards (e.g. an achievement followed by
   travel, a death followed by the death-screen formatting). If
   we treat the post-roll the same way as the pre-roll and clamp
   it to the last visible log line, the post-roll collapses to
   ~0 s and the next spotlight begins almost immediately — the
   moment doesn't land.

Both happen on real `.log` files in the captured runs we have.

## Decision

**Pre-roll: trim forward to the first log line.**
`load_spotlight_log_events()` advances `window_start_us` to the
first `.log` line's `ts_us` within the nominal 10 s window when
that line is later than the nominal start:

```python
first_log_ts_us = sliced[0].ts_us
if first_log_ts_us > win_start:
    win_start = first_log_ts_us
```

The info-box countdown recomputes from the trimmed window, so it
reflects the actual time-to-event from the first visible line
rather than a frozen-looking lead-in.

**Post-roll: never clamp.** `window_end_us = event.ts*1e6 + 5_000_000`
is the spotlight's end offset regardless of whether any log lines
fall in that 5 s. If the `.log` goes silent after the event, the
playback dwells on the last visible line for the full 5 s before
the scroll-clear transition
([ADR 0078](0078-spotlight-scroll-clear-via-phantom-rows.md)) fires.

**Aggregation-time vs load-time split.** The aggregator only
computes the nominal window from `event.ts ± _PRE_ROLL_S /
_POST_ROLL_S` — it does not touch the `.log`. The trim happens in
`load_spotlight_log_events()`, after the `.log` is parsed and
sliced. This keeps aggregation cheap (it can skip log parsing
entirely for the discoverability/empty-state probe) and pushes the
window adjustment to the point where the log content is known.

## Alternatives considered

**No trim — fixed 10 s pre-roll always.** Rejected after test
play. Leading silence with the countdown ticking felt like a
frozen viewport, and the player learned to skip the first few
seconds of every spotlight — wasted reel time.

**Symmetric trim on the post-roll** (clamp `window_end_us` back to
the last visible log line). Considered briefly. Rejected: the
post-roll's purpose is "let the moment settle", which is
meaningful even with no new lines. Clamping it would collapse
quiet post-rolls to zero — visually identical to the bug we just
fixed on the pre-roll side, but at the end of the scene instead
of the start.

**Drop spotlights with empty pre-rolls entirely.** Rejected.
Achievements and level-ups can legitimately fire in quiet
contexts, and they are still worth replaying — the highlight is
the event itself, not the surrounding chatter. Trimming the
pre-roll preserves the event with a tight, non-frozen lead-in;
dropping the spotlight throws away a real highlight.

**Trim the post-roll only when the next spotlight is from the
same character.** Considered as a way to reduce idle dwell when
the rotation produces same-character adjacency. Rejected — the
asymmetry (post-roll length depends on the neighbouring
spotlight) is harder to reason about than "5 s, always", and the
phantom-row transition already gives a visible scene break even
between same-character spotlights.

## Consequences

- **Countdown duration varies per spotlight.** Often less than
  10 s; occasionally ~0 s when the event itself is the first
  thing in the log slice. The info-box countdown reads the
  trimmed window directly via
  `SpotlightPlayback.event_progress(spot, offset_within)`, so the
  number is always honest.
- **`window_end_us` is load-bearing for the playback boundary.**
  `SpotlightPlayback` anchors inter-spotlight phantoms at
  `cursor_us + (window_end_us - window_start_us)`, not at the
  last log event's offset. This is what guarantees the 5 s
  post-roll dwell even when there are no log lines in it; a future
  refactor that walks from the last event instead would silently
  re-introduce the collapsed-post-roll bug.
- **Empty windows are still dropped.** Spotlights whose
  *entire* 15 s nominal window contains zero log lines (typically
  clock-skew artefacts) leave `spotlight.log_events` empty and
  are dropped by `_enter_spotlights()`. The trim only fires when
  there is at least one line in the window.
- **Aggregation stays cheap.** The `aggregate_spotlights()` pass
  doesn't open `.log` files; it only walks JSONLs. Log parsing
  happens once per `.log` (cached in the `_enter_spotlights`
  `cache` dict) during the eager pre-load that precedes
  `_enter_log_view_spotlight()`.

## Relation to other ADRs

- **Builds on
  [ADR 0044](0044-runs-and-character-scoped-persistence.md).**
  The `.log` files this ADR slices are the per-character logs
  defined there; the timestamp model (`ts_us` monotonic ascending)
  is what makes the `bisect_left` / `bisect_right` slice safe.
- **Anchors to
  [ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md).**
  The window asymmetry only matters once we have multiple
  spotlights in a reel; the per-event model is what produces the
  cases where pre-rolls collide with run starts and post-rolls
  trail into silence.
- **Interacts with
  [ADR 0078](0078-spotlight-scroll-clear-via-phantom-rows.md).**
  The transition phantoms sit between spotlights at the
  `window_end_us` boundary; the unclamped post-roll guarantees
  there is real dwell time before the wipe fires.
