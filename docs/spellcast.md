# Spellcast Cast-Attempt Owner

Single owner of the cast-feedback lines that several casters share, and of a
runtime-only FIFO of outgoing cast attempts. MUME emits the shared lines
without a spell name and in cast order; `lua/core/spellcast.lua` registers each
once, emits a neutral event, and keeps the attempt queue that lets consumers
attribute an order-dependent line to the right cast.

The queue is **runtime-only**: it is never persisted and is wiped on
`gmcp_char_name` (login / character switch) and `char_reset` (disconnect). The
shared lines exist because tt++ keys `#action` by pattern and allows one action
per pattern — co-registering the same line from two modules silently shadows
the earlier one. Owning each line here removes that hazard. See
[ADR 0123](decisions/0123-shared-cast-feedback-ownership.md) for the decision
and the cross-pop trade-off.

## The FIFO model

`_cast_queue` is a file-local Lua array. Each element is a table carrying at
least a `kind` field tagging which consumer owns the attempt:

```lua
{ kind = "blindness", prefix = "2." }   -- blindness, with an optional numeric prefix
{ kind = "charm" }                       -- charm; gains inflight = true once concentrating
```

A plain FIFO is correct, not heuristic, because MUME serialises spellcasting:
the next feedback line refers to the oldest in-flight cast, so the front of the
queue is always the cast the next line is about. The optional `prefix` field
(blindness) and `inflight` flag (charm) are consumer-specific decorations on the
generic entry.

## API

All six functions are exposed on the global `spellcast` table.

**`spellcast.enqueue(entry)`** — push a tagged entry onto the back and re-arm
the 10 s idle flush. Any unconsumed entry is dropped after 10 s of silence, so a
swallowed or ignored cast cannot mis-label a much-later success.

**`spellcast.pop_if_front_kind(kind)`** — pop and return the front entry only
when its `kind` matches; otherwise leave the queue untouched and return `nil`
(the front belongs to another consumer). Blindness pops with this — its success
line is unambiguous, so the front is always its own when a blind lands.

**`spellcast.mark_front_inflight(kind)`** — set `inflight = true` on the front
entry when its `kind` matches. Charm uses this to gate the ambiguous
"`<name> starts following you.`" line on a self-cast that has actually begun
concentrating (or a recalled stored charm).

**`spellcast.pop_if_front_inflight(kind)`** — pop and return the front entry
only when its `kind` matches **and** it has been marked in-flight; otherwise
leave the queue untouched and return `nil`. Charm pops with this, so a follow
with no in-flight charm at the front is left for whatever owns it (and ignored
by charm).

**`spellcast.fail_front()`** — drop the front entry unconditionally. Guarded: an
empty queue is a silent no-op. Emits no event.

**`spellcast.clear()`** — empty the queue and disarm the idle flush. Subscribed
to `gmcp_char_name` and `char_reset` so login and disconnect both reset cleanly.

## Registered lines

`_register_spellcast_actions()` registers, via `session_cmd()` at priority 3:

- **The eight shared failure lines** → each emits `spell_cast_failed`:

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

- **`^Nobody here by that name.$`** → `spellcast.fail_front()` directly
  (queue-only, **no event**). A bad target aborts the cast but is not a
  store-failure line, so it pops the front rather than emitting the shared
  event. Owned here so charm and blindness reuse it without a later move.

- **`^You quickly recall your stored spell...$`** → `spell_cast_recalled`. A
  recalled stored spell is a spell-in-flight signal, not a failure: it emits the
  neutral event for consumers and deliberately **does not** touch the queue.

- **`^You start to concentrate...$`** and
  **`^You muster all of your concentration...$`** → `spell_cast_started`. A
  self-cast that has begun concentrating. Charm is the only consumer (its
  in-flight gate).

## The 10 s idle flush

`spellcast.enqueue` arms a named `#delay {spellcast_que_flush}` set to call
`spellcast.clear()` after 10 s. Each new enqueue replaces it (named delays
replace), so the window is measured from the last push. A typed cast that never
produces any feedback line therefore cannot strand a stale entry that
mis-labels the next landing. `spellcast.clear()` undelays it.

## Consumers and the cross-pop

Three modules subscribe to the neutral events; none re-register a shared line:

- **blindness** enqueues `{kind="blindness", prefix=…}`, pops unconditionally
  with `pop_if_front_kind`. See [docs/blinds.md](blinds.md).
- **charm** enqueues `{kind="charm"}`, marks in-flight on
  `spell_cast_started` / `spell_cast_recalled`, pops gated with
  `pop_if_front_inflight`. See [docs/charm.md](charm.md).
- **stored-spells** keeps its **own** `_pending_attempts` FIFO and its
  store-specific failure lines, but subscribes to `spell_cast_failed` and
  `spell_cast_recalled`. See [docs/stored-spells.md](stored-spells.md).

Because `spell_cast_failed` is subscribed by both spellcast (`fail_front` on
`_cast_queue`) and stored-spells (`_drain_pending_attempt` on
`_pending_attempts`), one shared failure pops **both** fronts. With a blind/charm
and a store in flight at once, a single failure desyncs both queues. This is the
accepted trade-off; both modules guard the empty case and the 10 s flush bounds
the staleness. See [ADR 0123](decisions/0123-shared-cast-feedback-ownership.md).

## Registration global

`_register_spellcast_actions()` is a global Lua function defined in
`lua/core/spellcast.lua`. It is called by the `_register_spellcast_actions`
alias in `ttpp/core/spellcast.tin`, invoked from `SESSION CONNECTED` in
`ttpp/core/system.tin`. It runs **first** of the cast-feedback registrars —
before `_register_affect_actions`, `_register_stored_spells_actions`,
`_register_blinds_actions`, and `_register_charm_actions` — so the shared lines
and the `spellcast` table exist before any consumer's actions register.

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing alias and exists only to populate the
game session's action list and own the cast queue.

## Cross-links

- [docs/events.md](events.md) — the emitted events
  (`spell_cast_failed`, `spell_cast_started`, `spell_cast_recalled`).
- [docs/blinds.md](blinds.md), [docs/charm.md](charm.md),
  [docs/stored-spells.md](stored-spells.md) — the three consumers.
- [ADR 0123](decisions/0123-shared-cast-feedback-ownership.md) — single-owner
  decision and the cross-pop trade-off.

---
Back to [architecture.md](../architecture.md).
