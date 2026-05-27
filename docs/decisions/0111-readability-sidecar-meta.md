# ADR 0111 — Readability sidecar .meta format

**Status:** accepted  
**Date:** 2026-05-28  
**Context:** slice 2a — launcher Options view for readability modules

## Decision

Readability module metadata lives in a sidecar `.meta` file (TOML)
alongside each `.tin` module, rather than inside the `.tin` file itself.

## Context

The launcher and in-game popup need to show a description and
before/after preview for each readability module. The existing script
metadata convention (lua/scripts) uses `@`-tagged comment headers
inside the source file, parsed by both the Lua loader and the Python
launcher. This works well for single-line key/value metadata
(`@summary`, `@alias`, `@help`).

Readability modules need richer metadata:

- Multi-line before/after examples.
- Raw ANSI escape sequences in `example_after` for colour preview.
- Structured arrays (TOML `example_before = [...]`).

## Considered alternatives

### `#NOP` begin/end-marker headers in .tin

TinTin++ `#NOP` comments could carry structured metadata delimited
by markers (`#NOP META_BEGIN` / `#NOP META_END`). Rejected because:

- `#nop` is not opaque to `;` (CLAUDE.md rule) — a semicolon in any
  example line would be executed as a tt++ command.
- Multi-line values and ANSI escapes are awkward in tt++ comment
  blocks.
- The parser would need to handle tt++ quoting edge cases.

### JSON instead of TOML

JSON is universally supported but lacks:

- Multi-line strings (ANSI examples would need `\n` escaping).
- Comments (module authors can't annotate their metadata).

TOML's multi-line basic strings and inline comments make `.meta`
files more readable and author-friendly.

### @-tagged headers (matching scripts)

The script convention (`-- @summary`, `-- @alias`) works for
single-line values. Readability metadata includes arrays and ANSI
sequences that don't fit the `@key value` pattern cleanly. Extending
the `@` format with multi-line blocks would diverge from the Lua
loader's parser and add complexity for a UI-only concern.

## Trade-offs

- **Breaks consistency with script-management's static headers.**
  Justified by data-type difference: scripts carry short key/value
  metadata; readability modules need structured arrays with embedded
  ANSI. The two systems serve different file formats (.lua vs .tin)
  so the inconsistency doesn't create confusion for authors.
- **Two files per module** (`.tin` + `.meta`). The `.meta` is optional
  — a module without it still loads and toggles; it just shows no
  preview in the UI.
- **TOML dependency.** Python 3.11+ includes `tomllib` in the stdlib.
  Older Pythons need `tomli` (pure-Python, no C deps).

## Consequences

- The launcher's `readability_view.py` parses `.meta` via `tomllib`.
  Parse errors produce `(None, None, None)` — the module renders
  without preview sections rather than breaking.
- `example_before` and `example_after` are capped at 6 entries each
  to keep the preview compact.
- ANSI SGR escapes in `example_after` are converted to
  prompt_toolkit style tuples for rendering.
