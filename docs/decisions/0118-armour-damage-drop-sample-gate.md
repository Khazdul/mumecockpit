# 0118 — Armour damage-drop sample gate

**Status:** Accepted
**Date:** 2026-05-29

## Context

The `armour` spell can drop early when the character takes damage, not only at
its maximum duration. MUME sends no in-game signal distinguishing a
damage-triggered drop from a natural max-duration decay — both fire the same
drop string (`^You feel less protected.$`).

`affect_down` records `now - started_at` as an observed-duration sample for any
tracked affect with a `dropString_*`. For armour, a damage-triggered early drop
produces a short sample that pollutes the learned-duration mean and drags
`expected_duration` below the spell's true maximum — the same under-prediction
dynamic as ADR 0027, but triggered by damage drops rather than early
tick-prunes.

## Decision

For affects flagged `damage_droppable = true` in `affects_data.lua` (armour only
at time of writing), the data-table `duration` acts as a per-character floor on
the *sample* side.

In the `affect_down` handler: when `observed < data.duration` for a
damage-droppable affect, the sample is discarded — no ring-buffer push, no
`affects_learned.json` write — and a distinct `dbg` line is emitted. Drops at or
beyond `data.duration` are treated as natural decay and recorded normally, so
the learned mean can still rise above the data-table duration.

The gate sits on the sample side, not the prediction side: `_expected_duration`
is unchanged. Because no sub-floor sample ever reaches the ring-buffer, the mean
can never fall below `data.duration` — the floor falls out naturally.

Rendering is unchanged: the bar drains against `expected_duration`, and the drop
string remains the authoritative expiry signal (consistent with ADR 0027).

## Consequences

- armour's learned duration can only learn upward from `data.duration`; early
  damage drops no longer corrupt the estimate.
- The flag is opt-in. Affects without `damage_droppable` keep recording every
  natural drop sample in both directions — `data.duration` remains a pre-sample
  fallback for them, never a floor.
- The boundary case `observed == data.duration` counts as natural decay (the
  gate is strict `<`), so an exact-duration drop is recorded.

## Alternatives considered

**Floor on the prediction side** (clamp `_expected_duration` to `max(mean,
data.duration)`). Rejected: it would let polluted short samples persist in the
ring-buffer and silently distort any future logic that reads the raw samples;
gating at the sample source keeps the stored history honest.

**Global floor for all affects.** Rejected: other spells legitimately learn
downward (early dispel/refresh is a true short sample for them). The floor is
correct only where short durations are predominantly damage-triggered noise,
i.e. armour.

**Separate damage-drop trigger to distinguish the two drop causes.** Rejected:
MUME sends no distinguishing signal; the observed-duration threshold is the only
available discriminator.
