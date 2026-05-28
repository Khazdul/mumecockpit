# ADR 0115 — Reserve priority band 1–4 for core registrations

**Status:** Accepted
**Date:** 2026-05-28

## Context

tt++ fires only one matching `#action` per incoming line and only one
matching `#alias` per input line. The same single-fire rule applies to
`#highlight` and `#substitute` against any given line. Each of these
four GUI-editable commands accepts a priority brace-arg in the range
1–9 (lower number = higher precedence). When two entries match and
have the same priority, alphabetical ordering of the trigger string
decides who fires — implementation-defined, fragile, and silently
suppresses one side when patterns happen to overlap.

The defaults are the trap: both core registrations (anything under
`ttpp/main.tin`, `ttpp/core/`, or Lua-relayed via `game_cmd` /
`session_cmd`) and user registrations (anything under
`ttpp/profiles/`, hand-typed `#action` lines, or popup-editor entries)
land at priority 5 unless explicitly told otherwise. A user trigger
with a loose pattern can therefore win the single-fire slot over a
core trigger by accident of alphabet — the user trigger fires, the
core handler never runs, and there is no surfaced warning.

Two adjacent mechanisms already protect against related risks but do
not solve this one:

- **Class isolation ([ADR 0049](0049-per-session-state-outside-profile-class.md),
  [ADR 0097](0097-atomic-core-class-relay-registration.md)).** `{core}`
  vs `{<profile>}` controls persistence scope and bulk operations
  (`#class kill`, `#class write`). It does not affect fire-time
  precedence — two triggers in different classes still race normally
  on the same input line.
- **Pattern anchoring ([ADR 0026](0026-anchored-core-actions.md)).**
  Leading `^` and trailing `$` shrink the match surface so loose user
  patterns are less likely to overlap a core pattern. It is a hygiene
  layer, not a determinism layer — within the surface that *does*
  overlap, default-vs-default still loses to alphabet.

The three mechanisms are orthogonal. None of them alone gives core
registrations deterministic precedence; together they do.

## Decision

Priorities 1–4 are reserved for core registrations. Everything outside
`ttpp/profiles/` — `ttpp/main.tin`, files under `ttpp/core/`, and any
`#action`/`#alias`/`#highlight`/`#substitute` registered from Lua via
`game_cmd` or `session_cmd` — must carry an explicit priority in this
band.

Convention within the band:

- **3** — default for all core registrations.
- **4** — core dispatcher fallbacks that must lose to a sibling
  specific entry (e.g. the bare `cp` help-fallback alias must fire
  only when no `cp -X` specific alias matches).
- **1–2** — reserved for future high-criticality cases. Do not use
  opportunistically; raise the question in an ADR if a real need
  appears.

User registrations under `ttpp/profiles/` stay at the tt++ default
of 5. The popup profile editor does not expose the priority field,
so all UI-created entries land at 5 automatically. Any core
registration is therefore guaranteed to win the single-fire slot
over any UI-authored user registration.

## Mechanism

Two enforcement paths together realise the policy:

(a) **Direct registrations** in `ttpp/main.tin` and `ttpp/core/*.tin`
    carry an explicit priority brace-arg in the third position of
    their `#action` / `#alias` / `#highlight` / `#substitute` line.
    This ADR's accompanying change adds `{3}` to every such entry
    that was previously relying on the default, and lifts the bare
    `cp` fallback from `{6}` to `{4}`.

(b) **Lua-relayed registrations** via `game_cmd` / `session_cmd` will
    have the priority injected automatically by the helper itself.
    This ADR documents the policy; the helper change is a separate
    follow-up PR (PR 2 in this sequence). Until then, the four
    triggers in `ttpp/core/mud_events.tin` and `ttpp/core/clock.tin`
    that are registered indirectly via Lua delegates already carry
    `{3}` explicitly in their tt++-side action bodies, so the policy
    is satisfied for every existing core registration as of this PR.

## Orthogonality

Class membership (`{core}` vs `{<profile>}`) and priority band are
independent mechanisms with non-overlapping jobs:

- **Class** controls persistence scope (what gets written to the
  profile file on save) and bulk operations (`#class kill {core}`).
- **Priority** controls fire-time precedence (which of several
  matching entries wins the single-fire slot).

Both are needed. A core entry in `{core}` at default priority 5
still loses to a user trigger at priority 5 by alphabetical accident;
a core entry at priority 3 in the profile class still gets written to
disk on save and bleeds into future runs.

## Escape hatch

The 1–4 band is policy-reserved, not technically blocked. A power
user who hand-edits a `.tin` file or types `#action {pat} {body} {2}`
directly into the prompt can intentionally win precedence over core.
This is acceptable: cockpit is a power-user tool, and a competent user
who knows what they are doing should be able to override us if they
have a reason to. The popup editor — which is the path most users
will ever take — does not expose the field, so the policy holds for
the surface that matters.

## Open question (separate work)

Name collisions via `#read` are NOT addressed by priority. A user
profile that defines `#alias {cp}` would, on `#class read`, overwrite
the core `cp` alias entry outright; priority becomes moot because
there is only one entry left. The interaction between `#class read`
and pre-existing entries with the same key needs empirical
verification — flagged as follow-up work, not blocking this ADR.

## Alternatives considered

**(a) Single magic priority for everything core.** Set every core
registration to a single value (say 3) with no internal band.
Rejected because internal relative ordering matters in at least one
existing case: the `cp` dispatcher needs `cp -X` specifics (priority
3) to beat the bare `cp` help fallback (priority 4) when both
match. A band of two values is the minimum that works; reserving 1–2
for future use costs nothing.

**(b) Block user priorities below 5 in tt++.** Would make the policy
mechanically enforced rather than conventional. Rejected because tt++
has no registration-time hook to intercept `#action` priority
arguments, and the user can type the command directly into the prompt
in any case. Mechanical enforcement is not on the table; convention
plus the popup-editor not exposing the field is what we get.

**(c) Document the convention without applying it.** Rejected
because the existing core registrations are at default 5 today, so
the convention has no teeth until they are actually moved into the
band. The policy and the sweep go together in one PR.

## Consequences

- Every `#action` / `#alias` / `#highlight` / `#substitute` under
  `ttpp/main.tin` and `ttpp/core/*.tin` now carries an explicit
  priority brace-arg in {1,2,3,4}. Grep audit:
  `grep -rn '#action \|#alias \|#highlight \|#substitute ' ttpp/core/
  ttpp/main.tin` shows no plain two-arg form remains for these four
  commands (commented `#nop` lines excepted).
- Bare `cp` dispatcher now sits at priority 4 (was 6). Specific
  `cp -X` aliases sit at priority 3 (were default 5). The dispatch
  behaviour is unchanged: `cp -s` still hits its specific handler;
  `cp foo` still hits the help fallback.
- A loose user trigger registered at default priority 5 can no longer
  silently outrace a core trigger on the same line. The core trigger
  wins by policy, not by alphabetical luck.
- New core registrations going forward must specify `{3}` (or `{4}`
  for fallbacks) explicitly. Reviewers should reject plain two-arg
  forms of `#action`/`#alias`/`#highlight`/`#substitute` in
  `ttpp/core/`.
- Lua-relayed core registrations still rely on the upcoming
  `game_cmd` / `session_cmd` helper change to inject the priority
  automatically. Until that lands, any new Lua-side registration must
  carry `{3}` in the action/alias body explicitly, the same way
  `mud_events.tin` and `clock.tin` already do.

## Relation to other ADRs

- **Complements [ADR 0049](0049-per-session-state-outside-profile-class.md)
  and [ADR 0097](0097-atomic-core-class-relay-registration.md).** Those
  ADRs control where core registrations *live* (persistence scope);
  this one controls when they *fire* (precedence). The three together
  are the full picture for core-vs-user isolation.
- **Complements [ADR 0026](0026-anchored-core-actions.md).** Pattern
  anchoring shrinks the overlap surface; priority decides the winner
  inside that surface.
- **Extends the convention noted in [ADR 0050](0050-synchronous-nested-actions-with-class-discipline.md)**
  for the nested achievement trigger — that ADR already used
  priority 3 for its two-stage actions. This ADR generalises the
  same convention to every core registration.
