# 0087 — Three-grammar model for launcher menu chrome

**Status:** Accepted
**Date:** 2026-05-21

## Context

ADR 0085 added the shared `menu_chrome` helpers and named the two-mode
cursor grammar (gold *background* on filled buttons, gold *foreground*
on swatch / checkbox cells). ADR 0086 wired the Panes submenu to the
swatch grammar via the new `panes_grid` module. P3 of the chrome
sweep then went on to apply the **filled-button grammar**
(`button_fragment`, gold-background cells) to every selectable row of
the main / Options / Connection / Spotlights / Panes-bottom frames —
on the premise that "every selectable menu row" should share one
button cell.

Review of P3 surfaced three regressions:

- **Lost visual identity.** Vertical menu lists are not a row of
  buttons; they are a column of selectable labels. The `<< label >>`
  prefix-suffix arrow style — which the launcher used for years —
  carries the cursor with less screen weight than a gold-background
  cell does, and was retired without an upgrade in visual clarity.
- **Lost alignment.** Background-filled cells centre each row
  individually inside its button width, so leading `[ ]` / `( )`
  glyphs no longer stacked vertically. The pre-P3 alignment
  convention — left-aligned on a shared column inside a centred
  block — was the correct one for vertical lists; P3 broke it on
  every frame except the Profile pages.
- **Sticky hover.** Title-block, footer-block, and per-row padding
  fragments carry no mouse handler, so MOUSE_MOVE above the first
  row or below the last (or sideways past the row's text) never
  fires a handler to clear the previous row's hover. The launcher's
  pre-P3 frames had the same gap; the Profile / History frames
  already solved it by wrapping every chrome fragment in a
  clear-hover handler.

## Decision

### 1. Three-grammar model, codified

The launcher's chrome carries three distinct cell grammars; which one
applies depends on the **zone**, not on the state:

| Grammar                         | Helper                  | Where                                                                                                |
|---------------------------------|-------------------------|------------------------------------------------------------------------------------------------------|
| Gold-background filled buttons  | `button_fragment`       | Profile / History entry-list and button columns; profile editor's LITE kind-buttons.                 |
| Gold-foreground swatch cells    | `panes_grid_fragments`  | Panes submenu's pane × colour grid.                                                                  |
| Gold-arrow `<< label >>` rows   | `menu_row` (new)        | Every vertical menu list: `main`, `options`, `options_connection`, `options_spotlights`, and the `options_panes` headers-toggle / `Back` rows; popup-side equivalents under P5. |

`menu_row(label, label_col_w, state, mouse_handler=None,
inactive_style=C_ITEM)` is added to `menu_chrome.py`. It emits a fixed
3-cell prefix (`<< ` or `   `) + the label left-padded to
`label_col_w` + a fixed 3-cell suffix (` >>` or `   `). `state ∈
{"inactive", "hover", "selected"}` — selection wins over hover. The
selected state paints the arrows in `C_CURSOR_CELL` (gold) and the
label in `C_ACTIVE`; hover lightens the label to `C_HOVER`; inactive
leaves it in `inactive_style` (`C_ITEM` by default, `C_HINT` for the
Options "Text layout" placeholder). `C_CURSOR_CELL` is now broadened
to cover the menu-row arrows alongside the swatch-cell brackets — one
cursor-mark hue, shared across the two foreground-cursor zones.

`button_fragment` stays in place — P4 still needs it for the Profile
and History button columns. The unused state name `selected_focused`
is what those callers will hand back in; nothing in launcher.py uses
it for vertical menu lists any more.

### 2. Alignment convention, restored

Every menu list is left-aligned on a shared column inside a centred
block. Each frame computes `label_col_w` as the widest composed label
across its rows (including any leading `[ ]` / `( )` glyph). The
block — `label_col_w + 6` cells wide — is centred as a unit; the
leading glyphs stack vertically because every row's label is
left-padded to the same width, not because the chrome shifts. This
is the pre-P3 convention; it now applies to every menu frame, not
only the Profile pages.

The `options_panes` frame is the one place where two centred blocks
coexist on the same page: the colour grid sits in its own centred
block above, and the headers-toggle + `Back` rows sit in a second
centred block below. This supersedes the ADR 0086 detail that
described those two rows as filled-button cells centred individually.

### 3. Hover-clear invariant

In a menu frame, every emitted fragment is either a **selectable row**
(carries a MOUSE_MOVE handler that sets the frame's hover index to
that row's index) or **chrome** (carries a clear-hover handler that
resets the hover index to the no-hover sentinel). The clear-hover
handler is attached to:

- The title-block and footer-block fragments — via new `mouse_handler`
  keyword arguments on `title_block` and `footer_block`. When given,
  every emitted fragment carries the handler as a 3-tuple.
- Every blank-separator row inside the frame.
- The per-row centring left / right padding around each `menu_row`
  call (the row's body fragments already carry the row's set-hover
  handler).

Without the invariant, MOUSE_MOVE above the first row or below the
last (or sideways past the row's text) never fires, the previous
row's hover sticks, and the highlight trails the actual pointer
position. The pattern mirrors the existing `clear_hover` wiring in
the Profile / History frames.

The `options_panes` frame is the lone exception: its keyboard cursor
and mouse hover share `_options_panes_row` (there is no separate
hover index), so its clear-hover handler is a deliberate no-op that
exists only to keep the invariant well-formed.

### 4. Dead helpers removed

`_menu_button_state` (mapped `(active, hover)` → a `button_fragment`
state name) and `_centre_in_width` (centred a label inside a width,
used only by the Text-layout placeholder) are removed. The
placeholder's behaviour is subsumed by `menu_row(...,
inactive_style=C_HINT)`.

## Consequences

**Easier.** The cell grammar is now explicit at the call site — the
caller picks `menu_row` vs `button_fragment` vs `panes_grid_fragments`
based on the zone, and the rules above hold. Vertical menus regain
their pre-P3 weight and alignment without growing a `[X]` /  `( )`
column drift. The hover-clear invariant gives a single rule that
catches sticky-hover bugs at review time rather than at use time:
look at any chrome fragment, ask whether it carries a handler, fail
the review if it does not.

**Harder.** Three grammars to remember instead of one. The mitigation
is that each is anchored in a single helper and a single zone — the
choice is mechanical once the zone is known.

**Locked out.** The brief P3 design where every selectable row,
across every zone, was a uniform button cell. The argument for that
design was "one grammar to learn"; the regressions above (lost
visual identity, lost alignment, sticky hover) outweighed the
uniformity benefit. P3.1 supersedes it.

This ADR supersedes the P3 over-application of `button_fragment` and
the ADR 0086 detail about the `options_panes` headers-toggle / `Back`
rows using the filled-button cursor grammar.

## Alternatives considered

**Keep `button_fragment` everywhere and just fix the alignment.**
Reuse the filled-button cell but compute a shared `label_col_w` and
left-align inside it. Rejected: the cell's *background* fill is the
distinguishing element, and a near-black background under a label is
visually heavier than a `<< >>` prefix-suffix marker. Fixing
alignment alone leaves the visual-weight regression.

**Keep `<< label >>` rows but skip the centred-block alignment.**
Centre each row individually inside the block. Rejected: same root
cause as the P3 regression — leading `[X]` / `( )` glyphs would
stop stacking, which is the cue that the rows form a logical group.

**Solve sticky hover at the framework layer.** Add a global
"clear hover on any MOUSE_MOVE that hits a fragment without an
explicit handler" rule. Rejected: prompt_toolkit does not expose
that hook, and adding it framework-side would couple every cell's
hover semantics to a single global state. The per-frame invariant
is local and explicit and matches what the Profile / History frames
already do.
