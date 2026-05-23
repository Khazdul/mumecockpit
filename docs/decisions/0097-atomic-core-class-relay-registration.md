# ADR 0097 — Atomic `{core}`-class relay registration

**Status:** Accepted
**Date:** 2026-05-23

## Context

`game_cmd()` and `session_cmd()` in `lua/brain/io.lua` register tt++
aliases, actions, delays, and variables into the `{core}` class. Their
job is to ensure that script/infrastructure registrations never leak
into the on-disk profile file, which `#class write {<profile>}`
serializes on disconnect. The two-class model — `{<profile>}` for user
data, `{core}` for everything registered by scripts and infrastructure
— is documented in `docs/session-lifecycle.md` and ADR 0049.

The original implementation issued the triple as three separate
`tintin_cmd` calls per target session:

```lua
tintin_cmd(ses, "#class {core} {open}")
tintin_cmd(ses, cmd)
tintin_cmd(ses, "#class {core} {close}")
```

Each call produced its own relay file (`bridge/ipc/cmd_N.tin`), its own
`tintin_read <path>` line on stdout, and its own `#read` on the tt++
side. The argument for safety was that Lua is single-threaded and the
three writes hit the relay queue in order (FIFO), so the three `#read`s
would happen in order.

That reasoning was incomplete. FIFO guarantees ORDER, not ATOMICITY.
tt++ services other sessions' socket input between successive input
lines, and `#class {core} {open}` / `#class {core} {close}` mutate a
single global "last opened class" slot — tt++ has no per-session class
stack. A `#class`-manipulating trigger firing in another session
between the three `#read`s could overwrite the slot mid-triple. The
subsequent `#action` would then register under whatever class the
foreign operation left open (typically the active profile class `{%0}`)
instead of `{core}`, and the registration would leak into the saved
profile on `cp -s`.

The bug was race-driven and intermittent. The most visible incident
predating this ADR was `_profile_loaded` ending up in the profile file
on save — fixed (cdaa009) on the tt++ side by tightening that specific
registration, but the same shape of bug could reappear for any
Lua-relayed registration whenever any other session ran a `#class`
operation in the same input-line gap.

## Decision

`game_cmd` and `session_cmd` consolidate the open/cmd/close triple into
ONE relay file, whose first line carries three `;`-separated,
individually `#<ses>`-prefixed statements:

    #<ses> #class {core} {open};#<ses> <cmd>;#<ses> #class {core} {close}
    #system {rm -f <path>}

tt++ runs all `;`-separated statements on a single input line as one
unit before servicing any other session's socket input. The three
statements therefore execute back-to-back-to-back with no foreign
`#class` operation able to interleave, regardless of what triggers fire
in other sessions during the same scheduler tick. This is the same
atomicity unit the relay file already relied on for the two-line
`cmd` + `#system {rm}` pair; we are only extending the content of
line 1.

Implementation in `lua/brain/io.lua`:

- New file-local helper `_tintin_class_core_cmd(ses, cmd)` that writes
  one relay file containing the triple line and the cleanup line,
  reusing the existing `_tintin_cmd_seq` filename counter.
- `session_cmd(cmd)` — one helper call against `GAME_SESSION`; the
  pre-existing no-op + `dbg("session_cmd: no session")` when
  `GAME_SESSION` is nil is unchanged.
- `game_cmd(cmd)` — one helper call against `gts`, plus (when
  `GAME_SESSION` is set) one against `GAME_SESSION`. Each target gets
  its own file → `game_cmd` produces up to two files, each with its
  own self-contained, independently atomic triple line.
- `tintin_cmd` and `tintin` are untouched. They keep their plain
  `#<ses> <cmd>` single-string contract for direct infrastructure
  callers (`set_game_session`, `clear_game_session`).

The `<cmd>` substring inside the triple is byte-identical to what
`tintin_cmd` would have written. There is no extra brace wrapping and
no extra evaluation pass, so delayed `$var` / `%capture` substitution
in registered bodies is preserved exactly — registered actions still
read variables at fire time, not at registration time.

## Consequences

- Lua-relayed registrations land in `{core}` deterministically,
  independent of what other sessions are doing at the same instant.
  `#class write {<profile>}` on save sees a profile class that
  contains only user profile data.
- Relay-file count halves: every `session_cmd` now writes one file
  instead of three; every `game_cmd` writes two instead of six.
  Negligible perf win, but a small one for free.
- `tintin_cmd` semantics are unchanged. Existing direct callers
  (`set_game_session`, `clear_game_session`, `tintin_show`) behave
  exactly as before.
- Call-site signatures of `game_cmd` / `session_cmd` are unchanged.
  An audit of `lua/core/` and `lua/scripts/` confirmed that every
  caller passes a single brace-balanced statement with no top-level
  `;`. Any `;` in registered bodies — e.g. `events.emit(...); ...`
  joined inside `{#lua {...}}` — is brace-protected and never seen as
  a statement separator on the outer relay line.
- `docs/ipc.md` no longer claims that FIFO adjacency makes the triple
  safe; the section now states the actual atomicity boundary (one
  input line) and points at this ADR.

## Alternatives considered

**(a) Brace-wrapped single dispatch.** Write the triple as one
`#<ses> {#class {core} {open};<cmd>;#class {core} {close}}` and emit
that in one relay file. Rejected for the same reason ADR 0049 records:
nested brace-wrapping introduces an extra evaluation pass over `<cmd>`
that risks premature `$var` / `%capture` substitution in registered
bodies, so any action that depends on reading a variable at fire time
would silently freeze its value to the registration-time snapshot. The
`;`-separated, individually-prefixed form keeps `<cmd>` byte-identical
to its original content and avoids the extra unwrap entirely.

**(b) Bare command file plus tt++-side wrapping.** Have the Lua relay
write only `<cmd>` to a file and add a new tt++-side relay action that
reads the file inside `#class {core} {open}` / `#class {core} {close}`.
Rejected as a protocol change touching the tt++ side. It would expand
the IPC contract (Lua relay files are no longer self-describing
`#<ses> ...` lines), require coordinated changes in `main.tin`, and
make `bridge/ipc/cmd_*.tin` no longer human-greppable for "which
session is this for." The single-line consolidation lives entirely on
the Lua side and leaves the tt++ relay action unchanged.

**(c) Status quo + per-call defensive `#class write` audit.** Detect
leaked registrations post-hoc by greping the saved profile and
warning. Rejected as a band-aid that does not fix the underlying race
— stale profile entries would still ship on disk between the leak and
the next sanitize-and-re-save cycle, and `cp -e` users would never see
the warning.

## Relation to other ADRs

- **Continues [ADR 0049](0049-per-session-state-outside-profile-class.md)** —
  0049 introduced the two-class model and the `session_cmd()` /
  `#class {core} {open}/{close}` wraps. This ADR closes the remaining
  hole in the Lua-relay side of that wrap, where the wrap itself was
  not atomic against foreign-session interleaving.
- **Resolves the general case behind the `_profile_loaded` leak fixed
  in cdaa009.** That commit fixed the tt++-side registration of
  `_profile_loaded` so it lands in `{core}` instead of the profile
  class. The Lua relay had the symmetric vulnerability for every
  Lua-registered alias/action/var/delay. This ADR removes it for the
  whole class of Lua-relayed registrations.
- **Independent of [ADR 0081](0081-format-code-escaping.md)** — that
  ADR concerns `%`-code unwrapping inside alias bodies. The
  consolidation here keeps the `<cmd>` substring byte-identical to
  pre-change, so any `%`-escaping convention chosen at the call site
  is preserved.
