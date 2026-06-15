# 0140 — Unlabeled group-NPCs for the `all` display mode

**Status:** Accepted
**Date:** 2026-06-16

## Context

[ADR 0139](0139-group-pane-display-filter-renderer-side.md) added the
renderer-side display filter to the group pane — **Show players** (ON / OFF)
and **NPC visibility** (Off / Labeled) — drawing a subset of
`state.group.members` without touching the collector or the state file. The
third NPC-visibility stop, **All**, needs to show unlabeled group-NPCs —
charmies, pets, mounts, not-yet-labeled mercenaries.

Those members are not in `state.group.members`. [ADR 0094](0094-labeled-npcs-in-group.md)
and [ADR 0095](0095-promote-demote-npcs-on-label-change.md) deliberately keep
unlabeled `type:"npc"` entries in a file-local `_excluded` holding table,
off the `state.group` surface, so the canonical member set stays clean.
ADR 0095 further made an excluded-only `Group.Remove` **silent** (no events)
because nothing observable changed. `all` mode makes that holding table
observable, so both of those decisions need a narrow, deliberate revision.

## Decision

1. **Expose `_excluded` read-only as `state.group.unlabeled`** — a plain
   alias of the holding table. This is safe because `_excluded` is mutated
   in place and never reassigned (`reset()` clears it in place), so the alias
   never goes stale. It is **not** a membership set.
2. **`group_state.lua` serialises it as a separate top-level
   `unlabeled_npcs` array** — same per-member projection as `members` (via
   the shared `serialize_member` / `serialize_set`), id-sorted, **never
   merged into `members`**.
3. **The renderer appends it to the displayed set only when
   `group_npc_mode == "all"`** — `_displayed_members()` extends the displayed
   members with the loaded `unlabeled_npcs`, then id-sorts the combined set so
   members and unlabeled NPCs interleave. Unlabeled NPCs render as the bare
   `name` (they have no label).
4. **An excluded-only `Group.Remove` now fires `group_changed`** — and so do
   excluded-set adds and in-place vital updates — so the serialised
   `unlabeled_npcs` stays fresh. This reverses ADR 0095's silence for that
   case. **No membership event** is emitted for it; `members` and its
   membership events are untouched.

## Consequences

- `all` shows charmies / pets / mounts / unlabeled mercenaries live — vital
  ticks, room join / leave — with no full re-sync.
- Members-keyed consumers are unaffected: membership events still fire only
  for `members`, and run-log composition filters to `type == "ally"`, so
  unlabeled NPCs never reach the run-log.
- Cost: excluded-set changes now re-serialise `group.state` even when `all`
  is off. The Lua side is deliberately toggle-agnostic (the renderer gates
  display), which is the same cost class as the existing member-vital
  re-serialisation and preserves the layer discipline ADR 0139 established —
  the collector never reads a display preference.
- `state.group.unlabeled` is **read-only by contract**: non-pane consumers
  must keep ignoring it.

## Alternatives considered

**(a) Merge unlabeled NPCs into `state.group.members` for `all`.** Rejected:
it pollutes the canonical set; the run-log and every members-keyed consumer
would see them. This is exactly the "include everything / filter at the
renderer" design rejected by ADR 0094 / 0095.

**(b) A parallel membership-event pipeline for unlabeled NPCs
(`group_npc_added` / …).** Rejected for ADR 0095(a)'s reasons — two pipelines,
double the vital-pair freshness surface. `unlabeled` is a passive holding
table serialised for display, with no new membership events, so this is not
that rejected design.

**(c) Gate the Lua serialisation / eventing on whether `all` is active.**
Rejected: it couples the collector to a display preference — the coupling
ADR 0139 explicitly avoided. The renderer gates display; the Lua side stays
toggle-agnostic.

## Relation

Builds on [ADR 0139](0139-group-pane-display-filter-renderer-side.md). Revises
[ADR 0095](0095-promote-demote-npcs-on-label-change.md) on two points:
`_excluded` is now exposed read-only as `state.group.unlabeled`, and an
excluded-only `Group.Remove` is no longer silent. ADR 0095's promote / demote
membership logic and the [ADR 0094](0094-labeled-npcs-in-group.md)
labeled / unlabeled split are unchanged. (The 0095 dated note + status-line
cross-ref are modelled on the ADR 0094 ← 0139 precedent.)
</content>
</invoke>
