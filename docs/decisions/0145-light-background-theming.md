# 0145 — Light-background theming toolkit and per-pane effective-bg authority

**Status:** Accepted
**Date:** 2026-06-21

## Context

The cockpit gained a light ("paper") terminal background (ADR 0143) and
per-pane colour overrides (ADR 0086). Every colour and palette in the UI had
been derived for a dark canvas, and they wash out or read harshly on a light
background — or on a pane that carries its own light colour. The affected
surfaces span the whole stack:

- the pane shade ramp (ADR 0138), whose lightness ramp assumed dark fills;
- the timers and comm semantic colours;
- the UI base-text ANSI baked into `logs/ui.log` by the Lua emitters;
- the group bars;
- the frame borders;
- the input clock.

A light background is not a single global flag, because a pane can override its
own colour: one pane may be light while the terminal — and its neighbours — stay
dark, and vice versa.

## Decision

A light-mode colour toolkit lives in `pane_frame`, with a single per-pane
authority that every light/dark decision derives from:

- **`effective_bg(pane_key)`** — the pane's OWN background: `PANE_FILL_COLORS`
  for a named pane colour, or the live terminal background for
  terminal-default / unknown. This is the single source every light/dark
  decision derives from.
- **`is_light_bg`** (HSL lightness > 58) is the threshold;
  `pane_is_light(pane_key) = is_light_bg(effective_bg(pane_key))`.
- **`pane_shades`** carries two ramp tables (`_RAMP_DARK` / `_RAMP_LIGHT`). The
  light variant reflects the lightness (light fills, dark text) so the gauges
  blend into a light pane.
- **Transforms**, each moving a colour toward a target rather than blindly:
  - `light_shift` — darken + saturate a foreground, one-directional toward a
    target, for text painted on the canvas;
  - `washout` — desaturate + lighten, for fills;
  - `darken` — for the frame border;
  - `dark_ink` — bg-tinted, washed-out `l=40`, for body-text ink.
- **Achromatic overrides.** Colours the saturation transforms cannot help
  (white has no hue to shift) get explicit overrides — the UI bright-white base
  text maps to `dark_ink`.
- **Display-time remap.** UI colours baked into the persisted `logs/ui.log` by
  the Lua emitters are remapped at DISPLAY time in `ui_pane` (`_recolor`),
  keeping the log canonical and the colour work in the layer that can see the
  background.

## Principles learned

1. **The decision derives from the pane's OWN effective bg, not the
   terminal's.** An earlier version gated on the terminal background and assumed
   a named pane colour was always dark. That was wrong the moment a pane carried
   its own light colour. Resolving against `effective_bg(pane_key)` fixes it.
2. **Resolve per frame, not once at module load.** The pane colour is
   live-mutable (`terminal_bg` is static; the pane colour is not). An earlier
   version resolved the light/dark decision once at load, which left
   comm / group / ui stale after a live colour change while char / timers
   (already per-frame) flipped correctly. Every colour derived from the decision
   must be resolved per frame.

## Consequences

- Pure UI/state: no tt++ hot-path cost.
- A future light *named* pane colour works with no further code — the toolkit
  keys off `effective_bg`, not a hardcoded set of light names.
- Every light/dark-derived value is recomputed per frame, a negligible cost on
  these panes.
- The toolkit (transforms + `effective_bg` / `pane_is_light`) is reusable by any
  pane.

## Alternatives considered

- **A grand unified "semantic colour → theme resolver"** spanning
  panes / launcher / Lua. Rejected: over-engineering for a single light
  background, and it crosses package/layer boundaries. Per-pane application of a
  shared primitive is right-sized.
- **A pure mirror of the ramp (`L' = 100 − L`).** Rejected: it broke the
  dual-role shades (the `dim` hinge that serves two purposes). A tuned
  `_RAMP_LIGHT` table was used instead.
- **Making the Lua UI emitters background-aware.** Rejected: cross-layer (Lua
  cannot see the terminal background) and it would bake a transient display
  setting into the canonical log (cf. ADR 0013). The remap belongs at display
  time.
- **A blind darken/desaturate of every colour.** Rejected: it over-darkens
  already-dark colours and murders muted / recede ones (comm `C_TIME`). The
  transforms move toward a target instead.

## References

- Extends [ADR 0138](0138-character-pane-palette-gauges.md) — the shade ramp
  gained a light variant (`_RAMP_LIGHT`).
- Builds on [ADR 0099](0099-terminal-bg-detection-osc11.md) (`terminal_bg`),
  [ADR 0086](0086-panes-grid.md) (per-pane colour),
  [ADR 0126](0126-timers-layout-menu.md) (restated constants), and
  [ADR 0013](0013-comm-display-normalization.md) (canonical log).
