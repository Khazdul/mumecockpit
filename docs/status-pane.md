# Character Status Pane

The status pane is a right-column tmux pane that displays a live character
info board driven by GMCP data.
Touch this file when changing the renderer, the state-file schema, the field
layout, or layout integration.

Nine content rows make up the layout (no blank separators): a character
name + XP-progress row, a TP-progress thin bar, a row of four filled
toggle boxes (SNEAK / RIDE / CLIMB / SWIM), then a 2×2 block of stepped
gauges — MOOD / ALERTNESS, then POSITION / WIMPY. Each gauge is three
stacked rows: a centered uppercase label, a centered value on a full-width
bar, and a step-tick row marking the discrete positions. Everything
chromatic is derived per frame from the pane's palette shade ramp, so the
board retints with the pane colour. Game time is shown in the input-pane
clock strip, sourced from the same `status.state` payload. The gauge
redesign is recorded in [ADR 0138](decisions/0138-character-pane-palette-gauges.md).

## Architecture

```
GMCP payload ──► lua/core/char_state.lua ──► state.char.*
                                                   │
                                                   ▼
                          lua/core/status_state.lua
                          wraps Char.Name / StatusVars / Vitals
                          handlers; serialises projected view to
                          bridge/runtime/status.state (JSON, atomic write)
                                                   │
                                       mtime change │  50 ms poll
                                                   ▼
                          bridge/panes/status_pane.py (prompt_toolkit
                          Application; asyncio mtime poll task;
                          anchor-top; overflow indicator)
```

### State flow

`lua/core/status_state.lua` subscribes to `gmcp_char_name`,
`gmcp_char_status_vars`, `gmcp_char_vitals`, `char_reset`, and `clock_changed`
on the event bus. `char_state.lua` is the primary writer for all three Char.*
modules — `state.char.*` is fully updated before any subscriber runs. Each
subscription calls `serialize()` and writes `bridge/runtime/status.state` atomically.

`serialize()` is also exposed as `state.char.serialize` so non-GMCP writers
can request a re-serialise after mutating `state.char.*`. `lua/core/wimpy.lua`
uses this to refresh the WIMPY cell after the `Wimpy set to:` / `Wimpy removed.`
text triggers (which carry no GMCP packet). Writers must mutate state first,
then call `state.char.serialize()` so the snapshot reflects the new value.

### Disconnect clear

`mark_mume_disconnected()` in `lua/brain.lua` calls `state.char.reset()` after
`state.run.reset()`. `state.char.reset()` is defined in `char_state.lua`;
it wipes every non-function key in `state.char` while keeping the table
identity intact so cached references elsewhere stay valid, then emits
`char_reset`. `status_state.lua`'s `char_reset` subscriber calls `serialize()`,
producing a single atomic write to `bridge/runtime/status.state` with all character
fields null. The renderer displays `—` for null name and empty bars for null
progress. Gauge rows render label + empty `track` bar + all-inactive ticks
(no caret for wimpy). The content stays a fixed 9 rows produced by
`_build_frame` in `bridge/panes/status_pane.py`, and the tmux slot is sized
to `desired_status` (default 9) per ADR 0071.

### Inactive run

When `bridge/runtime/connection.state` is absent, every text provider
(`_status_text`, `_indicator_text`) returns blank fragments and the overflow
indicator is suppressed via the same `_run_active` flag. Pane structure
(size, splits, tmux borders, `cp -h` header status) is unchanged. The flag is
updated by the existing 50 ms poll loop on each tick.

### Polling

`bridge/panes/status_pane.py` polls `bridge/runtime/status.state` every 50 ms via an asyncio
task. On mtime change the task re-reads the file and calls `app.invalidate()`.
SIGWINCH is handled automatically by prompt_toolkit; no dirty flag is needed.

### Rendering

`bridge/panes/status_pane.py` is a `prompt_toolkit` full-screen `Application`
(`mouse_support=True`, `full_screen=True`, `color_depth=ColorDepth.DEPTH_24_BIT`).

Row helpers (`_build_frame`, `_build_toggles_row`, `_toggle_box`, `_label_cell`,
`_bar_cell`, `_tick_ord`, `_tick_wimpy`, `_two_cols`, etc.) still emit complete
ANSI strings per row. Each string is wrapped with `ANSI(...)`
and converted to fragments via `to_formatted_text(...)`. Rows are concatenated
with `("", "\n")` separators in a `FormattedTextControl` inside a
`Window(wrap_lines=False)`.

Anchor-top: the rows window has no scroll. Top rows are always at row 0; excess
rows are clipped at the bottom by the window boundary. Mouse wheel and clicks in
the pane do nothing.

### Overflow indicator

A 1-row `ConditionalContainer` sits below the rows window. It is visible when
`total_rows > pane_height`. When visible:

- Text: `↓ N more rows` where `N = total_rows − (pane_height − 1)`.
- Style: `fg:#d4a04e italic` (local constant `C_INDICATOR`).
- Not clickable.

### Width

The renderer reads its width from the live pane size on every frame via
`shutil.get_terminal_size().columns`. SIGWINCH triggers a prompt_toolkit
re-render so the new width is applied immediately without a restart. The bridge
layer imposes no minimum width on the right column (ADR 0038); the renderer
trusts the reported size and adapts fully (ADR 0023).

## State-file schema (`bridge/runtime/status.state`)

JSON written by `lua/core/status_state.lua`. Gitignored.

```json
{
  "character": "Aragorn",
  "race": "Man",
  "level": 50,
  "wimpy": 100,
  "maxhp": 420,
  "xp": 34000000,
  "tp": 122000,
  "xp_progress": 0.42,
  "xp_progress_baseline": 0.40,
  "tp_progress": 0.71,
  "tp_progress_baseline": 0.71,
  "run_xp": 5400,
  "run_tp": 0,
  "mood": "wimpy",
  "alertness": "normal",
  "sneak": "off",
  "ride":  "off",
  "position": "standing",
  "climb": "off",
  "swim": "off",
  "game_time": null,
  "time_period": null,
  "time_transition_at": null,
  "time_precision": null
}
```

`xp_progress` and `tp_progress` are computed by `lua/core/level_progress.lua`
from cumulative threshold tables (levels 1–100). Both are `null` during the
bootstrap window (before `Char.Vitals` and `Char.StatusVars` have both
arrived). `run_xp` and `run_tp` are populated by `lua/core/run_state.lua`.
`game_time` is populated via the `clock_changed` subscription. All non-progress
fields are retained in the payload for use by future rows.

`maxhp` (`Char.Vitals` → `state.char.maxhp`) is the wimpy gauge's denominator;
it is `null` at bootstrap and after a reset, which hides the wimpy caret. `level`
drives the `L<level>` badge overlaid on the name row (null → no badge).

`affects` was removed from the payload by ADR 0032 (no longer serialised).

### Field mapping from GMCP

| State field      | GMCP source                                            | Notes                                        |
|------------------|--------------------------------------------------------|----------------------------------------------|
| `character`      | `Char.Name` → `state.char.name`                        |                                              |
| `race`           | `Char.StatusVars` → `state.char.race`                  |                                              |
| `level`          | `Char.Vitals` → `state.char.xp` → `level_progress.level_from_xp` | derived from xp via the canonical threshold table; ignores `state.char.level` because `Char.StatusVars` is not reliably emitted after a death-induced level drop in MUME |
| `wimpy`          | `Char.Vitals` → `state.char.wimpy`; also `Wimpy set to:` / `Wimpy removed.` text triggers via `lua/core/wimpy.lua` | integer; null until first Vitals tick or wimpy text-trigger fires |
| `maxhp`          | `Char.Vitals` → `state.char.maxhp`                     | integer; wimpy gauge denominator; null at bootstrap/reset → no caret |
| `xp`             | `Char.Vitals` → `state.char.xp`                        |                                              |
| `tp`             | `Char.Vitals` → `state.char.tp`                        |                                              |
| `xp_progress`    | computed by `level_progress.compute_xp_progress`       | `null` until xp known; derives level from xp |
| `tp_progress`    | computed by `level_progress.compute_tp_progress`       | `null` until xp + tp + race all known; derives level from xp; troll scales thresholds ×0.1 |
| `mood`           | `Char.Vitals` → `state.char.mood`                      |                                              |
| `alertness`      | `Char.Vitals` → `state.char.alertness`                 |                                              |
| `sneak`          | `Char.Vitals` → `state.char.sneak`                     | null→"off", "s"/"S"→"on"                    |
| `ride`           | `Char.Vitals` → `state.char.ride`                      | null/false/json.null→"off", else→"on"        |
| `position`       | `Char.Vitals` → `state.char.position`                  |                                              |
| `climb`          | `Char.Vitals` → `state.char.climb`                     | null→"off", "c"/"C"→"on"                    |
| `swim`           | `Char.Vitals` → `state.char.swim`                      | bool→"on"/"off"                              |
| `run_xp`         | `lua/core/run_state.lua` → `state.run.xp`              |                                              |
| `run_tp`         | `lua/core/run_state.lua` → `state.run.tp`              |                                              |
| `game_time`          | `lua/core/clock.lua` → `state.world.clock.format("panel_time")` |                                 |
| `time_period`        | `lua/core/clock.lua` → `state.world.clock.next_transition()` |                                   |
| `time_transition_at` | `lua/core/clock.lua` → `state.world.clock.next_transition()` | unix epoch int; consumed by input-pane renderer |
| `time_precision`     | `lua/core/clock.lua` → `state.world.clock.next_transition()` | `"MINUTE"`/`"HOUR"`; consumed by input-pane renderer |

## Colour scheme

Everything chromatic is **palette-derived per frame**. `_build_frame` resolves
the pane's shade ramp once via `pane_frame.pane_shades("status")` and turns each
shade into an SGR escape with the local `_fg(hex)` / `_bg(hex)` helpers. The ramp
is a single hue (the pane colour's hue/saturation, `PANE_SHADE_HS`) walked down
its HSL lightness; under the terminal-default (`black`/`None`) pane the hue and
saturation come from `terminal_bg` instead, so the board tracks a tinted terminal
and collapses to neutral greys on a black/neutral background. See the
`pane_shades` docstring in `bridge/panes/pane_frame.py` and
[docs/pane-frame.md](pane-frame.md).

Shade → role (from the `pane_shades` docstring):

| Shade    | L  | Role in the status pane                                                        |
|----------|----|--------------------------------------------------------------------------------|
| `track`  | 15 | bar background / XP-baseline bg / toggle off-box bg / inactive step-ticks      |
| `dim`    | 27 | XP session-gain bg / TP-baseline `▀` fg / gauge labels                         |
| `mid`    | 42 | TP session-gain `▀` fg                                                          |
| `paneBg` | 8  | near-bg dark text: the inverted toggle-box label (both on and off)             |
| `vtext`  | 72 | gauge value text on the bar                                                    |
| `label`  | 60 | name-row foreground (player name and the `L<level>` badge)                     |
| `glow`   | 64 | active highlight: active step-tick, wimpy caret, toggle on-box bg              |

Only the structural escapes are fixed constants at the top of
`bridge/panes/status_pane.py`:

| Constant      | Escape / value           | Role                                              |
|---------------|--------------------------|---------------------------------------------------|
| `C_RESET`     | `\x1b[0m`                | Reset all (fg, bg, attrs)                          |
| `C_BG_RST`    | `\x1b[49m`               | Reset background only, keep foreground            |
| `C_INDICATOR` | `fg:#d4a04e italic`      | Overflow-indicator style — the shared cross-pane amber, not palette-derived |

The name-row reset between the XP background segments also uses `C_BG_RST`
(reset bg, keep the `label` foreground); see Row 1 below.


## Pane frame

The pane title is `status` (set via `select-pane -T`). The pane carries an
in-pane frame (a header row plus a half-block border) drawn by `pane_frame`,
replacing the old tmux `pane-border-status` header. Content renders within
`inner_width` / `inner_height` (`W-2` / `H-2` when the border is on, full size
when off); the header label is `Character`; the border is per-pane, toggled by
`border_status` in `startup.conf`. See [docs/pane-frame.md](pane-frame.md) for
the frame shape, border colour, and the `border_<key>` contract. No content
header rows are rendered inside the pane.

## Field layout

`W = shutil.get_terminal_size().columns` (adaptive; no upstream minimum enforced).

### Row 1 — character name with XP-progress background and level badge

- Full-width string: `state.char.name` (or `—` if null), capitalised and
  centered in W columns (truncated to W if longer, space-padded otherwise).
- Foreground: the palette-derived `label` shade everywhere on the row, so the
  name matches the `L<level>` badge.
- Three-segment background (palette shades, not fixed RGB):
  - leftmost `floor(W × xp_progress_baseline)` columns: `_bg(track)` — XP
    already present at session start.
  - next `floor(W × xp_progress) − floor(W × xp_progress_baseline)` columns:
    `_bg(dim)` — XP gained this session.
  - remaining columns: terminal default (no background, `C_BG_RST`).
- Level badge: when `level` is non-null, `L<level>` is overlaid right-aligned
  into the rightmost cells (`lstart = W − len("L<level>")`). The badge keeps the
  `label` foreground; the XP background still shows behind it. Null `level` →
  nothing overlaid. (Char names are short, so a centered name won't reach these
  cells in practice; if it ever does, the level wins them.)
- Segment emission: the row is split at every distinct boundary in
  `{0, fill_base, fill_total, lstart, W}`. Per segment the background is
  `track` / `dim` / `C_BG_RST` (by fill position) and the foreground is the
  `label` shade for both the name and the badge — the two stay independent of
  the background. A trailing `C_RESET` closes the row.
- See [Session-gain visualisation](#session-gain-visualisation) below for the
  baseline rules.

### Row 2 — TP-progress thin bar

- Leftmost `floor(W × tp_progress_baseline)` columns: `▀` (U+2580), foreground
  `_fg(dim)`, no background — TP already present at session start.
- Next `floor(W × tp_progress) − floor(W × tp_progress_baseline)` columns: `▀`,
  foreground `_fg(mid)`, no background — TP gained this session.
- Remaining columns: space characters, no colour.
- See [Session-gain visualisation](#session-gain-visualisation) below for the
  baseline rules.

### Row 3 — four filled toggle boxes (4-column layout)

Same `_col_widths(W)` distribution and three 1-char inter-column spacers as the
gauge block. Each cell (`_toggle_box`) fills its whole column with a centered
label:

- **label**: toggle name in uppercase (`SNEAK`, `RIDE`, `CLIMB`, `SWIM`),
  `.center(colW)` so it sits centered in the filled box.
- **box background**: off → `_bg(track)` (the value-bar shade); on →
  `_bg(glow)` (the active step-tick shade). The box shade carries the on/off
  distinction.
- **label foreground**: the inverted `paneBg` shade in both states — a dark
  label on the lighter box, so on reads clearly and off recedes.

| Col | Toggle | Off box     | On box     | Label fg (both) |
|-----|--------|-------------|------------|-----------------|
| 0   | SNEAK  | `track` bg  | `glow` bg  | `paneBg`        |
| 1   | RIDE   | `track` bg  | `glow` bg  | `paneBg`        |
| 2   | CLIMB  | `track` bg  | `glow` bg  | `paneBg`        |
| 3   | SWIM   | `track` bg  | `glow` bg  | `paneBg`        |

Only `"on"` (via `_is_on`) renders the on box; missing / `null` / `"off"` →
off box (no garbled text).

### Gauge block — MOOD / ALERTNESS, then POSITION / WIMPY

The four data rows are gone, replaced by a 2×2 block of stepped gauges. The
block uses **two** columns, not four: `_two_cols(W)` returns
`col_left = c1 + c2 + 1` and `col_right = c3 + c4 + 1` (from `_col_widths(W)`),
so the single inter-column spacer lands at index `c1 + c2 + 1` — exactly the
caps cell-2/cell-3 gap — and the gauge columns sit directly under the
RIDE/CLIMB toggle gap. `col_left + 1 + col_right == W`.

Each gauge occupies three stacked rows joined by `_row(left, right)` (the same
single unstyled spacer):

1. **Label row** (`_label_cell`): the stat name uppercased, `.center(colW)`,
   foreground `dim`, on the plain pane background (no bar).
2. **Value row** (`_bar_cell`): the value `.center(colW)` on a full-width
   `_bg(track)` bar, foreground `vtext`. A null/empty value renders as an empty
   `track` bar (no text).
3. **Tick row**: the discrete step markers (see below), on the **real tmux pane
   background** (`C_BG_RST`) — no fill behind the teeth.

Layout of the block (top to bottom):

| Rows | Left column (`col_left`) | Right column (`col_right`) |
|------|--------------------------|----------------------------|
| label / bar / ticks | MOOD     | ALERTNESS |
| label / bar / ticks | POSITION | WIMPY     |

Values come from `_ord_val` (lowercased, or `None` when absent) for the ordinal
stats; wimpy uses `str(int(wimpy))` (or `None`).

#### Ordinal step-ticks (`_tick_ord`)

For a stat with `N` steps, `N` `▀` teeth are placed across the column at
positions `round(k·(colW−1)/(N−1))` for `k` in `0..N−1`. Colliding positions
collapse to a single tooth (positions are de-duplicated into a set; the first
`0`, the last `colW−1`, and the active index always survive because they are
real positions in the list). The tooth matching the current value is `_fg(glow)`;
the rest are `_fg(track)`; non-tooth columns are spaces. The whole row sits on
`C_BG_RST`. An unknown / missing value leaves **every** tooth inactive (`track`).

Step orders (lowercased state value matched to its index):

- `MOOD_STEPS  = [wimpy, prudent, normal, brave, aggressive, berserk]`
- `ALERT_STEPS = [normal, careful, attentive, vigilant, paranoid]`
- `POS_STEPS   = [sleeping, resting, sitting, standing]`

#### Wimpy caret (`_tick_wimpy`, continuous)

Wimpy is continuous, not ordinal: a single `_fg(glow)` `^` at
`round(frac·(colW−1))`, `frac = clamp(wimpy / maxhp, 0, 1)`. There are no
inactive ticks. The caret is hidden entirely (all spaces) when `wimpy` is null
or `maxhp` is null/0. The row sits on `C_BG_RST`.

### Bootstrap behaviour

- `xp_progress` / `tp_progress` is `null` → bar renders empty (no fill).
- `xp_progress_baseline` / `tp_progress_baseline` is `null` or `0` → no
  session-gain segment is drawn; the bar is visually identical to the
  pre-feature single-shade rendering.
- `character` is `null` → `—` centered on row 1.
- `level` is `null` → no `L<level>` badge overlaid on row 1.
- Any ordinal gauge value (`mood` / `alertness` / `position`) is `null` →
  empty `track` bar and an all-inactive step-tick row.
- An ordinal value that is non-null but not in its step list → bar shows the
  value, but the step-tick row is all-inactive (no glowing tooth).
- `wimpy` is `null`, or `maxhp` is `null`/`0` → no wimpy caret (the wimpy bar
  also renders empty when `wimpy` is `null`).
- Any toggle field missing or `null` → rendered as the off box (no garbled text).

Level is derived from xp at serialise time (`level_progress.level_from_xp`).
A stale `state.char.level` (e.g. after a death-induced level drop, before the
next `Char.StatusVars` arrives) does not affect the bars or the `level` field
in `status.state`.

### Session-gain visualisation

Both the XP bar (Row 1) and TP bar (Row 2) split into a baseline segment and a
session-gain segment to show progress earned during the current session. The
baseline values (`xp_progress_baseline`, `tp_progress_baseline`) are computed
in `lua/core/level_progress.lua` from `xp − run_xp` and `tp − run_tp`.

| Scenario                                  | Baseline value                                      | Visual                                                                              |
|-------------------------------------------|-----------------------------------------------------|-------------------------------------------------------------------------------------|
| Level-up during session                   | 0 (re-anchored at the new level's start)            | Whole filled region renders in the session-gain shade (XP `dim` bg / TP `mid` fg) until the next level-up. |
| Disconnect / reconnect                    | `run_xp`/`run_tp` reset to 0 → baseline = current   | Bar reverts to all-baseline shade (XP `track` bg / TP `dim` fg) until the next XP/TP tick. |
| Lost XP this session (negative `run_xp`)  | current progress within the player's current level  | Whole filled region renders in the baseline shade; session-gain segment is zero-width. Session-gain segment reappears once `state.char.xp` climbs back above the session-start XP. |
| Death drops the player a level            | current progress within the new lower level         | Bar shows the player's progress within the new lower level, in the baseline shade. The session-gain shade does not return until the player has recovered past the original session-start XP, which may require levelling back up first. |

Troll TP scaling (×0.1) applies identically to both `tp_progress` and
`tp_progress_baseline`.

### Troll TP scaling

`lua/core/level_progress.lua` applies a ×0.1 multiplier to all TP thresholds
when `state.char.race` lowercases to `"troll"`. Sanity check: at level 5 with
100 TP, troll bar is full (100 / (1000 × 0.1) = 1.0); non-troll bar is 10 %.

## Layout integration

### Pane position

Right column (top to bottom): `status` → `timers` → `group` → `comm` → `ui` →
`dev`. Status is always the topmost right-column pane whenever it exists.

### Pane height

`desired_status` in `bridge/runtime/layout.conf` (default 9; content rows,
excludes the title row). The shipped default is seeded from
`DEFAULT_DESIRED[status]=9` in `bridge/layout/right_column_budget.sh`. Cold
start and WINCH size the pane from this value via the per-pane allocation
algorithm in [ADR 0071](decisions/0071-per-pane-desired-heights.md). Status
carries `MIN_HEIGHT[status]=3` — the only right-column pane held well above the
shared 1-row floor. The current content is 9 rows: 2 progress rows (XP + TP) +
1 toggle-box row + a 2×2 gauge block of 2 × (label + bar + ticks) = 6 rows.
Mid-session drag adjusts the height freely and the new value persists as the
next `desired_status` via `on_pane_resize.sh`; `cp -reset-heights` restores the
shipped default.

### Width constraint

`bridge/layout/on_window_resize.sh` enforces `MAIN_MIN = 30` (main/tt++ pane floor).
The right column has no minimum width enforced by the status pane — `ui_width`
from `bridge/runtime/layout.conf` is the sole authority (ADR 0038). The renderer is
adaptive and accepts any width (ADR 0023).

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -c`                           | `toggle_pane.sh status --persist`               |
| In-game popup → Options           | `toggle_pane.sh status --persist`               |
| Launcher Options → Character pane | `_save_conf` → `startup.conf show_status`       |

Persistence key: `show_status` in `bridge/runtime/startup.conf`. Fresh-install
default is `1` (status pane on), seeded by
`bridge/launcher/templates/startup.conf` (see ADR 0101). Upgraded installs
missing the key fall through to the aligned `${show_status:-1}` runtime guard
in `bridge/launcher/build_initial_layout.sh`.

---
Back to [architecture.md](../architecture.md).
