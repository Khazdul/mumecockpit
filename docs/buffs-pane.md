# Buffs Pane

Visualises `state.char.affects` — the active affect list maintained by
`lua/core/affects.lua`. Touch this file when changing the renderer, the
pane position, or the toggle wiring.

## Architecture

```
lua/core/affects.lua ──► state.char.affects
                                │
                    affects_changed event
                                │
                                ▼
                    lua/core/buffs_state.lua ──► bridge/buffs.state (JSON)
                                                        │
                                                 mtime poll (100 ms)
                                                        │
                                                        ▼
                                            bridge/buffs_pane.py
```

`buffs_state.lua` serialises `state.char.affects` to `bridge/buffs.state`
on every `affects_changed` event, on character reset (disconnect), and on
login. `buffs_pane.py` polls that file and renders the grid.

## State file schema (`bridge/buffs.state`)

Bare JSON array, one entry per active affect:

```json
[
  {"name": "armour",  "type": "protection", "expires_at": 1714001800},
  {"name": "hunger",  "type": null,         "expires_at": null}
]
```

`expires_at` is `null` for indefinite affects (no `duration` in
`affects_data.lua`). `type` mirrors the data-table value and may also be
`null` if absent from the data table.

## Rendering

`bridge/buffs_pane.py` is a prompt_toolkit full-screen Application.

### Sort order

1. **Group A** — `expires_at` is `null` (untimed). Sorted alphabetically by
   name (case-insensitive). Rendered first.
2. **Group B** — `expires_at` is set (timed). Sorted by `expires_at`
   descending (most time remaining first); alphabetical by name as tie-break.

### Grid layout

Terminal width `W = _term_cols()`, height `H = _term_rows()`, 4 cells per
row.

Cell width distribution (left to right):

```
base = W // 4
rem  = W % 4
widths = [base+1] * rem + [base] * (4 - rem)
```

Each cell occupies `cell_w` columns: `(cell_w - 1)` chars of
`NAME.ljust(cell_w - 1)` followed by `▌`. The separator `▌` uses style
`C_SEP`; the name content uses `C_CELL`.

Empty cells on a partial last row (when `n % 4 != 0`) are omitted — the
coloured row ends after the last populated cell's `▌`.

### Colour constants

```python
C_CELL_BG   = "bg:#66b2ff"   # cell background
C_CELL_FG   = "fg:#000000"   # cell foreground
C_SEP       = "fg:#66b2ff bg:#000000"  # ▌ separator
C_INDICATOR = "fg:#d4a04e italic"      # overflow indicator
```

### Overflow

```
total_rows = ceil(n / 4)
```

- If `total_rows <= H`: render all rows, no indicator.
- If `total_rows > H`: render `H − 1` rows, show indicator on the last row.

Indicator text: `↓ {hidden} more rows` where
`hidden = total_rows − (H − 1)`. Style: `C_INDICATOR`. No click handler.

### Polling

- mtime poll on `bridge/buffs.state` every 100 ms; reload and invalidate on
  change.
- Unconditional 1 Hz invalidate tick — keeps sort order current as
  `expires_at` values move relative to each other.

### Layout container

```
HSplit([
    Window(grid_control),
    ConditionalContainer(Window(indicator_control, height=1), filter=overflow),
])
```

No header, no border, no padding. Cursor hidden.

## Position

Right column (top to bottom): `status` → `buffs` → `comm` → `ui` → `dev`.

When a subset of right panes is open, ordering is preserved — buffs always
sits directly below status (when status is open) and above comm (when comm
is open). Toggling other right panes in any order does not break the
vertical order.

## Default height

`buffs_height=5` in `bridge/layout.conf`.

## Toggle

| Method                  | Mechanism                                        |
|-------------------------|--------------------------------------------------|
| `cp -b`                 | `toggle_pane.sh buffs` (runtime only)            |
| BUFFS button            | `toggle_pane.sh buffs --persist`                 |
| Launcher Options        | `_save_conf` → `startup.conf show_buffs`         |
| In-game popup → Options | `toggle_pane.sh buffs --persist`                 |

Persistence key: `show_buffs` in `bridge/startup.conf`. Fresh-install
default is `0` (pane closed). Existing installs without the key fall
through to the `${show_buffs:-0}` runtime guard — no change on upgrade.

The BUFFS button in the input-pane menu bar reflects the current pane state
(ON / OFF colour). Button state is polled from `startup.conf` every 250 ms
via mtime comparison — the same path as the other menu buttons.

## Pane title and border

Pane title: `buffs`. The `pane-border-format` in `bridge/tmux_start.sh`
maps this to the label ` Buffs ` when headers are on.

## Data layer

`state.char.affects` and the supporting disk files (`logs/affect_times/`,
`logs/affects_active/`) continue to be maintained by `lua/core/affects.lua`
regardless of whether the buffs pane is open. The data layer is independent
of the visualisation layer.

See [`docs/affects.md`](affects.md) for the full data-layer specification.

---
Back to [architecture.md](../architecture.md).
