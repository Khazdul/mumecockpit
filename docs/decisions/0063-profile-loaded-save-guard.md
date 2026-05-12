# 0063 — `_profile_loaded` guard on profile auto-save

**Status:** Accepted
**Date:** 2026-05-12

Extends [ADR 0061](0061-synchronous-ttpp-save-hooks.md).

## Context

ADR 0061 moved profile auto-save back into synchronous tt++ event
hooks (`cp -s`, `cp -e`, SESSION DEACTIVATED, the MMapper text
action). That fix closed the async-timing race in which a relayed
`_save_profile` ran against an already-zapped session and produced
an empty file.

A second, independent failure mode remained, surfaced by user
reproduction: a **failed connect** still wipes the profile.

Sequence:

1. User runs `connect` against an unreachable port (e.g. MMapper not
   running, wrong host).
2. tt++ opens the session — SESSION CONNECTED *does not fire* for the
   pre-connect bootstrap, but the session class is created empty by
   the time the connect fails. (In MMapper mode `_connect` opens a
   tt++↔MMapper socket immediately; the MUME-side connect can fail
   after that point.)
3. Connection fails. The session deactivates / disconnects without
   the SESSION CONNECTED body — and therefore without the profile
   `#read` — ever running.
4. SESSION DEACTIVATED (and, in MMapper mode, the text action) fires
   `_save_profile`.
5. `_save_profile` calls `#class {$_profile} {write}` against a class
   that exists but is empty.
6. The resulting file contains only `#class write`'s wrapping;
   `sanitize_profile.sh` strips the wrapping, leaving a 0-byte file.

The user's on-disk profile is destroyed.

This mode pre-existed ADR 0061 but was partly masked by the inline
`#class write` in the old `cp -e` path having the same flaw — exposure
increased once more paths routed through SESSION DEACTIVATED and the
shared `_save_profile` helper.

## Decision

Add a load-state flag `_profile_loaded` (in gts) and gate
`_save_profile` on it:

```
#alias {_save_profile} {
    #gts {
        #if {"$_profile" != "" && $_profile_loaded} {
            ...
        }
    }
}
```

The flag is:

- **Initialized to 0** at tt++ startup, alongside `_zapping_intruder`
  in `ttpp/core/system.tin`.
- **Set to 1** at the end of the SESSION CONNECTED load sequence —
  after the final `#%0 #class {%0} {open}` step that re-opens the
  class for runtime capture. Reaching that line means the profile
  `#read` completed and the class is populated.
- **Cleared back to 0** in both SESSION DISCONNECTED and SESSION
  TIMED OUT handlers — placed *after* `#session {gts}` and *before*
  `#lua {clear_game_session("%0")}`.

Ordering of the clear is load-bearing: the `#session {gts}` step
deactivates the game session, which triggers the SESSION DEACTIVATED
handler synchronously. That handler must still see
`_profile_loaded == 1` so the final save runs. Clearing the flag
before `#session {gts}` would suppress the legitimate disconnect
save.

The flag lives in gts (top-level `#var`, no `#%0` prefix) so
`_save_profile` — which runs inside `#gts { ... }` — can read it
regardless of which session deactivated.

## Consequences

- **Failed-connect protection.** A connect that never completes the
  SESSION CONNECTED body cannot wipe the on-disk profile. The session
  deactivates with `_profile_loaded == 0`; `_save_profile` no-ops.
- **No effect on the happy path.** Every documented save site (`cp -s`,
  `cp -e`, SESSION DEACTIVATED after a real session, the MMapper text
  action) runs while `_profile_loaded == 1`. The flag's existence is
  invisible to all four.
- **One more piece of session-tracked state.** Joins `$game_session`,
  `_zapping_intruder`, and the connection-state file as flags that
  track session liveness. The set is small and the lifecycle of this
  one mirrors `$game_session` exactly — set on CONNECTED, cleared on
  DISCONNECTED / TIMED OUT.

## Alternatives considered

**Detect empty class inside `_save_profile`** (`#info {classes}` /
size check). Possible but brittle — `#info` output parsing is fragile,
and "empty" is ambiguous (a profile with only a comment-marker would
look empty too). A binary loaded/not-loaded flag is unambiguous.

**Skip save when the disconnect happens "too fast" after connect**
(time-based heuristic). Wrong shape — the real predicate is "did the
profile content reach the class", not "how long did the session
live". A heuristic would either over-save (writing empty files when
the connect succeeded but the user disconnected immediately) or
under-save (losing real edits on a short legitimate session).

**Always write through a temp file and refuse to replace a non-empty
file with an empty one** (defence at the sanitizer layer). Useful as
a separate hardening, but it conflates "the profile is intentionally
empty" with "the save was bogus". The right fix is upstream — don't
issue the bogus `#class write` in the first place — and `_profile_loaded`
addresses that directly.

## Relation to other ADRs

- **Extends ADR 0061.** Same call sites, same `_save_profile` body;
  this ADR adds a precondition. The async-timing fix and the
  empty-class fix are independent but compose cleanly.
- **Independent of ADR 0058** (single dispatch point for disconnect
  signals). `mark_mume_disconnected()` is unchanged. The flag lives
  entirely in tt++.
- **Independent of ADR 0042** (blank profile template). The template
  guarantees the *seed* file is non-empty; this ADR guarantees the
  *runtime save* never overwrites a populated on-disk file with empty
  content.
