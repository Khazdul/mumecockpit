# 0008 — Session XP attribution across group kills

**Status:** Accepted (revised 2026-04-25)
**Date:** 2026-04-25

## Context

MUME emits `Char.Vitals` on **every combat hit**, not only on kills. This means
the XP field increments continuously during a fight, making the "first positive
delta after a mob_death" an unreliable attribution signal — it captures only the
per-hit XP from the last hit before the R.I.P. line, not the mob's full reward.

The original "next-delta" model attributed per-hit XP to the pending kill name,
then credited the killing-blow XP to no-one (GMCP arrives before R.I.P., so
the pending queue was empty at the killing blow), and later misattributed the
first per-hit delta from the next fight to the dead mob. All three are wrong.

## Decision

Accumulate XP continuously in `Char.Vitals`; fold on a **debounced timer**
triggered by `mob_death`.

- Each `mob_death` event pushes the mob name onto `pending_kills` and issues a
  named `#delay {sess_kills_fold}` (400 ms). Because the delay tag is named,
  each new `mob_death` within the window replaces the pending delay, so
  consecutive kills in a burst are batched into one fold.
- On fold, compute `pending_xp = state.char.xp − last_fold_xp` (total XP earned
  since the last fold), distribute evenly across all names in `pending_kills`
  using integer division, last entry gets the rounding remainder.
- Advance `last_fold_xp` to the current value and clear `pending_kills`.

```lua
local per = math.floor(pending_xp / n)
local rem = pending_xp - per * n
-- kill[n] receives per + rem
```

Negative XP (death penalty / level loss) triggers a full baseline reset rather
than crediting any kill or attempting recovery.

## Consequences

- Solo kills: full fight XP (all per-hit deltas + killing blow) is credited to
  the mob's name. Correct.
- Group kills within 400 ms receive equal credit. No per-mob server data exists,
  so equal split is the best achievable.
- Back-to-back solo kills separated by > 400 ms fold independently. If the
  player starts hitting the next mob within 400 ms of the previous death, both
  names share the combined XP — documented trade-off.
- Quest or non-kill XP earned between kills bleeds into the next kill's number.
  Accepted limitation; no source of truth to distinguish it.
- No orphan-XP concept; every XP delta is absorbed by the accumulator and
  credited on the next fold (or discarded if no mobs ever die).
- `cp -r` resets Lua state; next Vitals tick rebaselines from current XP, `Sess
  XP` resets to 0. Expected behaviour.

## Alternatives considered

- **Next-delta model (original).** Broken: attributes per-hit XP, not kill XP.
- **Parse per-kill text lines.** MUME does not emit per-kill XP text.
- **Attribute the whole delta to the most recent death.** Wrong for group fights.
- **Skip attribution entirely.** Loses the per-mob kill list wanted for future
  features.
