# Affect Tracker

Tracks active affects per character, learns observed durations from the last
3 sessions, and persists per character to disk. This document covers the
data layer and event bus; rendering is handled by the buffs pane — see
[`docs/buffs-pane.md`](buffs-pane.md) for the rendering spec.

## Data flow

```
MUME game output
      │
      ▼
tt++ #action (GAME_SESSION, priority 3)
  — one action per unique pattern string
  — registered by _affects_register_triggers() at SESSION CONNECTED / cp -r
      │
      ▼ events.emit("affect_init"|"affect_refresh"|"affect_down", name)
      │
      ▼
lua/core/affects.lua  ──►  state.char.affects      (active list)
                      ──►  state.char.affect_times  (ring-buffer history)
                      ──►  logs/affect_times/<character>.json  (disk)
```

## State schema

### `state.char.affects`

Array of currently-active affect entries:

```lua
{
    name              = "armour",    -- string, matches key in affects_data.affects
    type              = "protection",-- string, from data table
    started_at        = 1714000000, -- os.time() when init or refresh fired
    expected_duration = 1800,        -- integer seconds (mean of samples, else static, else nil)
    expires_at        = 1714001800, -- started_at + expected_duration, or nil
}
```

`expected_duration` and `expires_at` are nil for indefinite affects — those
whose data-table entry has no `duration` field (e.g. `hunger`, `thirst`,
`comfortable`, `growth`, `depression`).

### `state.char.affect_times`

Table mapping affect name → array of up to 3 observed durations (integers,
seconds). FIFO ring-buffer: push to end, drop from front when length exceeds 3.

```lua
{
    armour    = {1800, 1795, 1803},
    sanctuary = {268, 271, 267},
}
```

Both slots are initialised to `{}` at module load and re-initialised to `{}`
on each `Char.Name` (login). `state.char.reset()` (called on disconnect) wipes
them via the standard non-function-key sweep in `char_state.lua`.

## Indefinite affects

Entries in `affects_data.lua` without a `duration` field are indefinite. They
are tracked while active (entry exists in `state.char.affects`, removed when
the drop string fires), but no remaining time is computed, no row suffix is
rendered, and no observed durations are recorded. Examples: `hunger`, `thirst`,
`comfortable`, `growth`, `depression`.

The `duration` field is the single gate: if it is absent, `expected_duration`
and `expires_at` are both nil regardless of any legacy samples on disk. The
tick never prunes indefinite entries. Duration-less affects never appear in
`logs/affect_times/<character>.json`.

Indefinite affects are also excluded from active-list persistence (see
[Persistence — active list](#persistence--active-list) below). Rationale:
their state is unreliable across long absences and we prefer fresh
re-initialisation from in-game refresh strings.

- No `◆ TAG: name refreshed.` UI line is emitted when `initString_2`
  matches for a duration-less affect. The internal refresh path still
  runs (`started_at` is updated, `affects_changed` fires), but the
  player-facing announcement is suppressed because "refreshed" has no
  meaningful semantics without a timer.

## Persistence

**Path:** `logs/affect_times/<character>.json`

`<character>` is `state.char.name` exactly as received from GMCP `Char.Name`
(no case-folding, no sanitising).

**Format:**

```json
{
  "sanctuary": [266, 271, 269],
  "armour":    [1095, 1100, 1102]
}
```

Only affects that have been seen to drop naturally are persisted. Affects
pruned by the tick (past predicted expiry with no game confirmation) are NOT
recorded — that duration sample is suspect. Duration-less affects (no
`duration` field in the data table) never appear in this file; any such
entries written by an older version are filtered out at load time and removed
on the next write.

**Write:** atomic temp-file + `os.rename`, synchronous, inside `affect_down`.

**Read:** on `Char.Name` (via the `gmcp.handlers["Char.Name"]` wrap installed
by `_install_hooks()`). If the file is absent or malformed, `state.char.affect_times`
stays `{}` and a non-fatal `dbg` warning is logged.

## Persistence — active list

**Path:** `logs/affects_active/<character>.json`

`<character>` is `state.char.name` verbatim (same convention as
`logs/affect_times/`).

**Schema:** a JSON array of entries with the same shape as
`state.char.affects` items:

```json
[
  {
    "name": "armour",
    "type": "protection",
    "started_at": 1714000000,
    "expected_duration": 1800,
    "expires_at": 1714001800
  }
]
```

Indefinite affects (`expires_at == nil`) are never written. When the last
timed affect drops the file is written as an empty array (`[]`) rather
than deleted, keeping it as a stable presence indicator.

**Write (atomic temp-file + `os.rename`)** at four points:

- End of `affect_init` handler (after entry appended).
- End of `affect_refresh` handler (after `started_at` / `expires_at` updated).
- End of `affect_down` handler (after `table.remove`).
- End of `_affects_tick` after the prune sweep, but only when at least one
  entry was removed (tracked with a `pruned` flag).

**Read** on `Char.Name` as step 4 of the `_install_hooks()` wrap, immediately
after `_load_times()`:

- Missing or malformed file → `dbg` warning, `state.char.affects` stays `{}`.
- Each entry is skipped if: `expires_at == nil` (indefinite / corrupt), the
  affect name is absent from `affects_data.affects`, the data-table entry has
  no `duration` field (table changed under us), or `expires_at <= os.time()`
  (expired during downtime). Expired entries are counted separately in the
  `dbg` log line.
- Surviving entries are appended to `state.char.affects`. If any survive, the
  tick delay is armed and `affects_changed` is emitted.
- No `affect_ui` lines are emitted — restore is silent.
- `dbg` line: `[AFFECTS] restored N active affects (M expired)`.

## Pattern storage convention

Pattern strings in `affects_data.lua` (`initString_1`, `initString_2`,
`dropString_1`, `dropString_2`) are stored anchored (`^...$`) in
tt++-compatible form and passed verbatim to `#action` at registration time.
No transformation happens at runtime.

Patterns that share the same string (e.g. `second wind`'s `dropString_1` and
`winded`'s `initString_1`) are collapsed into a single `#action` whose body
emits all relevant events semicolon-separated inside one `#lua {}` block.

### When adding new affects

Pre-convert patterns before committing to the data file:

1. Replace `\.` with `.` (tt++ treats `.` as a literal dot; no escaping needed).
2. Replace `.*` with `%*` (tt++ zero-or-more wildcard).
3. Anchor the pattern with `^` at the start and `$` at the end.
   This guards against false matches from tells, says, narrates, and
   social emotes that quote the same line.

If the pattern contains regex metacharacters not covered by these steps
(`\d`, `\w`, `[...]`, `(...)`, `?`, `+`, `|`), it cannot be used directly —
rewrite the pattern or split it into separate entries.

Examples:

| Game string trigger                    | Pattern to store                  |
|----------------------------------------|-----------------------------------|
| `^You start glowing.`                  | `^You start glowing.$`            |
| `^You feel weaker.$`                   | `^You feel weaker.$`              |
| `^You completely drain.*$`             | `^You completely drain%*$`        |
| `^Your lungs seem to burst as.*$`      | `^Your lungs seem to burst as%*$` |

## Registration global

`_affects_register_triggers()` is a global Lua function defined in
`lua/core/affects.lua`. It is called by the `_register_affect_actions` alias
in `ttpp/core/affects.tin`, which is invoked from:

- `SESSION CONNECTED` in `ttpp/core/system.tin` (immediately after
  `_register_clock_actions`).
- The `cp -r` reload chain in `ttpp/core/system.tin` (same position).

The function also calls `_install_hooks()` on its first invocation per load
cycle, which wraps `gmcp.handlers["Char.Name"]` (to reload persisted times on
login) and `state.char.reset` (to cancel the tick on disconnect). The `_installed`
flag is file-local and resets to `false` on each `cp -r` (fresh module load).

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing alias and exists only to populate the
game session's action list from the data table.

## Periodic tick

A named `#delay {affects_tick}` runs every 10 seconds in GAME_SESSION while
at least one affect is active. Tick behaviour depends on whether the affect
has a configured drop string (`dropString_1` or `dropString_2`):

**No drop string** — prune at `expires_at` as before. No observed-duration
sample is recorded (game never confirmed the drop). Dbg log:
`[AFFECTS] tick expire: <name>`.

**Has drop string** — the drop message is the sole expiry signal. The tick
keeps the entry in overrun (`expires_at <= now`) and does nothing, so the
renderer can show `!` and `affect_down` can record the actual duration when
the drop arrives. A hard 2.5× safety net applies: if
`now - started_at >= floor(2.5 × expected_duration)` the entry is silently
pruned with no sample and no `affect_ui` "down" line. Dbg log:
`[AFFECTS] tick timeout (no drop): <name>`.

**Corrupt entry** (affect name absent from `affects_data.affects`) — pruned
immediately; dbg log `[AFFECTS] tick expire: <name>` (same path as no-drop).

The tick fires every 10 s regardless of overrun — `affects_changed` is emitted
each cycle so the renderer re-evaluates overrun cells.

The tick is self-rescheduling: if `state.char.affects` is non-empty after the
sweep it re-issues `#delay {affects_tick} {#lua {_affects_tick()}} {10}`.
Named non-numeric delays replace an existing delay of the same name (confirmed
by `ttpp_manual.txt`), so re-arming is idempotent.

The tick is armed on the 0→1 transition in `affect_init` and cancelled:
- When the last active affect drops (`affect_down` empties the array).
- When `state.char.reset()` fires (via the reset wrapper — only effective when
  GAME_SESSION is still set, i.e. the Core.Goodbye path; the SESSION DISCONNECTED
  fallback path finds GAME_SESSION nil, but the session dying clears all its
  delays automatically).
- By `cp -r`: `#kill delay` on GAME_SESSION kills all delays including the tick.

## Overrun

An affect with a drop string that remains active past its `expires_at` is in
**overrun**. Its entry stays in `state.char.affects` with no change to
`expires_at`. `status_state.lua` therefore emits a negative `remaining_seconds`
(not clamped). The status pane renders the cell with a `!` suffix instead of
`Xm`. The affect is removed — and its observed duration recorded — when
`affect_down` fires. The 2.5× safety net is the only tick-driven removal.

## Rendering

`state.char.affects` is the data source for the buffs pane renderer. See
[docs/buffs-pane.md](buffs-pane.md) for the rendering phase details.

Each `affect_init`, `affect_refresh`, and `affect_down` event also emits a
`◆ TAG: name verb.` line to the UI pane via `affect_ui()` — see
[docs/ui-messaging.md](ui-messaging.md) for the format and colour palette.

## Known limitations

### `cp -r` mid-session without reconnect

After `cp -r` the Lua brain restarts, clearing `state.char.affects` and
`state.char.affect_times`. MUME does not re-send `Char.Name` while the TCP
connection is live, so the persisted `affect_times` file is not reloaded until
the next full reconnect. Any affects that were active at the time of `cp -r`
are lost from the tracker's view. Accepted limitation — same root cause as
documented for `docs/status-pane.md`.

### `cp -r` does not restore the active affect list

For the same reason above, the active affect list is not restored after
`cp -r`: `Char.Name` is not re-emitted on a live TCP connection, so
`_load_active()` never runs. The affect list stays empty until the next full
login. Accepted — same root cause as the Name/Lv blank documented in
`docs/status-pane.md` and `docs/session-lifecycle.md`.

---
Back to [architecture.md](../architecture.md).
