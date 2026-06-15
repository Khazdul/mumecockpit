# 0094 — Track labeled NPCs in group membership

**Status:** Accepted (v1 limitation superseded by [ADR 0095](0095-promote-demote-npcs-on-label-change.md); display-filter note revised by [ADR 0139](0139-group-pane-display-filter-renderer-side.md))
**Date:** 2026-05-22

## Context

`Group.*` GMCP messages can carry three member types: `"ally"` (player
characters in the group), `"npc"` (key NPCs and hired mercenaries the
character is travelling with), and `"you"` (the character itself, already
fully covered by `Char.*`).

`lua/core/group_collector.lua` previously denied every `"npc"` and `"you"`
entry at merge time, so `state.group.members` contained only allies. This
made labeled NPCs — key NPCs and hired mercenaries that the player wants to
keep alive — invisible in the group pane, even though their HP / mana / moves
arrive over the same GMCP stream as ally vitals.

The server distinguishes these meaningful NPCs from background NPCs by
attaching a non-null `label` field — a player-facing display name (e.g.
the mercenary's given name) overriding the generic `name` (e.g.
`"citizen mercenary"`). Background NPCs with no special significance arrive
without a label.

## Decision

Include `"npc"` members in `state.group.members` when they carry a non-null
`label`. The membership predicate in `group_collector.lua` becomes:

- exclude `type == "you"` unconditionally;
- exclude `type == "npc"` when `label` is `nil` or `gmcp.null`;
- otherwise include.

`ally` handling is unchanged. The `label` field is added to `_field_map`
so it flows through into the member record, into `bridge/runtime/group.state`,
and into the pane renderer. The group pane prefers `label` over `name` when
rendering the row overlay so the player sees the meaningful name
("Aragorn") rather than the generic species string ("citizen mercenary").

`state.group.members` remains the canonical renderable set: anything in it
is meant to appear; the pane does not filter. `Group.Update` and
`Group.Remove` need no logic change — `Group.Update` is keyed by `id` and
only fires on entries already present; `Group.Remove` already silently
ignores ids that aren't in the table.

## Alternatives rejected

**(a) A separate `state.group.npcs` table with parallel events
(`group_npc_added` / `group_npc_updated` / `group_npc_removed`).** Two
parallel pipelines for what is one GMCP module, two consumers in the
renderer, and twice the surface area for vital-pair freshness bugs
(ADR 0052). NPCs and allies share the schema and the rendering — the
distinction is not worth a second pipeline.

**(b) Include every NPC and filter at the renderer.** Breaks the principle
that `state.group.members` is the canonical renderable set (ADR 0052
relies on this for vital-pair consistency). Every future consumer would
need to remember to apply the same filter; one forgetful subscriber would
display background NPCs in the wrong place.

## Consequences

- The group pane shows labeled NPCs alongside allies. Their bars use the
  same threshold colours and vital-pair freshness inference (ADR 0052).
- Background NPCs without labels remain invisible — no clutter.
- `state.group.members` continues to be the single canonical set. The
  predicate lives in one place (`_should_include` in
  `group_collector.lua`).

### v1 limitation: late-labeled NPCs not visible until re-sync

`Group.Update` is partial and does not carry `type`. If the server
labels an already-grouped NPC after the fact (sending only
`{"id":N,"label":"..."}` in an update), the collector currently has no
record of that id (it was excluded at `Group.Set` / `Group.Add` time as
an unlabeled NPC), so the update is ignored — the existing "update for
unknown id" `dbg` line covers it. The NPC will only appear once the next
full `Group.Set` re-sync arrives.

This is accepted for v1 because the trigger for labeling is rare (the
player usually hires or claims the NPC before the group forms, so the
label is present in the initial `Group.Add`), and full re-syncs happen
on every session connect and on most party-composition changes. If
late-labeling turns out to be common, the fix is to also include
unlabeled NPCs in a shadow table (`state.group._pending_npcs`) and
promote them into `members` when an update arrives carrying a non-null
label — deferred until there is evidence the limitation matters.

## 2026-06-16 note

[ADR 0139](0139-group-pane-display-filter-renderer-side.md) adds a
user-controlled display filter to the group pane (Show players / NPC
visibility). The renderer now draws a subset of `state.group.members`, so
"the pane does not filter" above describes this ADR's original
no-preference design. The membership decision is unchanged:
`state.group.members` is still the canonical set, the collector still owns
the predicate, and no Lua / state-file change was made — the filtering is
purely renderer-side.
