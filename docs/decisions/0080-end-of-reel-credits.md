# 0080 — End-of-reel scrolling credits

**Status:** Accepted
**Date:** 2026-05-17

## Context

The spotlight reel
([ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md))
plays a stitched sequence of per-event windows separated by
scroll-clear wipes
([ADR 0078](0078-spotlight-scroll-clear-via-phantom-rows.md)). When the
reel reaches `total_duration_us`, the existing
`_log_auto_pause_at_end()` hook used to park on the final log line and
flip to pause — identical to chain-mode behaviour. That worked, but
the reel **just stopped**: no closing beat, no acknowledgement that
the player had just watched a chronicle of their characters' deeds.

The reel deserves a payoff. We also have, by the end of the reel, a
ready-made data structure (the loaded `Spotlight` list) summarising
every tracked event across every character — exactly the material a
chronicle needs.

## Decision

**Roll a Pratchett-flavoured scrolling chronicle as the reel's
closing scene.** Auto-transition from `log_view` to a new `credits`
frame the moment the reel ends.

**Frame mechanics.**
- Fully black canvas (`bg:#000000`), full-screen.
- Text scrolls bottom-to-top at `_CREDITS_SCROLL_ROWS_PER_SEC = 3.0`
  rows/sec. The animation is row-quantised: at this rate the integer
  scroll offset advances every ~333 ms, so most ticks of the 15 Hz
  redraw loop just confirm the current frame is still valid.
- Fade bands at the bottom (`tr / fb`) and top
  (`(n - 1 - tr) / fb`) `_CREDITS_FADE_BAND_FRAC = 18%` of the
  viewport; middle is solid white. Brightness collapses to a
  hex `#vvvvvv` SGR string per terminal row.
- ESC pops back to the launcher main menu at any time. Mouse
  events do nothing. No other keys are bound.
- Auto-exit when the last credit line has scrolled clear of the
  top of the viewport (offset_floor ≥ `len(_credits_lines) +
  term_rows`).
- A dim `Escape to exit` hint is rendered as a Float above the
  scroll content (2 cells from the right edge, 1 row from the
  top, `fg:#555555 bg:#000000`) — pinned, never faded, never
  clobbered by the scroll text.

**Narrative generation.**
- Pure library at `bridge/launcher/credits.py`:
  `generate_credits_lines(spotlights, text_width) -> list[str]`
  returns a flat list of wrapped strings, one per visual line.
- Events are grouped by character; characters appear in
  oldest-first order (the character whose oldest event is oldest
  opens the chronicle). Within each character, events run
  chronologically.
- Each event becomes a complete narrative sentence chosen from a
  per-kind template list (PvP, death, level-up, achievement).
  Template choice is **deterministic** per event: an md5 hash of
  `(character, run_id, event.ts, event.kind)` modulo the list
  length picks the index, so the same event reads the same way
  across multiple runs of the credits.
- Each character gets a chapter header (deterministic on
  character name) with 3 blank rows above and 2 below.
- Opening line `Herein are recorded the deeds of your characters.`
  with 5 blank rows above and below. Closing line `The End.` with
  5 blank rows above. Trailing pad of `term_rows` blank rows is
  appended at frame-entry time so the closing line scrolls fully
  off the top before auto-exit fires.
- Dates render as `"<ordinal> of <Month>, <Year>"` (e.g. `"first
  of May, 2026"`) using an `_ORDINAL_WORDS` map for days 1–31.

The Pratchett register — understated, slightly wry, affectionate
toward the player — is set entirely in the template wording. There
is no template-selection logic that varies wording by anything
other than the deterministic hash; we deliberately accept the
occasional awkward pairing of a particular template with real
game data, and address it by refining the template list rather
than adding runtime conditions.

## Alternatives considered

**Static stats summary** (totals: deaths, kills, levels, etc.).
Rejected: not filmic; redundant with the History → stats panel
which already aggregates the same numbers in a richer form. The
reel's value is narrative, not quantitative.

**Highlight-reel loop** — replay the spotlight reel from the
beginning, or loop the most dramatic 2–3 spotlights. Rejected:
gets boring fast on the second pass, doesn't add narrative, and
doubles back through content the player has just watched.

**Just-ESC-out** — keep the existing chain-mode behaviour and
park on the last event with `End of session` in the header.
Rejected: the reel is curated content, not a raw log; ending on
"playback paused" undersells what just played. The reel deserves
a closing beat.

**Per-event runtime template selection** (e.g. prefer
"battle"-themed wording when the previous event was also a
death). Rejected for v1 — adds complexity, and the determinism
across runs is part of the appeal (the player learns "their"
chronicle's voice). If specific pairings read awkwardly, the
template list is the place to address it.

**Hold delay between last spotlight's post-roll and credits.**
Rejected as the default: the credit lines fading in at the bottom
already provide a natural transition out of the spotlight scene.
If it feels abrupt in practice we can revisit.

## Consequences

- **Credits length grows with event count.** A player with 200
  tracked events across several characters could see several
  minutes of credits; one with thousands could see tens of
  minutes. ESC always exits immediately, so this is a tolerable
  edge.
- **Determinism on template choice means occasional awkward
  pairings** between wording and game data (e.g. a death template
  whose dry tone reads oddly for what was actually a player's
  most tragic moment). The remedy is template refinement in
  `credits.py`, not runtime logic.
- **The auto-trigger is load-bearing for the closing beat.**
  `_log_auto_pause_at_end()` now branches on `_log_view_mode`:
  chain mode parks on the final event (unchanged); spotlight
  mode cancels playback, pops `log_view`, and pushes `credits`
  with the reel's spotlight list. A future refactor that
  shortcuts this hook for spotlight mode would silently restore
  the "reel just stops" behaviour.
- **The `credits` frame is the second prompt_toolkit frame in
  the launcher to own its own asyncio tick task** (after
  `log_view`'s 30 Hz redraw). The tick is cancelled on frame
  pop and on `_credits_finish()`.

## Relation to other ADRs

- **Closes the spotlight feature set opened by
  [ADR 0077](0077-spotlight-reel-scope-rotation-per-event.md).**
  ADR 0077 defined the reel scope and rotation; ADR 0078 defined
  the inter-spotlight scroll-clear; ADR 0079 the window trim
  asymmetry. This ADR defines what happens after the last
  spotlight ends.
- **Composes with
  [ADR 0078](0078-spotlight-scroll-clear-via-phantom-rows.md).**
  The phantom-row wipe between the last spotlight and the credits
  is not strictly needed — the credits frame paints over the
  entire viewport on its first render — but the existing
  post-roll dwell still applies, giving the last spotlight's
  content a beat to settle before the canvas flips to black.
- **Reuses
  [ADR 0069](0069-launcher-prompt-toolkit.md) frame-stack and
  key-binding patterns.** `credits` is a regular frame on the
  stack with its own `_in_frame("credits")` ESC binding;
  `_reset_to_main()` returns from credits to the launcher main
  menu, since the previous stack entry was `log_view` and we
  popped it before pushing `credits`.
