# Affect Tracker

Tracks active affects per character, learns observed durations from the last
3 sessions, and persists per character to disk. Phase A: data layer and event
bus only — no UI rendering. Phase B will extend `status_state.lua` and
`status_pane.py` to render the affect list.

## Data flow

```
MUME game output
      │
      ▼
tt++ #action (GAME_SESSION, priority 3)
  — one action per unique converted pattern
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

`expected_duration` and `expires_at` are nil when no duration is known (e.g.
affects with no `duration` field in the data table and no observed samples yet,
or affects without `dropString` entries like `growth`).

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
recorded — that duration sample is suspect.

**Write:** atomic temp-file + `os.rename`, synchronous, inside `affect_down`.

**Read:** on `Char.Name` (via the `gmcp.handlers["Char.Name"]` wrap installed
by `_install_hooks()`). If the file is absent or malformed, `state.char.affect_times`
stays `{}` and a non-fatal `dbg` warning is logged.

## Pattern conversion rules

`affects_data.lua` stores Mudlet-style regex strings in `initString_1`,
`initString_2`, `dropString_1`, `dropString_2`. `_affects_register_triggers()`
converts each pattern to a tt++ `#action` pattern:

1. Strip a single leading `^`.
2. Strip a single trailing `$`.
3. Replace `.*` with `%*` (tt++ zero-or-more wildcard).
4. Replace `\.` with `.` (tt++ treats `.` as a literal dot in action patterns).
5. If the result still contains regex metacharacters (`\`, `[`, `]`, `(`, `)`,
   `+`, `?`, `|`), log `[AFFECTS] unsupported pattern: <original>` and skip —
   no half-translated pattern is registered.

Patterns that share the same converted string (e.g. `second wind`'s
`dropString_1` and `winded`'s `initString_1`) are collapsed into a single
`#action` whose body emits all relevant events semicolon-separated inside one
`#lua {}` block.

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
at least one affect is active. It prunes entries whose `expires_at` is non-nil
and in the past. Pruned entries are silently removed — no observed-duration
sample is recorded because the game never confirmed the drop.

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

## Known limitations

### `cp -r` mid-session without reconnect

After `cp -r` the Lua brain restarts, clearing `state.char.affects` and
`state.char.affect_times`. MUME does not re-send `Char.Name` while the TCP
connection is live, so the persisted `affect_times` file is not reloaded until
the next full reconnect. Any affects that were active at the time of `cp -r`
are lost from the tracker's view. Accepted limitation — same root cause as
documented for `docs/status-pane.md`.

---
Back to [architecture.md](../architecture.md).
