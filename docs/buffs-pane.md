# Buffs Pane

A `prompt_toolkit` full-screen application that renders `state.char.affects`
as a colour-coded affect grid grouped by type (spells, buffs, debuffs), with
bar-drain animation, blink alerts for expiring affects, and row-based scroll.
Touch this file when changing the renderer, the pane position, or the toggle
wiring.

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
  {"name": "armour",  "type": "spell",  "expires_at": 1714001800, "expected_duration": 1800},
  {"name": "hunger",  "type": null,     "expires_at": null,       "expected_duration": null}
]
```

`expires_at` and `expected_duration` are both `null` for indefinite affects
(no `duration` field in the data table). `type` mirrors the data-table value
and may also be `null` if absent from the data table.

## Rendering

`bridge/buffs_pane.py` is a `prompt_toolkit` full-screen `Application`.

### Grouping

Affects are partitioned into three groups rendered top-to-bottom with no blank
rows between them. Empty groups produce no rows.

| Group   | Condition                                             |
|---------|-------------------------------------------------------|
| Spells  | `type == "spell"`                                     |
| Buffs   | `type` is neither `"spell"` nor `"debuff"`            |
| Debuffs | `type == "debuff"`                                    |

Each group lays out 4 affects per row.

### Sort within a group

Each group is independently sorted by the same key:

1. **Untimed** (`expires_at` is `null`) — alphabetically by name,
   case-insensitive. Rendered first.
2. **Timed** (`expires_at` is set) — by `expires_at` descending (most time
   remaining first); alphabetical by name as tie-break.

### Grid layout

Terminal width `W = _term_cols()`, height `H = _term_rows()`, 4 cells per row.

Cell width distribution (left to right):

```
base   = W // 4
rem    = W % 4
widths = [base + 1] * rem + [base] * (4 - rem)
```

Each cell occupies `cell_w` columns: `(cell_w - 1)` characters of
`NAME.upper()[:cell_w-1].ljust(cell_w-1)` followed by the `▌` separator.
Empty slots on a partial last row are omitted — the row ends after the last
populated cell's separator.

### Per-group palette

| Group   | Filled cell BG | Cell FG   | Separator FG | Separator BG |
|---------|----------------|-----------|--------------|--------------|
| Spells  | `#66b2ff`      | `#000000` | `#66b2ff`    | `#000000`    |
| Buffs   | `#00d900`      | `#000000` | `#00d900`    | `#000000`    |
| Debuffs | `#d90000`      | `#000000` | `#d90000`    | `#000000`    |

Overflow indicator style: `fg:#d4a04e italic`.

### Bar fill

```
pct    = max(0, min(1, remaining / expected_duration))
filled = int(pct * cell_w + 0.5)   # round-half-up; do NOT use Python round()
```

Python's `round()` uses banker's rounding (round-half-to-even), which produces
inconsistent bar widths at the 50 % boundary. `int(x + 0.5)` is always
round-half-up.

For indefinite affects (`expected_duration` or `expires_at` is `null`):
`filled = cell_w` (full bar, no drain).

### Separator rule

The `▌` separator renders in the **group colour** only when `filled >= cell_w`.
Otherwise it renders as `fg:#000000 bg:#000000` (black on black — invisible by
design). Adjacent depleted cells therefore merge visually.

### Depleted name colour

When `filled < cell_w` the name characters render as `fg:#1e1e1e bg:#000000`
(near-black on black), unless the cell is blinking — see below.

## Blink

An affect blinks when both conditions hold:

- `filled == 0` — bar is fully drained.
- `remaining <= 30` — fewer than 30 seconds until `expires_at`.

Blink continues past the predicted expiry (`remaining` goes negative) until
`affect_down` fires. Indefinite affects never blink.

**Phase:** `int(time.time()) % 2 == 0` → visible (`fg:#1e1e1e`); `== 1` →
hidden (`fg:#000000 bg:#000000`). Both halves are equal length because the
blink tick wakes just after each wall-clock second boundary (see Polling
below).

## Scroll

`_scroll_offset` is the index of the first visible row. `0` means the top row
is at the top of the pane; `N > 0` means `N` rows are hidden above.

Mouse-wheel down/up on the grid (`ListControl`) increments/decrements
`_scroll_offset`. The visible slice is calculated as:

```
list_height    = H - (1 if (_scroll_offset > 0 or total > H) else 0)
max_offset     = max(0, total - list_height)
_scroll_offset = max(0, min(_scroll_offset, max_offset))
start_idx      = _scroll_offset
end_idx        = min(total, start_idx + list_height)
visible        = all_rows[start_idx:end_idx]
```

New affects arriving while `_scroll_offset == 0` extend the bottom of the list
without shifting the visible window. New affects arriving while scrolled leave
the visible content unchanged — the renderer clamps `_scroll_offset` each frame.

### Indicator variants

| Condition                             | Text             | Clickable                      |
|---------------------------------------|------------------|--------------------------------|
| `_scroll_offset > 0`                  | `↑ N rows above` | Yes — resets offset to 0 (top) |
| `_scroll_offset == 0` and `total > H` | `↓ N more rows`  | No — informational only        |

N for `↑ N rows above` is `_scroll_offset`. N for `↓ N more rows` is
`total - (H - 1)`.

The indicator occupies a dedicated 1-row `ConditionalContainer` below the grid
window, hidden when neither condition holds.

## Polling and redraw cadence

- **State poll:** `os.stat(bridge/buffs.state).st_mtime` checked every 100 ms.
  On mtime change: reload JSON, call `app.invalidate()`. The renderer clamps
  `_scroll_offset` on the next frame.
- **Blink tick:** `asyncio` task that sleeps `1.0 - frac + 0.01` seconds,
  waking just after the wall-clock second boundary. Calls `app.invalidate()`
  each cycle so blink phase transitions are synchronised to wall-clock seconds
  and both halves remain equal length.

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

Persistence key: `show_buffs` in `bridge/startup.conf`. Fresh-install default
is `0` (pane closed). Existing installs without the key fall through to the
`${show_buffs:-0}` runtime guard — no change on upgrade.

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

## Staleness checklist

Items spotted during the 2026-05-03 docs refresh that were not fixed in this
pass. Delete entries as they are resolved.

- `docs/status-pane.md` §"Layout integration / Pane position" says
  `status` → `ui` → `dev`; should include `buffs` and `comm` in between
  now that both panes exist.
- `docs/status-pane.md` §"Future steps" mentions adding a game-time row as a
  future task; `game_time` / `time_period` / `time_remaining` are already in
  the `status.state` schema and rendered.
- `docs/status-pane.md` opening "Step 3 of a multi-step redesign…" banner is
  historical — all three steps are complete. Consider replacing with a plain
  description.
- `docs/launcher.md` §Profile-page table contains "(Phase 2)" parenthetical
  referring to a completed launch phase; the note can be dropped.

---
Back to [architecture.md](../architecture.md).
