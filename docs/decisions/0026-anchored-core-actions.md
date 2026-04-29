# 0026 — Anchored core #action patterns

**Status:** Accepted
**Date:** 2026-04-29

## Context

`affects_data.lua` stored trigger patterns without leading `^` or trailing `$`
under the incorrect belief that those anchors were Mudlet-specific syntax not
accepted by tt++. In fact `^` and `$` are valid tt++ anchors (confirmed in the
ACTION and REGEXP sections of `ttpp_manual.txt`). `ttpp/core/mud_events.tin`
and `ttpp/core/clock.tin` were already written with `^...$` anchors
independently and worked correctly.

An unanchored `#action` pattern matches any line that *contains* the pattern
text — including tells, says, narrates, and social emotes from other players
that quote the same phrase. Affect trigger strings are short and quotable
(`You feel weaker.`, `You start glowing.`), making false triggers realistic
in normal play. Each false trigger injects a phantom affect timer and emits a
spurious event on the bus.

## Decision

Anchoring `^...$` is the default for every core `#action` pattern that matches
a single complete server-emitted line. This rule is codified as Design
Principle 7 in `architecture.md`.

`affects_data.lua` has been inverted: all `initString_1`, `initString_2`,
`dropString_1`, and `dropString_2` values now carry the anchors. Wildcard
patterns (e.g. `^You completely drain%*$`, `^Your lungs seem to burst as%*$`)
place `%*` before the closing `$`, which is well-defined in tt++ — `%*` at the
end of a pattern translates to a greedy match of the remainder of the line, and
`$` still anchors against trailing content.

The conversion rule in `docs/affects.md` ("When adding new affects") has been
updated to match: step 3 now says to *add* `^` and `$` rather than drop them.

## Consequences

- Tells, says, narrates, and social emotes that quote an affect trigger line no
  longer fire core triggers. The phantom-timer bug is eliminated for all
  currently-tracked affects.
- `_affects_register_triggers()` deduplicates by pattern string before passing
  to `#action`; identical anchoring on shared patterns (e.g. `second wind`
  drop / `winded` init) keeps the dedupe working correctly.
- Contributors must anchor by default. Any unanchored core action must carry an
  inline comment explaining the intentional exception.

## Alternatives considered

**Anchor only `affects_data.lua`, document inconsistency.** Fixes the
immediate bug but leaves the rule implicit. The next contributor adding a core
trigger has no signal that anchoring is expected and will likely omit it.
Rejected.

**Apply anchoring to `lua/scripts/*.lua` in this same change.** Scripts such
as `autobow.lua` and `autostab.lua` register unanchored action patterns during
active runs and have the same exposure. However, scripts use dynamic
register/unregister lifecycles and each needs per-script verification against
live game output. Bundling script changes here would expand the blast radius
without clear benefit to the core rule. Rejected — flagged as follow-up work.

## Out of scope / follow-up

`lua/scripts/autobow.lua` and `lua/scripts/autostab.lua` register unanchored
`#action` patterns during active runs. They share the same false-trigger
exposure as `affects_data.lua` did. Anchoring those patterns requires
per-script verification against live game output and is left as follow-up work.
