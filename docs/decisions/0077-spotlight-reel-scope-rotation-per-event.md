# 0077 — Spotlight reel: scope, rotation, and one-event-per-spotlight

**Status:** Accepted
**Date:** 2026-05-17

## Context

The launcher's Spotlights surface is a cross-character "highlights
reel" playable in the same `log_view` engine that powers History's
chain log player. Building it required three design calls before any
rendering work could start:

1. **Whose runs feed the reel.** Per-character only (mirroring
   History), or cross-character?
2. **In what order spotlights play.** Strict chronological, strict
   round-robin, or something biased toward recency?
3. **How to handle multiple events close together in time.** Merge
   them into a single multi-event spotlight, or leave them as
   separate adjacent spotlights?

The four tracked event kinds — `char_death`, `level_up`, `pkill`,
`achievement` — already exist in the JSONL schema introduced by
[ADR 0044](0044-runs-and-character-scoped-persistence.md); the
data layer for reading them is the same pattern as the popup
Statistics aggregator ([ADR 0065](0065-run-stats-python-aggregator.md))
but scoped one level higher (every character, not the current run).

## Decision

**Cross-character aggregation.** `aggregate_spotlights()` in
`bridge/launcher/spotlights.py` walks
`data/runs/<character>/*.jsonl` for every character (skipping
`current.jsonl` and runs whose paired `.log` is missing), extracts
the four tracked event kinds, and merges the per-character
spotlight queues into a single reel.

**Newest-first round-robin rotation.** Each character's spotlights
are sorted newest-first by event timestamp; the merge picks the
queue whose head has the most recent timestamp at each step, but
skips the previous pick when an alternative exists. Pseudocode:

```python
queues: dict[character, deque[Spotlight]]  # newest-first per char
reel = []; last_char = None
while queues:
    candidates = list(queues)
    if last_char in candidates and len(candidates) > 1:
        candidates = [c for c in candidates if c != last_char]
    pick = max(candidates, key=lambda c: queues[c][0].events[0].ts)
    reel.append(queues[pick].popleft())
    last_char = pick
    if not queues[pick]:
        del queues[pick]
```

**One spotlight per event.** Every tracked event is its own
`Spotlight` with a nominal `[event.ts − 10 s, event.ts + 5 s]`
window. Two events from the same character within ~15 s become two
back-to-back spotlights for that character (the rotation rule
permits same-character adjacency when no other character has a
newer pending spotlight). No merging.

## Alternatives considered

**Per-character only (History-style listing).** Rejected — the
point of a highlights reel is to surface the best moments across
the player's roster. Per-character filtering may land later as an
optional view, but it is not the default.

**Strict chronological global ordering.** Rejected — a single
prolific character would dominate consecutive stretches, and early
playtesting felt monotonous: the reel turned into a one-character
biography until that character ran out of events.

**Strict round-robin without newest-first preference.** Rejected —
the reel's primary use case is "show me what's been happening
recently across my characters", and a strict round-robin spreads
old material from a long-inactive character across the recent
material from active ones. Newest-first preference surfaces recent
play while still alternating characters.

**Merge events within 15 s into multi-event spotlights.** Initially
specced and partially implemented. Rejected after test play: when
two events fell inside one ~15 s window, the merged spotlight
collapsed each event's 5 s post-roll into the next event's
pre-roll, so the second event got no breathing room. Salvaging
the merge model required rendering discrete sub-scenes per event
with seeks back in log time — visually confusing (the playhead
appeared to jump backwards inside one "spotlight") and more
complex than the per-event model. Per-event spotlights with the
rotation rule deliver the same density of content with cleaner
scene boundaries.

## Consequences

- **Same-character adjacency is allowed and intentional.** Two
  events from one character within ~15 s play as two consecutive
  spotlights for that character (the rotation rule explicitly
  permits this when no other queue has a newer head). This is
  cheaper, more honest, and visually clearer than merging.
- **Each event gets its full window.** Pre-roll and post-roll are
  per-spotlight, not per-event-within-a-spotlight, so the 5 s
  post-roll always lands regardless of neighbouring events.
- **Reel length scales with bursty clusters.** A character who
  level-ups three times in quick succession contributes three
  back-to-back spotlights; the reel grows but each scene stays
  clean.
- **Aggregation is cheap and stateless.** The aggregator re-reads
  every sealed JSONL on each call; no incremental cache, no
  watcher. Acceptable at launcher-frame scale — invoked once on
  Spotlights menu push.
- **Empty queues short-circuit naturally.** A character with no
  tracked events contributes no queue; an empty reel triggers the
  `spotlights_empty` frame from `_enter_spotlights()`.

## Relation to other ADRs

- **Builds on
  [ADR 0044](0044-runs-and-character-scoped-persistence.md).** The
  per-character sealed JSONL files this aggregator reads are the
  same files defined by that ADR; `_extract_events` consumes the
  schema unchanged.
- **References
  [ADR 0056](0056-previous-run-id-linking.md).** Run-to-run
  stitching is unused at the spotlight scope (each spotlight is a
  per-event window inside a single run), but the per-run files
  this ADR aggregates over are the same units chained elsewhere.
- **Mirrors the pattern from
  [ADR 0065](0065-run-stats-python-aggregator.md).** Same
  aggregator-in-Python shape (pure library, no Lua, no runtime
  state file); same drive-by-read-on-call model. The data layer
  is shared on the per-character JSONL contract, not on a common
  module.
