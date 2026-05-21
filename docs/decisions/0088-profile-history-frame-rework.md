# 0088 — Profile and History frame rework (launcher P4)

**Status:** Accepted
**Date:** 2026-05-21

## Context

P1–P3 of the launcher chrome pass (ADR 0085 / 0086 / 0087) introduced
the shared `menu_chrome` helpers, the panes colour grid, and the
three-grammar model for the cell types in the launcher's chrome:
`button_fragment` (gold-background filled buttons), `panes_grid`
(gold-foreground swatch cells), and `menu_row` (gold-arrow
`<< label >>` rows).

The Profile and History frames were the last launcher surfaces still
hand-rolling their button columns. They both rendered the action
column on the **right** of their table, behind a centred "Options"
header. The History frame additionally rendered a horizontal pill row
across the top of the table under a "Filter" header. Both columns
used the legacy near-black `C_BUTTON` / `C_BUTTON_HOVER` /
`C_BUTTON_DISABLED` palette — flat backgrounds with `C_SELECTED`
(black-on-light-grey) for the cursor in every focus state. The
Profile table's active-row ✓ painted `C_ACCENT` (gold), which
mis-signalled it as a transient cursor (gold is reserved for the
focused cursor across the rest of the launcher; ADR 0085 added
`C_OK` for persistent active markers but the existing ✓ wasn't
migrated to it).

Three problems followed from this:

- **Action columns on the right look like a sidecar.** The eye reads
  the table first; the buttons trail behind it. Putting the buttons
  on the left (and the filter on the left of History) makes the
  control surface — what you can *do* — the first thing the user
  sees.
- **The "Options" / "Filter" headers added noise.** They duplicated
  what the column already says by virtue of being a column of
  buttons / a list of filter names. The first button / sidebar row
  top-aligned with the table's header row gives the same visual
  grouping without the label.
- **The cursor row's colour didn't track focus.** Both frames used
  `C_SELECTED` for the cursor row in every focus state, so the user
  couldn't tell at a glance which zone keyboard focus was in. The
  rest of the launcher (profile editor, panes grid) already paints
  gold when its zone is focused and grey when it isn't.

## Decision

### 1. Profile frame — button column left, table right

The action buttons (Select / New / Edit / Rename / Delete / Export /
Back) move to the left of the table. The "Options" header is
removed; the column's first button top-aligns with the table's
`Name | Selected` header row.

The table moves to the right. Its `Selected` column's ✓ for the
active profile paints `C_OK` (green) instead of `C_ACCENT` (gold) —
gold is the focused-cursor colour, not the active marker.

Two zones with focus-on-push per ADR 0066: `_profile_table_window`
on the right, `_profile_options_window` on the left. `←` focuses
options, `→` focuses the table — opposite of the pre-P4 mapping,
following the new spatial layout. Tab / Shift+Tab cycle between
zones; disabled-button skip, sort, scroll, every action handler,
and the feedback row are unchanged.

### 2. History frame — filter sidebar left, table centre, options right

The horizontal filter pill row becomes a vertical left sidebar — one
`button_fragment` row per filter (`All` first, then characters
alphabetically). The "Filter" header is removed; the sidebar's first
row top-aligns with the runs-table header. The active filter follows
the cursor exactly as it did with the pill row — only the layout
changed, not the apply semantics. If the sidebar is longer than the
visible table area it scrolls in parity with the table (both
viewports use `_history_table_scroll` as their top index).

The runs table stays in the centre. Columns and sort are unchanged.

The button column (Run log / Stats / Rate / Save / Export / Delete /
Back) keeps the right side; the "Options" header is removed and the
first button top-aligns with the runs-table header row.

Three zones, left-to-right: `←` / `→` step between filter ↔ table ↔
options (no-wrap); Tab / Shift+Tab cycle. Cursor movement *within*
the sidebar is ↑ / ↓ now (replacing the old horizontal ← / →).
`_history_focused` 0/1/2 (filter / table / options) is unchanged.
Every action handler, sort, scroll, the feedback row, and the
Stats / Rate / Delete subframes are unchanged.

### 3. Cursor row picks up the button-cell grammar

Both frames' table cursor rows — and the History filter sidebar's
cursor row — paint `C_BUTTON_ACTIVE_FOCUSED` (gold bg) when their
zone is focused and `C_BUTTON_ACTIVE_UNFOCUSED` (grey bg) when not.
The button columns themselves use `button_fragment` directly:
cursor + zone focused → `selected_focused`; cursor + zone
unfocused → `selected_unfocused`; hover on a non-cursor enabled
button → `hover` (previews the unfocused-selected look); disabled →
`disabled`; else `inactive`. Hover stays `C_HOVER`; the cursor
always wins over hover.

This retires the legacy `C_BUTTON` / `C_BUTTON_HOVER` palette in the
launcher. The two tokens stay in `palette.py` because the in-game
popup is still on them (P5 will adopt the three-state grammar
there); the comment block above the tokens calls out the remaining
caller so they're not removed accidentally.

### 4. Subframe titles paint `C_SECTION`

For consistency with the parent frames and the rest of the launcher
submenu set, the modal subframes adopt `C_SECTION` (was `C_TITLE` or
`C_HEADER`):

- `profile_create_name`, `profile_create_choose`,
  `profile_create_copy_picker`, `profile_delete_confirm`,
  `profile_rename` — all were `C_TITLE`.
- `history_rate` — was `C_TITLE`.
- `history_delete_confirm` — was `C_HEADER`.

`history_detail` is excluded; it keeps its `C_HEADER` statistics
banner because that surface uses a different visual style overall.

### 5. Title and footer route through `menu_chrome`

The `profile` and `history` frames' title rows now use
`menu_chrome.title_block(title, cols, blank_above=2,
mouse_handler=clear_hover)` so the title paints `C_SECTION`
(matching every other launcher submenu under ADR 0085). The
title Window height becomes `title_block_height(2) = 4` rows.

The footer is now a single-row `Window` pinned to the final
terminal row via a flex_spacer between the feedback row and the
footer, matching the footer-anchoring contract the swept frames
already use. The footer-hint wording is unchanged.

## Consequences

**Easier.** Both frames share one cell grammar (`button_fragment`)
and one focus rule (gold-when-focused, grey-when-not) with the rest
of the launcher. The ✓ no longer competes with the cursor for the
same colour. The "Options" / "Filter" headers — which carried no
information that the column underneath didn't already convey — are
gone.

**Harder.** Anyone with the pre-P4 muscle memory of `→ focuses
options` on the Profile frame has to relearn one arrow: `←` now
focuses options instead. The history frame's filter row changes
from `← / →` (horizontal cursor move) to `↑ / ↓` (vertical cursor
move), which is also a one-time relearning cost.

**Locked out.** A "buttons on the right" layout for the launcher's
table frames. P5 onwards the popup still ships with action columns
on the right of its History surface; whether to migrate it to match
the launcher is open. For now the two surfaces diverge on this
detail.

This ADR completes the launcher side of the chrome pass started by
ADR 0085. The popup-side equivalent is the still-pending P5.

## Alternatives considered

**Keep the right-side columns and only fix the cursor colour and the
✓ tone.** The minimal patch — change `C_SELECTED` to a focus-aware
gold-bg, swap `C_ACCENT` to `C_OK` on the ✓, drop the "Options"
header. Rejected: the muscle memory cost is the same once we change
the cursor's behaviour, and we'd still have an "action column on the
right" pattern that no other launcher frame uses. The whole-frame
rework is the cleaner break.

**Use `menu_row` (`<< label >>`) instead of `button_fragment` for
the button columns.** Visually lighter and consistent with the main
menu. Rejected: the History button column has seven actions stacked
adjacent with no inter-button gap, and the `<< … >>` arrows on every
row would compete with the focused cursor's gold arrows. The
filled-button grammar is the right one for a tightly-packed action
column; `menu_row` is for sparse vertical menus where each row is
its own choice.

**Inline both reworks into one PR.** Rejected: the History frame is
the three-zone one and the Profile frame is the simpler two-zone
case. Verifying the Profile frame end-to-end before touching History
gives a known-good two-zone implementation to mirror.
