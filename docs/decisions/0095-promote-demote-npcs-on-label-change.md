# 0095 — Promote / demote NPCs on label change

**Status:** Accepted
**Date:** 2026-05-23

## Context

[ADR 0094](0094-labeled-npcs-in-group.md) decided to include `type:"npc"`
members in `state.group.members` when they carry a non-null `label`,
keeping the renderable set canonical and pane-filter-free. It also
recorded a v1 limitation: `Group.Update` is partial and does not carry
`type`, so if the server labelled an already-grouped NPC after the fact
(`{"id":N,"label":"..."}`), the collector had no record of that id
(excluded at `Group.Set` / `Group.Add` time) and dropped the update.
The NPC only appeared after the next full `Group.Set` re-sync.

The mercenary script (`lua/scripts/mercenaries.lua`) makes that case
the common case: hire produces a `Group.Add` with `type:"npc"` and no
label, followed almost immediately by the client-issued
`label mercenary <name>` and `group <name>`, which the server reflects
as a `Group.Update` carrying the new label. With v1 behaviour the
mercenary stays invisible until something else triggers a re-sync —
which, given the room-scoped membership model
([ADR 0096](0096-room-scoped-group-membership.md)), is unpredictable.

A second related case fell out of the same machinery: an unlabel
(`label:0`, `null`, or `""` on an `Update` for a current member) should
take the NPC back out of the group pane without leaking a phantom row.

We also wanted the membership-event surface to stay one-event-per-state-
change so subscribers (run-log, pane serializer, mercenary script)
don't need to deduplicate.

## Decision

Excluded NPCs are kept in a file-local `_excluded` holding table inside
`lua/core/group_collector.lua`, parallel to `state.group.members` but
deliberately not part of the `state.group` surface. The renderer and
all other consumers continue to see `state.group.members` only.

`Group.Update` now re-evaluates inclusion after merging:

- **Promote:** if the id was in `_excluded` and the update produced a
  non-empty string `label`, move the member into
  `state.group.members` and emit `group_member_added` (not
  `group_member_updated`).
- **Demote:** if the id was in `state.group.members`, the member is
  `type:"npc"`, and the update cleared the label, move the member back
  into `_excluded` and emit `group_member_removed` (not
  `group_member_updated`).
- **Plain in-place update:** the id was and still is in members — emit
  `group_member_updated` as before.
- **Excluded → excluded:** no membership event.

`group_changed` always fires afterwards, exactly once per packet.

Label normalisation is centralised in a small helper `_norm_label(v)`
that returns the string if it is non-empty and `nil` otherwise. MUME
sends `label:0` (integer) when unlabeled and a non-empty string once
labeled, so the helper folds `0`, `gmcp.null`, `nil`, and `""` to the
same value. After `_project` runs, a member's `label` field is always
either a non-empty string or `nil`.

`Group.Remove` for an id in `_excluded` only is silent — no events
emitted, including no `group_changed` — because no observable state
changed. Removals for ids in neither table are no-ops.

## Consequences

- The "label-after-group needs a Group.Set re-sync" limitation
  documented in ADR 0094 no longer applies; this ADR supersedes that
  limitation. ADR 0094's core decision (include labelled NPCs in the
  canonical member set) is unchanged.
- The mercenary script can hire a citizen mercenary and rely on a
  `group_member_added` event landing within one GMCP round-trip after
  the `label` command, with no re-sync waiting period.
- `_excluded` is invisible to every consumer that reads `state.group`.
  The membership predicate still lives in one place
  (`_classify` in `group_collector.lua`).
- `Group.Update` is now the only place where `group_member_added` /
  `group_member_removed` can fire without an accompanying GMCP packet
  of that intuitive shape (i.e. `Update` can produce an "add" event).
  Subscribers must treat the membership events as authoritative for
  membership rather than inferring it from packet type.

## Alternatives rejected

**(a) Separate `state.group.npcs` table with parallel events
(`group_npc_added` / `group_npc_updated` / `group_npc_removed`).**
Two parallel pipelines for what is one GMCP module, two consumers per
renderer, and twice the surface area for vital-pair freshness bugs
(ADR 0052). NPCs and allies share the schema and the rendering — the
distinction is not worth a second pipeline.

**(b) Include every NPC in `state.group.members` and filter at the
renderer.** Breaks the principle that `state.group.members` is the
canonical renderable set (ADR 0052 relies on this for vital-pair
consistency, and ADR 0094 reaffirmed it). Every future consumer would
need to remember to apply the same filter; one forgetful subscriber
would display background NPCs in the wrong place.

**(c) Keep the v1 limitation and rely on natural re-syncs.** Acceptable
for key NPCs the player encounters rarely, but unworkable for
mercenaries — the hire / label / group sequence is the primary use
case, and a label-after-group race that hides the mercenary
indefinitely is a user-visible regression. The mercenary work made
this no longer hypothetical.
