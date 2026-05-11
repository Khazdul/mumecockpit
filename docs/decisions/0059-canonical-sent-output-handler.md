# 0059 — Canonical `#event {SENT OUTPUT}` handler in `run_log.tin`

**Status:** Accepted
**Date:** 2026-05-11

## Context

tt++ allows only one `#event {<TYPE>}` handler per session: registering
a second one replaces the first silently. Two subsystems wanted to
react to `SENT OUTPUT` on the game session:

- `ttpp/core/run_log.tin` (`_register_run_log_capture`) appends each
  outbound command, prefixed with `> `, to the per-run `.log` file.
- `lua/core/stored_spells.lua` (`_register_stored_spells_actions`)
  dispatched `USER_INPUT:%0` to `brain.lua` for the
  `user_input` event bus, which drives store-attempt detection.

Both were called from `SESSION CONNECTED` in `ttpp/core/system.tin`,
with `_register_run_log_capture` listed *after*
`_register_stored_spells_actions`. The apparent order suggested the
run-log handler would win, but it did not:

- `_register_run_log_capture` runs as a pure tt++ alias, registering
  the `#event` synchronously inside the SESSION CONNECTED handler.
- `_register_stored_spells_actions` calls into Lua via `#lua {…()}`.
  That round-trips through the `lua` `#run` subprocess, where the Lua
  function builds a `session_cmd([[#event {SENT OUTPUT} …]])` call.
  `session_cmd` writes a `bridge/ipc/cmd_N.tin` file and prints
  `tintin_read <path>`; tt++ then asynchronously `#read`s the file
  and applies the registration.

The async path completes *after* the synchronous registration
regardless of the source-code ordering, so the stored-spells handler
silently overwrote the run-log one at every SESSION CONNECTED. The
observable symptom: per-run `.log` files contained inbound lines but
no `> `-prefixed outbound commands.

## Decision

There is a single canonical `#event {SENT OUTPUT}` handler per game
session, owned by `_register_run_log_capture` in
`ttpp/core/run_log.tin`. The handler body fans out to all consumers
via independently-gated branches:

```tintin
#%1 #event {SENT OUTPUT} {
    #if {&_run_log_path} {
        … per-run .log write …
    };
    #if {"%%0" != ""} {#lua {USER_INPUT:%%0}}
}
```

Each consumer's gate is independent: the `.log` write is gated on
`&_run_log_path` (set only between `_open_log` and `_close_log` for a
live run); the `USER_INPUT` dispatch is gated on non-empty payload
(to filter the IAC/GMCP flushes that also fire `SENT OUTPUT`, and to
preserve the previous semantics where empty sent output was not
forwarded — `RECEIVED INPUT` handles the empty-input case separately
for cast-abort detection).

`stored_spells.lua` loses its tt++-side `#event {SENT OUTPUT}`
registration; its Lua-side `events.subscribe("user_input", …)`
handler is unchanged and continues to receive the dispatch via the
consolidated handler.

New SENT OUTPUT consumers must append a gated branch to the handler
in `run_log.tin` rather than registering a competing `#event`.

## Alternatives considered

**(a) Move the handler to a dedicated new file
`ttpp/core/sent_output.tin`.** A clean separation of concerns and the
"correct" home if SENT OUTPUT had many independent consumers.
Rejected as premature abstraction for a two-line handler with two
consumers; revisit if a third consumer arrives and the file grows
beyond a handful of branches.

**(b) Move all dispatch to Lua: `run_log.lua` subscribes to a new
`user_input` event bus topic instead of tt++ doing the file I/O
directly.** Would centralise consumers on the Lua side. Rejected
because it pushes the per-line file write onto the Lua path that the
project deliberately keeps in tt++ (the `RECEIVED LINE` capture is
already in tt++ for PvP-responsiveness reasons; moving only the
`SENT OUTPUT` capture would create asymmetric architecture for no
gain — SENT OUTPUT volume is low, but the inconsistency would be
confusing).

**(c) Resolve the race by making `_register_stored_spells_actions`
synchronous (rewrite the registration as a pure tt++ alias).**
Rejected because it doesn't solve the structural problem — the next
subsystem that wants `SENT OUTPUT` reintroduces the same collision,
sync or async. The "one canonical handler" rule is the actual fix.

**(d) Leave both registrations in place and accept loss of one.**
Rejected — the run-log was the silent loser and its absence broke
replay fidelity (no outbound commands in the `.log`).

## Consequences

- Adding a new `SENT OUTPUT` consumer means appending one gated
  branch to the handler body in `run_log.tin`, not registering a
  competing `#event`. The convention is documented in the
  file-header `#nop` block and cross-referenced from
  `docs/runs.md`, `docs/stored-spells.md`, and `docs/ipc.md`.
- `run_log.tin` is now mildly misnamed — it owns more than just
  run-log capture. Accepted as the lesser cost relative to creating
  a new file for two lines (see alternative (a)).
- `stored_spells.lua`'s store-attempt detection now depends on the
  canonical handler in `run_log.tin` plus its own Lua
  `events.subscribe("user_input", …)`. Either piece going missing
  silently disables store tracking. The `docs/stored-spells.md`
  "Registration global" section calls this out explicitly.
- Per-run `.log` files now contain interleaved inbound and outbound
  lines as documented in `docs/runs.md` (the `> `-prefix
  discriminator is unchanged).
- Tt++ profile auto-save is unaffected — the consolidated handler is
  still bracketed in `#class {core} {open}/{close}` per ADR 0049, so
  it lives in `{core}` and `#class write {<profile>}` does not
  serialise it.

## Relation to other ADRs

- Builds on **ADR 0049** (per-session capture state outside the
  profile class): the `{core}`-class registration pattern from 0049
  still applies, now to the consolidated handler. The
  `#unevent {SENT OUTPUT}` / `#unevent {RECEIVED LINE}` hygiene lines
  at the top of `_register_run_log_capture` remain as transitional
  cleanup for legacy profile files (per 0049's amendment).
- Independent of **ADR 0046** (GMCP dispatch via events): this
  concerns a tt++ event, not the GMCP event-bus dispatch.
