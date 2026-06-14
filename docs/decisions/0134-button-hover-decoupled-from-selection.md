# 0134 — Button hover decoupled from the selected-unfocused fill

**Status:** Accepted
**Date:** 2026-06-14

## Context

The three-state button grammar (ADR 0083, extended by 0085 / 0087 / 0088)
painted the *hover* state with the same token as the *selected-unfocused*
state — `C_BUTTON_ACTIVE_UNFOCUSED` (light-grey fill). The stated rationale
was that hover should preview "how it would look if selected" — a single
motion of attention rather than two competing styles.

In practice the two collide. The selected-unfocused state is a *persistent*
fill that stays visible in its own column while the user works in a sibling
zone — the active kind tab while editing in the detail panel, the entry being
edited in the list, the active mode on the LITE/EDITOR toggle. A hover that
renders identically is indistinguishable from that persistent selection: the
user cannot tell "what I am pointing at" from "what is actually selected".
The preview rationale only holds when no persistent selection is co-visible,
which is not the common case in these columns.

## Decision

Button hover paints `C_HOVER` (foreground brightening, no background fill) —
the launcher's universal hover token, already used by `menu_row`, the
profile / history table rows, the highlight swatch cells, and the macro-key
cell. `C_BUTTON_ACTIVE_UNFOCUSED` (grey fill) now signals *selected* only.

The resulting grammar is orthogonal: a background **fill** means
"committed / selected" (grey when its owning zone is unfocused, amber when
focused); **foreground brightening** means "transient pointer". A fill never
means hover; brightening never means selection.

### Implementation

The grammar is realised in two places, both updated:

- The shared `_BUTTON_STYLES` mapping in `menu_chrome.py` — the `"hover"`
  key moved from `C_BUTTON_ACTIVE_UNFOCUSED` to `C_HOVER`. Covers every
  `button_fragment` caller (the Profile and History button columns).
- Two inline helpers in `profile_editor.py` — `_editor_kind_button_style`
  and `_editor_toggle_button_style` — which hand-roll the same three-state
  logic for the LITE kind-buttons row and the LITE/EDITOR toggle and build
  their own cell text. Their hover branch was split out of the combined
  `is_active or is_hover` test to return `C_HOVER`.

This corrects the implicit claim in ADR 0087 / 0088 that the kind-buttons
and the toggle render via `button_fragment`. They replicate the filled-button
grammar inline; only the Profile / History button columns call
`button_fragment`.

## Alternatives considered

**Dedicated dark-fill hover** — revive `C_BUTTON_HOVER` (`bg:#2a2a2a`) as the
button-hover token. Keeps hover as a fill but in the opposite direction
(dark) from the light selection fill, so the two stay distinguishable and
hover remains a "block" affordance. Rejected: it introduces a second,
fill-based hover idiom alongside the foreground-lift idiom used by every other
hover surface in the launcher (`menu_row`, table rows, swatch cells). One
hover idiom across the chrome was worth more than a marginally more prominent
button-hover block. `C_BUTTON_HOVER` stays in `palette.py` for the legacy
popup Options widgets but gains no new caller.

**Leave hover as the documented preview** — rejected; the persistent-selection
overload is the concrete defect being fixed.

## Consequences

- Hover is now a quieter signal (a brightness lift, not a grey block).
  Intentional: the block competed with selection.
- A hovered button is visibly distinct from a selected-but-unfocused one
  across the profile picker, the history frame, the profile-editor
  kind-buttons row, and the LITE/EDITOR toggle — on both the launcher and the
  in-game popup (shared `ProfileEditor` + shared `menu_chrome`).
- Supersedes the hover sub-clause of ADR 0083 and narrows the button-column
  hover description in ADR 0088 §3; both get dated addenda pointing here.
