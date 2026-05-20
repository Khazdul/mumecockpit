# 0084 — profile editor: Phase 6.2 polish batch

**Status:** Accepted
**Date:** 2026-05-20

## Context

Phase 6.1 shipped the menu/editor mode toggle, vertical kind column,
and the three-state colour grammar (ADR 0083). Eight follow-up
items surfaced during use that didn't fit any single subsystem but
shared the same overall theme: tighten what the user sees and how
they get there, by removing affordances that proved unnecessary and
fixing edge cases in the ones that stayed.

This ADR records four interlocking decisions from that batch that
have load-bearing semantics. The other four polish items (Page
Up/Down edge clamp, list-view body preview skip, footer hint
cleanup, list-view sort header removal) are implementation details
documented in `docs/launcher.md`.

## Decisions

### 1. Alphabetical sort with group separation in `profile_io`

`parse_profile` and `serialize_profile` now sort items into command
groups: groups sorted alphabetically by `#<command>` name, items
within each group sorted case-insensitively by the first
brace-argument, and a single blank line emitted between groups.
Empty-pattern Entries continue to drop on serialize (ADR 0042).
The sort applies to **any `#<command>` line**, not just the five
GUI-editable kinds — `#var`, `#event`, `#class`, `#showme`, etc.
end up in their own sorted groups via a shared `_classify_passthrough`
helper that reads `#<cmd>` + first `{...}` from a Passthrough.

`parse_profile` returns a sorted `Profile`. `serialize_profile`
sorts defensively at write time; this is the *only* canonical form
the editor produces from now on.

#### Consequences (drops)

The sort pass **drops** these classes of input:

- Blank lines (single source-of-truth blanks come from the
  emitted group separators)
- Free-text lines that don't begin with `#<cmd>`
- Malformed Passthroughs (`#var {x}` missing a closing brace, etc.)
- Multi-line Passthrough continuation lines: a `#class {x}\n  {y}\n}`
  block becomes three Passthroughs at parse time (only the GUI-editable
  kinds get multi-line parsing); the first classifies and survives,
  the continuation lines drop. This is a known limitation — users
  who hand-author multi-line `#class` blocks should keep them
  one-line. Detected only at save time (the lines disappear); no
  validation surface for it currently.

#### Why sort

- Predictable list view across sessions — opening a profile lands
  on the same Aliases tab with the same alphabetical row order.
- The list-view sort header was previously click-to-toggle
  ascending/descending; with canonical sort there's exactly one
  order, so the toggle, arrow glyph, and `_editor_sort_dir` state
  retire together.
- Mode flip (menu → editor → menu) becomes idempotent: the buffer
  is always the canonical form.

#### Mid-session create is NOT re-sorted

`+ New entry` appends to `Profile.items` and parks the cursor on
the new row. Re-sorting on every keystroke (Pattern column drives
sort key) would teleport the cursor as the user types — unusable.
Sort re-applies on the next save (ESC) or mode-flip (which goes
through serialize → parse). Until then the new entry sits at the
bottom of its kind group in the list view. The trade-off is
explicit in `docs/launcher.md`; if it feels wrong in practice we
can sort on create as well.

### 2. Highlight palette redesigned (selection decoupled from cursor)

The previous palette had three zones (Style / Text / Background)
with the **cursor position equal to the selection** — every cursor
move rewrote `entry.body`. Phase 6.2 separates the two: cursor
navigates freely; `Enter` (or mouse click) on a swatch toggles
whether that swatch is the selected text/bg colour. Exactly zero
or one swatch per dimension is selected at any time. Two new state
variables `_editor_hl_text_sel` and `_editor_hl_bg_sel` carry the
selection (each `None` or `(row, col)`); the body is composed from
selections, not cursors.

The grid layout collapses to 28 cells of inner content:

- 6+6 Text swatches under a centred `-- Text --` header
- 3-cell gap
- 6+6 BG swatches under `--- BG ---`

Each swatch renders as `[X]██` (selected) or `[ ]██` (unselected),
where `██` is a two-cell coloured band. The legacy `(None)` BG
cell and `Custom: <body>` slot are removed; an unparseable body
persists verbatim in `entry.body` until the user explicitly
toggles a swatch.

The Style row collapses to four inline toggles: `Bold`, `Und`,
`Blk`, `Rev`. `bold` was previously excluded from `_HL_STYLE_TOKENS`
because tt++'s `#highlight` modifier docs (`reset`, `light`, `dark`,
`underscore`, `blink`, `reverse`, `b`) don't list it. The Phase 6.2
spec calls for a Bold toggle anyway. Trade-off: if tt++ silently
ignores `bold` in a `#highlight` body the modifier has no visual
effect; if tt++ rejects the body the whole highlight fails. We
chose to surface the toggle per spec and document the risk here —
users who run into broken highlights can clear the Bold toggle.
(Phase 6.3 reversed this call — see addendum below.)

#### Why decouple cursor from selection

- Lets the user navigate the grid to compare swatches without
  side effects on the body.
- Matches the Style toggle row, which has always required an
  explicit Enter to flip a toggle.
- Aligns with how form widgets behave elsewhere in the launcher
  (option lists, profile picker) — the cursor is a focus indicator,
  not a commit.

#### Why drop the Custom slot

Of profiles in the wild, no observed body fails to decompose
unless the user hand-authored a tt++ form the palette doesn't
cover (`<rgb>` triplets, `reset` token, etc.). Those are rare and
the user can still hand-edit in editor mode. Carrying the Custom
slot meant a fourth render row, an extra commit path, and a stash
variable for marginal user benefit.

### 3. Stepwise Left-arrow fall-through across detail zones

Left at position 0 of a detail zone falls through one zone to the
left rather than no-op-ing. Full chain in `docs/launcher.md`
*Focus model*. Why: the previous behaviour required Shift+Tab or
explicit clicks to back out; stepwise Left matches how most text
editors and form widgets navigate.

### 4. MENU/EDITOR toggle activated by Left/Right

Previously `Enter` and `Space` activated the toggle. Phase 6.2
unbinds both — Left selects MENU, Right selects EDITOR (no-op
when the requested mode is already active). Why: frees `Enter` for
the buffer (insert newline) and other zones, and matches the
visual model of two adjacent buttons (Left/Right are the natural
horizontal nav).

## Migration

- Existing `.tin` profiles round-trip through the new sort on the
  next save — order changes from source order to canonical order,
  individual entries' `_raw` bytes are preserved. Blank lines and
  free text from the existing file disappear.
- `_editor_hl_custom_value` and the (None) BG cell are removed;
  existing user state files do not persist this anyway (it's
  per-session transient).
- Test suites in `bridge/launcher/tests/` updated to reflect the
  canonical output. The byte-exact round-trip tests now compare
  against the sorted-and-grouped form.

### Phase 6.3 round-trip qualification

Phase 6.3 added a per-entry post-parse normalisation for the
`action` / `alias` / `macro` kinds: bodies that tt++ rewrote on
`#write` (logout) into its indented multi-line form get their
leading/trailing whitespace-only lines stripped and their leading
four-space indentation removed. Routing the result through
`entry.body = …` clears `_raw` (since the string changes), so the
entry regenerates canonically on save (`#<kind> {pattern} {body}`)
with `;\n` newlines preserved but no indent.

**Byte-exact round-trip therefore holds only for entries already
in flat form.** Entries in tt++'s multi-line `#write` format
normalise on load and regenerate on save — the on-disk text after
the first save differs from the original by exactly the indent
strip + blank-edge strip. The cycle is stable: tt++ re-expands a
saved flat body to its multi-line form on the next `#write`; the
editor re-normalises on the next load. `blank_profile.tin` has
no multi-line bodies so its round-trip test is unaffected.

Highlights and substitutes are not normalised — tt++ doesn't
reformat them and their bodies may contain intentional whitespace.

### Phase 6.3 Bold-toggle removal

Phase 6.2 surfaced `bold` in the Style row per spec even though
tt++'s `#highlight` modifier docs don't list it (trade-off
documented above). Phase 6.3 reversed that call: bodies tt++
silently dropped or rejected were a worse outcome than the spec
gain. `_HL_STYLE_TOKENS` becomes `(underscore, blink, reverse)`
and the labels widen to `Undersc.`, `Blink`, `Reverse`. A
persisted body containing `bold` falls through `_hl_parse_body`
as unknown (rather than as a recognised style) — `_raw` is
retained and the body survives byte-exact on save until the user
explicitly edits the highlight in the palette. No Bold control
surfaces; the body renders through the palette's plain text-path
fallback. The leftmost-toggle Left-arrow fall-through (§3, "Style.
Bold → Pattern") now applies to `Undersc.` as the new leftmost
toggle.
