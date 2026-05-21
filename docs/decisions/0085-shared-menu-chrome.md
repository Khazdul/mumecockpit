# 0085 — Shared menu chrome between launcher and popup

**Status:** Accepted
**Date:** 2026-05-21

## Context

The launcher (`bridge/launcher/launcher.py`) and the in-game popup
(`bridge/launcher/ingame_menu.py`) are two `prompt_toolkit`
applications that share a colour palette (`palette.py`, since
ADR 0069) but still hand-roll their own title rendering, footer
anchoring, and button-cell styling. The two surfaces have drifted
in small ways: title spacing (the launcher emits two blank rows
above the title, the popup one), footers that float instead of
anchoring to the bottom row, and inconsistent state-to-style
mappings on three-state button cells.

A four-PR pass is unifying the visible chrome. P1 (this PR) lays
the scaffolding; P2–P4 adopt it frame-by-frame. The scaffolding
itself has to be reviewable in isolation — no frame is wired to
it yet, so the visible behaviour does not change.

Two related grammars need to be expressible in shared tokens:

- The existing three-state button grammar (inactive / active-zone-
  unfocused / active-zone-focused) from the profile-editor work
  (ADR 0083). Already encoded as `C_BUTTON_INACTIVE` /
  `C_BUTTON_ACTIVE_UNFOCUSED` / `C_BUTTON_ACTIVE_FOCUSED`.
- A two-mode cursor grammar across other zones: gold *background*
  on filled buttons (carried by the existing focused-active token),
  gold *foreground* on swatch / checkbox cells in palette zones
  (not previously a separate token), and a persistent green marker
  for "selected / active" that should never be confused with the
  transient cursor (the profile-table ✓ today renders in
  `C_ACCENT` gold, which mis-signals it as a transient cursor).

## Decision

### 1. Two new palette tokens

`C_OK` and `C_CURSOR_CELL` are added to `palette.py` with a comment
block that documents the cursor grammar in full (gold bg for
buttons, gold fg for swatch cells, grey bg for unfocused
selections, green for persistent active markers).

- `C_OK = "bold fg:#7ac46f"` — persistent "selected / active"
  marker. Will replace `C_ACCENT` on the profile-table ✓ in P2.
- `C_CURSOR_CELL = "bold fg:#ffaf00"` — foreground for the
  focused-cursor `[ ]` glyph in palette / swatch zones. Today the
  same cells effectively reuse `C_ACCENT`; the dedicated token
  lets the two diverge later without a search-replace pass.

Both tokens are listed in `__all__`. The legacy `C_BUTTON` /
`C_BUTTON_HOVER` constants stay in place because the History
and Profile Options widgets still depend on them and retire only
in P3.

### 2. `bridge/launcher/menu_chrome.py` helper module

A new pure-function module that returns fragment lists / tuples
both launchers can append to their own renderers. The helpers do
**not** import prompt_toolkit; they return plain `(style, text)`
tuples and let the caller attach mouse handlers and assemble
the surrounding frame structure. Four entries:

- `title_block(title, term_cols, blank_above)` — `blank_above`
  blank rows, then a centred `C_SECTION`-styled `title`, then one
  trailing blank row. `blank_above` is 2 for the launcher and 1
  for the popup; that single number is the only knob that
  reconciles the two surfaces' current title spacing.
- `title_block_height(blank_above) -> blank_above + 2` — lets
  callers compute the `content_rows` they pass to `footer_block`.
- `footer_block(footer_text, term_cols, term_rows, content_rows)` —
  emits `max(0, term_rows - content_rows - 1)` blank rows then
  the centred `C_HINT`-styled footer text, so the footer lands
  on the final terminal row. Zero-clamped on overflow.
- `button_fragment(label, width, state) -> (style, text)` — a
  three-state button cell. `state` is one of
  `{inactive, hover, selected_unfocused, selected_focused, disabled}`;
  hover deliberately previews the unfocused-selected look so the
  preview reads as a single motion of attention rather than two
  competing styles.

The module is unit-tested in
`bridge/launcher/tests/test_menu_chrome.py`. Tests run without
prompt_toolkit installed.

### 3. Nothing is wired yet

This PR deliberately wires no frame to the new module. P2–P4
adopt it incrementally — splitting that work keeps the diff for
each visible-behaviour change short and reviewable on its own,
and lets P1 land safely ahead of a freeze if one happens.

## Consequences

**Easier.** The launcher and popup get a single edit point for
title-row composition, footer anchoring, and button styling. The
two-mode cursor grammar (gold bg vs gold fg) is named in tokens
rather than implicit in which style happens to be reused.

**Harder.** Two surfaces with a small abstraction in between
instead of duplicated literals — one more file to read when
chasing a chrome bug. Mitigated by keeping the helpers pure and
small; failure modes show up directly in the unit tests rather
than in render output.

**Locked out.** Future divergence between launcher and popup
chrome now has a friction cost: any change has to either land in
both via the shared helper or be explicit about not being shared.
That friction is the point — the four-PR pass exists because the
two surfaces had drifted.

## Alternatives considered

**Inline edits, no shared module.** Touch each frame's title /
footer code in place across all four PRs. Rejected: the same
spacing logic and the same state-to-style map repeat across six
or seven frames per surface; the next consistency drift would be
weeks away.

**Subclass / template the prompt_toolkit container.** The two
surfaces could share a `Frame` subclass that owns title + footer.
Rejected: prompt_toolkit containers are heavyweight to extend and
the rendering each frame does is more bespoke than a single
template absorbs (kind-buttons rows, scrollbars, package widths).
A fragment-returning helper composes more cleanly with the
existing fragment-list renderers.

**Bundle the helper module adoption into P1.** Wire every frame
to the new helpers in the same PR that introduces them.
Rejected: the diff would mix mechanical refactor with the
visible-behaviour changes P2–P4 deliver (frames currently using
hand-rolled title spacing would visibly change). Splitting the
scaffolding from its use makes each visible-behaviour PR small
and isolated.
