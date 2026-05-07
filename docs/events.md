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
| `mob_death` | mob name string, kind (`"living"` \| `"undead"`) | `ttpp/core/mud_events.tin` |
| `event_sun` | `{what = "rise"\|"set"\|"light"\|"dark"}` | `lua/core/world_state.lua` (GMCP) |
| `mume_time_line` | full matched line string | `ttpp/core/clock.tin` `#action` |
| `room_clock_line` | full matched line string | `ttpp/core/clock.tin` `#action` |
| `clock_changed` | (none) | `lua/core/clock.lua` — emitted on each successful sync and on minute rollover in `tick()` |
| `affect_init` | affect name string (e.g. `"armour"`) | `ttpp/core/affects.tin` `#action` (via `_affects_register_triggers`) |
| `affect_refresh` | affect name string | `ttpp/core/affects.tin` `#action` |
| `affect_down` | affect name string | `ttpp/core/affects.tin` `#action` |
| `affects_changed` | (none) | `lua/core/affects.lua` — emitted on every state mutation and every tick |
| `wimpy_changed` | numeric string (`"0"`..`"N"`) | `ttpp/core/mud_events.tin` |
| `user_input` | raw sent-line string | `lua/brain.lua` `handlers["USER_INPUT"]` |
| `user_input_empty` | (none) | RECEIVED INPUT with empty `%0` in GAME_SESSION; `lua/brain.lua` `handlers["EMPTY_INPUT"]` |
| `user_cast` | spell text as captured from bracketed echo (un-resolved) | tt++ `#action` registered by `_register_stored_spells_actions` |
| `store_attempt_started` | spell full name string | `lua/core/stored_spells.lua` — `user_input` subscriber |
| `store_attempt_failed` | (none) | `ttpp/core/stored_spells.tin` `#action` (via `_register_stored_spells_actions`) |
| `store_succeeded` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `store_recalled` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `store_decayed` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `stored_spells_untracked` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `stored_spells_changed` | (none) | `lua/core/stored_spells.lua` — emitted on every state mutation and on `_load_active()` restore |

### `mob_death`

Emitted by the four patterns in `ttpp/core/mud_events.tin`. Payload:
`(name, kind)` where `name` is the mob name captured by `%1` (includes
article, e.g. `"an elven slave"`) and `kind` is `"living"` or `"undead"`.

| Pattern | kind |
|---------|------|
| `^%1 is dead! R.I.P.$` | `"living"` |
| `^%1 has drawn his last breath! R.I.P.$` | `"living"` |
| `^%1 has drawn her last breath! R.I.P.$` | `"living"` |
| `^%1 disappears into nothing.$` | `"undead"` |

The `kind` argument is new; existing subscribers that only take `name` are
unaffected — Lua ignores extra positional args.

**Subscribers:** `lua/scripts/autostab.lua`, `lua/scripts/autobow.lua`
(abort on kill), `lua/core/run_state.lua` (queues name for XP attribution),
`lua/scripts/coinlooter.lua` (loot coins, dispatches on kind).
`run_state` is the first core module to subscribe to its own bus — direct
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

    "The current time is 2:31 am."

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

### `affects_changed`

Emitted by `lua/core/affects.lua` with no payload whenever `state.char.affects`
is mutated — at the end of each `affect_init`, `affect_refresh`, and
`affect_down` handler (normal execution path only, after the actual mutation),
and at the end of every `_affects_tick()` invocation regardless of whether any
entries were pruned.

Subscribers should read `state.char.affects` directly for the new state.

**Subscribers:** `lua/core/status_state.lua` — calls `serialize()` to update
`bridge/status.state` and rewrite `status_height` in `bridge/layout.conf`
when the affect count changes. `lua/core/buffs_state.lua` — calls `serialize()`
to update `bridge/buffs.state` (affects and stored spells written together).

### `wimpy_changed`

Emitted by two patterns in `ttpp/core/mud_events.tin`. Payload is always a
numeric string — `"0"` when wimpy is disabled, `"N"` (the integer threshold)
when set.

| Pattern | Payload |
|---------|---------|
| `^Wimpy removed.$` | `"0"` |
| `^Wimpy set to: %1$` | captured digit string |

The Lua subscriber parses the string to a number and stores it in
`state.char.wimpy` (including `0` for disabled — the future character-pane
renderer distinguishes `0` from absent).

**Subscribers:** `lua/core/wimpy.lua` — updates `state.char.wimpy`, emits
`script_ui("WIMPY", ...)`.

### `user_input`

Emitted by `brain.lua`'s `handlers["USER_INPUT"]` on every line the user sends
to the MUD. The payload is the full raw sent-line string, reconstructed by
joining the IPC parts with `":"` (necessary because raw input may itself contain
`:`).

Source: `#event {SENT OUTPUT} {#lua {USER_INPUT:%0}}` in `ttpp/core/system.tin`
feeds the IPC path; the handler in `brain.lua` bridges it to the Lua event bus.

**Subscribers:** `lua/core/stored_spells.lua` — parses outgoing `cast 'store' X`
and `cast 'spell'` commands to drive the stored-spell FIFO queue and
`_last_cast_intent`.

### `user_input_empty`

Emitted by `brain.lua`'s `handlers["EMPTY_INPUT"]` when GAME_SESSION receives a
RECEIVED INPUT event with an empty `%0`. RECEIVED INPUT fires only on actual user
keystrokes — unlike SENT OUTPUT, which also fires on tt++ IAC/GMCP flushes —
so an empty `%0` here is unambiguously "user pressed Enter on an empty line",
which MUME interprets as a cast abort.

No payload.

**Subscribers:** `lua/core/stored_spells.lua` — if `_pending_attempts` is
non-empty, logs the abort and funnels into `store_attempt_failed` to pop the
oldest queued attempt. Silent no-op when the queue is empty.

### `user_cast`

Emitted by two `#action` triggers registered by `_register_stored_spells_actions()`
in GAME_SESSION at priority 3. MUME echoes every cast attempt as a bracketed line
regardless of whether the player typed full `cast '...'` syntax or a server-side
alias (e.g. `arm`, `fireb`). The two forms caught are:

    [cast 'armour']       — no speed prefix
    [cast n 'armour']     — with speed prefix

Payload is the spell text as captured from the echo (un-resolved). The `%1`/`%2`
captures absorb `cast` and any speed word respectively; `%2`/`%3` is the bare
spell name without quotes.

**Subscribers:** `lua/core/stored_spells.lua` — runs the captured text through
`_resolve_spell()` and, if it resolves to a non-`"store"` spell, updates
`_last_cast_intent`. The `"store"` spell is filtered out because store-attempt
tracking is driven by the SENT OUTPUT snooper, which also captures the target
spell that the bracketed echo does not include.

### `store_attempt_started`

Emitted by `lua/core/stored_spells.lua`'s `user_input` subscriber when an
outgoing `cast 'store' <spell>` command is successfully resolved. Payload is the
full spell name (e.g. `"fireball"`).

**Subscribers:** `lua/core/stored_spells.lua` — appends the spell name to the
`_pending_attempts` FIFO queue and logs `[STORED_SPELLS] attempt: <name>`.

### `store_attempt_failed`

Emitted by one of the twelve failure-pattern `#action` triggers registered by
`_register_stored_spells_actions()`. No payload.

Failure patterns include: not enough mana, backfire, nothing happens, fear,
relaxed, concentration lost, flee, mind full, general failure, unknown spell,
and invalid speed argument.

**Subscribers:** `lua/core/stored_spells.lua` — pops the front of
`_pending_attempts`. If the queue is already empty, logs
`[STORED_SPELLS] fail: queue empty (out of sync)` and takes no further action.

### `store_succeeded`

Emitted when the game sends `"You stored it."` No payload.

**Subscribers:** `lua/core/stored_spells.lua` — pops the front of
`_pending_attempts`, computes `expected_duration` (mean of up to 3 prior samples,
defaulting to 5400 s), appends a new entry to `state.char.stored_spells`,
persists the active list, and emits a `script_ui("STORE", ...)` line.

### `store_recalled`

Emitted when the game sends `"You quickly recall your stored spell..."` No
payload.

**Subscribers:** `lua/core/stored_spells.lua` — finds the entry in
`state.char.stored_spells` with the highest `started_at` whose `name` matches
`_last_cast_intent`. If found, removes the entry, persists the active list, and
emits a `script_ui("STORE", ...)` line. `_last_cast_intent` is NOT cleared so
that successive recalls of the same spell resolve correctly.

### `store_decayed`

Emitted when the game sends `"Your mind feels empty for a while."` No payload.

**Subscribers:** `lua/core/stored_spells.lua` — finds the oldest entry in
`state.char.stored_spells` (lowest `started_at`). If `tracked == true`, records
the observed duration to the ring-buffer in `state.char.stored_spell_times`
(FIFO, capped at 3 samples) and persists the times file; then refreshes
`expected_duration` and `expires_at` on all remaining active tracked entries of
the same spell so their countdowns reflect the freshly recorded sample. Removes
the entry and persists the active list. Emits a `script_ui("STORE", ...)` line
noting the observed duration or `(untracked)` depending on the `tracked` flag.

### `stored_spells_untracked`

Emitted by either of two patterns: `"You blast the area with magical energies."`
(self-cast) or `"%1 blasts the area with magical energies."` (other entity).
No payload.

A magic-blast consumes all currently stored spells in an indeterminate order,
making individual tracking impossible.

**Subscribers:** `lua/core/stored_spells.lua` — sets `tracked = false` and
`expires_at = nil` on every entry in `state.char.stored_spells`, persists the
active list, and calls `ui_warn("STORE: lost track of stored spells.")`. No-op
(no UI) when the list is already empty.

### `stored_spells_changed`

Emitted by `lua/core/stored_spells.lua` with no payload whenever
`state.char.stored_spells` is mutated — at the end of each `store_succeeded`,
`store_recalled`, `store_decayed`, and `stored_spells_untracked` handler, and
inside `_load_active()` after restoring persisted entries on `Char.Name`.

Subscribers should read `state.char.stored_spells` directly for the new state.

**Subscribers:** `lua/core/buffs_state.lua` — calls `serialize()` to write the
updated `stored_spells` array (alongside `affects`) to `bridge/buffs.state`
atomically, giving the buffs-pane renderer a fresh snapshot within one poll
tick.

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
