# 0133 — Timers-pane countdown (Clock) overlay; expiring-blink removed

**Status:** Accepted
**Date:** 2026-06-08

## Context

Each timed cell in the timers pane (`bridge/panes/timers_pane.py`) draws a
draining bar with the group/affect name overlaid on the left. A final-30s blink —
modelled on the buffs-pane blink (ADR 0033) — signalled imminent expiry. The blink
told you *that* a timer was about to lapse but not *how long* was left; users
asked for the precise time remaining instead.

The data needed was already on hand: each timed entry serialises `expires_at` /
`expected_duration`, and the pane already redraws on a 1 Hz tick (the tick that
drains the bar). So the question was purely a presentation one — how to surface the
remaining time without new redraw machinery, without touching the tt++ hot path,
and without Lua.

## Decision

- **Per-type opt-in.** A countdown is shown only for groups whose
  `timers_<type>_clock` flag is set (default `0`; the toggle lives in the timers
  layout menu — see [ADR 0126](0126-timers-layout-menu.md)). The countdown is a
  right-justified time rendered over the existing drain bar, with the name still on
  the left. This is pure presentation in `bridge/panes/timers_pane.py`: the data was
  already serialised and the existing 1 Hz tick already redraws, so there is **no**
  new redraw machinery, nothing added to the tt++ hot path, and no Lua.

- **Format.** `<= 90 s` shows whole seconds; `> 90 s` shows minutes rounded to the
  nearest minute, half up, via integer `(secs + 30) // 60`. So `91 s → 2m` and
  `150 s → 3m`; `"1m"` never appears (anything that would round to one minute is
  still inside the ≤90s whole-seconds band).

- **Narrow-cell ladder.** `_clock_content` renders a Tier A / B / C ladder so a
  narrow cell still shows a usable time, degrading gracefully as cell width shrinks.

- **Right edge.** A timed clock cell in the rightmost column uses the full cell
  width (no trailing separator) so the countdown reaches the pane's right edge. A
  *lone* last cell that is **not** in the rightmost column keeps its separator and
  stays aligned with the column above it.

- **Corner clearance.** The topmost-visible row's rightmost-column cell keeps a
  one-column trailing blank, so the box-drawing corner `+` floats over that blank
  rather than over the countdown digits. This is scroll-aware (it tracks whichever
  row is topmost-visible).

- **Blink removed.** The final-30s expiring-blink is gone. The draining bar plus the
  ticking countdown now carry the imminent-expiry signal. The 1 Hz tick is retained
  — it drives both the drain and the countdown.

- **What shows no countdown.** Charmies (which run their own count-up), indefinite
  affects, and untracked entries render no countdown.

## Consequences

- Opt-in and off by default: with no `timers_<type>_clock` config present, the pane
  looks exactly as before *minus the blink*.
- The timers blink — modelled on the buffs blink of ADR 0033 — is gone. ADR 0033 and
  ADR 0034 are left unchanged: their prompt_toolkit / renderer-side-compute rationale
  still stands and is unaffected by removing one consumer's blink.
- In the topmost-visible row, the rightmost-column cell's countdown renders one column
  to the left of the rightmost-column cells in the rows below it. That is the
  deliberate cost of reserving the corner blank so the `+` never lands on the digits.

## Alternatives considered

**`M:SS` format (the initial ship).** Show `m:ss` for everything. Rejected: noisier
than needed for a glanceable pane; whole seconds under 90s and rounded minutes above
it read faster at a glance.

**`ceil` minutes.** Round minutes up rather than half-up. Rejected: overstates the
time remaining near a boundary; nearest-minute (half up) is truer to the actual time
left.

**Keep the blink.** Retain the final-30s blink alongside the countdown. Rejected: the
draining bar and ticking countdown already convey imminence; a blink on top is
redundant motion.

**Let the `+` overlay the countdown.** The first right-edge ship let the corner `+`
sit over the rightmost-column countdown. Reverted via the one-column corner reserve
above: the `+` was obscuring the digits in the topmost row.

## See also

- [ADR 0126](0126-timers-layout-menu.md) — the Clock toggle column that gates this
  overlay (and the Teal-swatch retirement made to fit it).
- `docs/timers-pane.md` — the rendered behaviour, format ladder, and edge/corner
  handling.
