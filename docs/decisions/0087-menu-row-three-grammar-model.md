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

## Amendment — 2026-05-21 (P3.2)

Two corrections to the section above, kept here rather than spun into
a new ADR because P3.2 is a follow-up polish to this same decision.

**Arrows hug the label.** The original `menu_row(label, label_col_w,
state, …)` left-padded the label to `label_col_w`, so the selected
row's `<< … >>` arrows trailed empty padding (`<< Enter MUME      >>`)
instead of sitting one space off the label. The helper is now
`menu_row(label, state, …)` — the label is emitted unpadded and the
row is `len(label) + 6` cells wide, so the arrows always hug the
label. The label still does not shift between states because the
prefix and suffix are the same width (3 cells) in every state.

**Two alignment rules, not one.** Section 2 above ("Alignment
convention, restored") said every menu list left-aligns on a shared
column inside a centred block. That is correct only for the **glyph
menus** — frames whose rows carry leading `[ ]` / `( )` glyphs that
need to stack vertically (`options_connection`, `options_spotlights`,
and the headers-toggle + `Back` block of `options_panes`). For
**plain `<< label >>` menus** (`main` and `options`) the rows are
centred *independently* on their own width — the pre-P3 behaviour —
because there are no leading glyphs to stack. The two rules are not
the same; `docs/launcher.md` "Alignment convention" carries the
updated wording.

Glyph menus still compute `left_pad` from `label_col_w + 6` (centred
on the widest composed row), but now compute the per-row right pad
from each row's actual width to fill out to the right screen edge,
since `menu_row` no longer pads the label.

## Amendment — 2026-05-31 (P5 + toggle-list extension)

P5 — the popup side of the menu-row grammar — is now complete, and the
grammar is extended to the scripts/readability toggle lists on both
surfaces. The remaining `button_fragment` toggle / `Back` rows are
converted to `menu_row`, so the filled-button background-fill grammar
no longer paints any toggle or `Back` row black-on-amber (the
regression P3.1 fixed for the launcher's vertical menus, now closed on
the popup too):

- **Popup `panes` / `timers` frames** (`ingame_menu.py`): the
  `[X] Display pane headers`, `[X] Display headers`, `[X] Compact
  layout` toggles and both `Back` rows move from `button_fragment` to
  `menu_row`. These grid frames have no separate mouse-hover index, so
  the state map is cursor-row → `selected`, otherwise `inactive`.
  `button_fragment` is no longer imported by `ingame_menu.py`.
- **`options_scripts` / `options_readability` module rows** (the
  shared `scripts_view.py` / `readability_view.py` `_list_cell_frag` +
  `render_body`, both surfaces): the cursor row was `C_BUTTON_ACTIVE_*`
  (filled-button background). It now uses `menu_row`
  (`<< [X] name >>`): cursor → `selected`, hover → `hover`, enabled
  non-cursor → `inactive` (`C_ITEM`), disabled non-cursor → `inactive`
  (`C_PANE_OFF`). The shared `focus` parameter no longer splits a
  focused/unfocused cursor colour for these rows (the dead path is
  left in the signature, not preserved). `list_panel_width` widens by
  the 6 marker cells (longest composed `[X] name` + 6) so the module
  rows and the centred `<< Back >>` row share one column.

**Glyph stacking, padded variant.** The two `options_timers` toggles
(both surfaces) and the scripts/readability module rows left-pad each
composed label to a shared width (`ljust` to `label_col_w`, resp.
`list_w - 6`) rather than leaving it unpadded — so within these blocks
the trailing `>>` arrows align as well as the leading `[X]` glyphs.
The earlier glyph menus (`options_connection` / `options_spotlights` /
`options_panes`) keep the unpadded variant from the P3.2 amendment;
both variants stack the leading glyphs. `docs/launcher.md` "Alignment
convention" carries the two-variant wording.

`button_fragment` is unchanged and still correct for its zones — the
Profile / History button columns and the profile editor's kind-buttons
/ MENU-EDITOR toggle — and the panes/timers grid CELL rendering keeps
its gold-foreground swatch grammar.
