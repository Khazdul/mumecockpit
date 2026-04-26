# Game Clock

Passive MUME game-time tracker. Single-anchor model after MMapper's `src/clock`:
one variable (`mume_start_epoch`) encodes everything; current time is computed
on demand. Sync is purely passive — no commands are ever sent to MUME.

Touch this file when changing sync sources, persistence behaviour, or when
consuming game time from another module.

## Calendar

1 real second = 1 MUME minute. Full calendar:

| Unit  | Duration (real seconds) |
|-------|------------------------|
| Minute | 1 |
| Hour   | 60 |
| Day    | 1 440 (24 h) |
| Month  | 43 200 (30 days) |
| Year   | 518 400 (12 months = 360 days) |

Month names (0-indexed, Westron / Sindarin):

| Idx | Westron     | Sindarin   |
|-----|-------------|------------|
|  0  | Afteryule   | Narwain    |
|  1  | Solmath     | Ninui      |
|  2  | Rethe       | Gwaeron    |
|  3  | Astron      | Gwirith    |
|  4  | Thrimidge   | Lothron    |
|  5  | Forelithe   | Norui      |
|  6  | Afterlithe  | Cerveth    |
|  7  | Wedmath     | Urui       |
|  8  | Halimath    | Ivanneth   |
|  9  | Winterfilth | Narbeleth  |
| 10  | Blotmath    | Hithui     |
| 11  | Foreyule    | Girithron  |

Weekday names (0-indexed, Westron): Sterday, Sunday, Monday, Trewsday,
Hevensday, Mersday, Highday.

Dawn / dusk hours per month (MMapper `g_dawnHour` / `g_duskHour`):

```
dawn = { 8, 9, 8, 7, 7, 6, 5, 4, 5, 6, 7, 7 }
dusk = {18,17,18,19,20,20,21,22,21,20,20,19}
```

## Anchor formula

`mume_start_epoch` is the real unix timestamp corresponding to MUME virtual
year 0, month 0, day 0, hour 0. Current MUME time:

```
elapsed = os.time() - mume_start_epoch
year    = floor(elapsed / 518400)
month   = floor(elapsed / 43200)  % 12   -- 0-indexed
day     = floor(elapsed / 1440)   % 30   -- 0-indexed; +1 for display
hour    = floor(elapsed / 60)     % 24
minute  = elapsed % 60
```

## State schema (`state.world.clock`)

| Field              | Type            | Description |
|--------------------|-----------------|-------------|
| `mume_start_epoch` | int             | Unix epoch of MUME virtual y0/m0/d0/h0 |
| `last_sync_epoch`  | int or nil      | Real unix time of the most recent successful sync |
| `last_sync_reason` | string or nil   | `"sun_rise"`, `"sun_set"`, `"time_dated"`, `"time_day"`, `"room_clock"` |
| `precision`        | string          | `"UNSET"`, `"DAY"`, `"HOUR"`, or `"MINUTE"` |

## Public functions

**`state.world.clock.now()`** → table or nil

Returns nil when precision is `"UNSET"`. Otherwise returns:

```lua
{
    year, month,     -- month 0-indexed (0 = Afteryule)
    day,             -- 1-indexed (1-30)
    hour, minute,    -- 0-indexed
    weekday,         -- 0-indexed (0 = Sterday)
    season,          -- "Winter", "Spring", "Summer", or "Autumn"
    time_of_day,     -- "night", "dawn", "day", or "dusk"
    precision,       -- "DAY", "HOUR", or "MINUTE"
}
```

**`state.world.clock.format(style)`** → string

| Style     | UNSET | DAY example         | HOUR example        | MINUTE example    |
|-----------|-------|---------------------|---------------------|-------------------|
| `"compact"` | `"?"` | `"Solmath 26, 2973"` | `"~8 am, Solmath 26"` | `"8:00, Solmath 26"` |
| `"panel"`   | `"?"` | `"Solmath 26, 2973"` | `"~8 AM on Solmath 26"` | `"8:00 AM on Solmath 26"` |
| `"full"`    | `"?"` | weekday + full date + season | same | same |
| `"debug"`   | `"?"` | mse=… prec=… date/time | same | same |

The `~` prefix on HOUR indicates the minute is unknown.

`"panel"` uses 12-hour time with uppercase AM/PM and an `on` separator.
Midnight renders as `12 AM` / `12:00 AM`; noon as `12 PM` / `12:00 PM`.
The DAY row is identical to `"compact"` — no time component to show.

**`state.world.clock.tick()`** — called by a 1Hz tt++ ticker.

Computes the current moment and tracks whether the MUME minute has changed
since the previous tick. When the minute changes, emits `clock_changed` on
the event bus. No file I/O on tick.

## Sync sources

All three are passive subscribers on the Lua event bus. After every
successful sync, `clock_changed` is emitted on the event bus so subscribers
(e.g. `lua/core/status_state.lua`) can react immediately without waiting for
the next `Char.Vitals` tick.

Precision is monotonically non-decreasing during a session. A sync from a
lower-precision source (e.g. `time` output arriving after a sun event)
refreshes `mume_start_epoch` and `last_sync_epoch` but leaves precision
unchanged if the current precision is already higher. Precision is lowered
only by the 24 h / 7 d degradation rule applied at brain startup in
`_load()`.

> **gts-ticker constraint:** tt++ does not fire tickers in the startup session (`gts`). The clock ticker is therefore registered per game session inside `_register_clock_actions`, not at file-load time. It is created on SESSION CONNECTED and destroyed on disconnect.

### `event_sun` (emitted by `lua/core/world_state.lua`)

Body `{what = "rise"|"set"|"light"|"dark"}`. Only `"rise"` and `"set"` are
used; `"light"` and `"dark"` indicate room sun-shielding (indoors / dense
forest) and are ignored.

- `"rise"` → sets hour to `dawn[month+1]`, minute to 0
- `"set"`  → sets hour to `dusk[month+1]`, minute to 0

Requires precision ≥ DAY (month must be known). On success, upgrades
precision to MINUTE and writes `bridge/clock.state`.

### `mume_time_line` (emitted by `ttpp/core/clock.tin` on `time` output)

Two patterns matched in Lua (tt++ pre-filter passes the full line):

1. `"8 am on Mersday, the 26th of Solmath, year 2973 of the Third Age."` →
   full date + hour → DAY+HOUR anchor, precision HOUR (or MINUTE if already
   at MINUTE — minute is preserved from the current moment)
2. `"Mersday, the 26th of Solmath, year 2973 of the Third Age."` →
   date only (orc/troll/BN indoors) → DAY anchor, precision DAY (or higher
   if already higher — hour and minute are preserved from the current moment
   when current precision is ≥ HOUR / ≥ MINUTE respectively)

Hour and minute fields not communicated by the `time` output are preserved
from the existing moment when current precision makes them meaningful (HOUR
or MINUTE respectively). Mirrors MMapper's `parseMumeTime` field-overwrite
model.

The response `"You cannot guess the time indoors."` and the qualitative
outdoor snippets (`"It should be the end of the night soon."`, etc.) are
ignored — too coarse to anchor on.

### `room_clock_line` (emitted by `ttpp/core/clock.tin`)

Pattern: `"The current time is 8:00am."` → exact hour + minute.
Requires precision ≥ DAY. On success, precision MINUTE.

## Persistence — `bridge/clock.state`

Written atomically (temp-file + rename) after every successful sync. No
per-tick writes. Format:

```
mume_start_epoch=<int>
last_sync_epoch=<int>
last_sync_reason=<string>
precision=<UNSET|DAY|HOUR|MINUTE>
```

## Load-time degradation

Applied at brain startup when reading `bridge/clock.state`:

| `last_sync_epoch` age | Result |
|----------------------|--------|
| File missing / unreadable | `mume_start_epoch = SEED_EPOCH`, precision = UNSET |
| > 7 days              | Same as missing |
| 24 h – 7 days         | Keep epoch, force precision to DAY |
| ≤ 24 h                | Use stored values as-is |

## Seed

```lua
local SEED_EPOCH = 218678400   -- = 1696118400 - 2850 * 518400
```

Derived from: MUME year 2850 month 0 day 0 hour 0 coincided with unix
1696118400 (~October 1 2023 reset). When precision is UNSET, `format()`
returns `"?"` — the wrong year is never shown to the player.

**Refining the seed after a fresh install:** after the client has synced at
least once and `bridge/clock.state` exists, copy the `mume_start_epoch`
value out of that file and update `SEED_EPOCH` at the top of
`lua/core/clock.lua`. This keeps the cold-start estimate accurate and
reduces the UNSET window on future installs.

## Files

| File | Role |
|------|------|
| `lua/core/clock.lua` | Clock module — sync, state, public API |
| `ttpp/core/clock.tin` | Per-session ticker + `#action` pre-filters, registered via `_register_clock_actions` |
| `bridge/clock.state` | Persisted anchor (gitignored) |

---
Back to [architecture.md](../architecture.md).
