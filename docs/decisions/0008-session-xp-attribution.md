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

- `Char.Vitals` continuously updates running totals (`state.run.xp`, `state.run.tp`)
  and tracks `last_fold_xp` — the XP snapshot at the previous fold (or run
  start).
- Each `mob_death` event pushes the mob name onto `pending_kills` and issues a
  named `#delay {run_fold}` of **500 ms** in `GAME_SESSION` via
  `session_cmd`. Because the delay tag is named, each new `mob_death` within the
  window replaces the pending delay, so consecutive kills in a burst are batched
  into one fold.
- On fold, compute `pending_xp = state.char.xp − last_fold_xp` (total XP earned
  since the last fold), distribute evenly across all names in `pending_kills`
  using integer division; the last entry receives the rounding remainder.
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
- Group kills within 500 ms receive equal credit. No per-mob server data exists,
  so equal split is the best achievable.
- Back-to-back solo kills separated by > 500 ms fold independently. If the
  player starts hitting the next mob within 500 ms of the previous death, both
  names share the combined XP — documented trade-off.
- 500 ms is a deliberate safety margin. The trailing Vitals tick after a kill
  arrives well within this window in practice; the extra headroom protects
  against unknown server-side timing variation and is invisible to the player
  (the announce lands while loot/movement is still happening).
- Quest or non-kill XP earned between kills bleeds into the next kill's number.
  Accepted limitation; no source of truth to distinguish it.
- No orphan-XP concept; every XP delta is absorbed by the accumulator and
  credited on the next fold (or discarded if no mobs ever die).
- `cp -r` resets Lua state; next Vitals tick rebaselines from current XP, `Sess
  XP` resets to 0. Expected behaviour.

## Alternatives considered

- **Next-delta model (original).** Broken: attributes per-hit XP, not kill XP.
- **Edge-triggered fold on first `Char.Vitals` after `mob_death`.** Prototyped
  during phase B. Pros: lower latency on the announce, no timer. Rejected:
  relies on the implicit contract that MUME always emits Vitals after the
  trailing R.I.P. in a burst, and group kills depend on multiple R.I.P. lines
  arriving before that single trailing Vitals. Both hold today but neither is
  documented MUME behaviour. The 500 ms fixed window provides cheap insurance
  against future server-side timing changes at the cost of a
  player-imperceptible delay.
- **Parse per-kill text lines.** MUME does not emit per-kill XP text.
- **Attribute the whole delta to the most recent death.** Wrong for group fights.
- **Skip attribution entirely.** Loses the per-mob kill list wanted for future
  features.
