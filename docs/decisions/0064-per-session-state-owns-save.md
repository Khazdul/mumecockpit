# 0064 — Per-session state owns its own save

**Status:** Accepted
**Date:** 2026-05-12

Supersedes [ADR 0060](0060-disconnect-dispatch-canonical-save.md).
Refines [ADR 0061](0061-synchronous-ttpp-save-hooks.md) and
[ADR 0063](0063-profile-loaded-save-guard.md).

## Context

Two consecutive save-bug iterations both traced back to the same
root cause: trying to orchestrate per-session state from gts.

**Round 1 (ADR 0060 → 0061).** ADR 0060 routed the canonical save
through `mark_mume_disconnected()` in Lua, which queued
`_save_profile` via the async relay. On `cp -e` the relay drained
*after* the game session had been zapped, so `#class write`
dispatched into the void and the on-disk profile became a 0-byte
file. ADR 0061 reverted to synchronous tt++ save hooks (cp -s,
cp -e, SESSION DEACTIVATED, the MMapper text action).

**Round 2 (ADR 0063 → this ADR).** ADR 0063 added a
`_profile_loaded` guard so a failed connect couldn't overwrite a
populated profile with an empty class. The guard was placed in gts
on the reasoning that `_save_profile` ran inside `#gts { ... }` (a
holdover from 0060's helper structure).

That reasoning was wrong. SESSION events fire in the triggering
session's context, so `#var {_profile_loaded} {1}` in SESSION
CONNECTED landed in the *session's* scope, not gts. Meanwhile
`cp -s` wrapped its body in `#gts { ... }` and called
`_save_profile` from gts, where `$_profile_loaded` resolved to the
gts startup value (0). The guard silently blocked every save —
while the `#lua {system_ui(...)}` confirmation line emitted
"Profile saved" anyway, lying about success.

Two fixes were on the table:

(a) Force `_profile_loaded` into gts via `#gts #var` so the
existing structure works.

(b) Embrace the fact that *all* save call sites already run in
session context — input pane, popup `tmux send-keys` (focused on
the cockpit pane → game session), SESSION DEACTIVATED event body,
MMapper text action body — and drop the gts indirection entirely.

(a) patches around the wrong premise. The same gotcha re-emerges
any time a new per-session flag is added or a new save call site
is introduced from a different context.

(b) removes the indirection that caused the bug class in the first
place. The session owns the class, the flag, and the operations
on them. gts is reserved for cross-session coordination.

## Decision

**Per-session state is owned by the session.** The profile class,
the `_profile_loaded` flag, and any future session-class-resident
variable (affect history, run state, capture buffers, etc.) live
in the session that owns them. Operations on that state — read,
write, mutate, serialize — run in the session.

**`_save_profile` is session-context-only by design.** Its body is
a direct `#if` block:

```
#alias {_save_profile} {
    #if {"$_profile" != "" && $_profile_loaded} {
        #class {$_profile} {write} {ttpp/profiles/$_profile.tin};
        #system {bash $HOME/MUME/bridge/release/sanitize_profile.sh ttpp/profiles/$_profile.tin}
    }
}
```

No `#gts {...}` wrapper. No `#$_profile {...}` dispatch. No
cross-session indirection of any kind.

**Call-site invariant.** Every `_save_profile` invocation must
execute in the session whose class is being written:

- `cp -s` — runs in the session the input pane is focused on
  (game session in normal use). The `#gts` wrapper that used to
  surround its body is removed.
- `cp -e` — `_save_profile` is invoked *before* the `#gts;` step.
- SESSION DEACTIVATED — event body runs in the deactivating
  session.
- MMapper text action — registered against the game session,
  fires in that session.
- Popup Save button — sends `cp -s` via `tmux send-keys` to the
  cockpit pane, which is focused on the game session.

**`_profile_loaded` lifecycle stays in the session.** Set to `1`
at the end of the SESSION CONNECTED load sequence (no `#gts`
prefix), cleared back to `0` in SESSION DISCONNECTED and SESSION
TIMED OUT (also no prefix). The gts startup-init of the flag is
removed as dead code — gts's flag is never read under the new
model.

**gts is reserved for cross-session coordination.** The existing
`_zapping_intruder` single-session-enforcement flow, the
`$game_session` tracking variable, and `cp -e`'s shutdown
orchestration (zap-game-then-zap-gts) all remain in gts. That is
gts's actual role: coordination across sessions, not orchestration
of per-session work.

## Consequences

- **Save logic is direct.** `#class write` + sanitize, executed
  locally. No cross-session dispatch, no relay timing, no
  substitution-timing gotchas around `#$session {...}`.
- **The bug class is closed by construction.** The shape of the
  helper — flat `#if` body, no session prefix — makes it
  syntactically impossible to call from the wrong context without
  it silently no-opping. The no-op is the documented behaviour and
  the guard is doing its job; the bug was elsewhere (the silent
  emission of a misleading `system_ui` line from `cp -s`'s
  gts-wrapped body).
- **Future per-session state inherits the principle.** Any new
  state that lives in the session class — affect history, run
  state, capture buffers — gets serialised the same way: a
  session-context-only helper, called from session-context call
  sites, no gts indirection.
- **Residual edge case (documented, not defended).** An explicit
  `#gts; cp -s` from the input pane skips the actual save (guard
  fails in gts) while still emitting the "Profile saved"
  `system_ui` line. The normal popup and bare `cp -s` paths are
  unaffected. Tightening this would require either (i) restoring
  the wrong-direction `#gts` wrapper and re-introducing the bug
  class above, or (ii) a runtime check that the current session
  matches `$_profile`, which adds complexity for a path no user
  would take by accident.
- **Coverage matrix unchanged.** All four documented graceful
  save paths (cp -s, cp -e, SESSION DEACTIVATED, MMapper text
  action) still save. ADR 0061's synchronous-save guarantee and
  ADR 0063's failed-connect protection both hold.

## Alternatives considered

**Force `_profile_loaded` into gts via `#gts #var`.** Make the
flag a gts variable explicitly, keep `_save_profile`'s `#gts {...}`
wrapper, keep `cp -s`'s wrapper. The existing structure then
"works" because both the writer and the reader live in gts.

Rejected. This patches around the wrong premise. The flag describes
*session* state — whether *this session's* class has been
populated — and forcing it into gts pretends one session's load
state is global. The same gotcha re-emerges any time a new
per-session flag is added (the developer correctly puts it in the
session, calls a gts-wrapped helper, and the flag silently fails to
read). It also leaves a bigger design wart in place: per-session
work being orchestrated from gts.

**Keep the Lua-side relay save for closing the MMapper-mode gap.**
Use `tintin_cmd("<game_session>", "_save_profile")` from
`mark_mume_disconnected()` instead of the synchronous MMapper text
action. Rejected by ADR 0061 already (async timing vs `cp -e`
zap). Not revisited here.

**Inline the save body at each call site.** Skip the
`_save_profile` helper entirely; write `#class write` +
`sanitize_profile.sh` at each of the four call sites. Rejected for
the same reason ADR 0061 introduced the helper: a single definition
keeps the save sequence (write + sanitize order, paths, flags) in
one place when it inevitably needs to change again.

## Relation to other ADRs

- **Supersedes ADR 0060** — formally retires the
  "save in Lua dispatch point" design. ADR 0060 was already marked
  superseded by 0061; this ADR replaces it as the canonical
  reference for *why* the save lives where it does (the per-session
  ownership principle), not just *that* it lives in tt++.
- **Refines ADR 0061** — same four call sites, same synchronous
  hooks, same shared helper. This ADR formalises the call-site
  invariant that 0061 implicitly relied on but did not state.
- **Refines ADR 0063** — same `_profile_loaded` guard, same set/
  clear lifecycle. This ADR corrects the misstatement in 0063 that
  the flag lives in gts; it lives in the session, and the guard
  works because every call site runs in session context.
- **Independent of ADR 0058** — `mark_mume_disconnected()`
  remains the single dispatch point for popup auto-open and state
  teardown; that role is unaffected.
