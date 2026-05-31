# 0124 — Controlled-without-charm followers share the charm tracker

**Status:** Accepted

**Date:** 2026-05-31

## Context

Some MUME mobs are commanded *without* casting charm — the enslaved
shadow, the wood elf, and the dreadful warg. Each produces a fixed,
unambiguous follow line, and each belongs in the buffs pane's charm
group: the same list, rendering, persistence, and click-to-drop control.

The charm follow line `^%1 starts following you.$` is deliberately gated
behind the shared in-flight cast FIFO (see `docs/charm.md` and ADR 0123)
because it is ambiguous — mercenaries, pets, and group members also
"start following you." A charm add only fires when a charm cast is in
flight. Controlled mobs have no charm cast in flight, so that gate would
reject them.

The three mobs differ in lifetime. The enslaved shadow and dreadful warg
have no in-game duration; the wood elf does, and also emits an in-game
leave line. The dreadful warg is an in-game transform of an enslaved
shadow whose only signal is the warg's own follow line.

## Decision

Controlled mobs are recognised by **name**, not by separate triggers.
`_charm_on_followed` strips the article and, if the bare name is in a
module-local `CONTROLLED` table, dispatches to `_control_on_followed` and
returns **before** the in-flight gate. The add is ungated and does not
consume a queued charm cast.

`CONTROLLED` carries per-mob policy: *permanent* (no expiry, never
tick-pruned, manual-drop only) vs *timed* (the 99-game-minute charm cap),
plus a `supersedes` field (the warg removes one existing enslaved shadow
via `_remove_first_by_name`).

Permanent entries carry no `expires_at`; the existing
`if e.expires_at and …` guards in `_charms_tick` and `_load_active`
already skip them. The tick is armed only when a timed entry exists.

The wood elf's in-game leave line drops it immediately
(`_control_on_left`); its 99-minute cap is demoted to a safety ceiling
for a missed line.

## Consequences

- Controlled mobs reuse the entire charm data / render / persistence /
  drop machinery; only an add path and a name table are new.
- One matcher handles every follow line — no overlapping triggers, no
  priority race.
- Permanent entries live until manual drop and survive reconnect/restart.
- The buffs pane shows no count-up minutes for permanent entries; a
  count-up to the cap would falsely imply imminent drop.
- A future controlled mob is a one-line `CONTROLLED` entry (plus a leave
  line if it has one).

## Alternatives considered

**Separate per-mob `#action` triggers at band-4 priority (ADR 0115).**
The generic follow line drops to priority 4 so the specific follow
matchers win the single-fire slot. This works and is idiomatic (the same
shape as `cp -X` vs bare `cp`), but it leaves two triggers matching the
same line and relies on the priority band for determinism. Rejected in
favour of removing the overlap entirely — one matcher, Lua dispatch —
matching the "avoid the race by design" approach in `docs/events.md` and
keeping policy in one Lua table.

**A separate controlled-followers module.** Rejected: the add path needs
charm's locals (`_next_id`, `_save_active`, `state.char.charms`); a
separate file would force exposing them, adding cross-file coupling for
an otherwise charm-internal feature.

**Permanent entries with a sentinel huge `expires_at`.** Rejected:
nil-expiry is already handled cleanly by the tick/load guards and is
unambiguous; a sentinel would invite off-by-one count-up rendering.

**Drop the wood elf only at the cap (no leave line).** Rejected once the
leave line was found — it is the true expiry; the cap stays only as a
safety net.

## Relation to other ADRs

- Builds on the charm tracker (`docs/charm.md`) and the shared cast FIFO
  (ADR 0123), which controlled mobs deliberately bypass.
- Chooses the single-matcher path over the band-4 arrangement of ADR
  0115; cites 0115 for the single-fire rule that motivated the choice.
- Mirrors ADR 0027's "in-game drop is primary, timer is a safety ceiling"
  for the wood elf.
- Anchored patterns per ADR 0026.
