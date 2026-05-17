# 0076 — Filter IAC bytes from run-log SENT OUTPUT capture

**Status:** Accepted
**Date:** 2026-05-16

## Context

`ttpp/core/run_log.tin` owns the canonical `#event {SENT OUTPUT}`
handler for the game session (per [ADR 0059](0059-canonical-sent-output-handler.md)).
Its body has two independently-gated branches: append `> <command>`
to the per-run `.log` for player-replay, and dispatch `USER_INPUT:%0`
to `brain.lua` for the `user_input` event bus (currently consumed by
`stored_spells.lua`).

`SENT OUTPUT` fires on every `#send` — including outbound telnet
subnegotiations. Two normal sources leak into `.log`:

- **NAWS** (pane-resize notifications, `IAC SB NAWS … IAC SE`,
  `0xFF 0xFA 0x1F …`) fires on every tmux pane resize, often in
  multi-line bursts after MUME redraws (e.g. respawn cinematic).
- **GMCP** subnegotiations sent at connect by `ttpp/core/gmcp.tin`
  (`Core.Hello`, `Core.Supports.Set`, channel enables) — also
  `IAC SB … IAC SE`, leading byte `0xFF`.

Symptom in `<run-id>.log`:

```
<µs> > <IAC><SB><NAWS>...   # ff fa 1f ...
<µs> > <IAC><SB><GMCP>...   # ff fa c9 ...
```

Per [docs/runs.md](../runs.md), the `.log` is full-fidelity
player-action replay material. Telnet protocol overhead is noise
there, and exposing IAC bytes to `USER_INPUT:` consumers would also
let a future subscriber misread protocol traffic as a player command.

## Decision

The `SENT OUTPUT` handler in `ttpp/core/run_log.tin` filters events
whose first byte of `%0` is `0xFF` (IAC). The filter wraps both
branches in one place at the top of the event body, so neither the
`.log` write nor the `USER_INPUT` dispatch fires for IAC-prefixed
sends:

```tintin
#%1 #event {SENT OUTPUT} {
    #class {core} {open};
    #format _first {%%.1s} {%%0};
    #class {core} {close};
    #if {"$_first" != "\xFF"} {
        … existing .log-write branch …
        … existing USER_INPUT dispatch …
    }
}
```

`_first` is the per-fire helper variable; the `#class {core}`
brackets keep it out of the profile class on the same terms as
`_ts` (per [ADR 0049](0049-per-session-state-outside-profile-class.md)),
so profile auto-save is unaffected. Empty `%0` (e.g. an empty Enter)
yields `_first == ""`, which is not `\xFF`, so the existing
empty-Enter behaviour (`> ` line in `.log`, no `USER_INPUT` dispatch)
is preserved verbatim.

The filter is **outbound only**. Inbound IAC bytes are already
stripped by tt++'s telnet layer before `RECEIVED LINE` fires, so
`.log` inbound capture is unaffected and no symmetric change is
needed there.

## Alternatives considered

**(a) Filter only the `.log` write but keep the `USER_INPUT`
dispatch unchanged.** Rejected. The `user_input` event bus is a
public contract; today's only consumer (`stored_spells.lua`) happens
to ignore IAC payloads, but a future subscriber might not. Filtering
once at the source is cheaper than auditing every subscriber.

**(b) Filter post-hoc in a future log-reader / replay tool.**
Rejected. Cheaper to drop the bytes at source than to teach every
reader the IAC-skip rule, and it keeps the on-disk file honest with
its documented contract (player-action replay).

**(c) Switch `SENT OUTPUT` to a different tt++ event that excludes
IAC by construction.** Rejected — `ttpp_manual.txt` exposes no such
event; `SENT OUTPUT` is the only outbound hook.

**(d) Stop the IAC bursts at the source (suppress redundant NAWS
sends).** Out of scope; see "Explicitly parked" below.

## Explicitly parked

Investigation of why NAWS fires multiple times in a tight burst
after certain MUME events (e.g. the respawn cinematic) is parked.
The frequency itself is benign protocol traffic — clients are
allowed to renegotiate at will, and MUME ignores duplicates — and
the burst pattern likely originates in tmux's pane-redraw cascade
rather than in our client code. This filter cleans the symptom in
the run-log; the burst can be picked up independently, most
naturally after the planned pane-rendering rework, without blocking
or being blocked by anything here.

## Consequences

- `<run-id>.log` files no longer contain `> <IAC>…` rows. Verifiable
  with `xxd <run-id>.log | grep -c 'fffa'` (expected: `0`).
- `user_input` subscribers are guaranteed never to see an IAC-leading
  payload. The contract widens for free.
- The `SENT OUTPUT` handler grows by one wrapping `#if` and one
  helper `#format`. The canonical-handler contract from ADR 0059 is
  preserved: future SENT OUTPUT consumers still add gated branches
  inside the IAC gate, not as competing `#event` registrations.
- One extra `#format` per outbound event. Cost is negligible compared
  to the existing `_ts` / `_sent` formats already in the body, and
  the IAC-prefixed events that get short-circuited save a `#line log`
  syscall and a `#lua` round-trip on every tmux resize.
- Profile auto-save remains unaffected — `_first` is created and
  updated inside `#class {core} {open}/{close}` brackets, on the same
  terms as `_ts`.

## Relation to other ADRs

- **Builds on [ADR 0049](0049-per-session-state-outside-profile-class.md)** —
  the new helper `_first` lives in `{core}` via the same inline
  class-wrap pattern as `_ts`, so profile-class hygiene is unchanged.
- **Builds on [ADR 0059](0059-canonical-sent-output-handler.md)** —
  `run_log.tin` remains the single canonical home for `#event
  {SENT OUTPUT}` on the game session; the IAC gate sits in front of
  every consumer branch, so any future subscriber that joins the
  handler inherits the filter automatically.
- **Surfaced [ADR 0081](0081-format-code-escaping.md)** — the macOS
  connect-time deadlock attributed below to `\xFF` evaluation in `#if`
  conditions turned out to be a `%%`-vs-`%` unwrapping difference in
  `#format`; the project-wide convention that followed is recorded
  separately.

## Update 2026-05-17

The filter as originally landed was non-functional. The condition
`#if {"$_first" != "\xFF"}` does not evaluate the `\x` escape inside
the `#if` string literal: `$_first` (set via `#format _first {%.1s}`)
holds a real single 0xFF byte, while `"\xFF"` holds the literal
4-character string `\`, `x`, `F`, `F`. The comparison was always
unequal, so the gate never matched and every IAC-prefixed event fell
through to both branches.

On Linux this was masked. The PTY buffer between `tt++` and the lua
`#run` session is ~16–64 KB, the connect-time IAC burst (telnet
auto-responses to MUME's negotiation, ~10–15 frames back-to-back
through `SENT OUTPUT` → `#lua {USER_INPUT:<binary>}`) fit inside it,
and `brain.lua`'s `user_input` handler ignored the garbage payloads.
IAC bytes did leak into `.log` files but caused no visible harm.

On macOS the PTY buffer is ~4 KB. The same burst overflowed it; tt++
blocked writing to lua's stdin while lua simultaneously blocked
writing its response back to tt++'s stdin; tt++ stopped servicing its
event loop and the cockpit window went deaf immediately after the
MUME welcome banner. This is the root cause of the macOS-only
freeze-after-connect observed in the field.

**Fix** (`ttpp/core/run_log.tin`): bind a session/`{core}`-class
helper `_iac` via `#%1 #var {_iac} {\xFF};` at registration time —
a context where `\x` is evaluated reliably — and reference `$_iac`
from the filter (`#if {"$_first" != "$_iac"}`). Byte comparison then
succeeds and the gate works as the original decision intended.

The change preserves all original-decision properties verbatim:
filter placement (top of the `SENT OUTPUT` body, wrapping both
branches), `{core}`-class hygiene (per [ADR 0049](0049-per-session-state-outside-profile-class.md)),
outbound-only scope, and the canonical-handler contract from
[ADR 0059](0059-canonical-sent-output-handler.md). See also the
SENT OUTPUT recursion note in [docs/ipc.md](../ipc.md) for why the
USER_INPUT dispatch is the load-bearing path under buffer pressure.

## 2026-05-17 Update — corrected diagnosis

The "Update 2026-05-17" section above misidentified the root cause.
It attributed the macOS connect-time deadlock to `\xFF` not
evaluating inside `#if` string literals; that was a guess, not a
verified diagnosis, and the `_iac` workaround was justified on the
basis of that guess.

The actual root cause was on the *other* side of the comparison.
`#format _first {%%.1s} {%%0}` did not unwrap on macOS Homebrew tt++
2.02.61: instead of producing the first byte of the alias body's
`%%0`, `_first` was set to the literal four-character string `%.1s`.
The IAC gate therefore always passed (`"%.1s" != "$_iac"`), every
outbound subnegotiation flowed through both branches, and the
connect-time IAC burst overflowed the macOS PTY between tt++ and the
`lua` `#run` session. The same source built on Ubuntu unwrapped
`%%.1s` to `%.1s` at alias-call time and the gate worked there — the
asymmetry was a tt++ build/platform difference in `%%X` unwrapping
for `X` outside `0..99`, not in `#if` escape evaluation.

The corrected fix is in [ADR 0081](0081-format-code-escaping.md):
use single `%` for format codes (`%U`, `%T`, `%t`, `%p`, `%.1s`) and
reserve `%%` for alias arg substitutions (`%%0..%%99`), which are
the only `%%` forms that unwrap reliably on both platforms.

The `_iac` variable approach is **required**, not merely defensive
coding. With `%%.1s` corrected to `%.1s` (per
[ADR 0081](0081-format-code-escaping.md)), `_first` now holds a
real `0xFF` byte after the `#format`; an inline
`#if {"$_first" != "\xFF"}` would still fail because the right-hand
side stays the four-character literal `\xFF` on this build. Binding
the literal `0xFF` via `#%1 #var {_iac} {\xFF}` — where the manual
documents that `\x` *is* evaluated at assignment time — and
comparing `$_first` against `$_iac` is the only form of the gate
that works at byte equality.

The original "Update 2026-05-17" section above was therefore correct
on the underlying mechanism (`\x` not evaluating inside `#if` string
literals); its error was attributing the *connect-time deadlock* to
that cause, when in fact `%%.1s` non-unwrap (per
[ADR 0081](0081-format-code-escaping.md)) prevented the filter from
ever reaching the comparison with a real byte. Both issues had to be
fixed; the visible macOS symptom was driven by the `%%.1s` side, but
the `\x`-in-`#if` issue remains real and the `_iac` binding is the
load-bearing reason the corrected gate works.

> **Empirically verified 2026-05-17** on tt++ 2.02.61 (macOS
> Homebrew): `#if {"\xFF" == "\xFF"}` evaluates to *false*,
> confirming that `\x` escapes are not evaluated inside `#if` string
> literals on this build. The `_iac` variable approach (set via
> `#var`, where `\x` is reliably evaluated at assignment time) is
> therefore required, not merely defensive.
