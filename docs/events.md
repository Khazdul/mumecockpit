# Events

Authoritative reference for the Lua event bus: API, error handling, and
the catalogue of events currently emitted by the client. Touch this file
when adding a new trigger to `ttpp/core/mud_events.tin` or when a script
subscribes to a new event name.

See [docs/decisions/0007-event-bus.md](decisions/0007-event-bus.md) for the
design rationale.

## Overview

The event bus provides a lightweight fan-out mechanism for MUD events that
multiple scripts need to react to. The API (`events.subscribe`,
`events.emit`, `events.unsubscribe`) is defined in `lua/brain.lua`
alongside `gmcp.dispatch`, ensuring it is available before any core or
script module loads. High-priority core triggers in
`ttpp/core/mud_events.tin` (priority 3) capture MUD output and call
`events.emit(name, ...)`. Scripts subscribe at start time and unsubscribe
on abort — no changes to core files are needed when adding a new subscriber.

The bus is the canonical solution to the trigger-ownership problem: two
scripts registering the same `#action` pattern would race; subscribing to a
shared event is safe by design.

## API

**`events.subscribe(name, fn)`**  
Append `fn` to the handler list for `name`. Creates the list if absent.
Returns `fn` so the caller can pass it directly to `unsubscribe`.

**`events.unsubscribe(name, fn)`**  
Remove `fn` from the handler list for `name`. No-op if absent. Idempotent —
safe to call even when not currently subscribed (e.g. in cleanup paths that
run unconditionally).

**`events.emit(name, ...)`**  
Call each handler registered under `name` in order, passing the varargs.
Each handler runs under `pcall` — a crashing handler logs
`events handler error [<name>]: <err>` via `dbg()` and does not prevent
later handlers from running.

**`events.trace`** (default `false`)  
When true, every `emit` call logs `[EVENTS] <name> = <args>` to
`logs/debug.log`. Flip to `true` in `brain.lua` temporarily when debugging
event flow. Same pattern as `gmcp.trace`.

## Catalogue

| Event | Payload | Source |
|-------|---------|--------|
| `mob_death` | mob name string (includes article, e.g. `"an elven slave"`) | `ttpp/core/mud_events.tin` |
| `event_sun` | `{what = "rise"\|"set"\|"light"\|"dark"}` | `lua/core/world_state.lua` (GMCP) |
| `mume_time_line` | full matched line string | `ttpp/core/clock.tin` `#action` |
| `room_clock_line` | full matched line string | `ttpp/core/clock.tin` `#action` |
| `clock_changed` | (none) | `lua/core/clock.lua` — emitted on each successful sync and on minute rollover in `tick()` |
| `affect_init` | affect name string (e.g. `"armour"`) | `ttpp/core/affects.tin` `#action` (via `_affects_register_triggers`) |
| `affect_refresh` | affect name string | `ttpp/core/affects.tin` `#action` |
| `affect_down` | affect name string | `ttpp/core/affects.tin` `#action` |

### `mob_death`

Emitted by the four patterns in `ttpp/core/mud_events.tin`:

    ^%1 is dead! R.I.P.$
    ^%1 has drawn his last breath! R.I.P.$
    ^%1 has drawn her last breath! R.I.P.$
    ^%1 disappears into nothing.$

All four are kills — `disappears into nothing.` is the undead-death
message. The subscriber receives the mob name captured by `%1`; it does
not see which variant fired.

**Subscribers:** `lua/scripts/autostab.lua`, `lua/scripts/autobow.lua`
(abort on kill), `lua/core/sess_kills.lua` (queues name for XP attribution).
`sess_kills` is the first core module to subscribe to its own bus — direct
parallel to script subscribers, no special wiring needed.

### `event_sun`

Emitted by `lua/core/world_state.lua` inside the `Event.Sun` GMCP handler,
immediately after storing `state.world.sun`. Body is the decoded GMCP object:
`{what = "rise"|"set"|"light"|"dark"}`.

**Subscribers:** `lua/core/clock.lua` — acts only on `"rise"` and `"set"`;
`"light"` and `"dark"` indicate room sun-shielding and are ignored.

### `mume_time_line`

Emitted by `ttpp/core/clock.tin` when the game session receives `time`
command output. The payload is the full matched line string (tt++ `%0`); the
Lua subscriber re-parses it with a full Lua pattern for correctness. Two
game-text forms are caught by the same tt++ pre-filter:

    "8 am on Mersday, the 26th of Solmath, year 2973 of the Third Age."
    "Mersday, the 26th of Solmath, year 2973 of the Third Age."

**Subscribers:** `lua/core/clock.lua`.

### `room_clock_line`

Emitted by `ttpp/core/clock.tin` when the game session receives room-clock
output. Payload is the full matched line string. Game text form:

    "The current time is 8:00am."

**Subscribers:** `lua/core/clock.lua`.

### `clock_changed`

Emitted by `lua/core/clock.lua` whenever the displayed clock value would
change — after each successful sync (`event_sun`, `mume_time_line`,
`room_clock_line`) and on minute rollover inside `tick()`. No payload;
subscribers should read `state.world.clock.format(...)` for the new value.

**Subscribers:** `lua/core/status_state.lua` — calls `serialize()` to update
`bridge/status.state` immediately, without waiting for the next `Char.Vitals`
tick.

### `affect_init`

Emitted when a new affect becomes active on the character. The payload is the
affect name exactly as keyed in `affects_data.affects` (e.g. `"armour"`,
`"second wind"`).

Source: a `#action` registered by `_affects_register_triggers()` in
`lua/core/affects.lua`. One action fires per unique converted pattern; a single
game line can emit both `affect_down` for one affect and `affect_init` for
another (e.g. the shared second-wind / winded trigger).

**Subscribers:** `lua/core/affects.lua` — appends to `state.char.affects`,
arms the 10 s tick on the 0→1 transition.

### `affect_refresh`

Emitted when an already-active affect is re-applied (its `initString_2`
matches, or `initString_1` matches while the affect is already in
`state.char.affects`). Payload is the affect name string.

**Subscribers:** `lua/core/affects.lua` — updates `started_at` and
recomputes `expires_at` on the existing entry.

### `affect_down`

Emitted when an affect ends naturally (game sends the drop message).
Payload is the affect name string.

**Subscribers:** `lua/core/affects.lua` — records the observed duration to
the ring-buffer, persists to disk, removes the entry from `state.char.affects`,
cancels the tick if the list is now empty.

## Adding a new event

Events can come from two sources:

- **tt++ action** — add a `#action` line (at priority 3) inside a
  `_register_<module>_actions` alias in the relevant `ttpp/core/<module>.tin`,
  and call that alias from `SESSION CONNECTED` and `cp -r` in
  `ttpp/core/system.tin`. For project-wide events that have no owning module,
  use `ttpp/core/mud_events.tin` and the existing `_register_mud_events` alias.
- **Lua GMCP handler** — call `events.emit(name, payload)` inside the handler.

Then:
1. Add an entry to the Catalogue table above.
2. No further Lua-side registration is needed — any script can subscribe at
   load time without touching core files.

---
Back to [architecture.md](../architecture.md).
