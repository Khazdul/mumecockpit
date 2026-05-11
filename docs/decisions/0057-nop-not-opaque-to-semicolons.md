# 0057 — `#nop` is not opaque to semicolons

**Status:** Accepted
**Date:** 2026-05-11

## Context

tt++ parses `;` as a command separator at the parser level, regardless of
which command's argument the `;` happens to sit inside. `#nop` is no
exception: the text after the first unescaped `;` is treated as a fresh
command and executed in the active session. So

    #nop some comment text; with a semicolon

is parsed as two commands — `#nop some comment text` (a real no-op)
followed by `with a semicolon` (run as input). At `main.tin` load the
active session is `gts`, which has no server connection, so tt++ prints

    #NO SESSION ACTIVE. USE: #session {name} {host} {port} TO START ONE.

once per occurrence, visible in the game window above the welcome banner.

Four `.tin` files in the repo carried this defect: `ttpp/core/clock.tin`,
`ttpp/core/system.tin`, `ttpp/core/mud_events.tin`, and
`bridge/launcher/templates/blank_profile.tin`. ADR 0050 noted the same
mechanism in its "Related pitfalls" appendix for alias-body `#nop` lines
specifically; this ADR generalises the rule to every `#nop` and gives it
its own decision record so future contributors hit it on a doc grep.

`#nop {…}` with braces is safe — braces group the entire argument and
any internal `;` is literal.

## Decision

Do not use `;` in the argument of an unbraced `#nop`. Use one of:

- `,` for a list separator,
- `—` (em dash) for a clause break,
- parentheses for a parenthetical,
- or the braced form `#nop {…}` when `;` is genuinely required in the
  comment text (e.g. quoting a code snippet).

## Consequences

- Startup runs clean: no spurious `#NO SESSION ACTIVE` lines in the game
  window from `#nop` comments parsed on `main.tin` load.
- The rule is captured in `CLAUDE.md` under tt++ conventions, so future
  Claude sessions and human contributors get it at edit time rather than
  after a release.
- One-line audit:

      grep -nE '^[[:space:]]*#nop[[:space:]][^{].*;' $(git ls-files '*.tin')

  An empty result is the desired state.

## Alternatives considered

**Escape the semicolon (`\;`).** tt++ does honour `\;` as a literal
semicolon in many contexts, but the escape is easy to miss in review and
collides with reader expectations (`\;` looks like shell, not prose). The
ban-plus-alternatives rule reads more like English and is harder to get
wrong than "remember to escape".

**Wrap every `#nop` in braces by default** (`#nop {…}` everywhere).
Rejected as visual noise: the vast majority of `#nop` lines contain no
`;` and need no braces. A blanket rule pays a per-file cost to prevent a
defect that the audit grep already catches deterministically.

**Add a release-time lint** to `bridge/release/check_release.sh` that
re-runs the audit grep and fails the release on any hit. Adopted as
belt-and-suspenders: the rule lives in `CLAUDE.md` and this ADR for
edit-time guidance, and `check_release.sh` re-checks it before the tag
goes out. The lint is a few lines against the same grep used in the
initial audit, so the maintenance cost is negligible.

## Relation to other ADRs

- **ADR 0050** documents the alias-body manifestation of this mechanism
  (semicolons inside `#nop` lines nested in an `#alias` body). That ADR
  fixed the specific instance via braced `#nop {…}`; this ADR
  generalises the rule to every `#nop` site, braced or not.
