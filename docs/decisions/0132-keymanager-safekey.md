# 0132 — keymanager safekey: always resolvable, freshest re-election on expiry

**Status:** Accepted

**Date:** 2026-06-03

## Context

`psafe` / `tsafe` / `qtsafe` (the last bound to Alt+s) are an escape hatch: a
quick cast to a "safe" room's key. Keys expire 12 h after being picked, so the
designated safekey can go stale; we had to choose what happens then.

## Decision

The safekey is a **sticky per-character NAME designation**. The first key stored
into an empty library becomes it; `skey` / `safekey <name>` retargets it (a live
name only); `skey` with no argument reports it. When the designated key is no
longer live, `_ensure_safekey` re-elects the **freshest** remaining live key
(max `expires_at`), announcing the switch once (`Safekey expired; switched to
X.`); it is `nil` only on an empty library.

Named casts (`teleport` / `portal` / `scry` / `watchr`) do **not**
auto-substitute — an expired named key fails.

## Consequences

- The escape hatch is never dead while any key exists.
- The designation survives reconnect and follows `krename`.
- A stale safekey can silently send you to a different room than intended,
  mitigated by the one-line switch announcement and the Safe column in `keys`.

## Alternatives considered

**Fail safe** (`psafe` fails when the safekey expired). A dead escape key
mid-fight is worse than a live-but-different one. Rejected — a deliberate
availability-over-correctness call.

**Auto-substitute for named casts too.** A user naming a key expects that key or
an error, not a surprise substitution. The "always usable" contract is scoped to
the safekey only. Rejected.

## Relation to other ADRs

Shares the script and the locate-capture machinery of ADR 0131; the lazy-expiry
key library it draws on is documented in [docs/keymanager.md](../keymanager.md).
