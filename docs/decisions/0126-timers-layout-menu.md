# 0126 — Timers layout menu; defaults duplicated across bridge packages

**Status:** Accepted
**Date:** 2026-05-31

## Context

The previous PR taught the timers pane (`bridge/panes/timers_pane.py`)
to read per-group colour, column count, and visibility from
`bridge/runtime/timers_layout.conf` (keys `timers_<type>_enabled` /
`_color` / `_cols`; type tokens `spell` / `buff` / `debuff` / `stored`
/ `blind` / `charm`). The pane reads the file; nothing yet writes it.

This PR adds the writer: a "Timers layout" submenu in both Options
menus — the launcher (`launcher.py`, frame `options_timers`) and the
in-game popup (`ingame_menu.py`, frame `timers`) — modelled on the
existing Panes colour grid (ADR 0086).

Two shapes differ from the Panes grid and forced design choices:

1. **Per-group column count.** Panes have no numeric dimension; timer
   groups do (`cols`, clamped per type: charm 1–2, others 1–6). The
   grid needs an inline numeric control alongside the colour swatches.
2. **No shared import path.** The menu code lives in `bridge/launcher`;
   the pane lives in `bridge/panes`. The two packages are launched as
   separate processes with separate `sys.path` roots and share no
   module. The config contract (defaults, the cols clamp, the type
   tokens) therefore cannot be imported from one into the other.

## Decision

### Shared module: `bridge/launcher/timers_layout_grid.py`

A pure module (no prompt_toolkit import, no global state), imported by
both `launcher.py` and `ingame_menu.py`, mirroring `panes_grid.py`. It
re-exports `panes_grid.apply_cell_toggle` (the palette-agnostic
0-or-1 colour-cell model is identical) and adds:

- `timers_grid_fragments(rows, term_cols, cursor, cell_handler=None,
  stepper_handler=None)` — one row per group: label, nine colour
  swatches, then an inline `◄ N ►` column stepper. Row tuple is
  `(label, enabled, colour_index, cols, max_cols)`. There is **no**
  colour-name header row (unlike the panes grid). Cursor columns:
  colour cells `0..8`, `◄` at col 9, `►` at col 10. The digit between
  the arrows is display-only — never a cursor stop, never gold. Colour
  cells reuse the swatch-cell grammar (`C_ACTIVE` / `C_HINT` /
  `C_CURSOR_CELL` / `C_PANE_OFF`); a disabled row paints dim
  end-to-end as in panes.
- `clamp_cols(typ, raw)` / `step_cols(cols, max_cols, delta)` /
  `max_cols_for(typ)` — the column arithmetic and per-type clamp.
- `TIMERS_LAYOUT_TYPES` / `TIMERS_LAYOUT_LABELS` /
  `TIMERS_LAYOUT_DEFAULTS` — the config contract, restated (see below).

The charm swatch renders like any other colour cell; whether the
colour lands as bar-fill or name-foreground is the pane's concern, not
the matrix's.

### Palette: `TIMERS_COLOR_ORDER` in `palette.py`

Nine ordered `(name, hex)` swatches. The first six are exactly the six
group default colours, so every type's default lands on a real swatch
(spell→Blue, buff→Green, debuff→Red, stored→Magenta, blind→Cyan,
charm→Violet); the last three (Orange, Yellow, Teal) are additions at
matching saturation / brightness. `timers_color_hex(index)` and
`timers_color_index(hex)` are the lookups, mirroring `pane_color_hex`.
`timers_color_index` is case-insensitive (charm's default `#B388FF` is
stored uppercase). The rendered grid is 79 columns wide — well inside
the launcher and the 80%-width popup at a normal terminal.

### Shared render, per-surface commit

Same split as ADR 0086:

- **Launcher.** Deferred. The frame parses the file into an in-memory
  `_timers_layout` dict on entry, mutates it on each cell / stepper
  action, and writes the whole file on Back / ESC. A separate
  parse/save pair (`_parse_timers_layout` / `_save_timers_layout`)
  mirrors the `startup.conf` `_parse_conf` / `_save_conf` pair rather
  than reusing it — a different file and schema.
- **Popup.** Immediate and live. The frame re-reads the file on every
  render (`_read_timers_layout`) and writes the changed key(s) in
  place (`_persist_timers_layout_key`, a sibling of `_persist_conf_key`
  targeting the timers file). No tmux interaction: the running timers
  pane polls `timers_layout.conf` (~100 ms) and re-renders, so the
  edit applies live with no restart.

The file is optional. With no file present, all three consumers
(pane, launcher, popup) fall back to the defaults, so a fresh install
opens the grid with every group on, today's colours, and today's
column counts. No bootstrap template is shipped.

### Defaults duplicated across packages — intentional

`TIMERS_LAYOUT_DEFAULTS` and the per-type cols clamp are restated in
`bridge/launcher/timers_layout_grid.py` and already exist in
`bridge/panes/timers_pane.py` (`_LAYOUT_DEFAULTS` / `_clamp_cols`).
This is a deliberate duplication: the two packages share no import
path, and introducing one (a third shared package, or reaching across
`sys.path`) for one small constant table and a two-line clamp would
couple the launcher's start-up surface to the pane runtime for no real
gain. The defaults reproduce the pane's historic hardcoded grid
exactly; the duplication is small, static, and unlikely to drift. Both
sites carry a comment pointing at the other and at this ADR.

## Consequences

**Easier.** One grid edits all three dimensions of every group from a
single frame, on both surfaces. The popup applies changes live; the
launcher stages them for the next start. The colour grid, the
on/off-by-dim-row treatment, and the cursor grammar are all inherited
verbatim from the panes model, so the two submenus look and behave
alike.

**The duplication risk.** If the pane's defaults or clamp change, the
menu's copy must change too, or the menu will seed a fresh file with
values the pane would not have chosen. The cross-reference comments and
this ADR are the mitigation; there is no compile-time link. A future
consolidation (a shared `bridge/common` importable by both packages)
would remove the risk but is out of scope here.

## Alternatives considered

**Import the contract from `timers_pane.py`.** Reach across `sys.path`
so the menu imports `_LAYOUT_DEFAULTS` / `_clamp_cols` directly.
Rejected: it couples the launcher process to the pane runtime (and its
prompt_toolkit-free constraints differ), and `timers_pane.py` imports
pane-runtime modules the launcher has no business loading.

**A third shared package for the contract alone.** A `bridge/common`
importable by both `bridge/launcher` and `bridge/panes`. Rejected as
premature for one constant table and a two-line clamp; revisit if a
second such shared contract appears.

**Fold cols into the colour grid as more columns.** Represent column
count as extra checkbox columns rather than a stepper. Rejected: a
0-or-1 model does not express a 1–6 magnitude, and a six-wide stepper
strip per row would dwarf the swatches. The inline `◄ N ►` is compact
and reads as a magnitude control.
