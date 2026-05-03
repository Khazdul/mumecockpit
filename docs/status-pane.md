# Character Status Pane

The status pane is a right-column tmux pane that displays a live character
info board driven by GMCP data.
Touch this file when changing the renderer, the state-file schema, the field
layout, or layout integration.

**Step 3 of a multi-step redesign.** Step 1 replaced the old gold-framed box
with two progress-bar rows. Step 2 adds four data rows below them (race/level,
mood/sess-xp, alertness/sess-tp, position/wimpy). Step 3 adds four toggle-box
cells (sneak/ride/climb/swim) directly below the data block.

## Architecture

```
GMCP payload ──► lua/core/char_state.lua ──► state.char.*
                                                   │
                                                   ▼
                          lua/core/status_state.lua
                          wraps Char.Name / StatusVars / Vitals
                          handlers; serialises projected view to
                          bridge/status.state (JSON, atomic write)
                                                   │
                                       mtime change │  50 ms poll
                                                   ▼
                          bridge/status_pane.py (prompt_toolkit
                          Application; asyncio mtime poll task;
                          anchor-top; overflow indicator)
```

### State flow

`lua/core/status_state.lua` loads after `char_state.lua` and `level_progress.lua`
(alphabetical order within `lua/core/`). It wraps each of char_state's three
handlers: `Char.Name`, `Char.StatusVars`, `Char.Vitals`. After the original
handler runs (updating `state.char.*`), the wrapper serialises the projected
view and writes it atomically.

### Disconnect clear

`mark_mume_disconnected()` in `lua/brain.lua` calls `state.char.reset()` after
`state.session.reset()`. `state.char.reset()` is defined in `char_state.lua`;
it wipes every non-function key in `state.char` while keeping the table
identity intact so cached references elsewhere stay valid. The `status_state.lua`
wrapper around `state.char.reset` then calls `serialize()`, producing a single
atomic write to `bridge/status.state` with all character fields null. The
renderer displays `—` for null name and empty bars for null progress. Data rows
render as label-only (empty value cells). Pane height stays at `STATIC_ROWS = 11`
within one poll tick (≤ 50 ms).

### cp -r partial blank

After `cp -r` mid-session, **Name** shows `—` and progress bars show empty
until the next full reconnect. Other fields repopulate within seconds (next
`Char.Vitals` tick), but `xp_progress`/`tp_progress` depend on level (from
`Char.StatusVars`) which is a sticky module not re-emitted over an existing
connection.

**Status:** Accepted. Cosmetic effect under a secondary developer workflow.
Full reconnect restores all fields.

### Polling

`bridge/status_pane.py` polls `bridge/status.state` every 50 ms via an asyncio
task. On mtime change the task re-reads the file and calls `app.invalidate()`.
SIGWINCH is handled automatically by prompt_toolkit; no dirty flag is needed.

### Rendering

`bridge/status_pane.py` is a `prompt_toolkit` full-screen `Application`
(`mouse_support=True`, `full_screen=True`, `color_depth=ColorDepth.DEPTH_24_BIT`).

Row helpers (`_build_frame`, `_build_toggles_row`, `_build_data_rows`, etc.)
still emit complete ANSI strings per row. Each string is wrapped with `ANSI(...)`
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
layer enforces a minimum of **29 columns** (`RIGHT_MIN` in `on_window_resize.sh`
and `apply_layout.sh`); the renderer itself trusts the reported size.

## State-file schema (`bridge/status.state`)

JSON written by `lua/core/status_state.lua`. Gitignored.

```json
{
  "character": "Aragorn",
  "race": "Man",
  "level": 50,
  "wimpy": 100,
  "xp": 34000000,
  "tp": 122000,
  "xp_progress": 0.42,
  "tp_progress": 0.71,
  "session_xp": 5400,
  "session_tp": 0,
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
arrived). `session_xp` / `session_tp` are populated by `lua/core/sess_kills.lua`.
`game_time` is populated via the `clock_changed` subscription. All non-progress
fields are retained in the payload for use by future rows.

`affects` was removed from the payload by ADR 0032 (no longer serialised).

### Field mapping from GMCP

| State field      | GMCP source                                            | Notes                                        |
|------------------|--------------------------------------------------------|----------------------------------------------|
| `character`      | `Char.Name` → `state.char.name`                        |                                              |
| `race`           | `Char.StatusVars` → `state.char.race`                  |                                              |
| `level`          | `Char.StatusVars` → `state.char.level`                 |                                              |
| `wimpy`          | `Char.Vitals` → `state.char.wimpy`                     | integer; null until first Vitals tick        |
| `xp`             | `Char.Vitals` → `state.char.xp`                        |                                              |
| `tp`             | `Char.Vitals` → `state.char.tp`                        |                                              |
| `xp_progress`    | computed by `level_progress.compute_xp_progress`       | `null` until level + xp both known           |
| `tp_progress`    | computed by `level_progress.compute_tp_progress`       | `null` until level + tp + race all known; troll scales thresholds ×0.1 |
| `mood`           | `Char.Vitals` → `state.char.mood`                      |                                              |
| `alertness`      | `Char.Vitals` → `state.char.alertness`                 |                                              |
| `sneak`          | `Char.Vitals` → `state.char.sneak`                     | null→"off", "s"/"S"→"on"                    |
| `ride`           | `Char.Vitals` → `state.char.ride`                      | null/false/json.null→"off", else→"on"        |
| `position`       | `Char.Vitals` → `state.char.position`                  |                                              |
| `climb`          | `Char.Vitals` → `state.char.climb`                     | null→"off", "c"/"C"→"on"                    |
| `swim`           | `Char.Vitals` → `state.char.swim`                      | bool→"on"/"off"                              |
| `session_xp`     | `lua/core/sess_kills.lua` → `state.session.session_xp` |                                              |
| `session_tp`     | `lua/core/sess_kills.lua` → `state.session.session_tp` |                                              |
| `game_time`          | `lua/core/clock.lua` → `state.world.clock.format("panel_time")` |                                 |
| `time_period`        | `lua/core/clock.lua` → `state.world.clock.next_transition()` |                                   |
| `time_transition_at` | `lua/core/clock.lua` → `state.world.clock.next_transition()` | unix epoch int; consumed by input-pane renderer |
| `time_precision`     | `lua/core/clock.lua` → `state.world.clock.next_transition()` | `"MINUTE"`/`"HOUR"`; consumed by input-pane renderer |

## Colour scheme

Constants defined at the top of `bridge/status_pane.py`:

| Constant  | Escape                   | Role                                              |
|-----------|--------------------------|---------------------------------------------------|
| `C_RESET` | `\x1b[0m`                | Reset all                                         |
| `C_NAME`  | `\x1b[38;2;192;192;192m` | Row 1 text foreground (name + padding spaces)     |
| `C_XP_BG` | `\x1b[48;2;0;30;40m`    | XP bar background (RGB 0,30,40)                   |
| `C_BG_RST`| `\x1b[49m`               | Reset background only, keep foreground            |
| `C_TP_FG` | `\x1b[38;2;0;40;50m`    | TP bar `▀` foreground (RGB 0,40,50)               |
| `C_LABEL`         | `\x1b[38;2;128;128;128m`    | Data row label foreground (RGB 128,128,128)          |
| `C_VALUE`         | `\x1b[38;2;192;192;192m`    | Data row value foreground (RGB 192,192,192)          |
| `C_TOG_OFF_BG`    | `\x1b[48;2;0;0;0m`          | Toggle box background — off state (RGB 0,0,0 black)          |
| `C_TOG_OFF_LABEL` | `\x1b[38;2;25;25;25m`       | Toggle label foreground — off state (RGB 25,25,25)           |
| `C_TOG_OFF_FILL`  | `\x1b[38;2;0;0;0m`          | Toggle █ foreground — off state (RGB 0,0,0 black)            |
| `C_TOG_ON_BG`     | `\x1b[48;2;0;0;0m`          | Toggle box background — on state (RGB 0,0,0 black)           |
| `C_TOG_ON_LABEL`  | `\x1b[38;2;192;192;192m`    | Toggle label foreground — on state (RGB 192,192,192)         |
| `C_TOG_ON_FILL`   | `\x1b[38;2;0;0;0m`          | Toggle █ foreground — on state (RGB 0,0,0 black)             |


## Identity

The pane title is `status` (set via `select-pane -T`). The tmux
`pane-border-format` in `bridge/tmux_start.sh` maps the `status` title to the
label ` Character ` displayed in the top pane border. No header rows are
rendered inside the pane content.

## Field layout

`W = shutil.get_terminal_size().columns` (minimum 29, enforced upstream).

### Row 1 — character name with XP-progress background

- Full-width string: `state.char.name` (or `—` if null) centered in W columns
  (truncated to W if longer, space-padded otherwise).
- Foreground: `C_NAME` (RGB 192,192,192) everywhere on the row.
- Background: `C_XP_BG` (RGB 0,30,40) covers the leftmost
  `floor(W × xp_progress)` columns; remaining columns use the terminal default.
- Boundary trick: `<C_NAME><C_XP_BG><filled><C_BG_RST><unfilled><C_RESET>`.
  The background resets mid-line without touching the foreground.

### Row 2 — TP-progress thin bar

- Leftmost `floor(W × tp_progress)` columns: `▀` (U+2580), foreground `C_TP_FG`
  (RGB 0,40,50), no background.
- Remaining columns: space characters, no colour.

### Row 3 — four toggle-box cells (4-column layout)

Same `_col_widths(W)` distribution and 1-char mid-spacer as the data rows. Each
cell is laid out as `[icon][label][█-pad]`:

- **label**: toggle name in uppercase (`SNEAK`, `RIDE`, `CLIMB`, `SWIM`).
- **block-pad**: `col_w - len(label)` trailing `█` chars (min 0).

Both states share a black background (`C_TOG_*_BG = RGB 0,0,0`). The `█` pad
is also black, so it blends with the terminal background. State is communicated
entirely through label colour: off uses a near-invisible dark label
(`RGB 25,25,25`); on uses a light label (`RGB 192,192,192`).

| Col | Toggle | Off colours                                                             | On colours                                                            |
|-----|--------|-------------------------------------------------------------------------|-----------------------------------------------------------------------|
| 0   | SNEAK  | label `C_TOG_OFF_LABEL` (dark grey)                                     | label `C_TOG_ON_LABEL` (light)                                        |
| 1   | RIDE   | same                                                                    | same                                                                  |
| 2   | CLIMB  | same                                                                    | same                                                                  |
| 3   | SWIM   | same                                                                    | same                                                                  |

Missing or `"off"` value → cell renders in off state. `"on"` → on state.

### Row 4 — blank separator

Plain `" " * W` — no SGR.

### Rows 5–8 — four data rows (4-column layout)

`W = pane width`. Four columns sized by `_col_widths(W)`:

```python
base  = (W - 1) // 4
extra = (W - 1) %  4
cols  = [base + (1 if i < extra else 0) for i in range(4)]
```

A single-char spacer (no SGR) separates column 2 and column 3. Every row is
exactly W visible characters; no trailing padding ever needed.

| Row | Col 1 (label) | Col 2 (value)            | Col 3 (label) | Col 4 (value)              |
|-----|---------------|--------------------------|---------------|----------------------------|
| 5   | `RACE:`       | `race`                   | `LEVEL:`      | `level` (bare int)         |
| 6   | `MOOD:`       | `mood`                   | `SES-XP:`     | `session_xp` (fmt_sess)    |
| 7   | `ALERTNESS:`  | `alertness`              | `SES-TP:`     | `session_tp` (fmt_sess)    |
| 8   | `POSITION:`   | `position`               | `WIMPY:`      | `wimpy` (bare int)         |

Labels are truncated preserving the trailing colon; values are lowercased and
sliced. Null/missing values render as empty string (label + col-width spaces).
`session_xp`/`session_tp` are formatted as `"1.2k"` above 999 and bare integers
below. `level` and `wimpy` are bare integers.

Label foreground: `C_LABEL` (RGB 128,128,128). Value foreground: `C_VALUE`
(RGB 192,192,192). `C_RESET` between each value and the next label; spacer has
no SGR.

### Bootstrap behaviour

- `xp_progress` / `tp_progress` is `null` → bar renders empty (no fill).
- `character` is `null` → `—` centered on row 1.
- Any data-row value is `null` → empty string; only label text is shown.
- Any toggle field missing or `null` → rendered as off (no garbled text).

### Troll TP scaling

`lua/core/level_progress.lua` applies a ×0.1 multiplier to all TP thresholds
when `state.char.race` lowercases to `"troll"`. Sanity check: at level 5 with
100 TP, troll bar is full (100 / (1000 × 0.1) = 1.0); non-troll bar is 10 %.

## Layout integration

### Pane position

Right column (top to bottom): `status` → `ui` → `dev`. Status stays at the top
of the right column whenever it exists.

### Pane height

`status_height = 11` in `bridge/layout.conf`. `lua/core/status_state.lua`
sets `STATIC_ROWS = 11` and rewrites `layout.conf` + calls `apply_layout.sh`
whenever `STATIC_ROWS` changes, so adding a new row in `_build_frame` is a
two-place update (Python + Lua constant). Current breakdown: 2 progress-bar
rows + 1 toggle row + 1 blank separator + 4 data rows = 11 total.

### Width constraint

`bridge/on_window_resize.sh` enforces:

- `MAIN_MIN = 30` — main/tt++ pane floor
- `RIGHT_MIN = 29` — right column floor when status is open

Manual border drag is clamped to ≥ 29 in `bridge/on_pane_resize.sh`.

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -c`                           | `toggle_pane.sh status` (runtime only)          |
| In-game popup → Options           | `toggle_pane.sh status --persist`               |
| Launcher Options → Character pane | `_save_conf` → `startup.conf show_status`       |

Persistence key: `show_status` in `bridge/startup.conf`. Fresh-install default
is `1` (status pane on).

## Future steps

Subsequent commits may add further rows (game time, …). `STATIC_ROWS` in
`status_state.lua` and `_build_frame` in `status_pane.py` are the two places to
update for each new row.

---
Back to [architecture.md](../architecture.md).
