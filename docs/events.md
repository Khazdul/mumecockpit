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
| `gmcp_char_name` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `char_state.lua` primary writer |
| `gmcp_char_status_vars` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `char_state.lua` primary writer |
| `gmcp_char_vitals` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `char_state.lua` primary writer |
| `gmcp_comm_channel_text` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `comm_log.lua` primary writer |
| `gmcp_comm_channel_list` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `comm_log.lua` primary writer |
| `gmcp_event_sun` | `{what = "rise"\|"set"\|"light"\|"dark"}` | `lua/brain.lua` `gmcp.dispatch` — emitted after `world_state.lua` primary writer |
| `gmcp_event_darkness` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `world_state.lua` primary writer |
| `gmcp_event_moon` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `world_state.lua` primary writer |
| `gmcp_event_moved` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `world_state.lua` primary writer |
| `gmcp_core_goodbye` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `core_state.lua` primary writer |
| `gmcp_core_ping` | decoded body | `lua/brain.lua` `gmcp.dispatch` — emitted after `core_state.lua` primary writer |
| `run_started` | (none) | `lua/brain/connection.lua` `mark_mume_connected()` — emitted after `_write_connection_state()` and login `system_ui`, before `state.run.reset()` |
| `run_ending` | (none) | `lua/brain/connection.lua` `mark_mume_disconnected()` — emitted after `_clear_connection_state()` and logout `system_ui`, before `state.run.reset()` and `state.char.reset()` |
| `char_reset` | (none) | `lua/core/char_state.lua` `state.char.reset()` — emitted after wiping all non-function keys |
| `group_member_added` | member table (new member as stored in `state.group.members`) | `lua/core/group_state.lua` — `Group.Add` and `Group.Set` (net-new id) handlers |
| `group_member_updated` | member table (merged existing member) | `lua/core/group_state.lua` — `Group.Update` handler |
| `group_member_removed` | integer id | `lua/core/group_state.lua` — `Group.Remove` and `Group.Set` (removed id) handlers |
| `group_changed` | (none) | `lua/core/group_state.lua` — after every `Group.*` mutation and `state.group.reset()` |
| `mob_death` | mob name string, kind (`"living"` \| `"undead"`) | `ttpp/core/mud_events.tin` |
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
| `kill_attributed` | `{name = "<mob name>", xp = <integer>}` | `lua/core/run_state.lua` `_fold()` — emitted once per attributed kill after `script_ui` announce |
| `tp_gained` | `{delta = <integer>}` | `lua/core/run_state.lua` `gmcp_char_vitals` subscriber — emitted on each positive TP increase |
| `char_death` | (none) | `ttpp/core/mud_events.tin` — `"You are dead! Sorry..."` pattern |
| `pc_death` | PC name+race-suffix string | `ttpp/core/mud_events.tin` — three asterisk-wrapped R.I.P. patterns |
| `pkill_attributed` | `{name = "<pc name>", race = "<race suffix>", xp = <integer>}` | `lua/core/run_state.lua` `_fold()` — emitted once per attributed PC kill after `script_ui` announce |
| `achievement` | achievement description string | `ttpp/core/mud_events.tin` — two-stage trigger on `"You achieved something new!"` |

### `gmcp_<module>` events

`gmcp.dispatch` emits one event per incoming GMCP packet, always, whether or
not a primary handler is registered. The event name is derived by
`module_to_event`: camelCase boundaries become underscores, dots become
underscores, everything lowercased, prefixed `gmcp_`. For example:
`"Char.StatusVars"` → `"gmcp_char_status_vars"`.

The invariant: **`state.*` is already updated** when any subscriber runs,
because the primary writer (if set) runs inside `gmcp.dispatch` before the
event is emitted.

Subscriber order within an event equals registration order, which equals
alphabetical load order within `lua/core/`. Scripts in `lua/scripts/` load
after all core modules and subscribe last.

Detailed subscriber lists for the high-traffic events:

**`gmcp_char_name`** — `lua/core/affects.lua` (re-init affects, load
persisted data), `lua/core/buffs_state.lua` (serialize), `lua/core/comm_store.lua`
(init per-character archive), `lua/core/server_prefs.lua` (assert width),
`lua/core/status_state.lua` (serialize), `lua/core/stored_spells.lua`
(re-init stored spells, load persisted data).

**`gmcp_char_vitals`** — `lua/core/run_log.lua` (write deferred run_start row on
first tick), `lua/core/run_state.lua` (update XP/TP baseline; emit `tp_gained`
when TP increases), `lua/core/status_state.lua` (serialize). Added to
`events.trace_skip` to suppress log noise when tracing is on.

**`gmcp_char_status_vars`** — `lua/core/run_log.lua` (level-up detection),
`lua/core/status_state.lua` (serialize).

**`gmcp_comm_channel_text`** — `lua/core/comm_state.lua` (serialize, runs
first), `lua/core/comm_store.lua` (append to archive).

**`gmcp_comm_channel_list`** — `lua/core/comm_state.lua` (serialize).

**`gmcp_event_sun`** — see dedicated section below.

### `run_started`

Emitted by `mark_mume_connected()` in `lua/brain/connection.lua` immediately
after `_write_connection_state()` and the `system_ui("… logged in.")` line,
before `state.run.reset()`. No payload. `state.char.name` is populated when
this fires (set by the `Char.Name` primary writer before `mark_mume_connected()`
is called).

**Subscribers:** `lua/core/run_log.lua` — seals any orphaned `current.jsonl`
from a prior unclean session, then initialises the per-character archive
directory and arms the deferred run_start write.

### `run_ending`

Emitted by `mark_mume_disconnected()` in `lua/brain/connection.lua` after
`_clear_connection_state()` and the logout `system_ui` line, before
`state.run.reset()` and `state.char.reset()`. No payload. Both `state.char.name`
and `state.char.level` are still populated when this fires.

**Subscribers:** `lua/core/run_log.lua` — writes `run_end` row and seals
`current.jsonl` to `<run-id>.jsonl`.

### `char_reset`

Emitted by `lua/core/char_state.lua`'s `state.char.reset()` immediately after
wiping all non-function keys from `state.char`. No payload. Called from
`mark_mume_disconnected()` in `lua/brain.lua`.

**Subscribers:** `lua/core/affects.lua` (cancel the affects tick timer),
`lua/core/buffs_state.lua` (serialize blank buffs.state),
`lua/core/group_serializer.lua` (serialize empty group.state),
`lua/core/status_state.lua` (serialize blank status.state).

### `group_member_added`

Emitted by `lua/core/group_state.lua` when a new member joins the group. Payload is the member table as stored in `state.group.members[id]` — the same table reference, so subscribers must not cache it across events. Fired by `Group.Add` and by `Group.Set` for each id present in the new set that was absent in the old set.

Members with `type == "npc"` or `type == "you"` are discarded before this fires — the payload is always a tracked group member.

**Subscribers:** none currently — `group_serializer.lua` serializes on `group_changed` rather than per-member events.

### `group_member_updated`

Emitted by `lua/core/group_state.lua` after `Group.Update` merges partial fields into an existing member. Payload is the updated member table (same reference as `state.group.members[id]`, post-merge). Only the fields present in the GMCP payload are updated; absent fields retain their prior value.

**Subscribers:** none currently.

### `group_member_removed`

Emitted by `lua/core/group_state.lua` when a member leaves the group. Payload is the integer member id. Fired by `Group.Remove` and by `Group.Set` for each id present in the old set that is absent in the new set. The member has already been removed from `state.group.members` when this fires.

**Subscribers:** none currently.

### `group_changed`

Emitted by `lua/core/group_state.lua` after every `Group.*` mutation and by `state.group.reset()`. No payload. Subscribers should read `state.group.members` directly for the current state. Fires once per incoming GMCP packet even if multiple per-member events also fired in the same packet (e.g. a `Group.Set` that adds two members and removes one still emits a single `group_changed` at the end).

**Subscribers:** `lua/core/group_serializer.lua` — calls `serialize()` to write `bridge/runtime/group.state` atomically.

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

### `gmcp_event_sun`

Emitted by `lua/brain.lua` `gmcp.dispatch` immediately after `world_state.lua`'s
primary writer stores `state.world.sun`. Body is the decoded GMCP object:
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
change — after each successful sync (`gmcp_event_sun`, `mume_time_line`,
`room_clock_line`) and on minute rollover inside `tick()`. No payload;
subscribers should read `state.world.clock.format(...)` for the new value.

**Subscribers:** `lua/core/status_state.lua` — calls `serialize()` to update
`bridge/runtime/status.state` immediately, without waiting for the next `Char.Vitals`
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
`bridge/runtime/status.state` and rewrite `status_height` in `bridge/runtime/layout.conf`
when the affect count changes. `lua/core/buffs_state.lua` — calls `serialize()`
to update `bridge/runtime/buffs.state` (affects and stored spells written together).

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
updated `stored_spells` array (alongside `affects`) to `bridge/runtime/buffs.state`
atomically, giving the buffs-pane renderer a fresh snapshot within one poll
tick.

### `kill_attributed`

Emitted by `lua/core/run_state.lua`'s `_fold()` once per attributed kill,
immediately after the `script_ui("KILL", ...)` announce. Payload:
`{name = "<mob name>", xp = <integer>}` where `name` is the mob name as
captured by `mob_death` (includes article, e.g. `"an elven slave"`) and `xp`
is the even-split XP attributed to this kill (may be `0` for empty-Vitals
folds). For group kills inside the 500ms debounce window, fires once per mob
with the even-split share; the last mob receives the remainder. See ADR 0008
for the attribution model.

**Subscribers:** `lua/core/run_log.lua` — writes a `kill` row to
`current.jsonl`.

### `char_death`

Emitted by one pattern in `ttpp/core/mud_events.tin`. No payload.

| Pattern | Notes |
|---------|-------|
| `^You are dead! Sorry...$` | fires on player death (PvE, PvP, environment) |

**Subscribers:** `lua/core/run_state.lua` — increments `state.run.deaths`; no
fold interaction. `lua/core/run_log.lua` — writes a `char_death` row to
`current.jsonl` with the character's current level (omitted if not yet known).

### `pc_death`

Emitted by three patterns in `ttpp/core/mud_events.tin`. Payload is the full
string captured between the asterisks, including race-suffix (e.g.
`"Moraxus the Orc"`).

| Pattern | Notes |
|---------|-------|
| `^\*%1\* is dead! R.I.P.$` | standard PvP kill message |
| `^\*%1\* has drawn his last breath! R.I.P.$` | male-pronoun variant |
| `^\*%1\* has drawn her last breath! R.I.P.$` | female-pronoun variant |

The asterisks (`*`) are literal characters in the MUME output that delimit PC
names; they do not appear in mob R.I.P. lines. `%1` captures only the content
between the asterisks.

**Subscribers:** `lua/core/run_state.lua` — splits the payload into
`name` (first word) and `race` (remainder, or `""` if single word); appends
`{name, race}` to `M.pending_pkills`; calls `schedule_fold()` to debounce
XP attribution.

### `pkill_attributed`

Emitted by `lua/core/run_state.lua`'s `_fold()` once per attributed PC kill,
immediately after the `script_ui("PKILL", ...)` announce. Payload:
`{name = "<pc name>", race = "<race suffix>", xp = <integer>}` where `name`
is the first word of the R.I.P. string, `race` is the remainder (may be `""`),
and `xp` is the even-split XP attributed to this kill (may be `0` for
empty-Vitals folds). For mixed folds (mob kills + PC kills within the 500ms
window), XP is split evenly across all entries; the last entry processed
receives the remainder. See `kill_attributed` for the attribution model.

**Subscribers:** `lua/core/run_log.lua` — writes a `pkill` row to
`current.jsonl`.

### `achievement`

Emitted by a two-stage trigger in `ttpp/core/mud_events.tin`. Payload is the
achievement description string captured from the line immediately following the
marker line.

**Trigger mechanism.** The outer action matches `^You achieved something new!$`
at priority 3. Its body registers a one-shot inner `#action` synchronously —
the inner action fires on the very next received line, emits `achievement` with
that line as the payload, and `#unaction`s itself. Registration is synchronous
because Lua-armed registration via `session_cmd` is asynchronous (`tintin_cmd`
writes a temp file and signals tt++ via stdout), causing the inner action to
land after the current server-line block is consumed and the description line
is already past.

**Class discipline.** The inner action registration is wrapped in
`#class {core} {open}` / `{close}` inside the outer body. Without this wrap,
the inner action would be registered while the profile class is open (per ADR
0049), land in the profile auto-save, and persist across `cp -r`, accumulating
stale registrations. See
[ADR 0050](decisions/0050-synchronous-nested-actions-with-class-discipline.md)
for the full derivation.

**Escape split (3/3/4).** The trigger line lives inside the
`_register_mud_events` alias body, adding one substitution pass. Three `%`
signs in the file produce the inner pattern `^%1$` stored at outer firing (3);
three `%` signs produce the emit argument substituted at inner firing (3); four
`%` signs produce the literal `^%1$` unaction pattern that must match the stored
inner action (4). Moving this line out of the alias body would silently change
the required counts; see ADR 0050 before refactoring.

**Limitation.** The inner action matches the very next received line after the
marker. If a non-achievement line interleaves between the marker and the
description (rare in MUME's output stream), that line is captured instead. No
mitigation in this iteration.

**Subscribers:** `lua/core/run_log.lua` — writes an `achievement` row to
`current.jsonl`.

## Adding a new event

Events can come from three sources:

- **tt++ action** — add a `#action` line (at priority 3) inside a
  `_register_<module>_actions` alias in the relevant `ttpp/core/<module>.tin`,
  and call that alias from `SESSION CONNECTED` and `cp -r` in
  `ttpp/core/system.tin`. For project-wide events that have no owning module,
  use `ttpp/core/mud_events.tin` and the existing `_register_mud_events` alias.
- **GMCP dispatch** — `gmcp.dispatch` automatically emits `gmcp_<module_snake>`
  after every packet. Subscribing to the event is sufficient; no changes to
  `gmcp.dispatch` or the primary handler are needed.
- **Lua code** — call `events.emit(name, payload)` directly (e.g. `char_reset`).

Then:
1. Add an entry to the Catalogue table above.
2. No further Lua-side registration is needed — any script can subscribe at
   load time without touching core files.

---
Back to [architecture.md](../architecture.md).
