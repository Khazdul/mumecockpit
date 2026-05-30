# 0123 — Shared cast-feedback ownership (single owner, neutral events)

**Status:** Accepted
**Date:** 2026-05-31

## Context

Three casters react to the same generic cast-feedback lines that MUME emits
without a spell name:

- **blindness** (`lua/core/blinds.lua`),
- **stored-spells** (`lua/core/stored_spells.lua`),
- **charm** (`lua/core/charm.lua`).

The shared lines are eight failure lines (concentration loss, out of mana,
backfire, …), the stored-spell recall line
(`You quickly recall your stored spell...`), and the two concentration-start
lines. None of them carry a spell name, and they are order-dependent: MUME
serialises spellcasting, so the next feedback line refers to the oldest
in-flight cast.

tt++ keys `#action` by pattern and allows exactly one action per pattern, so
two modules registering the same line means the later registration silently
**shadows** the earlier one. This caused a real regression: an early
single-PR attempt had spellcast's recall-line registration shadow
stored-spells', breaking stored-spell unstore removal. Every module owning its
own copy of a shared line is a standing hazard, not a one-off bug.

## Decision

`lua/core/spellcast.lua` registers each shared line **exactly once** and emits
a neutral event — `spell_cast_failed`, `spell_cast_started`, or
`spell_cast_recalled`. Consumers subscribe; they never re-register a shared
line.

spellcast also owns a runtime-only FIFO (`_cast_queue`) of outgoing cast
attempts, each tagged by `kind`. Because casting is serialised, a plain FIFO
matches the server's success/failure order. The queue API is `enqueue`,
`pop_if_front_kind`, `mark_front_inflight`, `pop_if_front_inflight`,
`fail_front`, and `clear`, with a 10 s idle flush so a swallowed cast cannot
mis-label a much-later success.

The three consumers use the queue asymmetrically:

- **blindness** enqueues `{kind="blindness"}` and pops unconditionally
  (`pop_if_front_kind`) — its success line
  (`<name> seems to be blinded!`) is unambiguous, so item-cast and
  third-party blinds are captured too.
- **charm** enqueues `{kind="charm"}`, marks the front in-flight on the
  concentration/recall signal, and pops **gated** (`pop_if_front_inflight`) —
  its success line (`<name> starts following you.`) is ambiguous (mercs, pets,
  and group members also follow).
- **stored-spells** keeps its **own** separate FIFO (`_pending_attempts`) and
  its four store-specific failure lines, but subscribes to the shared
  `spell_cast_failed` and `spell_cast_recalled`.

## Consequences

What becomes easier: a new shared failure line is added in one place; adding a
caster is a subscription, not a re-registration; the shadowing regression
cannot recur for shared lines.

The load-bearing trade-off is the **cross-pop**. Two independent FIFOs exist:
spellcast's `_cast_queue` (blindness + charm) and stored-spells'
`_pending_attempts`. `spell_cast_failed` is subscribed by **both** spellcast
(`fail_front` pops `_cast_queue`) and stored-spells (`_drain_pending_attempt`
pops `_pending_attempts`), so a single shared failure pops both fronts. If a
blind/charm and a store are in flight simultaneously, one failure desyncs both
queues.

This is tolerated: both modules guard the empty case with a
"queue empty (out of sync)" `dbg`; simultaneous cross-type casts mid-flight are
rare (serialised casting plus the 10 s flush bound the staleness window); and
the alternative (one unified queue) would relocate the cross-pop rather than
remove it.

## Alternatives considered

**(a) Each module registers its own copy of the shared lines.** Rejected:
tt++'s one-action-per-pattern rule means the later registration shadows the
earlier — exactly the regression that motivated this ADR.

**(b) One unified queue across all casters including stored-spells.** Rejected:
stored-spells has a richer attempt model (target resolution, recall-by-intent)
that does not fit the simple kind-tagged FIFO, and merging would relocate the
cross-pop, not remove it.

**(c) A single `RECEIVED LINE` scan in Lua.** Rejected on the project's
no-hot-path-Lua stance — it routes every received line through Lua on the
latency-critical path to catch a handful of rare lines. See
[ADR 0050](0050-synchronous-nested-actions-with-class-discipline.md) for the
same rejection in another context.

See [`docs/spellcast.md`](../spellcast.md) for the owner, and
[`docs/blinds.md`](../blinds.md), [`docs/stored-spells.md`](../stored-spells.md),
and [`docs/charm.md`](../charm.md) for the three consumers.
