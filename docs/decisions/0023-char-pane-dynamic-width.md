# 0023 — Char pane adaptive width with uniform lw+1+rw split

**Status:** Accepted
**Date:** 2026-04-29

---

## Context

The status pane renderer previously used a fixed `WIDTH = 33` constant baked
into `bridge/status_pane.py`. The bridge layer enforced a matching 33-col
right-column floor in `apply_layout.sh`, `on_pane_resize.sh`, and
`on_window_resize.sh`.

The paired-row `_pair` helper used an asymmetric split: `lw = W // 2 = 16`,
`rw = W - lw = 17` (no separator). The affect block used `LEFT_W = 15`,
separator = 1, `RIGHT_W = 17`. Both right columns happened to start at column
17 at W=33, but only at that one width.

Supporting narrower right columns requires reworking the renderer so the split
is derived from the actual pane width rather than a compile-time constant.

## Decision

The char pane reads its width from the live pane size on every frame via
`shutil.get_terminal_size().columns`. SIGWINCH already sets a dirty flag, so no
extra plumbing is needed.

Both paired rows and the affect block use a uniform **lw + 1 + rw** formula:

```
lw  = W // 2
rw  = W - 1 - lw
sep = 1 space character between cells
total = lw + 1 + rw = W
```

The bridge-layer floor (`RIGHT_MIN`) drops from 33 to **29** in
`apply_layout.sh`, `on_pane_resize.sh`, and `on_window_resize.sh`.

## Consequences

- At W=33 the right column shifts from col 17 to col 18 (lw becomes 16 for
  both paired rows and affect cells, vs. the previous affect `LEFT_W=15`).
  Both blocks remain aligned with each other.
- `MAX_NAME` for affect cells becomes `cell_w - 4`; at W=29 that is 10 chars.
- Numeric values may be right-chopped mid-digit at very narrow widths
  (e.g. "1,234,567" → "1,234,5" at extreme narrowness). Accepted trade-off.
- The width-authority model in ADR 0005 is unchanged — only the floor value
  changes from 33 to 29.

## Alternatives considered

**Keep `_pair` asymmetric** (`lw = W // 2`, `rw = W - W // 2`) and derive the
affect block's `LEFT_W` from `lw - 1`. This preserves the col-17 alignment at
W=33 but yields 13+1+15 at W=29 instead of the requested symmetric 14+1+14.
Rejected — breaks the symmetric mental model the user explicitly chose.
