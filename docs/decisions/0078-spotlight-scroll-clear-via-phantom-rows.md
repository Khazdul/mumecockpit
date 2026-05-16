# 0078 — Scroll-clear spotlight transitions via phantom blank events

**Status:** Accepted
**Date:** 2026-05-17

## Context

The spotlight reel concatenates per-event log slices into a single
playback timeline ([ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md)).
Adjacent spotlights need visible separation or they bleed into one
another: the `log_view` play-mode renderer auto-scrolls so the
playhead event sits at the bottom of the viewport, which means a
new spotlight's first line would land directly under the previous
spotlight's last line with no break — no fade, no header glow, no
indication a scene change happened.

The same problem applies to the very start of the reel: without
some explicit separator, the first spotlight's pre-roll content
fills the viewport from the top, the info box renders against it,
and the player can't tell when the actual event window begins.

## Decision

**Insert a block of phantom blank `LogEvent`s at every spotlight
boundary** (and 100 more at the start of the reel, before
spotlight 0). The phantoms are created in `SpotlightPlayback.__init__`
and live in the regular `events` list — interleaved with real
events. Each phantom carries:

- `ts_us` = the boundary's playback offset (so all phantoms in a
  block share the same `playback_offset_us`).
- `fragments = [("", " ")]` — a single empty-but-renderable
  fragment so the row wraps to exactly one blank visual cell-tall
  row (the renderer skips zero-width rows).
- `run_id` = the previous spotlight's run_id (or this spotlight's,
  for the leading block) — opaque to playback but must be
  non-empty.
- Zero playback duration (every phantom in a block shares the
  boundary's `playback_offset_us`, so the playback clock crosses
  them in a single tick).

`_LOG_SPOTLIGHT_WIPE_ROWS = 100` is the block size. Phantom indices
are recorded in `phantom_event_indices: set` and queried via
`SpotlightPlayback.is_phantom(idx)`.

The play-mode auto-scroll mechanic does the rest: when the playhead
crosses onto a new spotlight, the 100 phantom rows immediately above
the playhead enter the visible buffer, fill the viewport with blank,
and push the previous spotlight's tail content off the top edge.
Effect: a clean wipe in a single render frame.

## Alternatives considered

**Black-frame flash.** Initially specced — render the log area
fully black for ~500 ms at each boundary, then unfreeze playback.
Implemented and rejected on test play:

- Felt visually jarring rather than clarifying.
- Required anchor-freeze gymnastics in the playback clock so the
  black phase didn't consume the next spotlight's pre-roll time.
- Added a special-case render branch in `_log_view_text_play` /
  `_log_view_text_pause` with no upside over the phantom model
  once the latter was prototyped.

**Terminal-level screen clear (`\x1b[2J`).** Doesn't fit the
log-as-event-buffer model — the buffer is a Python list of
`LogEvent`s wrapped by `prompt_toolkit`, not a live terminal whose
output we control with raw ANSI. A direct escape would fight the
framework.

**No transition (rely on the spotlight info box alone).** Rejected
on direct observation — adjacent spotlights bled together and the
player couldn't tell a scene change had happened. The info box
updating in the corner is not enough signal on its own.

**Single phantom row.** Trialled. A single blank between
spotlights reads as "blank line in the log", not "scene change".
The 100-row block guarantees the viewport fills with blank for at
least one frame at the boundary, regardless of viewport height.

## Consequences

- **The `events` list contains phantoms intermixed with real
  events.** Pause-mode cursor navigation must skip them —
  `_log_is_phantom(idx)` delegates to
  `SpotlightPlayback.is_phantom(idx)`, and `_log_skip_phantoms`
  snaps the cursor to the nearest non-phantom event in the
  direction of travel. The helper short-circuits in chain mode so
  chain-mode behaviour is untouched.
- **Pause-mode scrolling reveals phantom rows as visible blank
  gaps between spotlights.** Accepted — it reads as scene
  separation, not as broken playback.
- **The playback clock is unchanged.** Phantoms have zero
  playback duration, so there is no anchor freeze, no offset
  compensation, no special-case in `_log_current_playback_us()`.
  The first real event of a fresh spotlight fires exactly
  `_PRE_ROLL_S` seconds after the spotlight begins, identical to
  the no-transition case.
- **N/P seeks benefit automatically.** Both keys target a
  spotlight's start offset, which sits just past a phantom block,
  so the wipe occurs on seek without extra plumbing.
- **Scrubber drags benefit automatically.** A drag that drops
  inside a phantom block lands on the boundary offset; the
  playhead-at-bottom auto-scroll fills the viewport with the
  phantom block above and rolls into the spotlight cleanly.

## Relation to other ADRs

- **Builds on
  [ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md).**
  The boundaries this ADR wipes between are the spotlight
  boundaries that ADR's rotation produces.
