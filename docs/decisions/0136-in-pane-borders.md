# 0136 — In-pane pane borders

**Status:** Accepted
**Date:** 2026-06-14

## Context

The right-column panes were separated and labelled by tmux's own chrome:
`pane-border-status` drew a header line per pane and the inter-pane
`pane-border-style` row was painted to blend into the terminal background
(ADR 0099). This had two structural limits. The header line was a tmux
construct, so its colour, glyphs, and placement could not follow a pane's
own colour or react to per-pane state; and a pane's separator was a single
shared row between two panes, not something either pane owned.

We wanted each right-column pane to carry its own framed border and header,
coloured from that pane's colour, toggleable per pane, and drawn by the
pane process itself so it renders with the same adaptive width logic as the
pane content.

## Decision

Render the right-column panes' borders and headers **in-pane**, drawn by the
pane process, and turn tmux `pane-border-status` permanently off.

**Frame.** A foreground-only half-block frame around each pane's content:
top edge `▀`, bottom edge `▄`, left edge `▌`, right edge `▐`, with adaptive
quadrant corners `▛▜▙▟`, falling back to a full block `█` at all four corners
when the active font lacks the quadrant glyphs. The frame is foreground-only
so the tmux pane background (`select-pane -P bg=`) shows through everywhere.
The top edge carries a left-aligned header label (`Character`, `Timers`,
`Group`, `Comm`, `UI`); the label lives on the border, not in content.
Implemented in `bridge/panes/pane_frame.py` (`framed()`), which wraps a
pane's inner container in `ConditionalContainer` borders that collapse to
nothing when the frame is off.

**Border colour.** Each pane's border foreground is the pane's own colour
lifted +0x14 per channel (`lighten()`), so it reads as a frame a shade or
two lighter than the pane fill. For the terminal-default (`None` / `black`)
pane — which has no `bg` override — the border is instead derived from the
live terminal background (`layout.conf terminal_bg`, the same source
`apply_border_style.sh` uses, ADR 0099) lifted +0x14, so on a black terminal
it yields `#141414` (visibly darker than the grey pane's `#2a2a2a`) and on a
tinted terminal it tracks that canvas. The pane-colour → border-colour table
(`PANE_BORDER_COLORS`) and the label map are **restated** in `pane_frame.py`,
not imported from `bridge/launcher/palette.py`: `bridge/panes` must not import
`bridge/launcher` (ADR 0126).

**Corner support resolution.** Whether the active font covers the four
quadrant codepoints is resolved once at startup by
`bridge/launcher/frame_corners.py`. It reads the active font family from the
terminal config named by `MUME_TERMINAL` (foot / kitty / alacritty), then
checks coverage with **fontconfig** (`fc-list :family=…:charset=…`) where
available, else with **fontTools** loading the family's own font file. The
corners must come from the same font as the half-block edges to tile
seamlessly, so both backends match on the family's own file rather than
accepting a fallback font that merely carries the glyphs. The check is
controlled by the `frame_corners` setting (`auto` / `quadrant` / `block`) and
its outcome is persisted as `frame_corners_resolved` (`quadrant` | `block`)
in `layout.conf`, mirroring the OSC-11 terminal-bg lifecycle (ADR 0099).
`pane_frame.corners()` reads `frame_corners_resolved` live (polled by
`start_poll`), so a corner-style change in the popup re-renders the corners
without a relaunch.

**Per-pane key, no per-pane wiring.** Border state is per pane
(`border_<key>` in `startup.conf`). Each pane process derives its own key
from the running script's filename (`status_pane.py` → `status`) via
`_derive_pane_key()`, so `pane_frame` needs no per-pane wiring; an unknown
entry point derives `None` and the border resolves to off — safe by default.
Resolution contract: `border_<key>=1` → on; if absent, fall back to the
retired global `show_pane_dividers`; if that is also absent, default on.

**Menu surface.** The frame is exposed in the Panes grid (ADR 0086) as one
trailing **Border** column — a per-pane `[X]`/`[ ]` checkbox writing
`border_<key>` — in both the launcher and the in-game popup
(`panes_grid.py`, `launcher.py`, `ingame_menu.py`). A pane that is never
framed (`dev`) renders a dim inert blank in that column. The corner style is
a single cycle row beneath the grid (`Corner style: Auto/Quadrant/Block`)
that writes `frame_corners` and re-resolves `frame_corners_resolved` live.
The previous single global borders toggle is removed.

**Budget.** The height budget reserves two rows (top + bottom) per pane that
is both framed and bordered-on, via `rc_frame_extra()` in
`right_column_budget.sh`; the content budget is `AVAILABLE − Σ frame_extra`,
and each pane's reservation is added back when pinning its final tmux height,
so content height is preserved. Content renders in `inner_width = W−2` /
`inner_height = H−2` when framed.

## Alternatives considered (rejected)

- **Other border decorations / shades** (heavier fills, shaded edges):
  the half-block foreground-only frame was the cleanest read against the
  pane fill and let the background show through.
- **Rounded box-drawing glyphs** (`╭╮╰╯` etc.): box-drawing corners do not
  tile with half-block edges and pull in a different glyph family with its
  own coverage problems; the quadrant/block pair tiles seamlessly with the
  `▀▄▌▐` edges.
- **foot-only corner detection.** An early cut detected coverage only for
  foot. Rejected for a cross-platform path: fontconfig where present, else
  fontTools on the font file, covering kitty and alacritty and macOS where
  `fc-list` is absent.
- **Reinstating a right-column width floor.** With content now in `W−2`, a
  minimum width was tempting. Rejected — ADR 0038 keeps the right column
  floorless and the content adapts to `W−2`, same as it adapts to `W`.
- **A single global borders toggle.** The prior model. Replaced by per-pane
  `border_<key>` so each pane is independently framed.
- **A per-pane border sub-frame in the menu.** A dedicated borders frame was
  considered and rejected; the toggle folds into the Panes grid as one
  Border column, mirroring the timers Clock column (ADR 0126).

## Consequences

- tmux `pane-border-status` is off permanently; the inter-pane
  `pane-border-style` separator (ADR 0099) is no longer the pane divider.
- `show_pane_dividers` is retired to a fallback only — read by the border
  resolution when `border_<key>` is absent, never written by the menu.
- The timers pane's `+`/`×` corner control offsets to inner top-right
  `(top=1, right=1)` when its frame is on, to stay inside the frame — see
  the dated addendum to [ADR 0125](0125-buffs-pane-corner-control.md).
- Pane content renders in `W−2` / `H−2` when framed; the budget reserves the
  two rows so content height is preserved.

## Cross-references

- [ADR 0099](0099-terminal-bg-detection-osc11.md) — `terminal_bg` source for
  the terminal-default border and the persistence lifecycle mirrored by
  `frame_corners_resolved`.
- [ADR 0126](0126-timers-layout-menu.md) — `bridge/panes` must not import
  `bridge/launcher`; the restated colour/label tables follow that rule, and
  the Border column mirrors the timers Clock column.
- [ADR 0038](0038-drop-right-column-width-floor.md) — the right column stays
  floorless; content adapts to `W−2`.
- [ADR 0086](0086-panes-grid.md) — the Panes grid the Border column extends.
- [ADR 0125](0125-buffs-pane-corner-control.md) — the corner control whose
  pinning shifts under the frame.
