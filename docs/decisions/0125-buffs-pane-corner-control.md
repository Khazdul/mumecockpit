# 0125 — Buffs-pane corner control and single-cell glyph rule

**Status:** Accepted

## Context

The herblore add-view needs a mouse-driven open/close affordance pinned to the
buffs pane's top-right, drawn over a grid of coloured cells. The affordance had
to sit in the true corner regardless of how the grid below it was laid out, and
its glyph had to occupy exactly one terminal column.

## Decision

- The **+ / × corner control** is a single position-pinned `Float` at
  `top=0, right=0` (mode-aware glyph via `_corner_text`), rendered as an
  **inverted gold button** (black glyph on a gold background).
- The **add-view is a *mode*** within the existing pane (a `_view_mode` flag the
  `ListControl` text provider dispatches on), not a separate frame-stack.
- **Single-cell glyphs use plain ASCII/Latin-1** (`+`, `×`), never
  ambiguous-width glyphs.

## Alternatives considered (rejected)

- **Content-coupled overlay** (glyph on the last column of the first visible
  row): tried and reverted — partial grid rows omit their trailing cells, so the
  glyph drifted to mid-pane instead of the true corner. The `Float` decouples
  position from content.
- **A frame-stack à la the launcher's `ingame_menu`:** overkill for a two-state
  toggle.
- **Box-drawing heavy glyphs (╋ / ╳) and ambiguous-width Dingbats/Math glyphs
  (✚ / ✖ / ⊕):** the Dingbats/Math glyphs render double-width in some terminals
  (ambiguous East-Asian width resolved as wide), breaking the 1-column cell;
  box-drawing is reliably single-width but was disliked aesthetically.

## Consequences

- **General rule:** any future single-cell terminal glyph in the cockpit must be
  ASCII or Latin-1 (or independently verified single-width per terminal), never
  ambiguous-width — this avoids repeating the ✚ / ✖ / ⊕ width hunt.
- The inverted gold button does not show the underlying bar colour in its one
  corner column (accepted).
- The hover cue freezes when the pointer leaves the pane via an edge (terminals
  send no off-pane mouse events) — a known, accepted limitation across panes.

Cross-reference [docs/buffs-pane.md](../buffs-pane.md).

## Update — corner styling reverted

The inverted gold-button styling (black glyph on a gold background) was reverted
to a **gold foreground glyph on the terminal/pane background**, with hover
brightening the foreground (`C_ACCENT_FG` → `C_ACCENT_HOVER_FG`).

The rest of this ADR stands unchanged: the `Float` pinning at `top=0, right=0`,
the add-view-as-mode decision, and the ASCII/Latin-1 single-cell glyph rule are
unaffected. The "no underlying bar colour in the corner column" consequence still
holds — the `Float` paints the default bg.

## Update (2026-06-14) — corner offsets inside the in-pane frame

With the in-pane pane frame ([ADR 0136](0136-in-pane-borders.md)), the timers
pane gains a one-row top border and a one-column left/right edge when its border
is on. The `+`/`×` corner `Float` is therefore re-pinned to `top=1, right=1`
(inner top-right) **when the timers border is on**, so it sits inside the frame
and aligns with a top charm row's drop `×`. `timers_pane.py` updates the `Float`'s
`top`/`right` each tick from `pane_frame.frames_enabled("timers")`; `pane_frame`
polls the border state and invalidates on change, so toggling the timers border
in the popup repositions the `+` within a tick.

When the timers border is **off**, the `Float` returns to `top=0, right=0` and the
original Decision stands verbatim.

