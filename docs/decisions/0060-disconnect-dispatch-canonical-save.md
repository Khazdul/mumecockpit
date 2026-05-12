# 0060 — Disconnect dispatch as canonical profile-save point

**Status:** Superseded by [ADR 0064](0064-per-session-state-owns-save.md) (via [ADR 0061](0061-synchronous-ttpp-save-hooks.md))
**Date:** 2026-05-11

Supersedes the auto-save mechanism in ADR 0014.

> **Superseded 2026-05-11.** Routing the save through
> `tintin_cmd("gts", "_save_profile")` from `mark_mume_disconnected()`
> is async: tt++ may process the relay after `cp -e` has zapped the
> game session, at which point `#class write` dispatches to a dead
> session and the on-disk profile becomes a 0-byte file. ADR 0061
> reverses the design — saves move back to synchronous tt++ event hooks
> (cp -e, SESSION DEACTIVATED, MMapper text action) that all run while
> the session class is still alive.

## Context

ADR 0014 placed profile auto-save in two layers: a global SESSION
DEACTIVATED handler in `system.tin`, plus an inline save in `cp -e` as
defense in depth. That model has a gap in MMapper mode.

In MMapper mode the tt++↔MMapper socket stays alive across MUME
disconnects. The game-side tt++ session is not deactivated on a
graceful `quit` in-game or on an abrupt MUME-side drop that MMapper
detects but absorbs. SESSION DEACTIVATED therefore never fires, and
auto-save is missed for the entire class of "player ends the run by
quitting from the game" disconnects. Direct mode is unaffected because
its SESSION DISCONNECTED handler's `#session {gts}` step deactivates
the game session on its way out, which does trigger DEACTIVATED.

The asymmetry between modes is a structural property of where the
save signal lives. SESSION DEACTIVATED is a tt++-session-focus event;
the user-visible "I just disconnected" event is owned by
`mark_mume_disconnected()` in `lua/brain/connection.lua` (ADR 0058 /
the single-dispatch-point discipline). All disconnect signals already
funnel through `mark_mume_disconnected()`: `Core.Goodbye` GMCP, the
MMapper "MUME closed the connection." text trigger, and SESSION
DISCONNECTED via `clear_game_session()`. That is the right place to
attach the canonical save.

## Decision

Move the canonical profile-save point into
`mark_mume_disconnected()`, which fires `_save_profile` via the relay
(`tintin_cmd("gts", "_save_profile")`) immediately after the
transition guard and before any state teardown. The save runs once
per real connected→disconnected transition, in both modes, regardless
of which tt++ session is focused.

Three supporting changes:

1. **`_save_profile` helper alias in `ttpp/core/system.tin`.** Single
   definition of the `#class write` + `sanitize_profile.sh` body. Safe
   to call from any session context (internal `#gts`) and no-ops when
   no profile is loaded.

2. **`cp -s` and SESSION DEACTIVATED delegate to `_save_profile`.**
   `cp -s` retains its `system_ui` confirmation and `$_profile`-empty
   error path. SESSION DEACTIVATED is kept as defense-in-depth for
   the rare paths that deactivate the game session without going
   through `mark_mume_disconnected()` (e.g. a manual `#zap` of the
   game session from gts).

3. **`cp -e` drops its inline save block.** The remaining
   `#$game_session #zap` step in `cp -e` triggers SESSION DISCONNECTED
   → `clear_game_session()` → `mark_mume_disconnected()`, which now
   runs `_save_profile`. The inline duplicate added maintenance burden
   without buying coverage that the dispatch chain didn't already
   provide.

## Consequences

- **MMapper-mode gap closed.** Quitting in-game (or any abrupt
  MUME-side drop in MMapper mode) now auto-saves the profile via
  `Core.Goodbye` / the MMapper text trigger.
- **One save per disconnect transition in most cases.** Both modes
  hit `mark_mume_disconnected()` first; the transition guard makes
  any follow-up signal a no-op. Direct-mode disconnects redundantly
  fire SESSION DEACTIVATED as well; the second `_save_profile` is
  idempotent (same bytes to the same file, then a same-file
  sanitize). Harmless.
- **User-reconnect cycles now also save.** The `reconnect` alias
  deliberately produces a transient disconnect signal before the
  follow-up connect (ADR 0058). That signal now triggers
  `_save_profile`, adding ~1 extra profile write per user-initiated
  reconnect. The sentinel-suppressed popup-open path from ADR 0058
  is unaffected — the save runs before the popup decision.
- **The gts-modification limitation narrows.** ADR 0014 noted that
  settings modified from gts (e.g. `#mume #alias {...}` issued
  outside the game session) were lost if the user exited without
  refocusing the session. With the canonical save running from Lua
  on disconnect — not session-focus-dependent — changes made from
  gts *while connected* are now saved on the next disconnect. The
  residual gap is changes made from gts *after* disconnect, when no
  session class exists to serialise.
- **Crash / SIGKILL still uncovered.** PROGRAM TERMINATION cannot
  save (sessions already torn down); a SIGKILL or terminal close
  bypasses both paths. Periodic auto-save remains a separate Phase 2
  axis (see `docs/session-lifecycle.md` — "Possible future: periodic
  auto-save").
- **Two-place sync remains light.** The `_save_profile` body is the
  one place the save sequence is defined. Any future change to the
  save (e.g. compression, distinct path) touches only that alias.

## Alternatives considered

**Periodic save alone.** Replace the disconnect-driven save with a
recurring Lua timer that writes every N seconds. Rejected: a timer
bounds worst-case data loss but does not guarantee a save at the
exact moment the user expects one (the disconnect itself). The
disconnect-driven save is cheap and gives the strong guarantee
without precluding a periodic save as a separate, complementary axis.

**Explicit save calls at each GMCP / text-trigger site.** Wire
`_save_profile` into the `Core.Goodbye` handler, the MMapper text
trigger handler, and SESSION DISCONNECTED individually. Rejected:
spreads the save logic across files and re-introduces the asymmetry
the single-dispatch-point discipline (ADR 0058) was designed to
eliminate. Hooking the dispatch point itself is strictly cleaner.

**Keep `cp -e`'s inline save as belt-and-braces.** The inline save
was already redundant with the SESSION DEACTIVATED handler and is
now triply redundant once `mark_mume_disconnected()` covers the same
path. Defense in depth is valuable when the underlying mechanism is
fragile; here the dispatch-point proof is sufficient and the inline
duplicate adds maintenance burden (one more place to keep
$game_session vs $_profile straight, one more place to update if the
save sequence changes).

## Relation to other ADRs

- **Supersedes ADR 0014** (system-owned profile auto-save on session
  deactivation). 0014 introduced system ownership and the
  SESSION DEACTIVATED handler; this ADR keeps that handler as
  defense-in-depth but moves the canonical save out of it. ADR 0014
  is left in place for historical context — read 0014 first for the
  original problem statement, then this ADR for the current model.
- **Builds on ADR 0058** (single dispatch point for disconnect
  signals). `mark_mume_disconnected()` was already the funnel for
  popup auto-open and state teardown; attaching the save there is a
  direct extension of the same discipline.
- **Independent of ADR 0049** (per-session capture state outside the
  profile class) and ADR 0050 (synchronous nested actions with class
  discipline). The save still writes only the `{<profile>}` class;
  `{core}` is unaffected.
