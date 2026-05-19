# 0083 — profile editor: two-mode toggle and three-state colour grammar

**Status:** Accepted
**Date:** 2026-05-19

## Context

The first five phases of the launcher's profile editor (see
`docs/launcher.md`) shipped a form-based interface: a horizontal
tab strip across the top selecting the active kind (Aliases /
Actions / Macros / Highlights / Substitutes), a centred list +
detail package below it, and per-kind detail widgets (text body
for three kinds, palette grid for highlights, key-capture button
for macros).

Phase 6 was originally scoped as a **sixth Raw tab** added to the
existing horizontal strip — a plain-text view of the serialised
profile file, useful for users who already know tt++ syntax and
prefer to edit it directly. A design pass surfaced two friction
points with that approach:

1. The horizontal tab strip mixes two paradigms in a single nav
   widget — the first five tabs flip between *form layouts* over
   the same data; the Raw tab flips between *visual paradigms*
   (form vs. text buffer). A user clicking through the tabs to
   browse would land in the Raw view by accident.
2. The colour vocabulary across the editor had drifted. The
   active tab used `C_ACTIVE + underline` when unfocused but
   `C_SELECTED` (reverse-band amber) when focused. The list
   cursor used `C_SELECTED` regardless of focus. The detail-panel
   borders used `C_HINT` / `C_ACCENT`. Three different conventions
   meant the user couldn't predict from one indicator what another
   would look like in the same state.

The redesign converged on a two-mode toggle (form vs. text)
controlled by a dedicated widget separate from the kind nav, plus
a uniform colour grammar applied across every "this is selected"
affordance in the frame.

## Decision

The profile editor renders two mutually exclusive views over the
same in-memory `Profile`:

- **Menu mode** — the existing form-based editor, with kind
  navigation moved from the horizontal tab strip to a vertical
  column of five 3-row block buttons on the left.
- **Editor mode** — a full-frame plain-text view of the serialised
  file with line numbers, soft wrap, current-line highlight, and
  an inline scrollbar.

The two modes are switched via a pair of 1-row blocks (`MENU` and
`EDITOR`) on the title row, right-aligned so the `R` in `EDITOR`
sits above the right `┐` of the menu-mode detail-panel Pattern
frame below. Both modes are live-bound to the same `Profile`:
menu → editor serialises the items into the buffer; editor → menu
parses the buffer back. ESC in either mode parses if needed, then
saves and pops.

A **three-state colour grammar** is applied uniformly:

| State                              | BG     | Text   | Used for                                                                          |
|------------------------------------|--------|--------|-----------------------------------------------------------------------------------|
| Inactive (not selected)            | Black  | `C_ITEM` | Non-active kind buttons; non-active mode button                                |
| Active, owning zone unfocused      | Grey   | Black  | Selected kind when kind column unfocused; active mode when toggle unfocused; entry-list cursor row when list unfocused |
| Active, owning zone focused        | Amber  | Black  | Selected kind when kind column focused; active mode when toggle focused; entry-list cursor row when list focused; detail-panel frame borders |

The tokens (`C_BUTTON_INACTIVE`, `C_BUTTON_ACTIVE_UNFOCUSED`,
`C_BUTTON_ACTIVE_FOCUSED`) live in `palette.py`. Hover on an
inactive button paints the active-unfocused state — a preview of
how it would look if selected. Headers (`Pattern ▼  Body`,
`Pattern`, `Commands`, `─── Hint ───`) stay in muted grey
(`C_HINT`) at all times; the cursor row / button state is the
sole focus indicator.

**No keystroke binds mode switching.** Pressing `m`, `e`, `M`, or
`E` in any text-editing context (Pattern, Body, editor buffer)
inserts the literal character. Mode flip is exclusively via
toggle activation (focus + Enter / Space, or click).

## Consequences

- Kind navigation moves from a horizontal tab strip to a vertical
  block-button column. The five 3-row buttons stack without
  separator rows; the active button paints amber when the kind
  column has focus, grey otherwise.
- The detail panel narrows from 44 to 30 cells. Commands /
  New-text fields cap at 10 visible rows; bodies that exceed the
  cap render with an inline scrollbar in the rightmost inner cell
  of the box, and the viewport tracks the cursor.
- Editor mode renders without a frame around the buffer — the
  line-number column on the left and the scrollbar on the right
  delineate it. A subtle current-line highlight tracks the
  cursor.
- The lenient parser (unrecognised lines fall through to
  `Passthrough`) means user edits in editor mode never throw on
  flip-back to menu — the worst case is a previously-known entry
  becoming a `Passthrough` until reformatted.
- The `serialize_profile` / `parse_profile` helpers (extracted
  from `save_profile` / `load_profile`) carry the round-trip
  contract through the in-memory flip path. The byte-exact
  round-trip property continues to hold for files containing only
  the five known commands plus `#var`, `#event`, `#nop`, and
  blank lines.
- The reusable scrollbar widget's click behaviour changes to
  page-step (clicks above the thumb scroll up by one viewport,
  clicks below scroll down, clicks on the thumb itself are a
  no-op) — affects every caller, not just the editor. The
  previous centre-on-click behaviour was confusing for large
  lists.

## Alternatives considered

- **Sixth tab in the horizontal strip.** Rejected — mixes form
  and text-buffer paradigms in a single nav widget. Users
  clicking through tabs would land in the text view accidentally;
  the form-vs-text distinction warrants a dedicated affordance.
- **Modal dialog for the text editor.** Rejected — obscures the
  menu context when flipping, breaks the live-bound model
  (modal-vs-frame state would have to be reconciled separately).
- **Pill toggle with a single block + cursor inside it.**
  Rejected — the three-state grammar reads less consistently with
  the kind buttons. Two distinct blocks (each a button) lets the
  same `C_BUTTON_*` tokens apply to both widgets.
- **Keyboard shortcut to flip mode (e.g. Ctrl-E, F2).** Rejected —
  conflict-prone with text input. Tab cycle through the toggle
  plus Enter / Space activation is conventional and discoverable.
- **Remember mode across pushes.** Rejected for phase 6 to keep
  the contract simple; can be added later as a session state if
  the need surfaces.
