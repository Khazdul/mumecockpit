# ADR 0050 — Synchronous nested #action for two-stage triggers, with profile-class discipline

**Status:** Accepted  
**Date:** 2026-05-09

## Context

Some MUD events require a two-stage capture: the first server line is a fixed
marker (`"You achieved something new!"`), and the payload is the immediately
following line (the achievement description). No GMCP module surfaces this data.

Two prior implementations of the achievement trigger failed before this approach
was settled.

**Attempt 1 — Lua-armed inner action via `session_cmd`.**  
The outer `#action` body called a Lua function that issued `session_cmd` to
register the inner action. `session_cmd` routes through `tintin_cmd`, which
writes a temp file and signals tt++ via `"tintin_read"` on stdout. This is
asynchronous: the signal is processed by the tt++ event loop, not inline with
the current server-line block. By the time the inner action landed, the
achievement description line had already been consumed. The next server push
(typically a room update on the player's next input) was captured instead.

**Attempt 2 — Synchronous nested `#action` without class wrap.**  
The outer body registered the inner action directly with an `#action` command
(synchronous — no temp file, no event loop). This correctly captured the
description line. However, the profile class is open for the entire game session
(per ADR 0049 — the auto-save mechanism expects this). Any `#action` registered
while the class is open lands in the profile, is written by `#class write` on
disconnect, and is reloaded on the next session start or `cp -r`. After each
achievement, a new `^%1$` inner action accumulated in the profile. The only
remedy was editing the profile file directly.

## Decision

The outer action body registers the inner action synchronously via `#action`,
wrapped in `#class {core} {open}` / `{close}`:

```
#action {^You achieved something new!$} {
    #class {core} {open};
    #action {^%%%1$} {
        #lua {events.emit("achievement", "%%%1")};
        #unaction {^%%%%1$}
    } {3};
    #class {core} {close}
} {3}
```

The class wrap ensures the inner action registers into the `core` class, which
is not persisted by the profile auto-save. The outer action remains in the
profile class (it is a stable registration, not a runtime one — it is safe and
correct for it to survive across sessions). The inner action self-removes via
`#unaction` after it fires, so it never accumulates.

## Escape calculus

The achievement action line lives inside the `_register_mud_events %1` alias
body. Three substitution passes occur between file content and inner action
firing: alias-expansion → outer firing → inner firing. One `%` is removed per
pass at each `%N` reference.

| Token | `%` in file | Becomes | When |
|-------|-------------|---------|------|
| inner pattern | 3 (`%%%1`) | `^%1$` stored | outer fires |
| emit argument | 3 (`%%%1`) | description string | inner fires |
| unaction pattern | 4 (`%%%%1`) | `^%1$` literal match | inner fires |

The split is **3 / 3 / 4**. Both prior attempts shipped wrong counts (4/4/8
and 3/3/7 respectively). Refactoring this line — moving it out of the alias
body, or wrapping it differently — silently changes the required counts. Refactor
only with this table at hand.

## Consequences

- The inner action is registered in the `core` class and is discarded after
  firing. `#info action` after `cp -r` shows the outer marker action only.
- After any number of achievements, `cp -s` produces a profile file containing
  no `events.emit("achievement"...)` lines and no `^%1$`-pattern actions.
- Future two-stage triggers inside any `_register_<module>_*` alias body should
  follow this template: synchronous inner `#action` wrapped in
  `#class {core} {open}` / `{close}`, with the escape split derived from the
  number of alias-body passes.

**Known limitation.** The inner action matches the very next received line. If
a non-achievement line interleaves between the marker and the description (rare
in MUME's output stream), that line is captured instead. No mitigation in this
iteration.

## Alternatives considered

**(a) Lua-armed via `session_cmd`.** Rejected: asynchronous; inner action
arrives after the server-line block; miscaptures the next server push.

**(b) Catch-all `^%1$` action with an armed `#var` flag.** Would fire on every
server line; tt++'s "only one action triggers per line" rule makes resolution
order-dependent and collides with other priority-3 actions on shared patterns.
Rejected.

**(c) RECEIVED LINE handler in Lua.** Routes every line through Lua on the hot
path to catch a rare event. Rejected: latency cost disproportionate to the
value; same dispatching behaviour achievable without the overhead.

**(d) Profile-class write exclusion (close before inner register).** Profile
auto-save expects the class open for the session duration; closing and reopening
creates ordering windows for other registrations to miss the class. Rejected;
this is the same alternative considered and rejected in ADR 0049.

## Relation to other ADRs

- **ADR 0049** covers the same root cause — the profile class capturing runtime
  registrations — via a different mechanism (`#event` and `#var`). The
  mitigation there is explicit unset-before-register; here it is explicit class
  wrap for the runtime registration. Both solve the same invariant violation.
- **ADR 0044** establishes the run-log file layout; this ADR's `achievement`
  event writes into that structure.
