# Buffs Pane

A `prompt_toolkit` full-screen application that renders `state.char.affects`,
`state.char.stored_spells`, `state.char.blinds`, `state.char.charms`, and
`state.char.herblores` as a colour-coded grid grouped by type (spells, buffs,
debuffs, stored, blinds, charms; herblores fold into the buffs/debuffs groups),
with bar-drain animation, blink alerts for expiring entries, and row-based
scroll. Touch this file when changing the renderer, the pane position, or the
toggle wiring.

## Architecture

```
lua/core/affects.lua ──► state.char.affects ──────────────────────┐
                                │                                  │
                    affects_changed event                          │
                                │                                  ▼
lua/core/stored_spells.lua ──► state.char.stored_spells    lua/core/buffs_state.lua ──► bridge/runtime/buffs.state (JSON)
                                │                                  ▲           │
                    stored_spells_changed event ───────────────────┤    mtime poll (100 ms)
                                                                   │            │
lua/core/blinds.lua ──► state.char.blinds                          │            ▼
                                │                                  │  bridge/panes/buffs_pane.py
                    blinds_changed event ──────────────────────────┤
                                                                   │
lua/core/charm.lua ──► state.char.charms                           │
                                │                                  │
                    charms_changed event ──────────────────────────┤
                                                                   │
lua/core/herblores.lua ──► state.char.herblores                    │
                                │                                  │
                    herblores_changed event ───────────────────────┘
```

`buffs_state.lua` serialises `state.char.affects`,
`state.char.stored_spells`, `state.char.blinds`, `state.char.charms`, and
`state.char.herblores` to `bridge/runtime/buffs.state` on every
`affects_changed`, `stored_spells_changed`, `blinds_changed`, `charms_changed`,
or `herblores_changed` event, on character reset (disconnect), and on login.
`buffs_pane.py` polls that file and renders the grid.

## State file schema (`bridge/runtime/buffs.state`)

JSON object with affect/stored/blind/charm arrays plus the herblore arrays
(`herblores`, `herblore_catalog`):

```json
{
  "affects": [
    {"name": "armour",  "type": "spell",  "expires_at": 1714001800, "expected_duration": 1800, "tracked": true},
    {"name": "hunger",  "type": null,     "expires_at": null,       "expected_duration": null, "tracked": true},
    {"name": "bless",   "type": "spell",  "expires_at": null,       "expected_duration": null, "tracked": false}
  ],
  "stored_spells": [
    {"name": "earthquake", "expires_at": 1714005400, "expected_duration": 5400, "tracked": true},
    {"name": "fireball",   "expires_at": null,        "expected_duration": null,  "tracked": false}
  ],
  "blinds": [
    {"name": "2.orc", "expires_at": 1714000090, "expected_duration": 90},
    {"name": "troll", "expires_at": 1714000085, "expected_duration": 90}
  ],
  "charms": [
    {"id": 7, "name": "orc",              "started_at": 1714000000},
    {"id": 8, "name": "huge stone troll", "started_at": 1714000300}
  ],
  "herblores": [
    {"key": "Clearthought", "name": "Clearthought (neg)", "type": "debuff", "expires_at": 1714000720, "expected_duration": 360}
  ],
  "herblore_catalog": ["Healing", "Travelling", "Clearthought", "Walking", "Haste"]
}
```

`expires_at` and `expected_duration` are both `null` for indefinite affects
(no `duration` field in the data table) and for untracked stored spells
(post magic-blast). `type` mirrors the data-table value and may also be
`null` if absent from the data table. `blinds` entries are always timed
(90 s fixed) and never indefinite or untracked; a missing top-level
`blinds` key is treated as an empty array.

`charms` entries carry `{id, name, started_at}`, plus `expires_at` /
`expected_duration` for **timed** entries (charmed mobs and the timed
control-without-charm `wood elf`, which have a 99-min cap). The pane never reads
those for a countdown — it displays a count-**up** of minutes from `started_at`.
**Permanent** control-without-charm entries (`enslaved shadow`, `dreadful warg`)
omit `expires_at`; the pane keys off its absence to show no minutes (see "Charm
group"). `id` is the monotonic per-session id the click-to-drop X targets. A
missing top-level `charms` key is treated as an empty array. See
[docs/charm.md](charm.md).

`herblores` entries carry the **current phase** of each active herblore:
`{key, name, type, expires_at, expected_duration}`. They have no group of their
own — `_split_groups` appends each entry to the **Debuffs** list when its
`type == "debuff"` and to the **Buffs** list otherwise, *before* sorting, so a
herblore renders as an ordinary timed buff/debuff cell (same palette, same
bar-drain) and moves between the two groups by itself when a phase flips type.
`key` is the catalog key, used by the add-view to compute the active set and
drive its `[+]/[-]` toggle. `herblore_catalog` is the static list of catalog
keys the add-view lists, in order. A missing `herblores` / `herblore_catalog`
key is treated as an empty array. See [docs/herblores.md](herblores.md) and the
"Herblore add-view" section below.

The `tracked` field on an affect is `false` only for reconciliation-added
timed-capable entries that have no observed init/refresh yet (see
[`docs/affects.md`](affects.md#untracked-entries-stat--info-reconcile));
every other entry — normal timed, indefinite, reconciled-indefinite —
serializes `true`.

**Legacy fallback:** if the loaded value is a bare JSON array (pre-migration
state file), the renderer treats it as
`{ "affects": loaded, "stored_spells": [], "blinds": [], "charms": [], "herblores": [] }`
and shows only affects — no crash, no Stored, Blinds, Charm, or herblore cells.

## Rendering

`bridge/panes/buffs_pane.py` is a `prompt_toolkit` full-screen `Application`.

### Grouping

Groups are rendered top-to-bottom with no blank rows between them. Empty
groups produce no rows.

| Group   | Source          | Condition                                          |
|---------|-----------------|----------------------------------------------------|
| Spells  | `affects`       | `type == "spell"`                                  |
| Buffs   | `affects` + `herblores` | `type` is neither `"spell"` nor `"debuff"` |
| Debuffs | `affects` + `herblores` | `type == "debuff"`                         |
| Stored  | `stored_spells` | all entries (tracked and untracked)                |
| Blinds  | `blinds`        | all entries                                        |
| Charm   | `charms`        | all entries (one per row, after Blinds)            |

Each group lays out 4 entries per row, except **Blinds** (2 entries per row,
see "Blinds two-up layout") and **Charm** (1 entry per row, see "Charm group").

### Sort within a group

**Spells, Buffs, Debuffs** are each independently sorted by the same key:

1. **Untimed** (`expires_at` is `null`) — alphabetically by name,
   case-insensitive. Rendered first.
2. **Timed** (`expires_at` is set) — by `expires_at` descending (most time
   remaining first); alphabetical by name as tie-break.

**Stored** uses an inverted convention — tracked entries carry real expiry
data and are therefore rendered first; untracked entries represent degraded
state (post magic-blast) and are rendered last:

1. **Tracked** (`tracked == true`) — by `expires_at` descending (most time
   remaining first); alphabetical by name as tie-break.
2. **Untracked** (`tracked == false`) — alphabetical by name, case-insensitive.

**Blinds** are always timed (90 s) — sorted by `expires_at` descending
(most time remaining first); alphabetical by name as tie-break.

**Charm** is sorted by `started_at` **ascending** (oldest first), so the
longest-running charm — the one most likely to be stale and want dropping —
sits at the top of the group.

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

### Blinds two-up layout

The Blinds group is the sole exception to the 4-up grid. It renders **2 cells
per row** so the wider mob names fit. This is the *only* divergence — the cell
content is identical to every other group's, so the Blinds branch of
`_build_all_rows` reuses the shared `_cell_frags` renderer; it just lays out 2
cells per row instead of 4.

Cell width distribution over full width `W` uses the round-extra helper adapted
to 2 cells (same shape as the 3-bar group pane):

```
base   = W // 2
extra  = W % 2
widths = [base + (1 if i < extra else 0) for i in range(2)]
```

Each block occupies `cell_w` columns with the standard cell content —
`NAME.upper()[:cell_w-1].ljust(cell_w-1)` plus the `▌` separator — and inherits
the timed-cell drain (`filled = int(pct * cell_w + 0.5)`), the Blinds palette
(`#00cccc` fill / `#000000` fg / `#00cccc` separator), the depleted-grey
(`#666666`), the expiring-blink rule, and the separator rule, all unchanged.

Narrowing the pane truncates the name from the right
(`PACK HORSE` → `PACK HO` → `PA`). An odd blind count leaves a single block on
the last row; the row ends after that block's separator.

### Charm group

The Charm group is the second exception to the grid: it renders **one entry per
row, full width, with no bar**. Each row (`_charm_row_frags`) is laid out as:

```
<name, left-justified>  <mins, right-justified width 3>  X
```

- **Name** — light violet `#B388FF`. The **first letter is capitalised** and the
  inner case is preserved (mob long-names like `huge stone troll` →
  `Huge stone troll`), unlike the grid groups which upper-case the whole label.
  Truncated from the right to `W - 6` columns (1 X + 1 gap + 3 mins + 1 gap).
- **Minutes** — darker grey `#888888`, a count-**up** rendered as `Nm`
  right-justified in 3 columns (`" 0m"` … `"99m"`), computed as
  `min(99, int((now - started_at) // 60))` and capped at 99. A **permanent**
  controlled mob (`expires_at` absent) shows three blank spaces here instead, so
  timed and permanent rows keep an identical column layout.
- **X** — a clickable drop control in muted red `#CC5555`, brightening to
  `#E88888` while the pointer hovers over it (the `_hover_charm_id` cue).

**Click-to-drop.** Clicking the X calls `_send_charm_drop(id)`, which invokes
`_cp_charm_drop <id>` in the game/tt++ pane over the **same** `tmux send-keys`
channel `input_pane.py` forwards keystrokes through (target `mume:cockpit.0`,
one send-keys call with the line and `Enter`). The render loop never blocks on
it; the state file stays authoritative, so the row clears only once tt++ has
run the drop and `buffs_state.lua` rewrites `buffs.state`. See
[docs/charm.md](charm.md) for the drop handler.

**Known limitation (parked):** the `_cp_charm_drop` command shows up as a
persistent line in the tt++ game scrollback — a tt++ command-echo behaviour not
yet solved. The drop itself works correctly.

| Group          | Filled cell BG | Cell FG   | Separator FG |
|----------------|----------------|-----------|--------------|
| Spells         | `#66b2ff`      | `#000000` | `#66b2ff`    |
| Buffs          | `#00d900`      | `#000000` | `#00d900`    |
| Debuffs        | `#d90000`      | `#000000` | `#d90000`    |
| Stored         | `#ff66ff`      | `#000000` | `#ff66ff`    |
| Stored (untracked)¹ | `#cccccc` | `#000000` | `#cccccc`   |
| Blinds         | `#00cccc`      | `#000000` | `#00cccc`    |

¹ See "Untracked stored cells" below.

**Charm** has no filled cell and no separator (no bar), so it does not fit the
fill/separator columns above. Its colours are per-fragment instead:

| Fragment        | FG        | Notes                                          |
|-----------------|-----------|------------------------------------------------|
| Name            | `#B388FF` | light violet — matches the `◆ CHARM` UI tag    |
| Minutes         | `#888888` | darker grey — count-up `Nm`                    |
| Drop X          | `#CC5555` | muted red                                      |
| Drop X (hover)  | `#E88888` | brighter than `#CC5555` — pointer-hover cue    |

Overflow indicator style: `fg:#d4a04e italic`.

## Herblore add-view

The pane has two view modes, held in the module global `_view_mode`
(`"grid"` | `"add"`, default `"grid"`). The `ListControl`'s text provider
(`_list_text`) dispatches: `add` → `_add_view_frags()`, else the grid renderer.
Both modes are mouse-driven — there are **no** keybindings, mirroring the charm
X's click model and authoritative-state rule (see [docs/charm.md](charm.md)).

### Accent colour

The grid ╋ and the add-view ╳ share one accent — an inverted filled button:
black glyph on gold. `C_ACCENT_BTN` (`fg:#000000 bg:#d4a04e`, the gold of the
overflow indicator), brightening the background to `C_ACCENT_BTN_HOVER`
(`bg:#f0c070`) on hover. They deliberately do **not** reuse the charm-X red —
only the charm row's drop X is red.

### The corner control (╋ / ╳)

Both corner glyphs are owned by a single **position-pinned `Float`** at
`top=0, right=0`, not by any row. The root is a `FloatContainer` wrapping the
`HSplit([grid_window, indicator_container])` with one `corner_float` — a 1×1
`Window` (`dont_extend_width`/`dont_extend_height`) whose `FormattedTextControl`
calls `_corner_text`. Pinning to the pane's top-right (rather than overlaying the
last cell of the first visible row) keeps the glyph in the true corner even when
a partial first row omits its trailing cells, or the grid is empty.

`_corner_text()` returns:

- `[]` (nothing) when not `_run_active`.
- `[(C_ACCENT_BTN, "╋", _open_handler)]` in grid mode.
- `[(C_ACCENT_BTN, "╳", _close_handler)]` in add mode.

Both glyphs are box-drawing (╋ = U+254B, ╳ = U+2573), guaranteed single-width,
so the 1×1 corner never over- or under-flows its cell.

The fragment carries an explicit gold **background**, so the Float renders as a
filled gold button overwriting whatever cell sits beneath it (the bar colour is
not shown in that one column — accepted, and the intended look). The click
handler rides the Float's own fragment stream.

- ╋ hover via `_hover_plus`; ╳ hover via `_hover_close`. Each handler's
  `MOUSE_MOVE` sets its own hover flag and clears the other's. Hover brightens
  the gold background; the glyph stays black.
- `_open_handler` (╋) `MOUSE_DOWN`: switches `_view_mode` to `"add"`, resets
  `_scroll_offset` to 0, invalidates. `_close_handler` (╳) `MOUSE_DOWN`:
  switches back to `"grid"`, resets `_scroll_offset` to 0, invalidates.

### The add-view (`_add_view_frags`)

- **One row per `herblore_catalog` key**, in catalog order: `[+] Name` when the
  key is **not** in the active set, `[-] Name` when it **is**. The active set is
  `{e["key"] for e in herblores}`. The whole row is left-aligned, right-padded to
  full width, clickable, and brightens on hover (`_hover_herblore_key`,
  `C_ADD_ROW_FG` → `C_ADD_ROW_HOVER_FG`). Click: active → remove, else add.
- **The close "╳"** is **not** drawn here — the top-right corner `Float` owns it
  (see "The corner control" above). `_add_view_frags` builds only the catalog
  rows; an empty/absent `herblore_catalog` yields no rows (the Float still shows
  the ╳ over a blank pane).
- The view paginates by `_scroll_offset` exactly like `_grid_text` (build all
  rows, slice `[offset : offset + list_height]`).

### Send helper and authoritative state

`_send_herblore(action, key)` mirrors `_send_charm_drop`: one fire-and-forget
`tmux send-keys -t mume:cockpit.0 "<alias> <key>" Enter`, where `<alias>` is
`_cp_herblore_add` (add) or `_cp_herblore_remove` (remove). Catalog keys are
single tokens, so no quoting is needed. There is **no** optimistic UI update —
the `[+]/[-]` label flips on the next poll (~100 ms) once `herblores.lua`
rewrites `buffs.state`, same as the charm X.

### Hover and reset

`ListControl.mouse_handler`'s "non-fragment move clears hover" branch clears
`_hover_plus`, `_hover_herblore_key`, and `_hover_close` alongside
`_hover_charm_id`. When `_run_active` transitions True→False (disconnect), the
poll loop resets `_view_mode` to `"grid"`, `_scroll_offset` to 0, and clears
every hover global, so a disconnect mid-add-view returns to the grid.

### Untracked affect cells

An affect entry with `tracked == false` (reconciled from `stat`/`info` but
never seen via a real init/refresh string) renders as:

- **Bar fill:** none — no filled cell at all.
- **Name FG:** `#3a3a3a` (darker than the depleted-name grey, so it is
  clearly distinguishable from a tracked timed affect whose bar has
  drained).
- **Separator:** unstyled space (same as the depleted-cell separator).
- **Blink:** never.

`expires_at` and `expected_duration` are both `null` for these entries and
are ignored by the renderer; the `tracked` field is the sole gate. The
cell graduates to the normal tracked rendering as soon as `affect_init` or
`affect_refresh` fires for the same affect (handled in
[`lua/core/affects.lua`](../lua/core/affects.lua)).

### Untracked stored cells

An entry is untracked when `tracked == false` (set by magic-blast). Untracked
cells render differently from all other cells:

- **Bar fill:** always full (`filled = cell_w`) — no drain calculation.
- **Fill BG:** `#cccccc` (grey).
- **Name FG:** `#000000` (black, legible on grey fill).
- **Separator FG:** `#cccccc` (grey — blends with fill, invisible as separator).
- **Blink:** never.

The `tracked` field on the entry is the sole gate; `expires_at` and
`expected_duration` are both `null` for untracked entries and are ignored by
the renderer.

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

The `▌` separator renders in the **group colour** (no background) only when
`filled >= cell_w`. Otherwise it renders as an unstyled space, so it is
invisible regardless of terminal theme. Adjacent depleted cells therefore merge
visually on any background.

### Depleted name colour

When `filled < cell_w` the name characters render as `fg:#666666` (mid-grey on
terminal background), unless the cell is blinking — see below.

## Blink

An affect blinks when both conditions hold:

- `filled == 0` — bar is fully drained.
- `remaining <= 30` — fewer than 30 seconds until `expires_at`.

Blink continues past the predicted expiry (`remaining` goes negative) until
`affect_down` fires. Indefinite affects never blink.

**Phase:** `int(time.time()) % 2 == 0` → visible (`fg:#666666`); `== 1` →
hidden (unstyled space — invisible on any background). Both halves are equal
length because the blink tick wakes just after each wall-clock second boundary
(see Polling below).

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

Scroll is **view-aware**: `_current_total_rows()` returns the grid row count in
grid mode (`_total_rows(*_split_groups())`) and the catalog row count in the
add-view (`len(herblore_catalog)`, min 1 for the blank X row). The wheel handler,
`_indicator_text`, and the indicator `ConditionalContainer` filter all key off
`_current_total_rows()`, so the sticky "↓ N more rows" / "↑ N rows above" row
works in **both** views. Switching `_view_mode` (either direction) resets
`_scroll_offset` to 0, so each view starts at the top.

### Indicator variants

| Condition                             | Text             | Clickable                      |
|---------------------------------------|------------------|--------------------------------|
| `_scroll_offset > 0`                  | `↑ N rows above` | Yes — resets offset to 0 (top) |
| `_scroll_offset == 0` and `total > H` | `↓ N more rows`  | No — informational only        |

N for `↑ N rows above` is `_scroll_offset`. N for `↓ N more rows` is
`total - (H - 1)`.

The indicator occupies a dedicated 1-row `ConditionalContainer` below the grid
window, hidden when neither condition holds.

## Inactive run

When `bridge/runtime/connection.state` is absent, every text provider
(grid and overflow indicator) returns blank fragments and the overflow
indicator is suppressed via the same `_run_active` flag. Pane structure
(size, splits, tmux borders, `cp -h` header status) is unchanged. The flag is
updated by the existing 100 ms poll loop on each tick.

## Polling and redraw cadence

- **State poll:** `os.stat(bridge/runtime/buffs.state).st_mtime` checked every 100 ms.
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

`desired_buffs=5` in `bridge/runtime/layout.conf` (content rows, excludes
title row). Cold start and WINCH size the pane from this value via the
per-pane allocation algorithm in [ADR 0071](decisions/0071-per-pane-desired-heights.md);
mid-session drag adjusts the height freely and the new value persists as
the next `desired_buffs` via `on_pane_resize.sh`. `cp -reset-heights`
restores the shipped default.

## Toggle

| Method                  | Mechanism                                        |
|-------------------------|--------------------------------------------------|
| `cp -b`                 | `toggle_pane.sh buffs --persist`                 |
| Launcher Options        | `_save_conf` → `startup.conf show_buffs`         |
| In-game popup → Options | `toggle_pane.sh buffs --persist`                 |

Persistence key: `show_buffs` in `bridge/runtime/startup.conf`. Fresh-install
default is `1` (pane open), seeded by `bridge/launcher/templates/startup.conf`
(see ADR 0101). Upgraded installs that pre-date the key fall through to the
aligned `${show_buffs:-1}` runtime guard in
`bridge/launcher/build_initial_layout.sh`, so the buffs pane will open on the
next cockpit start.

## Pane title and border

Pane title: `buffs`. The `pane-border-format` in `bridge/launcher/tmux_start.sh`
maps this to the label ` Buffs ` when headers are on.

## Data layer

`state.char.affects` and the supporting disk files under
`data/characters/<character>/` continue to be maintained by
`lua/core/affects.lua` regardless of whether the buffs pane is open. The data
layer is independent of the visualisation layer. The same applies to
`state.char.stored_spells` (`lua/core/stored_spells.lua`, persists to
`stored_spells_active.json`), `state.char.blinds` (`lua/core/blinds.lua`,
persists to `blinds_active.json`), and `state.char.charms`
(`lua/core/charm.lua`, persists to `charms_active.json`). All three survive
reconnect and a full restart.

See [`docs/affects.md`](affects.md), [`docs/stored-spells.md`](stored-spells.md),
[`docs/blinds.md`](blinds.md), and [`docs/charm.md`](charm.md) for the full
data-layer specifications.

---
Back to [architecture.md](../architecture.md).
