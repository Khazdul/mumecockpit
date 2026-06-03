# 0131 — keymanager locate capture: arm on data, whole-line %0, self-removing terminator

**Status:** Accepted

**Date:** 2026-06-03

## Context

keymanager must capture multi-line `locate life` output, gag the raw rows, and
reformat them into a numbered pick list — without loading the latency-critical
hot path. ADR 0050 rejected a `RECEIVED LINE` handler for exactly this kind of
per-line work.

## Decision

- **Arm on the data, not on input.** Result rows are self-identifying — each
  ends in `key: '<key>'` — so a normal pattern-triggered `#action` recognises
  and gags them. No sent-output snoop, no `locatel` alias. A block starts on the
  first matched row and ends on the first blank line.
- **Capture the whole line via `^%1  key: '%2'$`.** In a tt++ `#action`, `%0` is
  the matched *segment*, not the full line; a leading anchored wildcard makes the
  match (and `%0`) span the line, which Lua re-parses with its own regex. (See
  [docs/ipc.md](../ipc.md).) The line is forwarded as one opaque payload because
  it carries both single quotes and a colon and must not be colon-split.
- **The blank-line terminator is installed at fire time** by the row action and
  removes itself after rendering, so `^$` is live only during a locate block.
  Blank lines are common in MUME; an always-live `^$` would dispatch to Lua on
  each one. The fire-time install is wrapped in its own `;`-joined
  `#class {core} {open};…;#class {core} {close}` so it lands in `{core}` (never
  serialising into the saved profile — ADR 0049/0097) and runs atomically on one
  input line (ADR 0050/0097).
- **Parse, pick buffer, and library live in Lua;** tt++ only gags and forwards.

## Consequences

- Any locate output is reformatted regardless of how it was cast.
- Zero-match locates render nothing; no input snooping is needed.
- The `^$` terminator and the `%0` whole-line capture are tt++ subtleties future
  edits must respect — a tail-only pattern would forward only the tail, and a
  permanently-registered `^$` would leak Lua dispatches onto every blank line.

## Alternatives considered

**Sent-output snoop to arm** (à la spellcast / charm). Depends on the cast
spelling, needs a `locatel` alias or a spell-prefix match, and can arm with no
data following. Rejected.

**Always-registered `^$` gated by a flag.** Fires on every blank line — either a
Lua dispatch each time or a per-session tt++ var that risks profile leakage
(ADR 0049). Rejected.

**`RECEIVED LINE` / parse in tt++.** `RECEIVED LINE` is the hot path (ADR 0050),
and the variable-width column split is far easier in Lua. Rejected.

## Relation to other ADRs

Complements ADR 0049 / 0050 / 0097 (class discipline, nested actions, atomic
relay); builds on them for the `{core}` scoping and single-line atomicity. The
safekey behaviour of the same script is ADR 0132.
