# 0096 — GMCP group membership is room-scoped

**Status:** Accepted
**Date:** 2026-05-23

## Context

The GMCP `Group.*` messages were initially treated as if they tracked
the player's full group roster: a `Group.Set` at login, `Group.Add` /
`Group.Remove` for join / leave, and `Group.Update` for vital changes
in between. That mental model matches how a chat-style "who's in your
party" sidebar would work and is what most consumers (the group pane,
the mercenary script, the run-log composition tracker) initially
assumed.

Empirically, MUME's `Group.*` traffic does not work that way. The
server only reflects the subset of the group that is in the same room
as the player:

- When a group member walks into a different room from the player,
  the server sends `Group.Remove` for that member's id — even though
  the group bond is intact and the member is still alive and grouped.
- When the member returns (or the player follows), the server sends
  `Group.Add` with a **new id**, not the original one. The mapping
  "id → identity" is therefore valid only for the current visit; ids
  are reassigned on every re-add.
- This behaviour is uniform across `type:"ally"` (player allies) and
  `type:"npc"` (key NPCs, mercenaries). Confirmed by reading both
  alongside the room-change pattern in active sessions.

The mercenary script made this load-bearing. A hired mercenary that
follows the player will be added / removed dozens of times per run as
the player passes through one-tile rooms. Treating each `Group.Remove`
as "the mercenary's contract ended" would drop the record on the first
room exit and lose the timer state. Treating each `Group.Add` as "this
is a different mercenary" would prevent the script from tying the new
id back to the existing label-keyed record.

Run-log composition (the `group_changed` JSONL row) faces a related
problem: if every room-step causes Group churn, the log would fill
with noise. The run-log accordingly diffs on player-ally composition
only, and even then only on add / remove events.

## Decision

Treat GMCP group ids as **transient presence handles**, not stable
identities. The contract is:

- `Group.Add` / `Group.Set` mean "this member is in your current
  room"; the id is valid only for this presence interval.
- `Group.Remove` means "this member is not in your current room"; it
  is **not** a permanent departure. Consumers that need to know when
  a member actually left the group (or died, or logged out) must get
  that signal from somewhere other than `Group.Remove` alone.
- For consumers needing a stable per-member identity across room
  changes, the key is `label` (for `type:"npc"`) or `name` (for
  `type:"ally"`). Both survive id reassignment.
- A round-trip through the player's room is enough to invalidate any
  cached `id → member` reference. The buffer/opponent cross-apply
  in `group_collector.lua` therefore re-resolves the identity string
  against `state.group.members` on every `*-hits` packet rather than
  caching the resolved member.

For the mercenary script specifically:

- Records are keyed by lowercase label (the stable identity).
- `Group.Add` (re-)binds the transient id back to the record and
  marks `present = true`.
- `Group.Remove` clears `present` and the id; the record stays.
- Removal of the record happens via text triggers (the
  `leaves and goes to seek another employer` line for honest leaves
  and the `mob_death` event for in-room deaths) or the script's
  periodic expiry timer for everything else.

## Consequences

- The group pane reflects the current room, not the abstract roster.
  This matches the player's situational-awareness needs (a member
  out of range can't be healed anyway) and was already the de-facto
  behaviour; ADR 0096 makes the contract explicit so future panes
  don't reinvent a roster view from the same stream.
- The run-log `group_changed` row's existing player-ally-only diff
  is reaffirmed as the right shape: an NPC bouncing in and out of
  the room is presence churn, not group composition change.
- `state.group.members` cannot be used as a roster source. Anything
  that wants "list everyone the player is grouped with, in this room
  or not" must either build that list from another signal (text
  triggers for `group` command output) or accept that it does not
  exist in GMCP form.
- The mercenary script's reliance on text triggers plus an expiry
  timer becomes principled rather than a workaround: GMCP genuinely
  cannot tell us about an out-of-room mercenary's state.

## Limitations

A member who leaves the game (quit, link loss, group disband) while
out of the player's room produces no GMCP signal. For mercenaries the
periodic expiry timer is the only fallback — if the contract was
already due, the merc drops off the panel on the next tick after the
~90 s anchored-expiry threshold; if the contract still had time, the
record persists until expiry and the panel mis-states the merc as
"away" rather than gone. There is no reliable out-of-room detection
within the current GMCP module set; subscribing to `Room.Chars` would
not help because that module is per-room too.

## Alternatives rejected

**(a) Treat ids as stable and ignore `Group.Add` re-assignments.**
The server reassigns ids unilaterally; "ignoring" reassignment means
the next `Group.Update` for the new id has no record to merge into
and the entry is lost. Not a viable read of the wire data.

**(b) Build a parallel roster table from the `group` text command
output.** Requires a synchronous round-trip on every connect (and
periodically), couples the group pane to text parsing that the rest
of the client has been moving away from, and still doesn't tell us
about an out-of-room death without further triggers. Deferred until
there is a concrete pane that needs full-roster data.

**(c) Treat each `Group.Remove` as a departure and re-add as a new
member.** Simpler, but breaks the mercenary timer (records would
reset every room) and produces an `group_changed` JSONL row on every
step for ally-and-NPC mixed groups. Loses the property that
membership events correspond to actual membership changes.
