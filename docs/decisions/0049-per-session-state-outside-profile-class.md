# ADR 0049 — Per-session capture state stays out of the profile class

**Status:** Accepted (amended 2026-05-11)  
**Date:** 2026-05-09

## Context

tt++ session profiles (`ttpp/profiles/<name>.tin`) are written via
`#class {name} {write} {file}` on session deactivation, and re-read
via `#%0 #read ttpp/profiles/%0.tin` on SESSION CONNECTED. The class
file contains all `#var`, `#alias`, `#action`, `#event` etc. that
were registered while the class was open.

When the run-log `.log` capture was first implemented, the
`_register_run_log_capture` alias registered a `#event {RECEIVED LINE}`
handler in the game session, and `_open_log` set `_run_log_path` via
`tintin_cmd`. Both happened while the profile class was open, so
both got persisted to disk on disconnect.

On the next session, profile load restored the persisted state:
- `#var {_run_log_path} {<previous-run-path>}` re-set the variable
  to the path of the *previous* run.
- `#event {RECEIVED LINE} { … #line log $_run_log_path … }` was
  re-parsed during `#class read`, and tt++ substituted
  `$_run_log_path` to its loaded value at parse time. The registered
  event body had the previous path baked in literally, frozen against
  any subsequent var changes.

`_register_run_log_capture` ran later in SESSION CONNECTED but did
not displace the loaded state cleanly: the new `#event` body had
delayed substitution, but the loaded baked-in version coexisted or
won depending on tt++ internals.

The visible symptom was a one-step lag: every run wrote to the
*previous* run's `.log` file. Manual `#showme {$_run_log_path}`
showed the correct current path, but the registered event ignored
it because the path was already baked into the body string.

## Update (2026-05-11): structural fix

The original decision was a workaround at the registration layer:
`#unevent` / `#unvar` before re-register, accepting that the
profile class would still acquire stale state across saves.

The structural fix puts per-session capture state in the `{core}`
class by construction:

- **Lua side.** `_open_log` / `_close_log` register `_run_log_path`
  via `session_cmd()` instead of raw `tintin_cmd(GAME_SESSION, ...)`.
  `session_cmd()` brackets the registration in
  `#class {core} {open}` / `#class {core} {close}`, so the variable
  lands in `{core}`.
- **tt++ side.** `_register_run_log_capture` brackets the
  `#event {RECEIVED LINE}` registration in `#class {core} {open}` /
  `#class {core} {close}`, so the event itself is owned by `{core}`.
  The event body additionally wraps its `#format _ts {%U}` line in
  the same way, so the per-line timestamp variable `_ts` is created
  and updated in `{core}` regardless of which class is active when
  the event fires. `#format _ts {%U}` remains a top-level statement
  in the event body — the wrap is inline, not function indirection,
  so per-fire `%U` freshness is preserved.

Profile auto-save (`#class write {<profile>}`) now correctly
excludes this state because it only serializes profile-class items.
The unset-before-register hygiene survives only as a transitional
safeguard for legacy profile files that already contain baked-in
state from the pre-`{core}` architecture; it can be removed once
all known profiles have been resaved under the new model.

## Decision

Per-session capture state must not persist across tt++ sessions.
The `_register_run_log_capture` alias explicitly clears state before
re-registering:

    #%0 #unevent {RECEIVED LINE};
    #%0 #unvar _run_log_path;
    #%0 #event {RECEIVED LINE} { … }

Each session starts with a known clean slate regardless of what the
profile class restored. The fresh `#event` body uses `$_run_log_path`
with delayed substitution; since the var is unset at registration
time, no premature substitution occurs. `_open_log` sets the var
per-run; the event reads it at fire time.

This pattern applies to any future feature whose state is inherently
per-session and where stale persisted values would cause incorrect
behaviour. Examples to be alert for: `#var` or `#event` referencing
filesystem paths derived from runtime state (timestamps, character
names, run IDs).

## Alternatives considered

**(a) Close the profile class before registering.** Would prevent
persistence at the source. Rejected because profile auto-save
expects the class open for the session duration; reopening creates
a window where other registrations might miss the class, and adds
fragile ordering constraints.

**(b) Store `_run_log_path` in the gts namespace instead of the
session class.** Would isolate it from profile auto-save. Rejected
at the time because the `#event {RECEIVED LINE}` body that reads
the variable runs in the game session; cross-session variable
lookups via `@ses{$var}` were thought to be syntactically heavier
and would muddy the registration pattern.

The 2026-05-11 amendment inverts this rationale. The relevant
infrastructure — `session_cmd()` on the Lua side, `#class {core}
{open}/{close}` on the tt++ side — already exists for exactly this
purpose, and the variable still lives in the game session (just in
a different class). No `@ses{...}` lookups are needed; the
registration pattern is in fact cleaner than the unset-before-
register workaround it replaces.

**(c) Pass the path as an event argument instead of a variable.**
Not directly possible — tt++ event arguments (`%0..%99`) are line
content; we don't control what tt++ passes as args.

**(d) Use a constant filename like `current.log` and rename on
seal, paralleling `current.jsonl`.** Would eliminate per-run path
from the event body. Rejected because tt++'s `#line log` doesn't
tolerate the file being renamed mid-session — it would keep
writing to the old inode or fail. The orphan-rename pattern works
for `current.jsonl` because Lua-side `os.rename` is atomic and
Lua doesn't hold an open handle.

**(e) Ignore the issue, document the lag.** Rejected because
replay accuracy depends on each run's `.log` matching its
`.jsonl` exactly; a one-run lag shifts the entire replay.

The chosen approach (explicit unset before re-register) is
simplest, has no ordering dependencies, and the intent is
self-documenting in the alias body.

## Consequences

- Per-session capture state lives in `{core}` by construction —
  `_run_log_path` via `session_cmd()`, the `RECEIVED LINE` event
  and `_ts` via the `#class {core} {open}/{close}` wraps in
  `_register_run_log_capture`. Profile auto-save no longer
  acquires this state because `#class write {<profile>}`
  serializes only profile-class items.
- The `#unevent {RECEIVED LINE}` / `#unvar _run_log_path` lines
  in `_register_run_log_capture` remain only as transitional
  hygiene for legacy profile files that already contain baked-in
  pre-`{core}` state. They may be removed in a future release
  once all known profile files have been resaved under the new
  architecture.
- `_register_run_log_capture` is still idempotent across SESSION
  CONNECTED — re-registering the same event in the same class is
  a no-op modulo body replacement.
- Lines arriving between SESSION CONNECTED and the first
  Char.Vitals (~1 s of login screen) are correctly not written,
  because `_run_log_path` is unset and the event body no-ops via
  `#if {&_run_log_path}`.
- Future capture features (e.g., a possible RECEIVED INPUT mirror
  for player commands) should follow the structural model:
  register infrastructure state in `{core}` via `session_cmd()`
  (Lua) or explicit `#class {core} {open}/{close}` wraps (tt++),
  not in the profile class.

## Relation to other ADRs

- Builds on **ADR 0044** (runs and character-scoped persistence):
  the run-log mechanism this ADR concerns lives entirely within
  the file layout established by 0044.
- Independent of **ADR 0046** (GMCP dispatch via events): this
  concerns tt++-side state, not the Lua event bus.
