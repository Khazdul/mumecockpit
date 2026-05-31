# Blinds Tracker

Tracks blinded targets with fixed 90 s timers. Two deliberately decoupled
layers: the inbound "<name> seems to be blinded!" line creates a bar
unconditionally (Layer 1); the outgoing cast snoop supplies the numeric
prefix (`2.orc`) when one was typed (Layer 2). MUME serialises spellcasting,
so a plain FIFO of attempt entries is correct, not heuristic.

The cast-attempt FIFO, the shared cast-failure lines, and the 10 s idle flush
no longer live here — they belong to [`lua/core/spellcast.lua`](../lua/core/spellcast.lua),
which several casters share. Blinds enqueues a `{kind="blindness", prefix=…}`
entry on snoop and pops it on its own success line; spellcast owns the queue
mechanics and the shared failure handling. See [docs/spellcast.md](spellcast.md)
and [ADR 0123](decisions/0123-shared-cast-feedback-ownership.md).

This document covers the data layer and event bus; rendering is handled by
the buffs pane — see [`docs/buffs-pane.md`](buffs-pane.md) for the rendering
spec.

## Data flow

```
                                       outgoing cast text
                                              │
                                              ▼
                                   user_input subscriber
                                   — parse blindness cast
                                              │
                                              ▼
                       spellcast.enqueue({kind="blindness", prefix=…})
                                              │
inbound MUME line                  shared _cast_queue (spellcast.lua)
"... seems to be blinded!"                    │
      │                                       │
      ▼                                       │
tt++ #action (GAME_SESSION, priority 3)       │
  — registered by                             │
    _register_blinds_actions()                │
    at SESSION CONNECTED                      │
      │                                       │
      ▼ _blinds_on_blinded("<raw name>")     │
      │   — strips "An "/"A " article         │
      │   — spellcast.pop_if_front_kind   ◀───┘
      │     ("blindness") (or false if
      │     front is not a blindness)
      ▼
state.char.blinds  ──►  events.emit("blinds_changed")
                    ──►  buffs_state.lua serialises
```

## State schema

### `state.char.blinds`

Array of currently-blinded target entries:

```lua
{
    name              = "2.orc",  -- includes any numeric prefix that was
                                  -- typed on the cast; bare game name if
                                  -- the cast was uncast-prefixed or
                                  -- unobserved
    started_at        = 1714000000,
    expected_duration = 90,        -- always 90; blindness has fixed duration
    expires_at        = 1714000090,
}
```

Initialised to `{}` at module load and on every `gmcp_char_name` (login),
then repopulated from `blinds_active.json` (see [Persistence](#persistence)).
`state.char.reset()` (called on disconnect) wipes the in-memory list via the
standard non-function-key sweep in `char_state.lua`, but the on-disk file is
the cross-session survivor and is **not** touched on disconnect — reconnect
reloads it.

### Pending-attempts FIFO

Blinds no longer keeps its own FIFO. Pending casts live in the **shared**
`_cast_queue` owned by [`lua/core/spellcast.lua`](../lua/core/spellcast.lua).
A blindness cast enqueues a table `{kind = "blindness", prefix = num}` where
`prefix` is a string number prefix (e.g. `"2."`) or `false` (the cast carried
no explicit number). `false` is used rather than `nil` so the field round-trips
cleanly. spellcast owns the idle flush and the shared failure draining; see
[docs/spellcast.md](spellcast.md).

## Layer 2 — outgoing cast snoop

Subscribes to `user_input` (see [docs/events.md](events.md#user_input)).
A line is recognised as a blindness cast when:

- the first whitespace token is a prefix of `cast` (1–4 chars, case-folded:
  `c`, `ca`, `cas`, `cast`);
- it contains a single-quoted token that, lowercased, is a prefix of
  `blindness` of length ≥ 3 (`'bli'` matches, `'bl'` does not);
- any words between the cast token and the quoted spell (a spellspeed) are
  ignored — no spellspeed list is enforced.

The trimmed text after the closing quote yields the prefix:

- `^(\d+\.)` (e.g. `2.orc`, `1.troll`) → `{kind="blindness", prefix=that}` is
  enqueued onto the shared FIFO;
- anything else (bare name, empty, or no target) → `prefix = false` is enqueued.

`spellcast.enqueue` re-arms a named `#delay {spellcast_que_flush}` on every
push. After 10 s of no new pushes the whole queue is cleared, so an unanswered
cast does not strand a stale entry that mis-labels the next successful blind.
The flush is owned by spellcast and is shared across all casters.

## Layer 1 — landed-blindness handler

A single `#action` registered by `_register_blinds_actions()` at priority 3:

```
^%1 seems to be blinded!$  →  _blinds_on_blinded("%1")
```

Handler steps:

1. **Normalise the name** — strip a leading `An ` or `A ` article only when
   followed by whitespace, so player names like `Anaru` or `Aragorn` are
   left intact.
2. **Pop the shared FIFO** — `e = spellcast.pop_if_front_kind("blindness")`,
   then `num = e and e.prefix or false`. The pop is conditional on the front
   entry being a blindness; a front belonging to another caster is left
   untouched and `num` is `false`. The bar is created regardless of FIFO state
   (Layer 1 must always work).
3. **Append the entry** with `name = (num or "") .. normalised_name`,
   `started_at = now`, `expected_duration = 90`, `expires_at = now + 90`.
4. **Arm the prune tick** — `#delay {blinds_tick} {#lua {_blinds_tick()}} {2}`.
   Named non-numeric delays replace an existing delay of the same name, so
   re-arming on every landing is idempotent.
5. **Emit `blinds_changed`**.

## FIFO-pop triggers

The shared `_cast_queue` front is dropped by several independent paths. Every
pop is guarded — a pop on an empty queue is a silent no-op, because the trigger
may belong to a different spell.

### 1. Success line

Pop happens inside `_blinds_on_blinded` via `spellcast.pop_if_front_kind("blindness")`
alongside the bar insertion (see
[Layer 1](#layer-1--landed-blindness-handler)). The popped entry's `prefix`
becomes the bar's name. Only a blindness at the front is consumed; a front
belonging to another caster is left in place.

### 2. Failure lines

The **eight shared** cast-failure lines are registered once by spellcast (not
here); each emits `spell_cast_failed`, and spellcast's own subscriber calls
`spellcast.fail_front()` to drop the front. Blinds does **not** subscribe to
`spell_cast_failed` — it relies on spellcast draining the front. See
[docs/spellcast.md](spellcast.md#registered-lines) for the eight lines.

The only failure line still owned by blinds is the blindness-specific
`^Your victim is already blind.$`, registered in `_register_blinds_actions()`;
it calls `spellcast.fail_front()` directly (queue-only, no event). The generic
`^Nobody here by that name.$` bad-target line is owned by spellcast.

### 3. Empty input (cast cancel)

Pressing Enter on an empty line tells MUME to abort the current cast.
**spellcast** (not blinds) subscribes to the `user_input_empty` event bus topic
and calls `spellcast.fail_front()`. Blinds no longer subscribes to this event.

Accepted narrow desync: with a mix of casts in flight, a shared failure or
empty-line abort drops whatever is at the front, which may not be the blind.
Low-stakes — Layer 1 still draws the bar regardless, just possibly without (or
with the wrong) numeric prefix.

### Idle flush

If a typed cast never produces any signal, spellcast's 10 s idle-flush `#delay`
({`spellcast_que_flush`}) clears the entire shared queue so a stuck entry cannot
indefinitely mis-label a later landing. The flush is owned by spellcast.

## Periodic tick

A named `#delay {blinds_tick}` runs every 2 seconds in GAME_SESSION while
at least one blind is active. The sole job is to remove entries whose
`expires_at <= now`. Blindness has no in-game drop string — the 90 s timer
is the only removal path — so there is no overrun / no 2.5× safety net.

- Re-armed every cycle if `state.char.blinds` is non-empty (named delays
  replace, so re-arming is idempotent).
- Cancelled on `char_reset` (only effective when GAME_SESSION is still set;
  the SESSION DISCONNECTED fallback finds GAME_SESSION nil, but the session
  dying clears its delays automatically).
- Emits `blinds_changed` only on a prune cycle (the renderer's blink/drain
  is wall-clock-driven and does not need ticking events).

## Persistence

Active blinds survive reconnect and a full application restart, mirroring the
stored-spells active list (see [docs/stored-spells.md](stored-spells.md) and
[docs/affects.md](affects.md)). The store is
`data/characters/<char>/blinds_active.json`, where `<char>` is
`state.char.name` verbatim (the `data/characters/<character>/` convention in
[architecture.md](../architecture.md)).

- **Write** — `_save_active()` does an atomic temp-file + `os.rename` write of
  `state.char.blinds`. An empty list is written as `[]` (the file is never
  deleted), so reconnect always finds a definitive answer. It is called at
  exactly two mutation points: at the end of `_blinds_on_blinded` (after the
  entry is appended) and in `_blinds_tick` after the prune sweep, gated on the
  `pruned` flag. It is **not** called on `char_reset` — disconnect must never
  overwrite or delete the file.
- **Load** — `_load_active(char_name)` runs from the `gmcp_char_name` handler
  (cold start and reconnect), after the in-memory list is reset to `{}`. It
  reads the file (absent/malformed → leave `{}` with a non-fatal `dbg`),
  repopulates `state.char.blinds`, and drops any entry with
  `expires_at <= os.time()` (its 90 s elapsed during downtime). There is no
  name validation — blind names are mob names, not a canonical table. If any
  blind survives, the prune tick is armed; `blinds_changed` is emitted at the
  end regardless so the buffs pane re-serialises independent of module load
  order. Logs `[BLINDS] restored N (M expired)`.

No migration shim exists — blinds were never persisted before, so there is no
old `logs/` location to migrate from.

## Registration global

`_register_blinds_actions()` is a global Lua function defined in
`lua/core/blinds.lua`. It is called by the `_register_blinds_actions`
alias in `ttpp/core/blinds.tin`, invoked from `SESSION CONNECTED` in
`ttpp/core/system.tin` (after `_register_stat_reconcile_actions`).

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing alias and exists only to populate
the game session's action list.

## Rendering

`state.char.blinds` is serialised into `bridge/runtime/buffs.state` as a
top-level array `blinds`. The buffs pane renders it as the fourth group
(after Spells / Buffs / Debuffs / Stored) and immediately **before** the
Charm group, using the standard timed-affect cell renderer (drain bar +
expiring-blink) laid out **2 cells per row** so the wider mob names fit. See
[docs/buffs-pane.md](buffs-pane.md#blinds-two-up-layout) for the two-up layout
and [docs/buffs-pane.md](buffs-pane.md#per-group-palette) for the cell
appearance and the palette entry.

## UI-pane announcements

Two `char_ui("blind", name, verb)` lines surface to the UI pane via the
standard `◆`-family character-state helper (see
[docs/ui-messaging.md](ui-messaging.md#character-events)):

- **Landing** — `_blinds_on_blinded` emits `char_ui("blind", name, "up")`
  after the entry is appended and `blinds_changed` is emitted. `name` is
  the full entry name including any numeric prefix (e.g. `2.orc`).
- **Tick prune at 90 s** — `_blinds_tick` emits
  `char_ui("blind", name, "down")` for each entry removed at expiry,
  using the entry's name (snapshotted before `table.remove`).

Renders as:

```
◆ BLIND: 2.orc up.
◆ BLIND: 2.orc down.
```

The `BLIND` tag renders in the same cyan (`#00CCCC`) as the buffs-pane
Blinds group, so the UI-pane line and the pane bar read as one surface.

No UI line is emitted on:
- a failed cast (spellcast's failure-line pop of the shared FIFO is silent);
- an empty-input cancel (spellcast's `user_input_empty` pop is silent);
- disconnect (the state wipe via `char_reset` is silent).

---
Back to [architecture.md](../architecture.md).
