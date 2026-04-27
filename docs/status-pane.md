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
                                       mtime change │  50 ms poll
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

### Disconnect clear

`mark_mume_disconnected()` in `lua/brain.lua` calls `state.char.reset()` after
`state.session.reset()`. `state.char.reset()` is defined in `char_state.lua`;
it wipes every non-function key in `state.char` while keeping the table
identity intact so cached references elsewhere stay valid. The `status_state.lua`
wrapper around `state.char.reset` then calls `serialize()`, producing a single
atomic write to `bridge/status.state` with all character fields null. The
renderer displays `—` for null values. The `Affected by:` header and the
4-row affect block are always rendered, so the pane height stays at
`STATIC_ROWS + 1 + 4 = 11` within one poll tick (≤ 50 ms) — blank affect
rows replace any previously shown affects.

`mark_mume_disconnected()` is idempotent: a duplicate signal finds
`bridge/session.state` already absent and returns before reaching the reset
call, so no double-clear occurs. `Time:` retains its last value — `state.world`
(the clock) is separate state and is out of scope for the disconnect clear.

1. `io.open(bridge/status.state.tmp, "w")` → write JSON
2. `os.rename(tmp, bridge/status.state)` → atomic replace

The Python reader never sees a partial file.

### cp -r partial blank

After `cp -r` mid-session, **Name** and **Lv** show `—` and **Sess XP** /
**Sess TP** show `0` until the next full reconnect. Other fields (XP, TP,
mood, alertness, sneak, climb, swim, position) repopulate within seconds.

`cp -r` restarts the Lua brain. `state.char` is re-initialised empty.
`Char.Vitals` ticks on a steady cadence, so it fires within seconds and
triggers `serialize()` via the existing wrap in `status_state.lua` — writing
a partial snapshot to `bridge/status.state`. `Char.Name` and
`Char.StatusVars` are sticky modules: MUME emits them at login and does not
re-emit on a TCP connection that stays open across the reload, so
`state.char.name` and `state.char.level` remain nil for the remainder of the
session.

Same root cause as the "cp -r clears uptime" limitation described in
[docs/session-lifecycle.md](session-lifecycle.md): Lua state is process-local
and one-shot GMCP modules are not re-emitted over an existing connection.

**Status:** Accepted. Cosmetic effect under a secondary developer workflow.
Full reconnect restores all fields.

### Polling

`bridge/status_pane.py` polls `bridge/status.state` every 50 ms using
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
  "time_period": null,
  "time_remaining": null,
  "affects": [
    {"name": "Sanctuary", "type": "spell", "remaining_seconds": 272}
  ]
}
```

`session_xp` and `session_tp` are populated by `lua/core/sess_kills.lua`
(phase 4 — implemented). `game_time` is populated by the `clock_changed`
subscription in `lua/core/status_state.lua` (phase 3 — implemented). `affects`
is populated by the `affects_changed` subscription in `lua/core/status_state.lua`
(phase 2 — implemented). The renderer displays `—` when null (bootstrap window
before first Vitals tick). The affect block is always rendered (4 blank rows
when `affects` is empty).

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
| `game_time`      | `lua/core/clock.lua` → `state.world.clock.format("panel_time")` | null when precision is UNSET; `"?"` string when clock loaded but unsynced; time-only at HOUR/MINUTE, date at DAY |
| `time_period`    | `lua/core/clock.lua` → `state.world.clock.next_transition()` | `"day"` or `"night"` (current period); null when precision < HOUR |
| `time_remaining` | `lua/core/clock.lua` → `state.world.clock.next_transition()` | pre-formatted countdown string (`"H:MM"` or `"~N"`); null when precision < HOUR |
| `affects`        | `lua/core/affects.lua` → `state.char.affects` via `affects_changed` | array of `{name, type, remaining_seconds}` objects; `remaining_seconds` is nil when no duration known |

## Colour scheme

Constants defined at the top of `bridge/status_pane.py`:

| Constant         | Escape                          | Role                                |
|------------------|---------------------------------|-------------------------------------|
| `C_LABEL`        | `\x1b[38;2;154;168;183m`        | #9AA8B7 steel-blue — labels        |
| `C_VALUE`        | `\x1b[1;97m`                    | Bold bright white — values          |
| `C_RESET`        | `\x1b[0m`                       | Reset all                           |
| `C_AFFECT_SPELL` | `\x1b[38;2;122;169;214m`        | #7AA9D6 light steel-blue — spell affects |
| `C_AFFECT_BUFF`  | `\x1b[38;2;143;188;143m`        | #8FBC8F soft sage green — buff affects  |
| `C_AFFECT_DEBUFF`| `\x1b[38;2;201;112;112m`        | #C97070 muted brick red — debuff affects |
| `C_SUN`          | `\x1b[38;2;255;176;0m`          | #FFB000 intense amber gold — ☼ sun icon (upcoming day) |
| `C_MOON`         | `\x1b[38;2;74;144;226m`         | #4A90E2 vivid sky blue — ☾ moon icon (upcoming night) |

## Identity

The pane title is `status` (set via `select-pane -T`). The tmux
`pane-border-format` in `bridge/tmux_start.sh` maps the `status` title to the
label ` Character ` displayed in the top pane border. No header rows are
rendered inside the pane content.

## Field layout

Paired rows (two fields side by side in 33 cols) and single rows:

```
Name: <name>          Lv: <level>
XP: <xp>              TP: <tp>
Sess XP: <sess_xp>    Sess TP: <sess_tp>
Mood: <mood>          Alert: <alertness>
Pos: <position>       Sneak: <sneak>
Climb: <climb>        Swim: <swim>
Time: <game_time>                          ← UNSET / DAY: single full-width row
Time: <H:MM AM/PM>   ☾ in <H:MM>          ← MINUTE (day→night example)
Time: <~H AM/PM>     ☼ in <~N>            ← HOUR   (night→day example)
Affected by:
  <affects>           ← 4 blank rows when no affects are active
```

At HOUR/MINUTE precision the Time row splits into a 16-col left half (label +
time-only value in `C_VALUE`) and a 17-col right half with a three-colour split:
icon in `C_SUN` (☼, intense amber) or `C_MOON` (☾, vivid sky blue), and the
countdown value in `C_VALUE` (bright white) — e.g. `☾ 4:20` or `☼ ~3`. At DAY or UNSET precision
`time_period` / `time_remaining` are null and the single full-width
`_row("Time:", ...)` fallback is used.

The `Affected by:` header and the 4-row affect block are always rendered.

Labels in `C_LABEL`, values in `C_VALUE`. Numeric values (`xp`, `tp`)
formatted with comma separators (232,200 rather than 232200).

## Layout integration

### Pane position

Right column (top to bottom): `status` → `ui` → `dev`. When a subset of
right panes is open, ordering is preserved — status stays at the top of the
right column whenever it exists; ui sits below status (or at the top if status
is absent); dev is always at the bottom.

### Pane height

`status_height=9` in `bridge/layout.conf` (9 body rows, no header). The pane
identity is shown in the tmux border label instead. `status_height` is driven
dynamically by `lua/core/status_state.lua` based on affect count; 9 is the
cold-start default before the first Lua serialise fires.

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
(default 20) and `status_height` (default 9) live in `layout.conf`.
Every right-column operation ends with a call to `apply_layout.sh`.

## Toggle

| Method                            | Mechanism                                       |
|-----------------------------------|-------------------------------------------------|
| `cp -c`                           | `toggle_pane.sh status` (runtime only)          |
| In-game popup → Options           | `toggle_pane.sh status --persist`               |
| Launcher Options → Character pane | `_save_conf` → `startup.conf show_status`       |

Persistence key: `show_status` in `bridge/startup.conf`. Fresh-install default
is `1` (status pane on). Existing `startup.conf` files that lack `show_status`
fall through to the runtime `${show_status:-0}` guard — existing installs see
no change.

## Affects

`lua/core/status_state.lua` subscribes to `affects_changed` (emitted by
`lua/core/affects.lua` on every state mutation and every tick). On each
notification it re-serialises `state.char.affects` into the `affects` array
in `bridge/status.state`.

### Schema

Each entry is an object:

```json
{"name": "Sanctuary", "type": "spell", "remaining_seconds": 272}
```

`remaining_seconds` is omitted (`null`) when no duration is known (affect has
no duration in the data table and no observed samples yet).

### Rendering

`status_pane.py` renders the affect block as a two-column grid. One
`Affected by:` header row is always emitted, followed by `BLOCK_ROWS` affect
rows:

```
BLOCK_ROWS = max(4, ceil(N / 2))
```

where N is the current affect count. Affects fill top-to-bottom, left cell
then right cell, in sort order. Empty cells render as spaces.

**Cell widths** (total `WIDTH = 33`):

| Cell  | Width |
|-------|-------|
| Left  | 16    |
| Right | 16    |

A 1-col `C_RESET` separator space sits between the two cells; total per affect row: `LEFT_W + 1 + RIGHT_W = 33`.

**Cell format — duration-bearing affect** (`remaining_seconds` is not null):

```
<name><padding><suffix>
```

- `suffix`: `"Xm"` using ceiling division — 0–59 s shows `1m`.
- `padding` = `cell_w − len(name) − len(suffix)`, minimum 1 space. Suffix is right-aligned at the cell edge.
- `MAX_NAME = 12` (`LEFT_W − min-padding(1) − len("99m")(3) = 16 − 4`). Applied globally before cell placement.
- Total = exactly `cell_w` visible chars.

**Cell format — indefinite affect** (`remaining_seconds` is null):

- Name fills `cell_w`, padded/truncated; no suffix, no separator space.

**Reference rendering** (`bless` 7m + `armour` 18m, both `spell` type):

```
bless         7m armour       18m
^^^^^^^^^^^^^^^^ ^^^^^^^^^^^^^^^^
   LEFT_W=16   ↑    RIGHT_W=16
           separator
```

Left cell: `bless`(5) + 9 padding + `7m`(2) = 16. Separator: 1. Right cell: `armour`(6) + 7 padding + `18m`(3) = 16. Total 33.

**Name resolution** (applied once using `MAX_NAME = 12`):

1. If name is in `_AFFECT_SHORTNAMES` → use shortname.
2. Else if `len(name) > 12` → truncate to 11 chars + `"."`.
3. Else use name as-is.

**Shortname mapping:**

| Full name                              | Shortname       |
|----------------------------------------|-----------------|
| `breath of briskness`                  | `briskness`     |
| `detect magic`                         | `det. magic`    |
| `detect evil`                          | `det. evil`     |
| `night vision`                         | `night vis.`    |
| `sense life`                           | `sense life`    |
| `Blood of Sauron`                      | `BoS`           |
| `a pitch-black robe (pale tones)`      | `pitch robe`    |
| `a pure white robe (pale tones)`       | `white robe`    |
| `heightened senses`                    | `h. senses`     |
| `heightened senses (faded)`            | `h. senses-`    |
| `dark aura`                            | `dark aura`     |
| `dark aura (faded)`                    | `dark aura-`    |
| `spectral health`                      | `spec. health`  |
| `very comfortable`                     | `v. comfort.`   |
| `shadow-link`                          | `shadow-link`   |

**Colour:** each cell is coloured independently by its affect's `type`:

  | `type`    | Constant          | Hex      |
  |-----------|-------------------|----------|
  | `spell`   | `C_AFFECT_SPELL`  | #7AA9D6  |
  | `buff`    | `C_AFFECT_BUFF`   | #8FBC8F  |
  | `debuff`  | `C_AFFECT_DEBUFF` | #C97070  |
  | (unknown) | `C_VALUE`         | fallback |

Empty cells use `C_RESET`. Each row ends with `C_RESET`.

### Sort order

Category order: **buff → spell → debuff → unknown**, alphabetical within each
category (case-insensitive). Unknown types sort after debuffs. Sort is applied
in `lua/core/status_state.lua` before serialisation; the renderer uses the
order as-is.

### Dynamic height

```
status_height = STATIC_ROWS + 1 + max(4, ceil(N / 2))
```

- `STATIC_ROWS`: count of always-rendered body rows (Name/Lv, SessXP/TP,
  Mood/Alert, Pos/Sneak, Climb/Swim, Time) — currently `6`. Lives in
  `lua/core/status_state.lua`; bump whenever a static body row is added or
  removed in `bridge/status_pane.py`.
- `+ 1`: the always-rendered `Affected by:` header row.
- `max(4, …)`: height is stable for N ≤ 8 (minimum 4 affect rows = height
  14). For N > 8, height grows by one row per two additional affects.

`lua/core/status_state.lua` owns this: after each atomic write to
`bridge/status.state` it checks the new height against `_last_height`; if
different it rewrites `status_height=` in `bridge/layout.conf` (atomic
tmp-rename) and fires:

```lua
tintin_cmd("gts", "#system {bash bridge/apply_layout.sh}")
```

The existing clamp behaviour in `apply_layout.sh` ensures dev pane keeps
≥ 1 row regardless of affect count.

## Extension points (phases 3–4)

### Phase 3 — Game time (implemented)

Clock module `lua/core/clock.lua` and the status-pane wiring are both active.

`lua/core/status_state.lua` populates `game_time` in `serialize()`:

```lua
local nt = state.world.clock and state.world.clock.next_transition() or nil
-- in payload:
game_time      = state.world.clock and state.world.clock.format("panel_time") or nil,
time_period    = nt and nt.period or nil,
time_remaining = nt and nt.remaining or nil,
```

It also subscribes to the `clock_changed` event emitted by `clock.lua` after
every sync and on each minute rollover:

```lua
events.subscribe("clock_changed", function() serialize() end)
```

This means the panel updates immediately on a sync — not on the next
`Char.Vitals` tick.

**Consumer contract:** `state.world.clock.format("panel_time")` returns:
- `"?"` when precision is UNSET (no sync yet) — renderer shows `?`
- `"Solmath 26, 2973"` (DAY precision — date known, hour unknown)
- `"~8 AM"` (HOUR precision — time only, no date)
- `"8:00 AM"` (MINUTE precision — time only, no date)

`state.world.clock.next_transition()` returns nil at UNSET/DAY; at HOUR/MINUTE
it returns `{period, remaining}` driving the right-half countdown column.

The `"compact"` format (`"8:00, Solmath 26"`, lowercase am/pm, comma separator)
remains available for other consumers; the panel no longer uses it.

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
