# 0139 — Group-pane display filter is renderer-side

**Status:** Accepted
**Date:** 2026-06-16

## Context

The `Options → Panes → Group` controls — **Show players** (ON / OFF) and
**NPC visibility** (Off / Labeled) — needed a home in the data flow.

[ADR 0094](0094-labeled-npcs-in-group.md) established that
`state.group.members` is the canonical renderable set: anything in it is
meant to appear, and "the pane does not filter." That was the right design
when there was no display preference — every member in the collector's set
should be drawn. The new controls introduce a per-user display preference,
so something now has to decide which subset of `members` to draw.

## Decision

The **renderer** applies the user display filter; the collector is
untouched. `bridge/panes/group_pane.py` adds `_displayed_members()`, driven
by the two `startup.conf` keys `group_show_players` / `group_npc_mode`
(read live via `_read_display_options()` on the pane's poll):

- `type == "ally"` — kept iff players are on;
- `type == "npc"` — kept iff NPC mode is not `off`;
- any other / unknown type — kept (defensive parity with the collector).

The collector's membership decision (ADR 0094 / 0095) is unchanged:
`state.group.members` stays the canonical membership set, and the serialised
`members` list in `bridge/runtime/group.state` is unchanged. The displayed
set is a pure renderer-side subset of `members`. **No Lua / state-file
change.**

## Consequences

- Members-keyed consumers (the run-log `group_changed` composition, the
  mercenary / charm logic) are unaffected — `members` and its events are
  untouched.
- The displayed set is no longer identical to `members`; consumers that
  want the canonical roster must read `members`, not what the pane shows.
- Live application: the pane re-reads `startup.conf` on its poll, so a popup
  change shows within a tick — no restart.
- Sets up the later `all` mode, which will feed unlabeled group-NPCs via a
  separate serialised list rather than polluting `members` — its own ADR.

## Alternatives considered

**(a) Filter in the collector's membership predicate (`_classify` reading
the conf).** Rejected: it couples a display preference to membership.
"Players: OFF" would drop allies from `state.group.members`, changing
run-log composition and any members-keyed consumer; mid-session toggles
would emit spurious `group_member_added` / `group_member_removed` and write
bogus join / leave run-log rows.

**(b) A separate displayed-members serialisation already in this step.**
Rejected as premature: this step's filtering is a pure subset of `members`,
so the renderer needs no extra data. The separate list is only justified
once `all` mode needs data not present in `members`.

## Relation

Revises the "the pane does not filter" note in
[ADR 0094](0094-labeled-npcs-in-group.md): that line describes 0094's
original no-preference design, and the renderer now applies a user display
filter. 0094's labeled-NPC membership decision stands; 0095 and 0096 are
untouched. (Note + status-line cross-ref modelled on the
ADR 0010 ← 0129 precedent.)
