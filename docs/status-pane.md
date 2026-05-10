# Character Status Pane

The status pane is a right-column tmux pane that displays a live character
info board driven by GMCP data.
Touch this file when changing the renderer, the state-file schema, the field
layout, or layout integration.

Two progress-bar rows (XP and TP), a row of four toggle-box cells
(SNEAK / RIDE / CLIMB / SWIM), a blank separator, and two data rows
(alertness/position, mood/wimpy) make up the six-row layout. Game time is
shown in the input-pane menu bar, sourced from the same `status.state`
payload.

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

### Disconnect clear

`mark_mume_disconnected()` in `lua/brain.lua` calls `state.char.reset()` after
`state.run.reset()`. `state.char.reset()` is defined in `char_state.lua`;
it wipes every non-function key in `state.char` while keeping the table
identity intact so cached references elsewhere stay valid, then emits
`char_reset`. `status_state.lua`'s `char_reset` subscriber calls `serialize()`,
producing a single atomic write to `bridge/runtime/status.state` with all character
fields null. The renderer displays `—` for null name and empty bars for null
progress. Data rows render as label-only (empty value cells). Pane height stays
at `STATIC_ROWS = 6` within one poll tick (≤ 50 ms).

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
| `run_xp`         | `lua/core/run_state.lua` → `state.run.xp`              |                                              |
| `run_tp`         | `lua/core/run_state.lua` → `state.run.tp`              |                                              |
| `game_time`          | `lua/core/clock.lua` → `state.world.clock.format("panel_time")` |                                 |
| `time_period`        | `lua/core/clock.lua` → `state.world.clock.next_transition()` |                                   |
| `time_transition_at` | `lua/core/clock.lua` → `state.world.clock.next_transition()` | unix epoch int; consumed by input-pane renderer |
| `time_precision`     | `lua/core/clock.lua` → `state.world.clock.next_transition()` | `"MINUTE"`/`"HOUR"`; consumed by input-pane renderer |

## Colour scheme

Constants defined at the top of `bridge/panes/status_pane.py`:

| Constant  | Escape                   | Role                                              |
|-----------|--------------------------|---------------------------------------------------|
| `C_RESET` | `\x1b[0m`                | Reset all                                         |
| `C_NAME`  | `\x1b[38;2;192;192;192m` | Row 1 text foreground (name + padding spaces)     |
| `C_XP_BG` | `\x1b[48;2;0;30;40m`    | XP bar background — baseline segment (RGB 0,30,40) |
| `C_XP_NEW_BG` | `\x1b[48;2;92;15;91m`   | XP bar session-gain segment background (RGB 92,15,91 — `#5C0F5B`) |
| `C_BG_RST`| `\x1b[49m`               | Reset background only, keep foreground            |
| `C_TP_FG` | `\x1b[38;2;0;40;50m`    | TP bar `▀` foreground — baseline segment (RGB 0,40,50) |
| `C_TP_NEW_FG` | `\x1b[38;2;61;10;60m`   | TP bar session-gain segment `▀` foreground (RGB 61,10,60 — `#3D0A3C`) |
| `C_LABEL`         | `\x1b[38;2;128;128;128m`    | Data row label foreground (RGB 128,128,128)          |
| `C_VALUE`         | `\x1b[38;2;192;192;192m`    | Data row value foreground (RGB 192,192,192)          |
| `C_TOG_OFF_LABEL` | `\x1b[38;2;83;72;56m`       | Toggle label foreground — off state (RGB 83,72,56 — `#534838` warm dark brown) |
| `C_TOG_ON_LABEL`  | `\x1b[38;2;212;160;78m`     | Toggle label foreground — on state (RGB 212,160,78 — `#D4A04E` warm gold)        |


## Identity

The pane title is `status` (set via `select-pane -T`). The tmux
`pane-border-format` in `bridge/launcher/tmux_start.sh` maps the `status` title to the
label ` Character ` displayed in the top pane border. No header rows are
rendered inside the pane content.

## Field layout

`W = shutil.get_terminal_size().columns` (adaptive; no upstream minimum enforced).

### Row 1 — character name with XP-progress background

- Full-width string: `state.char.name` (or `—` if null) centered in W columns
  (truncated to W if longer, space-padded otherwise).
- Foreground: `C_NAME` (RGB 192,192,192) everywhere on the row.
- Three-segment background:
  - leftmost `floor(W × xp_progress_baseline)` columns: `C_XP_BG` (RGB 0,30,40)
    — XP already present at session start.
  - next `floor(W × xp_progress) − floor(W × xp_progress_baseline)` columns:
    `C_XP_NEW_BG` (RGB 92,15,91 — `#5C0F5B`) — XP gained this session.
  - remaining columns: terminal default (no background).
- Boundary trick:
  `<C_NAME><C_XP_BG><baseline><C_XP_NEW_BG><session-gain><C_BG_RST><unfilled><C_RESET>`.
  The background changes mid-line without touching the foreground; `C_BG_RST`
  resets only the background at the trailing edge.
- See [Session-gain visualisation](#session-gain-visualisation) below for the
  baseline rules.

### Row 2 — TP-progress thin bar

- Leftmost `floor(W × tp_progress_baseline)` columns: `▀` (U+2580), foreground
  `C_TP_FG` (RGB 0,40,50), no background — TP already present at session start.
- Next `floor(W × tp_progress) − floor(W × tp_progress_baseline)` columns: `▀`,
  foreground `C_TP_NEW_FG` (RGB 61,10,60 — `#3D0A3C`), no background — TP
  gained this session.
- Remaining columns: space characters, no colour.
- See [Session-gain visualisation](#session-gain-visualisation) below for the
  baseline rules.

### Row 3 — four toggle-box cells (4-column layout)

Same `_col_widths(W)` distribution and 1-char mid-spacer as the data rows. Each
cell is laid out as `[label][space-pad]`:

- **label**: toggle name in uppercase (`SNEAK`, `RIDE`, `CLIMB`, `SWIM`).
- **space-pad**: `col_w - len(label)` trailing space chars (min 0), unstyled.

No background is set; the terminal background shows through. State is
communicated entirely through label colour: off uses a warm dark brown label
(`RGB 83,72,56`); on uses a warm gold label (`RGB 212,160,78`).

| Col | Toggle | Off colours                          | On colours                          |
|-----|--------|--------------------------------------|-------------------------------------|
| 0   | SNEAK  | label `C_TOG_OFF_LABEL` (`#534838`)  | label `C_TOG_ON_LABEL` (`#D4A04E`) |
| 1   | RIDE   | same                                 | same                                |
| 2   | CLIMB  | same                                 | same                                |
| 3   | SWIM   | same                                 | same                                |

Missing or `"off"` value → cell renders in off state. `"on"` → on state.

### Row 4 — blank separator

Plain `" " * W` — no SGR.

### Rows 5–6 — two data rows (4-column layout)

`W = pane width`. Four columns sized by `_col_widths(W)`:

```python
base  = (W - 1) // 4
extra = (W - 1) %  4
cols  = [base + (1 if i < extra else 0) for i in range(4)]
```

A single-char spacer (no SGR) separates column 2 and column 3. Every row is
exactly W visible characters; no trailing padding ever needed.

| Row | Col 1 (label) | Col 2 (value)        | Col 3 (label) | Col 4 (value) |
|-----|---------------|----------------------|---------------|---------------|
| 5   | `MOOD:`       | `mood`               | `ALERTNESS:`  | `alertness`   |
| 6   | `WIMPY:`      | `wimpy` (bare int)   | `POSITION:`   | `position`    |

Labels are truncated preserving the trailing colon; values are lowercased and
sliced. Null/missing values render as empty string (label + col-width spaces).
Only `wimpy` is a bare integer.

Label foreground: `C_LABEL` (RGB 128,128,128). Value foreground: `C_VALUE`
(RGB 192,192,192). `C_RESET` between each value and the next label; spacer has
no SGR.

### Bootstrap behaviour

- `xp_progress` / `tp_progress` is `null` → bar renders empty (no fill).
- `xp_progress_baseline` / `tp_progress_baseline` is `null` or `0` → no
  session-gain segment is drawn; the bar is visually identical to the
  pre-feature single-colour rendering.
- `character` is `null` → `—` centered on row 1.
- Any data-row value is `null` → empty string; only label text is shown.
- Any toggle field missing or `null` → rendered as off (no garbled text).

### Session-gain visualisation

Both the XP bar (Row 1) and TP bar (Row 2) split into a baseline segment and a
session-gain segment to show progress earned during the current session. The
baseline values (`xp_progress_baseline`, `tp_progress_baseline`) are computed
in `lua/core/level_progress.lua` from `xp − run_xp` and `tp − run_tp`.

| Scenario                                  | Baseline value                                      | Visual                                                                              |
|-------------------------------------------|-----------------------------------------------------|-------------------------------------------------------------------------------------|
| Level-up during session                   | 0 (re-anchored at the new level's start)            | Whole filled region renders in the session-gain colour until the next level-up.     |
| Disconnect / reconnect                    | `run_xp`/`run_tp` reset to 0 → baseline = current   | Bar reverts to all-baseline colour until the next XP/TP tick.                       |
| Lost XP this session (negative `run_xp`)  | clamped to current progress                         | Session-gain segment is zero-width; the loss is not separately visualised.          |

Troll TP scaling (×0.1) applies identically to both `tp_progress` and
`tp_progress_baseline`.

### Troll TP scaling

`lua/core/level_progress.lua` applies a ×0.1 multiplier to all TP thresholds
when `state.char.race` lowercases to `"troll"`. Sanity check: at level 5 with
100 TP, troll bar is full (100 / (1000 × 0.1) = 1.0); non-troll bar is 10 %.

## Layout integration

### Pane position

Right column (top to bottom): `status` → `buffs` → `comm` → `ui` → `dev`. Status stays at the top
of the right column whenever it exists.

### Pane height

`status_height = 6` in `bridge/runtime/layout.conf`. `lua/core/status_state.lua`
sets `STATIC_ROWS = 6` and rewrites `layout.conf` + calls `apply_layout.sh`
whenever `STATIC_ROWS` changes, so adding a new row in `_build_frame` is a
two-place update (Python + Lua constant). Current breakdown: 2 progress-bar
rows + 1 toggle row + 1 blank separator + 2 data rows = 6 total.

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

Persistence key: `show_status` in `bridge/runtime/startup.conf`. Fresh-install default
is `1` (status pane on).

---
Back to [architecture.md](../architecture.md).
