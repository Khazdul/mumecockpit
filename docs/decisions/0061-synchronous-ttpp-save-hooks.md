# 0061 — Synchronous tt++ event hooks as profile-save points

**Status:** Accepted
**Date:** 2026-05-11

Supersedes [ADR 0060](0060-disconnect-dispatch-canonical-save.md).

## Context

ADR 0060 moved the canonical profile-save point into
`mark_mume_disconnected()` in `lua/brain/connection.lua`, on the
reasoning that the Lua dispatch point was the single funnel for all
disconnect signals (per ADR 0058) and therefore the natural place to
hook the save. The implementation called
`tintin_cmd("gts", "_save_profile")` immediately after the transition
guard.

That dispatch is asynchronous. `tintin_cmd` writes a relay file
(`bridge/ipc/cmd_N.tin`) that tt++ subsequently `#read`s on its own
event loop. There is no ordering guarantee between the relay drain and
any subsequent tt++ action.

The `cp -e` shutdown path exposes the resulting race:

1. User runs `cp -e`.
2. `cp -e` issues `#$game_session #zap`, which fires SESSION
   DISCONNECTED.
3. SESSION DISCONNECTED runs `#lua {clear_game_session("%0")}`, which
   calls `mark_mume_disconnected()`.
4. `mark_mume_disconnected()` queues `_save_profile` via the relay.
5. `cp -e` continues with `#zap` (its own gts zap).
6. tt++ exits before — or while — the relayed `_save_profile` is
   read. By the time the relay is processed (if at all), the game
   session class no longer exists. `#$_profile { #class {$_profile}
   {write} … }` dispatches to a dead session, falls through to gts
   where no matching class exists, and `#class write` produces no
   output. `sanitize_profile.sh` then strips the (empty) wrapping
   and leaves a 0-byte file on disk.

The same failure mode applies to MMapper-mode graceful `quit`: the
relay was the only save path for that scenario, and async timing
produced empty writes under load.

Confirmed by user reproduction: both `cp -e` and game-side `quit`
in MMapper mode resulted in empty profile files.

## Decision

Move all disconnect-time saves back to **synchronous tt++ event hooks
that fire while the game session class is still alive**. Drop the
Lua-relay save entirely. `mark_mume_disconnected()` reverts to its
pre-0060 role: popup auto-open, `run_ending` emit, state teardown.
It no longer carries a save responsibility.

Four save points, all synchronous, all calling the shared
`_save_profile` helper:

1. **`cp -s`** — user-triggered, popup Save button. Unchanged from
   ADR 0060.

2. **`cp -e`** — runs `_save_profile` inline, before its
   `#$game_session #zap` step. Restores the pre-0060 explicit save,
   now via the shared helper rather than duplicating the body.

3. **SESSION DEACTIVATED handler** (in `ttpp/core/system.tin`, runs in
   gts) — fires `_save_profile` on every game-session deactivation.
   Covers manual `#zap` from gts, the zap step of `cp -e`, and the
   direct-mode `SESSION DISCONNECTED → #session {gts}` chain that
   deactivates the game session on its way out.

4. **MMapper text action** (`Status: MUME closed the connection.`,
   registered against the game session by SESSION CONNECTED) — fires
   `_save_profile` and then `#lua {mark_mume_disconnected()}`. The
   save runs first, while the session class is still alive. The Lua
   call still handles popup auto-open and state teardown. Closes the
   MMapper-mode gap where SESSION DEACTIVATED never fires because the
   tt++↔MMapper socket stays alive across MUME disconnects.

`_save_profile` itself is unchanged from ADR 0060 — still the single
definition of the `#class write` + `sanitize_profile.sh` body in
`ttpp/core/system.tin`, still no-ops when `$_profile` is empty.

## Consequences

- **Empty-file regression fixed.** Every save now runs against a live
  session class. `cp -e` and MMapper-mode `quit` produce non-empty,
  well-formed profile files.
- **Coverage matrix unchanged from ADR 0060's intent.** All four
  graceful exit paths — `cp -s`, `cp -e`, direct-mode disconnect,
  MMapper-mode disconnect — save. The mechanism is just different.
- **Save responsibility leaves Lua.** `mark_mume_disconnected()` is
  now purely a state-teardown / UX function. Its single-dispatch-point
  discipline (ADR 0058) still holds for popup auto-open and run-state
  reset; it just no longer doubles as the save funnel.
- **Two-place sync, not one.** The save logic now lives at four call
  sites instead of one. Mitigated by `_save_profile` being the only
  place the save *body* is defined — adding a new save point is a
  one-line `_save_profile;` call. Removing or modifying the save
  sequence still touches only the helper.
- **Crash / SIGKILL / terminal close remain uncovered.** All four
  save points require a live tt++ event loop. A killed process or
  closed terminal bypasses every path. Periodic auto-save remains
  parked as a separate Phase 2 axis (see `docs/session-lifecycle.md`
  — "Possible future: periodic auto-save").
- **`reconnect` cycles still save.** The MMapper-mode `reconnect`
  alias issues `_disconnect`, which triggers the MMapper text action
  and so saves. The direct-mode `reconnect` `#zap`s, which triggers
  SESSION DEACTIVATED and so saves. The user-reconnect sentinel
  (ADR 0058) only suppresses popup auto-open in
  `mark_mume_disconnected()`; the save runs independently.

## Alternatives considered

**Keep the Lua relay but force synchronous draining before `#zap`.**
Possible in principle (e.g. a `tintin()` flush call followed by a
delay), but introduces timing fragility for no real benefit — the
problem is precisely that the save and the zap race, and any
synchronization primitive added in Lua is weaker than just having
the save in tt++ in the first place.

**Hook only the MMapper text action; keep `mark_mume_disconnected()`
as the canonical save for everything else.** Rejected: the original
0060 design point — funnel everything through Lua — is what produced
the race in `cp -e`. Splitting save responsibility between Lua and
tt++ would mean *some* disconnects race and *others* don't, which is
harder to reason about than "all saves are synchronous tt++".

**Schedule periodic save and remove disconnect-driven save
entirely.** Rejected for the same reason as in ADR 0060: a timer
bounds worst-case loss but doesn't guarantee a save at the moment
the user expects one. Periodic save remains parked as a complementary
future axis, not a replacement.

## Relation to other ADRs

- **Supersedes ADR 0060.** Reverses the "save in Lua dispatch point"
  decision; keeps the `_save_profile` helper and the structure of
  SESSION DEACTIVATED + `cp -s` introduced there.
- **Independent of ADR 0058** (single dispatch point for disconnect
  signals). `mark_mume_disconnected()` remains the single funnel for
  popup auto-open and state teardown — that part of 0058 is
  unaffected.
- **Independent of ADR 0014.** The system-owned auto-save model
  introduced there is still in force; this ADR just moves the hook
  set back into tt++ where 0014 originally placed it.
