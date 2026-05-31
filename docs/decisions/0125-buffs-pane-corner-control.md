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
