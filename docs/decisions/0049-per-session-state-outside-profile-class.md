# ADR 0049 — Per-session capture state stays out of the profile class

**Status:** Accepted  
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
because the `#event {RECEIVED LINE}` body that reads the variable
runs in the game session; cross-session variable lookups via
`@ses{$var}` are syntactically heavier and would muddy the
registration pattern.

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

- `_register_run_log_capture` is idempotent across both
  SESSION CONNECTED (fresh session) and cp -r reload (existing
  session). Both call sites work without further conditionals.
- Lines arriving between SESSION CONNECTED and the first
  Char.Vitals (~1 s of login screen) are correctly not written,
  because `_run_log_path` is unset and the event body no-ops via
  `#if {&_run_log_path}`.
- Profile files may still contain stale `_run_log_path` values
  and event bodies, but the unset-before-register pattern makes
  that harmless. Profile cleanliness is not asserted.
- Future capture features (e.g., a possible RECEIVED INPUT mirror
  for player commands) should follow the same pattern: explicit
  `#unevent` and `#unvar` for any state they own, before
  re-registering.

## Relation to other ADRs

- Builds on **ADR 0044** (runs and character-scoped persistence):
  the run-log mechanism this ADR concerns lives entirely within
  the file layout established by 0044.
- Independent of **ADR 0046** (GMCP dispatch via events): this
  concerns tt++-side state, not the Lua event bus.
