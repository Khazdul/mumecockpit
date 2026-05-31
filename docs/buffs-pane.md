# Buffs Pane

A `prompt_toolkit` full-screen application that renders `state.char.affects`,
`state.char.stored_spells`, `state.char.blinds`, and `state.char.charms` as a
colour-coded grid grouped by type (spells, buffs, debuffs, stored, blinds,
charms), with bar-drain animation, blink alerts for expiring entries, and
row-based scroll. Touch this file when changing the renderer, the pane
position, or the toggle wiring.

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
                    charms_changed event ──────────────────────────┘
```

`buffs_state.lua` serialises `state.char.affects`,
`state.char.stored_spells`, `state.char.blinds`, and `state.char.charms` to
`bridge/runtime/buffs.state` on every `affects_changed`,
`stored_spells_changed`, `blinds_changed`, or `charms_changed` event, on
character reset (disconnect), and on login. `buffs_pane.py` polls that file and
renders the grid.

## State file schema (`bridge/runtime/buffs.state`)

JSON object with four arrays:

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
  ]
}
```

`expires_at` and `expected_duration` are both `null` for indefinite affects
(no `duration` field in the data table) and for untracked stored spells
(post magic-blast). `type` mirrors the data-table value and may also be
`null` if absent from the data table. `blinds` entries are always timed
(90 s fixed) and never indefinite or untracked; a missing top-level
`blinds` key is treated as an empty array.

`charms` entries carry only `{id, name, started_at}` — the serialised form has
**no** `expires_at` / `expected_duration` (the in-memory entry has a 99-min cap,
but the pane displays a count-**up** of minutes from `started_at`, not a
countdown). `id` is the monotonic per-session id the click-to-drop X targets. A
missing top-level `charms` key is treated as an empty array. See
[docs/charm.md](charm.md).

The `tracked` field on an affect is `false` only for reconciliation-added
timed-capable entries that have no observed init/refresh yet (see
[`docs/affects.md`](affects.md#untracked-entries-stat--info-reconcile));
every other entry — normal timed, indefinite, reconciled-indefinite —
serializes `true`.

**Legacy fallback:** if the loaded value is a bare JSON array (pre-migration
state file), the renderer treats it as
`{ "affects": loaded, "stored_spells": [], "blinds": [], "charms": [] }`
and shows only affects — no crash, no Stored, Blinds, or Charm group.

## Rendering

`bridge/panes/buffs_pane.py` is a `prompt_toolkit` full-screen `Application`.

### Grouping

Groups are rendered top-to-bottom with no blank rows between them. Empty
groups produce no rows.

| Group   | Source          | Condition                                          |
|---------|-----------------|----------------------------------------------------|
| Spells  | `affects`       | `type == "spell"`                                  |
| Buffs   | `affects`       | `type` is neither `"spell"` nor `"debuff"`         |
| Debuffs | `affects`       | `type == "debuff"`                                 |
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
  `min(99, int((now - started_at) // 60))` and capped at 99.
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
