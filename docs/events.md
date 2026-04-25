# Events

Authoritative reference for the Lua event bus: API, error handling, and
the catalogue of events currently emitted by the client. Touch this file
when adding a new trigger to `ttpp/core/mud_events.tin` or when a script
subscribes to a new event name.

See [docs/decisions/0007-event-bus.md](decisions/0007-event-bus.md) for the
design rationale.

## Overview

The event bus provides a lightweight fan-out mechanism for MUD events that
multiple scripts need to react to. High-priority core triggers in
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

| Event | Payload | Source patterns |
|-------|---------|-----------------|
| `mob_death` | mob name string (includes article, e.g. `"an elven slave"`) | see below |

### `mob_death`

Emitted by the four patterns in `ttpp/core/mud_events.tin`:

    ^%1 is dead! R.I.P.$
    ^%1 has drawn his last breath! R.I.P.$
    ^%1 has drawn her last breath! R.I.P.$
    ^%1 disappears into nothing.$

All four are kills — `disappears into nothing.` is the undead-death
message. The subscriber receives the mob name captured by `%1`; it does
not see which variant fired.

## Adding a new event

1. Add one or more `#action` lines to `ttpp/core/mud_events.tin` at
   priority 3, emitting your chosen event name via
   `#lua {events.emit("event_name", "%1")}`.
2. Add an entry to the Catalogue table above.
3. No Lua-side registration is needed — any script can subscribe at load
   time without touching core files.

---
Back to [architecture.md](../architecture.md).
