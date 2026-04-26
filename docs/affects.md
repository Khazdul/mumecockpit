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

## Pattern storage convention

Pattern strings in `affects_data.lua` (`initString_1`, `initString_2`,
`dropString_1`, `dropString_2`) are stored in tt++-compatible form and passed
verbatim to `#action` at registration time. No transformation happens at
runtime.

Patterns that share the same string (e.g. `second wind`'s `dropString_1` and
`winded`'s `initString_1`) are collapsed into a single `#action` whose body
emits all relevant events semicolon-separated inside one `#lua {}` block.

### When adding new affects

Pre-convert patterns before committing to the data file:

1. Replace `\.` with `.` (tt++ treats `.` as a literal dot; no escaping needed).
2. Replace `.*` with `%*` (tt++ zero-or-more wildcard).
3. Drop a leading `^` if present.
4. Drop a trailing `$` if present.

If the pattern contains regex metacharacters not covered by these four steps
(`\d`, `\w`, `[...]`, `(...)`, `?`, `+`, `|`), it cannot be used directly —
rewrite the pattern or split it into separate entries.

Examples:

| Game string trigger                    | Pattern to store               |
|----------------------------------------|--------------------------------|
| `^You start glowing.`                  | `You start glowing.`           |
| `[[^You feel weaker\.]]`               | `[[You feel weaker.]]`         |
| `^You completely drain.*$`             | `You completely drain%*`       |
| `^Your lungs seem to burst as.*$`      | `Your lungs seem to burst as%*`|

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

## Rendering

`lua/core/status_state.lua` subscribes to `affects_changed` and projects
the active list into `bridge/status.state` with `name`, `type`, and
`remaining_seconds` for each entry. `bridge/status_pane.py` renders each
entry as a type-coloured `"- <name> <Xm>"` row. See
[docs/status-pane.md](status-pane.md) for layout, colour constants, and
dynamic-height details.

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
