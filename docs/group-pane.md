# Group Pane

A `prompt_toolkit` full-screen application that renders `state.group.members`
as three horizontal bars per member (HP / Mana / Moves), with the member name
left-aligned as an overlay starting from column 0. Anchor-top; overflow
indicator when the pane is shorter than the member list.

## Architecture

```
lua/core/group_collector.lua ──► state.group.members ──────────────────┐
                                         │                              │
                             group_changed / char_reset events          │
                                         │                              ▼
                                         └───────────► lua/core/group_state.lua ──► bridge/runtime/group.state (JSON)
                                                                                │
                                                                      mtime poll (100 ms)
                                                                                │
                                                                                ▼
                                                                    bridge/panes/group_pane.py
```

`group_state.lua` serialises `state.group.members` to `bridge/runtime/group.state`
on every `group_changed` or `char_reset` event, and once at load time.
`group_pane.py` polls that file and renders the member list.

## State-file schema (`bridge/runtime/group.state`)

Source of truth: [`lua/core/group_state.lua`](../lua/core/group_state.lua).

The file is a JSON object:

```json
{"members": [ ... ]}
```

Each member entry contains the raw vitals (`hp`, `maxhp`, `mana`, `maxmana`,
`mp`, `maxmp`), their band-string equivalents (`hp_string`, `mana_string`,
`mp_string`), and the pre-computed percentages used by the renderer:

| Field        | Type           | Meaning                                                  |
|--------------|----------------|----------------------------------------------------------|
| `hp_pct`     | `number\|null` | HP fraction in [0,1]; `null` if unresolvable             |
| `hp_known`   | `bool`         | `true` = computed from value/maxv; `false` = band midpoint |
| `mana_pct`   | `number\|null` | Mana fraction; `null` if unresolvable                    |
| `mana_known` | `bool`         | Same semantics as `hp_known`                             |
| `mp_pct`     | `number\|null` | Moves fraction; `null` if unresolvable                   |
| `mp_known`   | `bool`         | Same semantics as `hp_known`                             |

The renderer reads `*_pct` directly and does **not** recompute from
`value/maxv` or strings. `*_known` affects threshold interpretation only via
the midpoint value already baked into `*_pct`; see
[ADR 0052](decisions/0052-group-vital-pair-freshness.md).

Members are ordered ascending by `id` (sorted by `group_state.lua`); the
renderer preserves that order.

## Rendering

`bridge/panes/group_pane.py` is a `prompt_toolkit` full-screen `Application`.

### Row layout

Terminal width `W = shutil.get_terminal_size().columns` per frame.

```
[ HP bar ][ Mana bar ][ MP bar ]   total = W
```

Three bars fill the entire row with no name prefix column and no separator
spaces between bars. Bar widths are distributed left-to-right using the same
round-extra helper as the buffs pane (adapted for 3 bars):

```python
base   = W // 3
extra  = W %  3
widths = [base + (1 if i < extra else 0) for i in range(3)]
```

At narrow widths bars become very small or zero; content is simply chopped
(ADR 0023 spirit). No graceful degradation in this phase.

### Bar fill rounding

```python
fill = int(pct * bar_w + 0.5)   # round-half-up; do NOT use Python round()
```

`int(x + 0.5)` is always round-half-up. Python's `round()` uses banker's
rounding, which produces inconsistent bar widths at the 50 % boundary.

For null `*_pct`: `fill = 0` (empty bar, no overlay text colouring).

### Threshold colours

The same threshold is applied uniformly to all three bars:

| Condition           | Bar BG    |
|---------------------|-----------|
| `pct <= 0.25`       | `#e02020` |
| `0.25 < pct ≤ 0.45` | `#ff7020` |
| `pct > 0.45`        | default   |
| `pct is null`       | default   |

Default colours:

| Bar  | BG        |
|------|-----------|
| HP   | `#0a8a30` |
| Mana | `#1f5fcc` |
| MP   | `#a07030` |

> **Note — MP thresholds:** MP bands in `group_collector.lua` are still
> placeholder (calibration pending server data; see ADR 0052). At band
> boundaries the midpoint may misclassify — the renderer applies the
> ≤45 %/≤25 % threshold on whatever `mp_pct` it receives. Mis-categorisation
> is visible (orange or red MP bar) and accepted; it is not hidden.

### Name overlay (full row)

The member `name` is left-aligned from column 0 across the row (`W` columns),
truncated to `W` chars without an ellipsis:

```python
name_trunc = name[:W]
name_start = 0
name_end   = len(name_trunc)
```

At narrow widths a long name visibly extends across HP / Mana / MP bar
boundaries. Per-character style is determined by which bar the column falls in
and whether that column is within the bar's fill:

| Column position         | FG        | BG           |
|-------------------------|-----------|--------------|
| `local < bar_fill`      | `#000000` | that bar's BG|
| `local >= bar_fill`     | `#cccccc` | terminal BG  |

When `member.name` is `null` in the state file, no overlay is rendered
(all columns follow plain-bar fill rules with spaces).

### Overflow indicator

When the number of members exceeds the pane height `H`:

```
↓ N more members
```

rendered in `fg:#d4a04e italic` in a 1-row `ConditionalContainer` below the
member list. `N = total − (H − 1)`. The list shows the first `H − 1` members
(anchor-top). No upward-scroll variant in this phase.

When members is empty the pane renders nothing (empty space).

## Polling cadence

`os.stat(group.state).st_mtime` is checked every **100 ms** via an asyncio
task. On mtime change: reload JSON, call `app.invalidate()`. Same pattern as
`buffs_pane.py`. Atomic-write semantics (`.tmp` → `os.rename`) on the producer
side ensure no partial reads.

## Position

Right column (top to bottom): `status` → `buffs` → **`group`** → `comm` →
`ui` → `dev`.

When a subset of right panes is open, ordering is preserved — group always
sits directly below buffs (when buffs is open) or below status (when buffs is
closed and status is open), and above comm (when comm is open). Toggling other
right panes in any order does not break the vertical order.

## Default height

`group_height=4` in `bridge/runtime/layout.conf` (documented intent only).
Per [ADR 0030](decisions/0030-right-column-heights-free.md), right-column
heights are tmux-managed at creation (equal-share among siblings) and are
freely user-resizable. No height is enforced on open or apply-layout.

## Pane title and border

Pane title: `group`. The `pane-border-format` in
`bridge/launcher/tmux_start.sh` maps this to the label ` Group ` when headers
are on (`cp -h`).

## Toggle

| Method                  | Mechanism                                        |
|-------------------------|--------------------------------------------------|
| `cp -g`                 | `toggle_pane.sh group --persist`                 |
| GRP button              | `toggle_pane.sh group --persist`                 |
| Launcher Options        | `_save_conf` → `startup.conf show_group`         |
| In-game popup → Options | `toggle_pane.sh group --persist`                 |

## Persistence key

`show_group` in `bridge/runtime/startup.conf`. Fresh-install default is `0`
(pane closed). Existing installs without the key fall through to the
`${show_group:-0}` runtime guard — no migration needed.

---
Back to [architecture.md](../architecture.md).
