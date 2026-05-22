# 0089 — Profile editor Editor-mode syntax highlighting

**Status:** Accepted
**Date:** 2026-05-22

## Context

ADR 0083 added the lite ↔ editor mode toggle to the profile editor; ADR
0084 polished the editor's rendering loop down to a per-row style-run
budget (line-num cell + 1–5 content runs + scrollbar) with one mouse
handler per visible row. The Editor mode itself rendered the whole
buffer as one flat colour (`C_ITEM` on the body, with `C_SELECTED` for
the cursor cell and the shift-arrow selection band, and the two
current-line `bg:#1f1f1f` / `bg:#141414` row tints).

Flat colour reads as a wall of text on any non-trivial profile. The
tt++ surface area in a real profile — `#action {...} {#nop ...}`,
`#alias {target} {kick %1}`, `#highlight {...} {<088>}` — has enough
internal structure that even *muted* syntax cues make scanning the
file substantially easier. We had two ways to provide them.

## Options considered

### Option A — best-effort lexical tokeniser (chosen)

A single left-to-right scan over the buffer text emits non-overlapping
spans of five kinds: `command`, `brace`, `delim`, `var`, `code`. The
tokeniser has no concept of tt++ grammar — it does not know whether a
given `{...}` is an alias body, an action's argument list, or just a
literal brace inside a regex. It tracks one bit of state ("are we in
command position?") to decide whether `#identifier` is a command or
arbitrary text. Everything else is purely sigil-based:

- `#word` colours iff at logical-line start (after optional
  whitespace) or immediately after `{` / `;`.
- `{` and `}` always colour (1-char span each), except when consumed
  inside a `${...}` var span.
- `;` always colours (1-char span).
- `$id`, `${...}`, `&id`, `%1..%99`, `%*`/`%.`/etc. colour as vars.
- `<088>`, `<aaa>`, `<F000000>` colour as colour codes; `\n`, `\xFF`,
  `\u{...}`, `\UNNNNNN` colour as escapes.

Trade-offs:

- **Correct on the common cases.** Every `#alias`, `#action`,
  `#highlight`, `#var` at start-of-line or after `{ ` colours. Every
  `${...}` is a single span. Every `<088>` is a single span.
- **Occasional miscolouring of literal `;` and `#` inside bodies.**
  A `say hi; how are you?` body has `;` painted in `C_SYN_DELIM`; a
  body that legitimately contains `#42` colours nothing (it's not in
  command position), but a body that contains `;#foo` would
  highlight `#foo` even though `;` here is part of a literal
  message — not a tt++ separator. We judged this harmless: the
  miscolouring is rare in practice, never affects edit behaviour,
  and the colours are deliberately muted so a wrong call doesn't
  scream.
- **No whitelist of command names.** Unknown commands and user typos
  colour anyway. We never want syntax highlighting to silently
  suggest "you spelled `#aliias` correctly" — the colour follows the
  sigil shape, not a known-name list.
- **One pass, identity-cached.** O(N) tokenisation per buffer
  mutation; zero work per render frame after the cache warms. The
  span list is keyed off the buffer text reference using the same
  `is`-compare pattern as `_editor_buffer_line_starts_cache` and
  `_editor_buffer_visual_cache`.

### Option B — full tt++ parser (rejected)

Build a real tokeniser that understands `{...}` nesting, knows that
`#nop {;}` contains a literal `;` not a separator, and tracks command
arguments. Pros: visually correct on every edge case; could
distinguish "command argument" vs "free body text" colouring.

Cons:

- tt++ grammar is rich. `#nop` swallows arguments unparsed; `#format`
  and the `%U`/`%T`/`%t` format codes are context-sensitive; nested
  `${...}` interactions, `\x` inside `${...}`, the `~` colour-code
  prefix, and the `%%n` escape are all special cases. We would be
  carrying a second, parallel implementation of the tt++ parser
  alongside `profile_io.py`'s structural parser — and the two would
  drift.
- The visual gain on the common case is zero. On the rare case
  (literal `;`/`#` inside a body) the gain is a single character not
  being miscoloured. Not worth the parser.
- Render-mode-only highlighting does not need to be sound. Editor
  mode does not act on the spans; only `profile_io.parse_profile`
  does, and it has its own structural parser that is the
  authoritative round-trip.

### Option C — Pygments / `prompt_toolkit.lexers` (rejected)

Pull in a real lexer framework. Pros: free batteries. Cons: no tt++
lexer exists; we would still write Option A, just inside a heavier
shell.

## Decision

Go with Option A. The tokeniser is roughly ~200 lines of pure Python
with no third-party deps; the integration into the editor body
render is a single per-cell pointer that walks forward across the
visible rows once per frame. The five `C_SYN_*` palette tokens are
deliberately muted so the highlight reads as "structure, not
attention" — the cursor cell and the selection band keep priority.

The rule for *what counts as a token* is sigil-driven (and tested in
`bridge/launcher/tests/test_ttpp_syntax.py`); if a future tt++ release
adds a new sigil, this is the file to edit.

## Consequences

- Editor mode renders syntactically coloured text immediately after
  any buffer mutation. Lite mode is unchanged; the
  lite ↔ editor round-trip is unaffected (parser is `profile_io`,
  not the syntax tokeniser).
- The per-row style-run count rises from the ADR-0084 ceiling of
  ~5 to a typical ~10–15. Acceptable: the dominant cost on this
  surface was always closures-per-cell (now still one closure per
  row), and the merge-adjacent-runs collapse keeps the count
  bounded by the number of token transitions in the visible chunk.
- `_editor_buffer_syntax_cache` joins the two existing buffer-
  identity caches. Cache invalidation is automatic on every
  mutation (Python string immutability).
- Future tuning of the five `C_SYN_*` hex values is independent of
  the tokeniser logic; tuning happens entirely in `palette.py`.
