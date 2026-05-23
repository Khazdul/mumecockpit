# ADR 0098 — Width-responsive comm channel-filter header

**Status:** Accepted
**Date:** 2026-05-23

## Context

The comm pane's one-row channel-filter header had — until this ADR — a
fixed render: a hardcoded 2–3 character abbreviation per channel (`Na`,
`Te`, `Sa`, `Ye`, `Pr`, `Em`, `Wh`, `Qu`, `Son`, `Soc`), joined by single
spaces, with a leading inert space. The label table lived in
`CHANNEL_LABELS` at the top of `bridge/panes/comm_pane.py`. Unknown
channels fell back to `channel[:2].capitalize()`. The scheme was
introduced by [ADR 0013](0013-comm-display-normalization.md) to replace
a dynamic label-collision algorithm whose output drifted when the server
re-ordered `Comm.Channel.List`.

The shipped width (sum of all advertised labels + separators + leading
inert space) is on the order of 30 columns. Panes are meant to be freely
resizable — `ui_width` in `bridge/runtime/layout.conf` is the sole
authority for the right column (ADR 0038), and there is no minimum width.
When the user narrowed the column below that threshold, the
`FormattedTextControl` for the header silently clipped the fragment list
at the right edge: trailing channels disappeared, and clicking on a
visible cell still worked but the now-invisible channels could not be
toggled until the pane was widened again. The clipped cells were not the
"least important" ones — they were just whichever happened to sit at the
end of `CHANNEL_LABELS`' declaration order.

This conflicted with the pane's design goal that filter and solo state
remain reachable for every advertised channel regardless of pane width.

## Decision

Width-responsive header. Display names are abbreviated by even prefix
truncation to fit the current pane width; separators are dropped as a
last step before any channel is lost. The renderer no longer carries
fixed short-code values.

**Display-name resolution.** Per channel, in order:

1. `CHANNEL_DISPLAY[name]` — sparse override map, currently
   `{"tales": "Narrates"}`. Only populated when the visible label must
   differ from both the GMCP channel name and the server-provided
   caption.
2. `caption` field from `state["channels"]` (set by
   `Comm.Channel.List`).
3. `name.title()` — last-resort fallback when no caption is set.

The override is **display-only**: `CHANNEL_COLORS`, `CHANNEL_VERBS`,
`forward_toggle` / `forward_solo`, and `comm_filters.conf` all stay keyed
on the GMCP channel name.

**Channel order.** `CHANNEL_ORDER` is a list of channel names in the
same fixed order the retired `CHANNEL_LABELS` dict had as keys (`tales`,
`tells`, `says`, `yells`, `prayers`, `emotes`, `whispers`, `questions`,
`songs`, `socials`). Filtered against advertised channels; unknown
advertised channels appended in `Comm.Channel.List` order.

**Algorithm — `_header_layout(caps, W)`.** Given resolved display names
`caps` and available width `W`:

```
N = len(caps)
if W - (N - 1) >= N:        # >= 1 char per cell, with separators
    sep, budget, visible = 1, W - (N - 1), N
elif W >= N:                # 1 char per cell, no separators
    sep, budget, visible = 0, W, N
else:                       # cannot fit all channels at 1 char each
    sep, visible = 0, W     # render first W channels, drop the rest
    budget = visible

target = budget // visible
rem    = budget %  visible
if target >= max(len(caps[i]) for i in range(visible)):
    cell_w[i] = len(caps[i])              # natural, tight
else:
    cell_w[i] = target + (1 if i < rem else 0)
```

Each cell is `caps[i][:cell_w[i]]` left-justified and space-padded to
`cell_w[i]`. Cells are joined with `sep` space(s). No leading and no
trailing padding. Total visible width is `W` or less by construction.

**Fragment emission.** `_header_text()` emits one
`(style, padded_cell, mouse_handler)` fragment per visible channel
(the **whole** padded width is the click target, so the hit area grows
with the pane) and one inert `(" ", "")` fragment between cells when
`sep == 1`. In the narrowest `sep == 0` mode no separator fragments are
emitted at all. The previous leading inert space is gone — cells start
flush.

Style and handler contract are unchanged from ADR 0013: enabled →
`CHANNEL_COLORS[name]`, disabled → `C_LABEL_OFF`; left-click on
`MouseEventType.MOUSE_DOWN` → `forward_toggle`, right-click on the same
event → `forward_solo`.

## Consequences

- **The header never overflows.** Total visible width is bounded by `W`
  for every value of `W ≥ 0`, so trailing channels are never silently
  clipped by `FormattedTextControl`'s right-edge truncation.
- **Hit area scales with the pane.** Because the whole padded cell is
  the click target, narrow panes still surface meaningful click zones
  for every visible channel, and wide panes expose generous click
  targets without changing the layout.
- **Short-prefix collisions are accepted.** At the narrowest widths two
  channels may share a single starting letter (e.g. `S` for both `says`
  and `songs`). No uniqueness logic — the design trade is predictability
  of widths over uniqueness of glyphs. Filter colour and solo state
  still disambiguate behaviourally on hover/click.
- **Trailing channels can drop off the header** at extreme narrowness
  (below one column per channel including the no-separator regime).
  This is accepted: filter and solo state are independent of header
  visibility, so a dropped channel's filter still suppresses its
  messages, and the channel reappears the moment the pane widens.
  Resizing is the user's escape hatch.
- **Curated short-code values retired.** `CHANNEL_LABELS` (the dict of
  fixed `Na`/`Te`/`Sa`/… values) is gone. Only the **order** survives,
  as `CHANNEL_ORDER`. `CHANNEL_DISPLAY` is sparse — currently a single
  entry — and stays sparse by intent. Adding a new channel needs only a
  `CHANNEL_ORDER` append (and a `CHANNEL_COLORS` / `CHANNEL_VERBS`
  entry where appropriate); no new short-code value to bikeshed.
- **The `label` field in `comm.state` stays untouched.** It was already
  unused by the renderer (ADR 0013); this ADR does not change that. Lua
  still emits it for backward compatibility.

## Alternatives considered

**(a) Keep fixed labels; horizontally scroll or clip the header.**
Rejected — clipping is the original bug, and horizontal scroll on a
one-row header has no obvious affordance and hides channels by default.

**(b) Per-channel minimum-width floor.** Set a hard minimum (say, 2
columns per visible channel) and clip below it. Rejected — re-introduces
overflow at higher channel counts and produces a different "dropped
channel" experience depending on which channels MUME currently advertises.
The accepted-drop behaviour in the chosen design is uniform and easy to
reason about.

**(c) Overflow indicator (e.g. trailing `…` or `>N` glyph) when channels
are dropped.** Rejected — costs a cell and adds rendering complexity for
a state the user can resolve in one resize. The accepted-drop is
self-correcting on widen.

**(d) Keep curated unique short labels and just adjust separator
spacing.** Rejected — short codes are not derivable at arbitrary widths
(2 chars × 10 channels still doesn't fit a 12-column pane), so a fallback
still has to exist. Two layout regimes (curated + fallback) are worse
than one (even-truncation everywhere) for predictability.

## Relation to other ADRs

- **Supersedes part of [ADR 0013](0013-comm-display-normalization.md)** —
  specifically the `CHANNEL_LABELS` bullet under Decision and the matching
  bullet under Consequences. ADR 0013 carries a dated update referencing
  this ADR. The rest of ADR 0013 (display normalization, self/other
  colour, action-channel verbatim rendering, destination fallback, etc.)
  is unaffected.
- **Continues [ADR 0038](0038-drop-right-column-width-floor.md)** in spirit:
  the right column has no minimum width, so the comm pane has to
  function gracefully across the full width range that `ui_width` can
  produce. This ADR closes the last fixed-width assumption in the comm
  pane renderer.
