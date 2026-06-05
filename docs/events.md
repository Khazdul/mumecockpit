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
`ttpp/core/mud_events.tin` (in the core priority band per
[ADR 0115](decisions/0115-core-priority-band.md)) capture
MUD output and call `events.emit(name, ...)`. The file is not uniformly
priority 3: the broad mob-death patterns sit at 4 and the specific
pc-death patterns at 3 so the latter win the single-fire slot on
overlapping `*Name*` R.I.P. lines (see the `mob_death`/`pc_death` notes). Scripts subscribe at start time and unsubscribe
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
| `group_member_added` | member table | `lua/core/group_collector.lua` — emitted by `Group.Set` (for ids new vs old), `Group.Add`, and `Group.Update` when an excluded NPC is promoted into `state.group.members` because the update carried a non-empty string `label` |
| `group_member_updated` | member table | `lua/core/group_collector.lua` — emitted by `Group.Update` after an in-place merge (including freshness inference) when membership did not change, and by the `gmcp_char_vitals` subscriber when `buffer-hits` / `opponent-hits` is cross-applied onto a group member (once per affected member) |
| `group_member_removed` | member id (integer) | `lua/core/group_collector.lua` — emitted by `Group.Set` (for ids removed), `Group.Remove`, and `Group.Update` when a labeled NPC is demoted out of `state.group.members` because the update cleared its `label` |
| `group_changed` | (none) | `lua/core/group_collector.lua` — emitted after every `Group.*` handler, on `state.group.reset()`, and by the `gmcp_char_vitals` subscriber whenever it cross-applied at least one `*-hits` band onto a group member |
| `mob_death` | mob name string, kind (`"living"` \| `"undead"`) | `ttpp/core/mud_events.tin` |
| `mume_time_line` | full matched line string | `ttpp/core/clock.tin` `#action` |
| `room_clock_line` | full matched line string | `ttpp/core/clock.tin` `#action` |
| `clock_changed` | (none) | `lua/core/clock.lua` — emitted on each successful sync and on minute rollover in `tick()` |
| `affect_init` | affect name string (e.g. `"armour"`) | `ttpp/core/affects.tin` `#action` (via `_affects_register_triggers`) |
| `affect_refresh` | affect name string | `ttpp/core/affects.tin` `#action` |
| `affect_down` | affect name string | `ttpp/core/affects.tin` `#action` |
| `affects_changed` | (none) | `lua/core/affects.lua` — emitted on every state mutation and every tick |
| `affects_observed` | array of name strings | `lua/core/stat_reconcile.lua` — emitted after parsing the `Affected by:` / `You are subjected to the following temporary effects:` block in `stat`/`info` output (stored-spell lines split off into `stored_spells_observed`) |
| `stored_spells_observed` | array of name strings | `lua/core/stat_reconcile.lua` — emitted alongside `affects_observed` with the names of `- stored spell <name>` lines from the same block (prefix stripped, duplicates preserved) |
| `wimpy_changed` | numeric string (`"0"`..`"N"`) | `ttpp/core/mud_events.tin` |
| `user_input` | raw sent-line string | `lua/brain.lua` `handlers["USER_INPUT"]` |
| `user_input_empty` | (none) | RECEIVED INPUT with empty `%0` in GAME_SESSION (registered by `_register_input_ipc_actions` in `ttpp/core/input_ipc.tin`); `lua/brain.lua` `handlers["EMPTY_INPUT"]` |
| `user_cast` | spell text as captured from bracketed echo (un-resolved) | tt++ `#action` registered by `_register_stored_spells_actions` |
| `store_attempt_started` | spell full name string | `lua/core/stored_spells.lua` — `user_input` subscriber |
| `store_attempt_failed` | (none) | `lua/core/stored_spells.lua` `#action` (via `_register_stored_spells_actions`) — the four store-specific failure lines |
| `store_succeeded` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `store_decayed` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `stored_spells_untracked` | (none) | `ttpp/core/stored_spells.tin` `#action` |
| `stored_spells_changed` | (none) | `lua/core/stored_spells.lua` — emitted on every state mutation and on `_load_active()` restore |
| `spell_cast_failed` | (none) | `lua/core/spellcast.lua` `#action` (via `_register_spellcast_actions`) — the eight shared cast-failure lines |
| `spell_cast_started` | (none) | `lua/core/spellcast.lua` `#action` — the two concentration-start lines |
| `spell_cast_recalled` | (none) | `lua/core/spellcast.lua` `#action` — `^You quickly recall your stored spell...$` |
| `blinds_changed` | (none) | `lua/core/blinds.lua` — emitted on every state mutation (landing) and on each tick that prunes at least one expired entry |
| `charms_changed` | (none) | `lua/core/charm.lua` — emitted on every `state.char.charms` mutation (landing, tick prune, explicit drop, `_load_active`) |
| `herblores_changed` | (none) | `lua/core/herblores.lua` — emitted on every `state.char.herblores` mutation (add, remove, each tick that advances a phase or drops an elapsed herblore, `_load_active`) |
| `kill_attributed` | `{name = "<mob name>", xp = <integer>}` | `lua/core/run_state.lua` `_fold()` — emitted once per attributed kill after `script_ui` announce |
| `tp_gained` | `{delta = <integer>}` | `lua/core/run_state.lua` `gmcp_char_vitals` subscriber — emitted on each positive TP increase |
| `char_death` | (none) | `ttpp/core/mud_events.tin` — `"You are dead! Sorry..."` pattern |
| `pc_death` | PC name+race-suffix string | `ttpp/core/mud_events.tin` — three asterisk-wrapped R.I.P. patterns |
| `pkill_attributed` | `{name = "<pc name>", race = "<race suffix>", xp = <integer>}` | `lua/core/run_state.lua` `_fold()` — emitted once per attributed PC kill after `script_ui` announce |
| `achievement` | achievement description string | `lua/core/world_state.lua` — re-emit of GMCP `Event.Achieved` |

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
persisted data), `lua/core/comm_store.lua`
(init per-character archive), `lua/core/server_prefs.lua` (assert width),
`lua/core/status_state.lua` (serialize), `lua/core/stored_spells.lua`
(re-init stored spells, load persisted data), `lua/core/timers_state.lua`
(serialize).

**`gmcp_char_vitals`** — `lua/core/run_log.lua` (write deferred run_start row on
first tick), `lua/core/run_state.lua` (update XP/TP baseline; emit `tp_gained`
when TP increases), `lua/core/status_state.lua` (serialize),
`lua/core/group_collector.lua` (cache buffer/opponent identity strings and
cross-apply `buffer-hits` / `opponent-hits` onto the matching group member
as `hp_string`; emits `group_member_updated` and `group_changed` when at
least one member was touched). Added to `events.trace_skip` to suppress log
noise when tracing is on.

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
`lua/core/group_collector.lua` (calls `state.group.reset()`, which wipes members and emits `group_changed`),
`lua/core/group_state.lua` (serialize blank group.state),
`lua/core/status_state.lua` (serialize blank status.state),
`lua/core/timers_state.lua` (serialize blank timers.state).

### `group_changed`

Emitted by `lua/core/group_collector.lua` with no payload after every `Group.*` GMCP
handler completes, at the end of `state.group.reset()`, and by the
`gmcp_char_vitals` subscriber whenever it cross-applied at least one `*-hits`
band onto a group member (see the Char.Vitals buffer/opponent cross-apply in
[docs/gmcp.md](gmcp.md#char)). No payload; subscribers should read
`state.group.members` directly for the new state.

**Subscribers:** `lua/core/group_state.lua` — calls `serialize()` to write
`bridge/runtime/group.state` atomically. `lua/core/run_log.lua` — appends a
`group_changed` row to `current.jsonl` only on player-ally composition changes
(via `group_member_added` / `group_member_removed`); vitals updates and
NPC-only churn do not produce rows.

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

These four patterns are registered at priority 4 (not the core default of
3) so they lose the single-fire slot to the more specific pc-death patterns
on PvP `*Name*` R.I.P. lines ([ADR 0115](decisions/0115-core-priority-band.md);
see [`pc_death`](#pc_death)).

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
`bridge/runtime/status.state`. `lua/core/timers_state.lua` — calls `serialize()`
to update `bridge/runtime/timers.state` (affects and stored spells written together).

### `affects_observed`

Emitted by `lua/core/stat_reconcile.lua` after the player runs `stat` or
`info` and MUME prints the active-affects block. Payload is an array of
affect-name strings (raw, lowercase, exactly as MUME prints them after the
leading `- `). The list may be empty (block contained only the header and
terminator). Lines starting with the literal prefix `stored spell ` are
split off into the parallel `stored_spells_observed` event and do not
appear in this payload.

Sources caught by the two permanent header `#action` triggers (priority 3):

| Header pattern | Game context |
|----------------|--------------|
| `^Affected by:$` | `stat` output |
| `^You are subjected to the following temporary effects:$` | `info` output |

Each header trigger arms a dynamic catch-all `^%1$` inline (synchronously
inside the outer body, see ADR 0050) which forwards every received line to
the brain via the `STAT_LINE:<raw>` structured-event path. The handler
classifies each `^- (.+)$` capture by the `stored spell ` prefix: matching
captures go to the stored-spell buffer (prefix stripped), the rest to the
affect buffer. On the first line that does not start with `- ` the handler
emits `affects_observed` followed by `stored_spells_observed`, calls
`session_cmd("#unaction {^%1$}")`, and clears both buffers. Re-echoes of
either header line are skipped explicitly.

**Subscribers:** `lua/core/affects.lua` — reconciles `state.char.affects`
against the observed list (iterates `affects_data.affects`, the known
universe; unknown names — future MUME additions — are skipped). Adds
untracked entries for newly-observed timed-capable affects, removes
silently for active-but-unobserved entries, leaves everything else alone.

### `stored_spells_observed`

Emitted by `lua/core/stat_reconcile.lua` immediately after `affects_observed`,
carrying the names of `- stored spell <name>` lines from the same block
(literal `stored spell ` prefix stripped, duplicates preserved as multiple
array entries — two stored earthquakes produce two `"earthquake"` entries).
The list may be empty.

Classification is by the prefix only, never by name: a block containing
both `- armour` and `- stored spell armour` produces one affect entry for
`armour` (via `affects_observed`) and one stored-spell entry for `armour`
(via this event), reconciled independently.

**Subscribers:** `lua/core/stored_spells.lua` — runs a per-name multiset
diff against `state.char.stored_spells`. Names absent from
`spells_data.spells` are skipped silently with a `dbg` line. For each name
in the union of want and have: `want > have` adds `(want - have)`
untracked entries (same shape as magic-blast-produced entries: `tracked =
false`, no `started_at` / `expires_at`); `have > want` removes
`(have - want)` entries, preferring untracked first and then tracked by
oldest `started_at`. Equal counts leave entries untouched, so tracked
timers keep running. Removals are silent — no `char_ui` line and no
duration sample is recorded (a reconcile removal is not a natural decay).
Emits `stored_spells_changed` and writes the active-list file only if
something changed.

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

**Subscribers:** `lua/core/wimpy.lua` — updates `state.char.wimpy`, then calls
`state.char.serialize()` (exposed by `lua/core/status_state.lua`) to refresh
`bridge/runtime/status.state` so the WIMPY cell updates within one poll tick
without waiting for an unrelated `Char.Vitals` event. `status_state.lua` is
deliberately not subscribed directly: subscriber order is alphabetical load
order, and `status_state` loads before `wimpy`, so it would otherwise serialise
the pre-mutation value.

### `user_input`

Emitted by `brain.lua`'s `handlers["USER_INPUT"]` on every line the user sends
to the MUD. The payload is the full raw sent-line string, reconstructed by
joining the IPC parts with `":"` (necessary because raw input may itself contain
`:`).

Source: `#event {SENT OUTPUT} {#lua {USER_INPUT:%0}}` in `ttpp/core/system.tin`
feeds the IPC path; the handler in `brain.lua` bridges it to the Lua event bus.

**Subscribers:** `lua/core/stored_spells.lua` — parses outgoing `cast 'store' X`
and `cast 'spell'` commands to drive the stored-spell FIFO queue and
`_last_cast_intent`. `lua/core/blinds.lua` — parses outgoing
`cast '<blindness-prefix>' [<n>.<name>]` commands; on a match enqueues
`{kind="blindness", prefix=…}` onto the **shared** cast-attempt FIFO owned by
`lua/core/spellcast.lua` so the next "seems to be blinded!" landing inherits
the right target label. `lua/core/charm.lua` — recognises an outgoing charm
cast and enqueues `{kind="charm"}` onto the same shared FIFO. `spellcast.enqueue`
re-arms the 10 s idle flush so an unconsumed entry is dropped automatically; see
[docs/spellcast.md](spellcast.md).

### `user_input_empty`

Emitted by `brain.lua`'s `handlers["EMPTY_INPUT"]` when GAME_SESSION receives a
RECEIVED INPUT event with an empty `%0`. RECEIVED INPUT fires only on actual user
keystrokes — unlike SENT OUTPUT, which also fires on tt++ IAC/GMCP flushes —
so an empty `%0` here is unambiguously "user pressed Enter on an empty line",
which MUME interprets as a cast abort.

The `#event {RECEIVED INPUT}` handler is registered by
`_register_input_ipc_actions` in `ttpp/core/input_ipc.tin`, invoked from
`SESSION CONNECTED` in `ttpp/core/system.tin`. This is cross-cutting
input-IPC infrastructure; consumer modules subscribe to the event bus topic
rather than owning the tt++ registration.

No payload.

**Subscribers:** `lua/core/stored_spells.lua` — if `_pending_attempts` is
non-empty, logs the abort and funnels into `store_attempt_failed` to pop the
oldest queued attempt. Silent no-op when the queue is empty.
`lua/core/spellcast.lua` — calls `spellcast.fail_front()` to drop the front of
the shared cast-attempt FIFO (an empty-line Enter is a cast abort). Blinds and
charm no longer subscribe to this event directly; they drain through the shared
FIFO. See [docs/spellcast.md](spellcast.md).

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

Emitted by one of the **four store-specific** failure-pattern `#action` triggers
registered by `_register_stored_spells_actions()`. No payload.

The four store-only lines are: `^Your mind is too full to store it.$`,
`^You failed.$`, `^You do not know any such a spell.$`, and
`^You can cast quickly, fast, normally, carefully, or thoroughly.$`. The eight
*shared* cast-failure lines (out of mana, backfire, nothing happens, fear,
relaxed, concentration lost, flee, too afraid) are no longer registered here —
they are owned by `lua/core/spellcast.lua` and emit `spell_cast_failed`, which
this module also subscribes to (see below and [docs/spellcast.md](spellcast.md)).

**Subscribers:** `lua/core/stored_spells.lua` — `_drain_pending_attempt` pops
the front of `_pending_attempts`. If the queue is already empty, logs
`[STORED_SPELLS] fail: queue empty (out of sync)` and takes no further action.
The empty-input abort (`user_input_empty`) also routes here.

### `spell_cast_failed`

Emitted by one of the **eight shared** cast-failure `#action` triggers
registered by `_register_spellcast_actions()` in `lua/core/spellcast.lua`. No
payload.

| Pattern (anchored) | Cause |
|---|---|
| `^Argh! You cannot concentrate any more...$` | concentration loss |
| `^Nah... You feel too relaxed to do that.$` | sitting / resting |
| `^In your dreams, or what?$` | spell not memorised |
| `^Alas, not enough mana flows through you...$` | out of mana |
| `^Your spell backfired!$` | backfire |
| `^Nothing seems to happen.$` | resisted / no effect |
| `^You flee %1.$` | fled mid-cast |
| `^You are too afraid.$` | fear effect |

These lines are registered **once** here rather than re-registered by each
caster, because tt++ keys `#action` by pattern and a second registration of the
same line silently shadows the first.

**Subscribers:**
- `lua/core/spellcast.lua` — `spellcast.fail_front()` drops the front of the
  shared cast-attempt FIFO (`_cast_queue`).
- `lua/core/stored_spells.lua` — `_drain_pending_attempt` pops the front of its
  own `_pending_attempts` FIFO.

**Cross-pop:** because both subscribers fire on the same event, a single shared
failure pops **both** fronts. With a blind/charm and a store in flight at once,
one failure desyncs both queues — the accepted trade-off; both modules guard the
empty case and the 10 s idle flush bounds the staleness. See
[ADR 0123](decisions/0123-shared-cast-feedback-ownership.md) and
[docs/spellcast.md](spellcast.md).

### `spell_cast_started`

Emitted by either of the two concentration-start `#action` triggers registered
by `_register_spellcast_actions()` — `^You start to concentrate...$` and
`^You muster all of your concentration...$`. No payload. A self-cast that has
begun concentrating.

**Subscribers:** `lua/core/charm.lua` — `spellcast.mark_front_inflight("charm")`
marks the front charm entry in-flight, the gate that distinguishes a real charm
follow from a merc/pet/group follow. See [docs/charm.md](charm.md).

### `spell_cast_recalled`

Emitted when the game sends `^You quickly recall your stored spell...$`. No
payload. A recalled stored spell is a spell-in-flight signal, not a failure: the
trigger is owned by `lua/core/spellcast.lua` and deliberately **does not** touch
the cast queue.

**Subscribers:**
- `lua/core/stored_spells.lua` — finds the entry in `state.char.stored_spells`
  with the highest `started_at` whose `name` matches `_last_cast_intent`. If
  found, removes the entry, persists the active list, and emits a
  `char_ui("store", name, "recalled")` line. `_last_cast_intent` is NOT cleared
  so successive recalls of the same spell resolve correctly. (Behaviour
  unchanged — only the line's ownership moved from stored-spells to spellcast.)
- `lua/core/charm.lua` — `spellcast.mark_front_inflight("charm")` marks the
  front charm entry in-flight (a recalled stored charm is also a real
  charm-in-flight signal).

### `store_succeeded`

Emitted when the game sends `"You stored it."` No payload.

**Subscribers:** `lua/core/stored_spells.lua` — pops the front of
`_pending_attempts`, computes `expected_duration` (mean of up to 3 prior samples,
defaulting to 5400 s), appends a new entry to `state.char.stored_spells`,
persists the active list, and emits a `script_ui("STORE", ...)` line.

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
`spell_cast_recalled` (the recall handler), `store_decayed`, and
`stored_spells_untracked` handler, and inside `_load_active()` after restoring
persisted entries on `Char.Name`.

Subscribers should read `state.char.stored_spells` directly for the new state.

**Subscribers:** `lua/core/timers_state.lua` — calls `serialize()` to write the
updated `stored_spells` array (alongside `affects`) to `bridge/runtime/timers.state`
atomically, giving the timers-pane renderer a fresh snapshot within one poll
tick.

### `blinds_changed`

Emitted by `lua/core/blinds.lua` with no payload whenever
`state.char.blinds` is mutated — at the end of `_blinds_on_blinded` after
appending a new entry, and at the end of `_blinds_tick` only when the
sweep actually removed at least one expired entry (the renderer's
bar-drain and expiring-blink are wall-clock-driven, so per-tick events
when nothing changed would be pure noise).

Subscribers should read `state.char.blinds` directly for the new state.

**Subscribers:** `lua/core/timers_state.lua` — calls `serialize()` to
write the updated `blinds` array (alongside `affects` and `stored_spells`)
to `bridge/runtime/timers.state` atomically, giving the timers-pane renderer
a fresh snapshot within one poll tick.

### `charms_changed`

Emitted by `lua/core/charm.lua` with no payload whenever `state.char.charms` is
mutated — on landing (`_charm_on_followed`), on each `_charms_tick` that prunes
at least one expired entry, on explicit drop (`charm_drop`), and at the end of
`_load_active` after restoring persisted entries on `gmcp_char_name`. Mirrors
`blinds_changed`.

Subscribers should read `state.char.charms` directly for the new state.

**Subscribers:** `lua/core/timers_state.lua` — calls `serialize()` to write the
updated `charms` array (alongside `affects`, `stored_spells`, and `blinds`) to
`bridge/runtime/timers.state` atomically. The `_load_active` emit is load-bearing:
`charm.lua` loads before `timers_state.lua` alphabetically, so the timers pane
re-serialises regardless of module load order. See [docs/charm.md](charm.md).

### `herblores_changed`

Emitted by `lua/core/herblores.lua` with no payload whenever
`state.char.herblores` is mutated — on `herblore_add` and `herblore_remove`, on
each `_herblores_tick` that advances at least one entry to a new phase or drops
an entry whose phases all elapsed, and at the end of `_load_active` after
restoring persisted entries on `gmcp_char_name`. Mirrors `charms_changed`.

Subscribers should read `state.char.herblores` directly for the new state.

**Subscribers:** `lua/core/timers_state.lua` — calls `serialize()` to write the
updated `herblores` array (the current phase of each entry, alongside `affects`,
`stored_spells`, `blinds`, and `charms`) to `bridge/runtime/timers.state`
atomically. The `_load_active` emit is load-bearing, exactly as for
`charms_changed`. See [docs/herblores.md](herblores.md).

### `kill_attributed`

Emitted by `lua/core/run_state.lua`'s `_fold()` once per attributed kill,
immediately after the `script_ui("KILL", ...)` announce. Payload:
`{name = "<mob name>", xp = <integer>}` where `name` is the mob name as
captured by `mob_death` (includes article, e.g. `"an elven slave"`) with any
trailing MUME label (e.g. `" (MIN)"`) stripped by `run_state` before it
reaches `state.run`, and `xp` is the even-split XP attributed to this kill
(may be `0` for empty-Vitals folds). For group kills inside the 500ms debounce window, fires once per mob
with the even-split share; the last mob receives the remainder. See ADR 0008
for the attribution model.

**Subscribers:** `lua/core/run_log.lua` — writes a `kill` row to
`current.jsonl`.

### `char_death`

Emitted by one pattern in `ttpp/core/mud_events.tin`. No payload.

| Pattern | Notes |
|---------|-------|
| `^You are dead! Sorry...$` | fires on player death (PvE, PvP, environment) |

**Subscribers:** `lua/core/run_state.lua` — increments `state.run.deaths` and
announces `▶ DEATH: You died.` via `script_ui`; no fold interaction.
`lua/core/run_log.lua` — writes a `char_death` row to
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

These three patterns are registered at priority 3 and win over the overlapping
broad [`mob_death`](#mob_death) pattern (which the asterisk-wrapped line also
matches) by the explicit priority gap — not by alphabetical ordering
([ADR 0115](decisions/0115-core-priority-band.md)). tt++ fires only one
`#action` per line, so without the gap the mob fallback would shadow this event.

**Subscribers:** `lua/core/run_state.lua` — strips any trailing MUME label
(e.g. `" (MIN)"`) from the payload, then splits the remainder into
`name` (first word) and `race` (rest, or `""` if single word); appends
`{name, race}` to `M.pending_pkills`; calls `schedule_fold()` to debounce
XP attribution. The strip happens before the split so the label never
lands in `race`.

### `pkill_attributed`

Emitted by `lua/core/run_state.lua`'s `_fold()` once per attributed PC kill,
immediately after the `script_ui("PKILL", ...)` announce. Payload:
`{name = "<pc name>", race = "<race suffix>", xp = <integer>}` where `name`
is the first word of the R.I.P. string (after any trailing MUME label is
stripped by `run_state`), `race` is the remainder (may be `""`), and `xp` is
the even-split XP attributed to this kill (may be `0` for empty-Vitals
folds). For mixed folds (mob kills + PC kills within the 500ms
window), XP is split evenly across all entries; the last entry processed
receives the remainder. See `kill_attributed` for the attribution model.

**Subscribers:** `lua/core/run_log.lua` — writes a `pkill` row to
`current.jsonl`.

### `achievement`

Re-emitted by `lua/core/world_state.lua` from the GMCP `Event.Achieved` message.
Payload is the achievement description string carried in the `what` field of
the GMCP body.

**Source.** MUME sends `Event.Achieved {"what": "<description>"}` directly when
a new achievement is unlocked. The world-state collector pulls `body.what` and
emits `achievement` with that string. Bodies with missing or null `what` are
dropped silently.

**History.** This event was previously sourced from a two-stage tt++ trigger on
the `"You achieved something new!"` marker line plus a one-shot inner `#action`
on the following line — see
[ADR 0050](decisions/0050-synchronous-nested-actions-with-class-discipline.md)
for the historical mechanism and its constraints. The contract is unchanged;
only the source moved from tt++ to GMCP.

**Subscribers:**
- `lua/core/run_log.lua` — writes an `achievement` row to `current.jsonl`.
- `lua/core/world_state.lua` — UI announcement: `script_ui("ACHIEVEMENT", "Unlocked.")`
  plus `tintin_show` of `## ACHIEVEMENT: <text>` to the mume main window. The
  split is because the achievement string routinely exceeds the 33-char
  `script_ui` budget; `script_ui` carries a short fixed notice and the full
  text goes to the game window.

## Adding a new event

Events can come from three sources:

- **tt++ action** — add a `#action` line inside a
  `_register_<module>_actions` alias in the relevant `ttpp/core/<module>.tin`,
  and call that alias from `SESSION CONNECTED` in `ttpp/core/system.tin`.
  For project-wide events that have no owning module, use
  `ttpp/core/mud_events.tin` and the existing `_register_mud_events` alias.
  Two flavours of the alias exist, and they get their priority differently
  ([ADR 0115](decisions/0115-core-priority-band.md) defines the 1–4 core
  band; `3` is the default):
  - **Direct** — the alias body contains tt++ `#action` lines literally.
    Each `#action` must carry `{3}` as the third brace-arg explicitly
    (e.g. `mud_events.tin`, `clock.tin`).
  - **Lua-delegating** — the alias body calls
    `#lua {_register_<module>_triggers()}` and the actual `#action`
    registrations happen on the Lua side via `session_cmd`. The helper
    auto-injects `{3}` per the [docs/ipc.md](ipc.md) injection
    contract, so the call site
    must not (and should not) add `{3}` explicitly. Examples:
    `affects.tin`, `stat_reconcile.tin`, `stored_spells.tin`.
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
