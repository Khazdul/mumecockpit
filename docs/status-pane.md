# Character Panel

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
  "session_xp": 5400,
  "session_tp": 0,
  "mood": "wimpy",
  "alertness": "normal",
  "sneak": "off",
  "position": "standing",
  "climb": "off",
  "swim": "off",
  "game_time": null,
  "affects": []
}
```

Phase 1 populates all fields except `game_time` and `affects` — these are
reserved slots for phases 3–4. `session_xp` and `session_tp` are populated by
`lua/core/sess_kills.lua` (phase 4 — implemented). The renderer displays `—`
when null (bootstrap window before first Vitals tick) and empty for `affects`.

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
| `session_xp`   | `lua/core/sess_kills.lua` → `state.session.session_xp` | null during bootstrap window; resets to 0 on `cp -r` (rebaselines on next Vitals tick — expected behaviour, not a bug) |
| `session_tp`   | `lua/core/sess_kills.lua` → `state.session.session_tp` | null during bootstrap window; resets to 0 on `cp -r` (rebaselines on next Vitals tick — expected behaviour, not a bug) |
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
│       Character Panel         │
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
Time: <game_time>
Affected by:
  <affects or "—">
```

Labels in `C_LABEL`, values in `C_VALUE`. Numeric values (`xp`, `tp`)
formatted with comma separators (232,200 rather than 232200).

## Layout integration

### Pane position

Right column (top to bottom): `status` → `ui` → `dev`. When a subset of
right panes is open, ordering is preserved — status stays at the top of the
right column whenever it exists; ui sits below status (or at the top if status
is absent); dev is always at the bottom.

### Pane height

`status_height=12` in `bridge/layout.conf` (3 header + 9 body rows). In phase 1
this value is fixed at 12 (matches rendered content). The char↔ui top border is
not user-resizable — dragging it snaps back without persisting any change;
`status_height` is never overwritten by a drag. Phase 2 will drive this
dynamically from `lua/core/status_state.lua` based on affect count.

`bridge/apply_layout.sh` owns all right-column heights. It applies
`ui_height` first (clamped so dev keeps ≥ 1 row when present), then
`status_height`; `dev` receives the residual. Applying ui before status means
tmux propagates tight-height squeezes char → ui → dev, preserving char as long
as possible. All three are re-established after every right-column operation.
The ui↔dev bottom border is the only height-flex border — dragging it persists
`ui_height = U`.

### Width constraint

`bridge/on_window_resize.sh` enforces a global constraint:

- `MAIN_MIN = 30` — main/tt++ pane floor
- `RIGHT_MIN = 33` — right column floor when any right pane is active

When the terminal is wide enough for both floors, right column is clamped to
at least `RIGHT_MIN`. When the terminal is narrowed so main would fall below
30, main wins and the right column shrinks below 33. Manual border drag is
clamped to ≥ 33 in `bridge/on_pane_resize.sh`.

`bridge/apply_layout.sh` additionally enforces the 33-col floor whenever status
is open: if the right column is narrower than 33 when `apply_layout.sh` runs
(e.g., after `cp -c` opens status into a column that was previously dragged
narrow), it widens the column automatically provided main can stay ≥ 30 cols.

### Height

`bridge/apply_layout.sh` owns all right-column heights. Apply order is
ui-first: `ui_height` is applied first (clamped so dev keeps ≥ 1 row when
present), then `status_height`; dev receives the residual. This order ensures
tmux propagates tight-height squeezes char → ui → dev. Both `ui_height`
(default 20) and `status_height` (fixed 12 in phase 1) live in `layout.conf`.
Every right-column operation ends with a call to `apply_layout.sh`.

## Toggle

| Method                         | Mechanism                                     |
|--------------------------------|-----------------------------------------------|
| `cp -c`                        | `toggle_pane.sh status` (runtime only)        |
| In-game popup → Options        | `toggle_pane.sh status --persist`             |
| Launcher Options → Character pane | `_save_conf` → `startup.conf show_status` |

Persistence: `show_status` in `bridge/startup.conf` (default `0`).

## Extension points (phases 2–4)

### Phase 2 — Affects tracker

- Set `affects` in the JSON schema to an array of strings (affect names).
- `status_pane.py` already renders `affects` as a list when non-empty.
- Populate from GMCP or text triggers in `status_state.lua`.
- Dynamic height — Lua writes a new `status_height` to layout.conf when
  `state.char.affects` length changes, then calls `apply_layout.sh` via
  `tintin_cmd('gts', '#system {bash bridge/apply_layout.sh}')` (or
  equivalent). If tmux can't grant the new height (ui and dev would be
  squeezed below a 1-row floor), apply_layout.sh should eat dev first
  (`tmux kill-pane` + clear show_dev runtime), then ui. Priority order:
  status > ui > dev. Not implemented in phase 1.

### Phase 3 — Game time (implemented)

Clock module `lua/core/clock.lua` is implemented and ready. To wire it to
the status pane:

1. In `lua/core/status_state.lua`, set `game_time` in `serialize()`:
   ```lua
   game_time = state.world.clock and state.world.clock.format("compact") or nil,
   ```
2. `status_pane.py` already renders `game_time` when non-null.

**Consumer contract:** `state.world.clock.format("compact")` returns:
- `"?"` when precision is UNSET (no sync yet)
- `"Solmath 26, 2973"` (DAY precision — date known, hour unknown)
- `"~8 am, Solmath 26"` (HOUR precision — `~` means minute unknown)
- `"8:00, Solmath 26"` (MINUTE precision — fully synced)

See [docs/clock.md](clock.md) for full API and sync source details.

### Phase 4 — Session XP/TP deltas (implemented)

Implemented in `lua/core/sess_kills.lua`. On first `Char.Vitals` after
connect, the current XP/TP is snapshotted as the baseline. Each subsequent
positive XP delta is attributed evenly across the kills queued via
`mob_death` events since the previous tick, and a `▶ KILL: <name>, <xp> xp.`
line is emitted to the UI pane per attributed kill. `state.session.kills` is
an append-only list of `{name, xp}` for the session.

`cp -r` resets the baseline: Lua state is wiped on reload, so the next
Vitals tick rebaselines from the current XP and `Sess XP` starts fresh from 0.
This is expected behaviour, not a bug.

---
Back to [architecture.md](../architecture.md).
