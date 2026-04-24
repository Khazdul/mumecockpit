# Character Status Pane

The status pane is a right-column tmux pane inserted between `ui` and `dev`
that displays a flicker-free, live character info board driven by GMCP data.
Touch this file when changing the renderer, the state-file schema, the field
layout, or any of the phase 2–4 extension points.

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
                                       mtime change │  250 ms poll
                                                   ▼
                          bridge/status_pane.py (tail-like loop)
                          redraws in-place via ANSI (no \e[2J)
```

### State flow

`lua/core/status_state.lua` loads after `char_state.lua` (alphabetical order
within `lua/core/`). It wraps each of char_state's three handlers:
`Char.Name`, `Char.StatusVars`, `Char.Vitals`. After the original handler
runs (updating `state.char.*`), the wrapper serialises the projected view and
writes it atomically:

1. `io.open(bridge/status.state.tmp, "w")` → write JSON
2. `os.rename(tmp, bridge/status.state)` → atomic replace

The Python reader never sees a partial file.

### Polling

`bridge/status_pane.py` polls `bridge/status.state` every 250 ms using
`os.stat().st_mtime`. On mtime change it re-reads and re-renders. SIGWINCH
sets a dirty flag; the next poll tick redraws even without mtime change.

### Rendering

Same flicker-free rules as `bridge/launcher.sh` (see `docs/launcher.md`):

- Cursor home (`\e[H`) at start of each redraw.
- Each line followed by `\e[K` (clear to EOL).
- `\e[J` at end (clear below last line).
- Never `\e[2J`.
- No trailing newline on last line.
- Cursor hidden (`\e[?25l`) on start; restored on SIGTERM and normal exit.

### Width

Internal render width: **33 columns**. Overflow is truncated. The right-column
floor for the layout system is also 33 (`RIGHT_MIN` in `on_window_resize.sh`).

## State-file schema (`bridge/status.state`)

JSON written by `lua/core/status_state.lua`. Gitignored.

```json
{
  "character": "Aragorn",
  "level": 50,
  "xp": 232200,
  "tp": 3424,
  "session_xp": null,
  "session_tp": null,
  "mood": "wimpy",
  "alertness": "normal",
  "sneak": "off",
  "position": "standing",
  "climb": "off",
  "swim": "off",
  "carrying": "comfortable",
  "game_time": null,
  "affects": []
}
```

Phase 1 populates all fields except `session_xp`, `session_tp`, `game_time`,
and `affects` — these are reserved slots for phases 2–4. The renderer
displays them as `—` / empty when null/empty.

### Field mapping from GMCP

| State field    | GMCP source                  | Notes                              |
|----------------|------------------------------|------------------------------------|
| `character`    | `Char.Name` → `state.char.name`    | kebab→snake by char_state          |
| `level`        | `Char.StatusVars` → `state.char.level` |                               |
| `xp`           | `Char.Vitals` → `state.char.xp`   |                                    |
| `tp`           | `Char.Vitals` → `state.char.tp`   |                                    |
| `mood`         | `Char.Vitals` → `state.char.mood` |                                    |
| `alertness`    | `Char.Vitals` → `state.char.alertness` |                               |
| `sneak`        | `Char.Vitals` → `state.char.sneak` | null→"off", "s"/"S"→"on"         |
| `position`     | `Char.Vitals` → `state.char.position` |                               |
| `climb`        | `Char.Vitals` → `state.char.climb` | null→"off", "c"/"C"→"on"         |
| `swim`         | `Char.Vitals` → `state.char.swim`  | bool→"on"/"off"                  |
| `carrying`     | `Char.Vitals` → `state.char.carrying` |                               |
| `session_xp`   | phase 4 — always null in phase 1   |                                   |
| `session_tp`   | phase 4 — always null in phase 1   |                                   |
| `game_time`    | phase 3 — always null in phase 1   |                                   |
| `affects`      | phase 2 — always [] in phase 1     |                                   |

## Colour scheme

Constants defined at the top of `bridge/status_pane.py`:

| Constant  | Escape                          | Role                          |
|-----------|---------------------------------|-------------------------------|
| `C_LABEL` | `\x1b[38;2;154;168;183m`        | #9AA8B7 steel-blue — labels  |
| `C_VALUE` | `\x1b[1;97m`                    | Bold bright white — values    |
| `C_FRAME` | `\x1b[38;2;166;140;90m`         | Muted gold — box frame        |
| `C_TITLE` | `\x1b[1;38;2;222;184;135m`      | Burlywood — header title      |
| `C_RESET` | `\x1b[0m`                       | Reset all                     |

## Header

Three-row box drawn at 33 columns:

```
┌───────────────────────────────┐
│       Character Status        │
└───────────────────────────────┘
```

Frame in `C_FRAME`, title text in `C_TITLE`.

## Field layout

Paired rows (two fields side by side in 33 cols) and single rows:

```
Name: <name>          Lv: <level>
XP: <xp>              TP: <tp>
Sess XP: <sess_xp>    Sess TP: <sess_tp>
Mood: <mood>          Alert: <alertness>
Pos: <position>       Sneak: <sneak>
Climb: <climb>        Swim: <swim>
Carrying: <carrying>
Game time: <game_time>
Affected by:
  <affects or "—">
```

Labels in `C_LABEL`, values in `C_VALUE`. Numeric values (`xp`, `tp`)
formatted with comma separators (232,200 rather than 232200).

## Layout integration

### Pane position

Right column (top to bottom): `ui` → `status` → `dev`. When a subset of
right panes is open, ordering is preserved — status stays between ui and dev
when both are present, below ui if only ui exists, above dev if only dev exists.

### Default height

`status_height=14` in `bridge/layout.conf`. Resize with the border or set
directly in layout.conf between sessions.

### Width constraint

`bridge/on_window_resize.sh` enforces a global constraint:

- `MAIN_MIN = 30` — main/tt++ pane floor
- `RIGHT_MIN = 33` — right column floor when any right pane is active

When the terminal is wide enough for both floors, right column is clamped to
at least `RIGHT_MIN`. When the terminal is narrowed so main would fall below
30, main wins and the right column shrinks below 33. Manual border drag is
clamped to ≥ 33 in `bridge/on_pane_resize.sh`.

### Height ratio

When `ui` and `dev` are both open alongside `status`, the `ui_height_ratio`
applies to the `ui + dev` subtree only — status pane height is managed
separately via `status_height`. The existing `on_window_resize.sh` height
ratio logic excludes status automatically (queries ui/dev by title) and
then explicitly restores `status_height` after the ratio resize.

## Toggle

| Method                       | Mechanism                                     |
|------------------------------|-----------------------------------------------|
| `cp -c`                      | `toggle_pane.sh status` (runtime only)        |
| In-game popup → Options      | `toggle_pane.sh status --persist`             |
| Launcher Options → Status pane | `_save_conf` → `startup.conf show_status`   |

Persistence: `show_status` in `bridge/startup.conf` (default `0`).

## Extension points (phases 2–4)

### Phase 2 — Affects tracker

- Set `affects` in the JSON schema to an array of strings (affect names).
- `status_pane.py` already renders `affects` as a list when non-empty.
- Populate from GMCP or text triggers in `status_state.lua`.
- Dynamic pane-height adjustment based on affect count is a phase 2 item.

### Phase 3 — Game time

- Set `game_time` to a string (e.g. "dusk, day 5 of March").
- Source: text-triggered world clock (no GMCP module available).
- `status_pane.py` renders it directly when non-null.

### Phase 4 — Session XP/TP deltas

- Set `session_xp` / `session_tp` to integer deltas.
- Requires SESSION hook wiring to capture start-of-session XP/TP baseline.
- The `_orig_vitals` wrapper in `status_state.lua` is the right place to
  compute the delta once the baseline is available.

---
Back to [architecture.md](../architecture.md).
