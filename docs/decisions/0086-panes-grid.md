# 0086 — Panes configuration as a single colour grid

**Status:** Accepted
**Date:** 2026-05-21

## Context

The Panes submenu — both in the launcher (Options → Panes) and in the
in-game popup — previously listed the six right-column panes as
selectable rows, and pushed a per-pane subframe with an Enabled toggle
plus seven radio rows (Black / Red / Green / Blue / Grey / Orange /
Purple) to choose the pane's tint. That is two frames per surface and
nine clicks / keystrokes to flip a single pane between two colours
(into the subframe, set, back out — twice, since the subframes do not
remember the previous choice).

The state model is much smaller than the UI suggests: each pane is
either off, or on with exactly one of seven colours. The radio
already collapses to one selection per pane, so storing the choice as
"a column index in a fixed list" is faithful to what is actually on
disk in `startup.conf` (`show_<key>` and `pane_color_<key>`).

The earlier ADR 0085 landed the shared `menu_chrome` helpers
(`title_block` / `footer_block` / `button_fragment`) and the two-mode
cursor grammar (gold *background* on filled buttons, gold *foreground*
on swatch / checkbox cells) without wiring any frame to them. The
Panes submenu was the first frame queued to adopt them.

## Decision

### Single-frame `pane × colour` grid

`options_panes` (launcher) and `panes` (popup) are rebuilt as one
frame each. Rows of the grid are the six panes; columns are the
seven palette entries. Each `(pane, colour)` cell is a checkbox plus
a 3-cell colour swatch — `[X]███` or `[ ]███`. Per row, **0 or 1
cells are checked**: zero checked is the pane's off state (the row
paints dim end-to-end via `C_PANE_OFF`); one checked is the pane's
on state with that colour.

Enter / click semantics live in `panes_grid.apply_cell_toggle`:

- Clicking the active colour of an on pane turns it off.
- Clicking any other cell turns the pane on with that colour
  (clearing any previously checked cell in the row).

The frame below the grid is unchanged in shape: blank row · `[X]
Display pane headers` toggle · blank row · `Back`. The headers toggle
and `Back` use the filled-button cursor grammar; grid cells use the
swatch-cell grammar.

### Shared module: `bridge/launcher/panes_grid.py`

Pure module (no prompt_toolkit import, no global state), imported by
both `launcher.py` and `ingame_menu.py`. Three entries:

- `panes_grid_fragments(rows, term_cols, cursor, cell_handler=None)`
  — fragments for the colour-name header row plus one row per pane.
  Cell-colour precedence: cursor cell brackets → `C_CURSOR_CELL`;
  else on an enabled row, checked → bright (`C_ACTIVE`), unchecked →
  dim (`C_HINT`); on a disabled row, everything → `C_PANE_OFF` except
  the cursor cell brackets which stay gold. Swatches paint their
  colour on enabled rows, `C_PANE_OFF` on disabled rows. The
  colour-name header row paints in `C_HINT`. When `cell_handler` is
  provided each cell's fragments are emitted as 3-tuples carrying the
  returned mouse handler.
- `apply_cell_toggle(enabled, colour_index, col) -> (enabled,
  colour_index)` — pure state transition.
- `grid_width() -> int` — total horizontal width, for centring.

`C_PANE_OFF` is added to `palette.py` (one step darker than `C_HINT`).
Tests in `bridge/launcher/tests/test_panes_grid.py` cover
`apply_cell_toggle` (on / off / switch-colour) and
`panes_grid_fragments` cell-colour precedence (cursor, checked,
disabled-row dim); they run without prompt_toolkit installed.

### Shared render, per-surface commit

The render path is shared; the commit path is not. Each surface keeps
the persistence behaviour it already had:

- **Launcher.** Deferred. Cell clicks mutate `_conf`; `_save_conf`
  fires on Back / ESC. No tmux interaction at the launcher — the
  cockpit is not running yet.
- **Popup.** Immediate and live. Cell clicks compute the delta from
  the current tmux state (pane open-state re-probed on every render),
  drive `toggle_pane.sh <target> --persist` when the open/closed
  state changes, and `tmux select-pane -t mume:cockpit.<idx> -P
  bg=<hex|default>` when the pane is — or has just become — open.
  The colour name is also written to `startup.conf` via the in-place
  `_persist_conf_key` helper so it survives the next cold start.

The `startup.conf` schema is unchanged. Both surfaces read and write
the existing `show_<key>` and `pane_color_<key>` entries; the grid
model maps `show_<key>=1` with an empty or unknown `pane_color_<key>`
to the Black column (index 0).

## Consequences

**Easier.** Two clicks instead of six to switch a pane's colour
(one click to set the new colour, optional second click to toggle
off). The whole-screen render shows every pane's current state at a
glance — previously you had to enter each subframe to see its
colour. The visual treatment also signals off vs. on much more
directly: an entire dim row reads as off without any "Enabled" label
to parse.

**Harder.** A single click now has two effects (open the pane *and*
set its colour, or close it). For the popup that translates into a
two-step delta (`toggle_pane.sh` + `select-pane -P bg`) where the
old subframe issued each separately on user request. The delta logic
is straightforward, but it does mean the popup re-probes tmux state
on every cell click rather than treating "enabled" and "colour" as
independent dimensions.

**Locked out.** The previous UI let the user pre-stage a colour on a
closed pane — open the per-pane subframe of an off pane, click a
colour radio, the colour persists to `startup.conf` for the next
cockpit start (in the launcher) or the next time the pane is opened
(in the popup). The grid loses that affordance: there is no way to
mark "off, but if it were on it would be purple" — checking a cell
necessarily turns the pane on. The same can be achieved by checking
the colour and then un-checking the same cell, but only in the
launcher (where the persisted state lives in `_conf` until save) —
the popup applies each click immediately and the off transition does
not preserve a pending colour change. The trade-off is accepted: the
pre-staging feature was discoverable only by accident, the new UI
makes the dominant case (flip the pane on with a colour) the
shortest path, and the rare case of preparing a configuration ahead
of time can be handled by editing `startup.conf` directly.

## Alternatives considered

**Keep the subframes, just adopt `menu_chrome`.** The lower-friction
P2 — change nothing about the model, just swap title / footer
rendering for the shared helpers. Rejected: the model is the
expensive part. A pass that touches the Panes frames anyway is the
right moment to collapse the model down to what the data actually
is.

**Two-state checkbox per pane plus a separate "colour" picker
column.** Keep an explicit on/off checkbox in front of each row and
render the colours as seven additional buttons to the right. The
checkbox and the colour buttons stay logically separate (clicking a
colour does not enable the pane; clicking the checkbox does not
choose a colour). Rejected: it preserves the pre-stage affordance
but at the cost of two clicks instead of one for the dominant case,
and at the cost of a busier row that is harder to read at a glance.

**Render the radios horizontally inside each pane row, but as
radios.** Same fan-of-seven inside each row, but still mutually
exclusive within the row and gated by a separate Enabled toggle.
Rejected: same problem as the previous alternative, plus the visual
ambiguity of "is this row off, or is its colour just unset" — which
the dim-entire-row treatment specifically removes in the chosen
design.

**A grid that is per-pane × on/off (one column) and per-pane ×
colour (seven columns) as separate widgets.** Rejected: the on/off
state is already encoded in "zero cells checked", so factoring it
into a separate column duplicates the same bit.
