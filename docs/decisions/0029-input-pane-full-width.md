# 0029 — Input pane spans full window width

**Status:** Accepted
**Date:** 2026-04-30

## Context

The input pane previously sat below `main` in the left-column subtree, so it
spanned only the width of `main`. `open_pane.sh` enforced this by using
`split-window -v` (no `-f`) for the input split and `-h -f` for right-column
splits — `-f` was required on right-column splits so they became siblings of
the whole left-column subtree rather than of `main` alone, which would have
moved input outside that subtree unintentionally.

ADR 0024 made input always-on. With input always present, the asymmetric
layout — right column running full window height, input confined to the main
column — became permanently visible and was felt as a visual imbalance.

## Decision

Input is a window-level vertical-split sibling of the top container (which
holds `main` and the right column). `open_pane.sh` adds `-f` to the input
split and drops `-f` from the right-column splits in the no-right-column
branch.

```
window
├─ [hsplit]                      ← top container
│  ├─ main (pane 0)
│  └─ right column (status → comm → ui → dev, top to bottom)
└─ input                          ← full window width, 1 row
```

## Consequences

- The input pane's top border spans the full window width, which is slightly
  more prone to accidental drag. `on_window_resize.sh` re-pins input to 1 row
  on terminal resize, but a deliberate drag between resizes will leave input
  expanded until the next resize. This matches the old-layout behaviour and is
  left as-is — no new pin in `on_pane_resize.sh`.
- `apply_layout.sh`, `on_window_resize.sh`, `on_pane_resize.sh`, drag
  detection, height/width floors, and the narrow-terminal collapse logic are
  all unchanged — they operate on pane titles, not tree position.
- `main` remains at pane index 0 (created by `new-session`). No other code
  depends on input's pane index.

## Alternatives considered

**Keep input below main only (status quo).** Rejected: the asymmetric layout
is visually unbalanced and wastes horizontal space for typing.

**Add input-height pinning to `on_pane_resize.sh`.** Rejected for now as a
behaviour change outside this spec's scope. Can be revisited if accidental
input drags become a real problem.
