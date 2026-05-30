# 0122 — Credits as a standalone launcher entry; spotlight reel ends in pause

**Status:** Accepted. Supersedes [ADR 0080](0080-end-of-reel-credits.md).
**Date:** 2026-05-30

## Context

[ADR 0080](0080-end-of-reel-credits.md) made the spotlight reel auto-roll
into a scrolling credits chronicle as its closing beat. The chronicle was
reachable **only** by playing or seeking the reel to its end, which then
auto-transitioned `log_view` → `credits`.

Two problems surfaced in practice:

- **The chronicle is the revisitable part, but it was gated.** The reel is
  a one-shot watch; the credits chronicle is the thing a player wants to
  return to. Hiding it behind watching (or scrubbing) the whole reel made
  the more durable artifact the harder one to reach.
- **The end-of-reel build under-reported deeds.** The credits were
  generated from the reel's *playable* spotlight list — events whose `.log`
  window came back empty are dropped from the reel
  ([ADR 0079](0079-spotlight-pre-roll-trim-post-roll-unclamped.md)), so
  they never appeared in the chronicle either, even though they are real,
  tracked deeds.

## Decision

Promote credits to a **standalone top-level main-menu entry** ("Credits",
positioned between Spotlights and About), and stop the reel from rolling
into it.

- `_enter_credits()` builds the chronicle from `aggregate_spotlights()` +
  `generate_credits_lines()` with **no `.log` loading**. It therefore
  chronicles **all** tracked events (respecting the Options → Spotlights
  toggles), including the empty-window events the reel drops per ADR 0079.
- An empty result routes to a new `credits_empty` frame mirroring
  `spotlights_empty` (with `no_data` / `filtered` variants).
- The reel no longer transitions into credits. `_log_auto_pause_at_end()`
  in spotlight mode now parks-and-pauses on the last spotlight, identical
  to chain mode. The `→` / `►`-at-last-spotlight "jump to credits"
  affordance and `_log_spotlight_jump_to_credits()` are removed.

## Consequences

- **Credits is reachable directly and cheaply** — aggregation only, no
  eager log-load — instead of requiring a full reel watch or scrub.
- **The chronicle now covers more events than the old end-of-reel credits
  did.** It can be non-empty even when the Spotlights reel itself is empty
  (every `.log` window came back empty) — arguably more correct for a
  "deeds" chronicle, which only needs event metadata, not playable log
  windows.
- **ADR 0080's end-of-reel closing beat is gone.** The "reel just stops"
  concern that 0080 set out to fix is now met differently: the reel has a
  defined paused end-state (park-and-pause on the last spotlight), and the
  chronicle is a deliberate, always-available menu choice rather than an
  end-of-reel surprise.
- **The credits frame now has a single entry point.** Consequently
  `_log_auto_pause_at_end()` collapses to one park-and-pause branch with no
  spotlight-mode special case.

## Alternatives considered

**Keep both the standalone entry and the end-of-reel auto-credits.**
Rejected: two entry points for one frame, and the end-of-reel build (the
reel's playable subset) would diverge from the standalone build (all
events) — the same frame would show different content depending on how you
arrived. One canonical path is clearer.

**Standalone credits built from the reel's playable subset** (load logs,
mirror the reel's empty-window drop). Rejected: a needless eager log-load
for a chronicle that only needs metadata, and it would carry forward the
ADR 0079 drop, under-reporting deeds whose `.log` window is empty.

## Relation to other ADRs

- **Supersedes [ADR 0080](0080-end-of-reel-credits.md)** — the
  end-of-reel auto-roll into credits is removed.
- **Interacts with
  [ADR 0079](0079-spotlight-pre-roll-trim-post-roll-unclamped.md)** — the
  standalone credits path deliberately does **not** mirror the reel's
  empty-window drop, so it chronicles events 0079 excludes from the reel.
- **Builds on [ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md)**
  for aggregation scope (`aggregate_spotlights()`) and
  **[ADR 0069](0069-launcher-prompt-toolkit.md)** for the frame-stack and
  key-binding patterns the standalone `credits` / `credits_empty` frames
  use.
</content>
</invoke>
