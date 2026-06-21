# 0138 — Character pane palette-derived stepped gauges

**Status:** Accepted
**Date:** 2026-06-16

## Context

The Character (status) pane rendered its lower half with fixed colours:
magenta/teal session-gain (XP/TP) bars, gold/brown colour-coded toggle text,
and flat `LABEL: value` rows for mood, alertness, wimpy, and position. None of
these retinted with the per-pane colour (ADR 0086) or with `terminal_bg`
(ADR 0099) — they stayed magenta/teal/gold regardless of the chosen pane hue or
a tinted terminal under the "None" pane colour. The flat ordinal rows also
conveyed neither the scale (how many steps a stat has) nor the current step
well: "MOOD: wary" tells you the value but not where it sits on the range.

## Decision

- **Palette-derived shade ramp.** `pane_frame.pane_shades` walks one hue down a
  lightness ramp — `track`, `dim`, `mid`, `paneBg`, `vtext`, `label`, `glow`.
  The hue is the pane colour's `(h,s)`, or `terminal_bg`'s when the pane colour
  is "None"; `(h,s)` is restated at each step (`PANE_SHADE_HS`, ADR 0126).
- **Two-level semantics.** `track` is base/off (value bars, inactive ticks,
  toggle off-box); `glow` is active (active step-tick, wimpy caret, on-box).
- **XP/TP bars** retint from the ramp (`track`/`dim`, `dim`/`mid`), replacing
  the fixed magenta/teal.
- **Toggle row → filled boxes** (off=`track`, on=`glow`) with inverted `paneBg`
  labels, replacing the gold/brown colour-coded text.
- **2×2 stepped-gauge block** for mood/alertness/wimpy/position: a centered
  `dim` label, a centered `vtext` value on a `track` bar, and `▀` step-ticks
  drawn on the real pane background (active `glow` / inactive `track`). Wimpy is
  continuous — a single `glow` caret at `wimpy/maxhp` — which required
  serialising `maxhp`.
- **Column geometry.** `_two_cols` (`col_left = c1+c2+1`, `col_right = c3+c4+1`)
  aligns the gauge gap with the caps RIDE/CLIMB gap at any width, refining
  ADR 0023's uniform split.
- **Level badge** `L<level>` on the name row; the player name uses the `label`
  shade.
- Content grew 6 → 9 rows; `desired_status` / `MIN_HEIGHT[status]` bumped
  accordingly (ADR 0071).

## Consequences

- The whole lower half retints with the pane colour, and with a tinted terminal
  under the "None" colour — closing the gap that left magenta/teal/gold fixed.
- Pure UI/state: no tt++ hot-path cost. `maxhp` and `level` come from existing
  GMCP; only their serialisation was added.
- +3 content rows raises the pane's desired/min height (ADR 0071).
- The shade ramp is reusable by the other right-column panes.

## Alternatives considered

- **A fixed gold accent** for the active state — rejected; it would not retint,
  so the highlight folds into `glow` to show the chosen colour instead.
- **Filled proportional bars per stat** — too loud; the four bars dominated the
  pane.
- **A single glowing marker / `▲` pointer / intensity-ramp text / fill+text
  combos** — none conveyed granularity *and* position the way discrete ticks
  do.
- **Left-aligned labels and values** — centered won for the boxes and gauges.
- **A `paneBg`-shade fill behind the ticks** — drawing the ticks on the real
  pane background reads cleaner, with nothing competing behind them.
- **A dedicated self-HP bar** — declined; the four stepped states plus the
  continuous wimpy caret sufficed.

## References

ADR 0086, 0099, 0136, 0126, 0023, 0071.

## Amendment — 2026-06-21

The shade ramp now has a light-background variant. `pane_shades` carries two
ramp tables (`_RAMP_DARK` / `_RAMP_LIGHT`); the light variant reflects the
lightness (light fills, dark text) so the gauges blend into a light pane. The
variant is chosen per frame from the pane's own effective background. See
[ADR 0145](0145-light-background-theming.md).
