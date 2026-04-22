# Architecture Decision Records

Short, append-only records of non-obvious design decisions. Future me (or
future Claude) can read these to understand *why* something is the way it
is without digging through git history.

## When to add an ADR

Add an ADR when a decision:
- Constrains future choices (e.g. "Lua, not Python").
- Has a non-obvious rationale (the "why" isn't recoverable from the code).
- Was a trade-off — document what the alternatives were.

Don't ADR everything. Routine choices go in code comments or the relevant
`docs/*.md`.

## Format

Filename: `NNNN-short-slug.md`, zero-padded sequence number.

Body template:

    # NNNN — Title

    **Status:** Accepted | Superseded by NNNN | Deprecated
    **Date:** YYYY-MM-DD

    ## Context
    What forces are at play? What problem are we solving?

    ## Decision
    What did we decide? Stated plainly.

    ## Consequences
    What becomes easier. What becomes harder. What we're locked out of.

    ## Alternatives considered
    One paragraph per serious alternative, and why it wasn't chosen.

## Rules

- Once committed, ADRs are **append-only**. If a decision changes, write a
  new ADR that *supersedes* the old one; update the old one's Status line
  only.
- Keep ADRs short (half a page, one page max).
