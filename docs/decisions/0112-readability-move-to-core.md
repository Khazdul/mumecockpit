# ADR 0112 — Move readability loader from lua/scripts to lua/core

**Status:** accepted

## Context

Readability is always-on infrastructure with its own user-facing toggle UI
(the Readability menu in both the launcher and the in-game popup). Its
modules are individually toggled via `startup.conf`; the loader itself has
no opt-in semantics and no `@`-tagged metadata header.

Placing it in `lua/scripts/` (the initial slice-1 implementation) made it
appear as a top-level togglable script in the launcher's Scripts view and
the popup's Scripts list, alongside its own module-level toggles — a
redundant and confusing dual-toggle UX.

## Decision

Move `lua/scripts/readability.lua` to `lua/core/readability.lua`.

The `scripts.readability` public API namespace is unchanged. Per
`architecture.md`, the `scripts.<name>` convention names a callable API
surface for tt++ `#lua` dispatch; it is orthogonal to file location.

## Consequences

- Readability loads unconditionally as part of the core tier. Its startup
  banner contribution moves from the script count to the core count.
- Readability no longer appears in `scripts.cache`, the launcher's Scripts
  view, or the popup's Scripts view.
- The `readability_enabled` key in `startup.conf` continues to control
  which *modules* load — the loader itself is not toggleable.
- `#lua {scripts.readability.reload()}` continues to work unchanged.

## Supersedes

The short-lived placement of readability in `lua/scripts/` from the initial
slice-1 readability implementation.

## See also

- [ADR 0111](0111-readability-sidecar-meta.md) — sidecar `.meta` format for module metadata.
