# 0117 — Achievement capture via GMCP Event.Achieved

**Status:** Accepted
**Date:** 2026-05-29

## Context

MUME added a GMCP `Event.Achieved { "what": "<description>" }` message at our
request, surfacing achievement data directly. ADR 0050's two-stage
marker-line + one-shot inner `#action` existed only because no GMCP module
carried this data — that constraint no longer applies.

## Decision

Capture achievements via a passive GMCP collector. The `Event.Achieved`
handler in `lua/core/world_state.lua` reads `body.what` and emits the
existing `achievement` event; the two-stage `#action` in
`ttpp/core/mud_events.tin` is removed. The `achievement` event contract
(payload is the description string; subscribed by `run_log.lua` for the
JSONL row, by `world_state.lua` for the UI announcement) is unchanged.

## Consequences

- The brittle 3/3/4 escape discipline and `#class {core}` wrap from ADR 0050
  are gone — there is no nested action and no profile-class capture risk.
- The known limitation in ADR 0050 (an interleaved line between marker and
  description miscaptures the wrong string) no longer applies: GMCP delivers
  the description in-band on a structured message.
- Capture is now subject only to the `gmcp.modules` subscription gate
  (`"Event 1"` package subscription in `Core.Supports.Set` /
  `gmcp.modules`). If the server drops Event support, achievements stop
  flowing — there is no tt++ fallback.
- ADR 0050's "future two-stage triggers should follow this template" guidance
  is left in place as historical record; the template stands for any future
  case where the data is genuinely not in GMCP.

## Alternatives considered

**Keep the tt++ trigger as a backup.** Rejected: dual sources would race
and double-emit, and the tt++ trigger has the interleaved-line failure mode
the GMCP source fixes. Cleaner to remove it entirely.

## Supersedes

[ADR 0050](0050-synchronous-nested-actions-with-class-discipline.md)
