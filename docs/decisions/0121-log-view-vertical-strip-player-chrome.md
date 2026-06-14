# 0121 — log_view player chrome: vertical strip + floating controls

**Status:** Accepted
**Date:** 2026-05-30

**Revised 2026-06-14:** Two points are partially revised by ADR 0135:

- (a) Point 6 (chain markers placed by snap-to-nearest-log-line, ~1 s
  precision) is revised for pkill/char_death: they now content-match
  their actual `.log` event line, with the time-snap as fallback;
  achievement/level_up keep the snap.
- (b) The floating event-marker layer is now click-to-seek (revising the
  original "the 2-col strip owns click/drag-to-seek" / marker-layer-
  does-not-seek stance): a discrete marker click seeks to that event via
  the shared `_log_seek_to_offset_us`, mode-preserving and
  bottom-anchored. Drag-to-seek remains the strip's. See
  `docs/launcher.md`.

## Context

The `log_view` player — shared by chain mode (history Run log) and
spotlight mode — drove playback through a **bottom horizontal controls
overlay** (rewind / play-pause / a 30-cell horizontal scrubber / a time
readout) plus a top header, both painted on the cyan-dark
`C_LOG_OVERLAY_BG` panel tint. Three things pushed a redesign:

- **Visual mismatch.** The cyan overlay clashed with the cockpit menus'
  colour language and with the OSC 11 terminal canvas the rest of the
  launcher now blends into (ADR 0099).
- **Font fragility.** The media glyphs (`⏮ ⏸ ▶`, plus `━` / `●` for the
  scrubber) rendered as emoji or tofu on a meaningful fraction of
  terminals/fonts.
- **Intrusiveness.** A bottom bar plus a reserved scrubber width made the
  chrome feel pasted-on rather than part of the canvas.

## Decision

Replace the bottom controls + cyan overlay with:

- A **right-edge vertical strip** — a full-height played/unplayed grey
  track with a sub-row-precise **gold half-block playhead**.
- A small **floating control box** (rewind / play-pause / `MM:SS / MM:SS`
  clock) bottom-right.
- **De-cyaned chrome** — every chrome surface paints its cells in the
  resolved `_terminal_bg` (ADR 0099) so it blends with the canvas instead
  of pasting a panel.
- **K/D/A/L event markers** floated along the strip at event rows.

## Non-obvious calls

1. **Strip + markers are floating overlays over a full-width log, not a
   reserved VSplit column.** The log wraps at the full terminal width;
   the strip and marker layer are pure Floats that occlude the cells
   beneath them while shown. Smallest blast radius (no log-window
   restructuring), the auto-hide reuses the existing header/controls
   Float machinery, and — decisively — on hide the log reclaims the full
   width with no gutter and no reflow. Trade-off: while visible the strip
   covers the rightmost 2 cols and the markers cover a few cells at event
   rows. Accepted.
2. **Auto-hide extended to all chrome at 6 s.** Previously 3 s and only
   the header + controls. The strip is chrome too, so always-on would
   defeat the blend goal; `_LOG_OVERLAY_HIDE_DELAY` is now 6.0 s and
   covers header + strip + marker layer + box together. Permanent in
   pause; any key/mouse activity re-arms via `_log_touch_overlays()`.
3. **Chain opens playing from 00:00** (was paused), matching spotlight
   mode so both entry points behave identically.
4. **Gold is reserved for the strip playhead only.** It is the single
   focus accent; the box play/pause control is grey. One accent reads
   cleaner than two competing golds.
5. **Font-safe glyph set** — `█ ▀ ▄ ► ◄ ┌ ─ ┐ │ └ ┘ ▌`, retiring
   `⏮ ⏸ ▶ ━ ●`. The half-block playhead (`▀` / `▄`, fg+bg both set per
   the half-block convention) also buys 2× vertical resolution at the
   played/unplayed seam.
6. **Chain markers placed by snap-to-nearest-log-line.** Run-archive
   JSONL events carry epoch-second fold-time timestamps;
   `LogPlayback.offset_for_ts_us` snaps each to the nearest `.log` line's
   `ts_us` and returns that line's playback offset, which places markers
   correctly across stitched runs regardless of how gaps are clamped, at
   ~1 s precision. RunStats was insufficient — it retains a timestamp
   only for achievements — so a dedicated four-kind reader,
   `run_stats.marker_events`, feeds `set_marker_events()` once on push.
7. **Spotlight info box shifted left** (`_SPOTLIGHT_BOX_RIGHT =
   _LOG_STRIP_W + 2`) so it coexists with the now full-height strip
   without a wide gap.

## Alternatives considered

- **VSplit reserved column for the strip.** Rejected — it forces the log
  window to reflow and leaves a gutter when the strip hides, the exact
  behaviour the float design avoids.
- **Keep the cyan overlay background.** Rejected — the visual mismatch
  with the canvas-blended menus was a primary driver.
- **Derive chain markers from RunStats.** Rejected — RunStats only
  timestamps achievements, so it cannot place K/D/L markers; hence the
  dedicated `run_stats.marker_events` reader.
- **Colour-coded event letters.** Explored in mockups, dropped for a
  restrained dark-grey rail with the single gold playhead accent — keeps
  gold's focus signal unambiguous.

## Relationships

Builds on ADR 0099 (terminal-bg detection) for the canvas-blended chrome.
Touches the spotlight player (ADR 0077–0080), which shares the same
`log_view` playback engine, overlays, and strip.
