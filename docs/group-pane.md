# Group Pane

A `prompt_toolkit` full-screen application that renders `state.group.members`
as three horizontal bars per member (HP / Mana / Moves), with the member name
centred over the mana bar. Anchor-top; overflow indicator when the pane is
shorter than the member list.

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
[NAME 12] [space] [HP bar] [space] [Mana bar] [space] [MP bar]
```

Three bar widths share the residual `W − 12 − 3` columns distributed
left-to-right with the same round-extra helper:

```python
residual = W - 12 - 3
base     = residual // 3
extra    = residual %  3
widths   = [base + (1 if i < extra else 0) for i in range(3)]
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

| Condition          | Bar BG    | Bar FG (▌) |
|--------------------|-----------|------------|
| `pct <= 0.25`      | `#d92020` | `#d92020`  |
| `0.25 < pct ≤ 0.45`| `#ff8c00` | `#ff8c00`  |
| `pct > 0.45`       | default   | default    |
| `pct is null`      | default   | default    |

Default colours:

| Bar  | BG       | FG (▌)   |
|------|----------|----------|
| HP   | `#00b050`| `#00b050`|
| Mana | `#2a7fff`| `#2a7fff`|
| MP   | `#d4a020`| `#d4a020`|

> **Note — MP thresholds:** MP bands in `group_collector.lua` are still
> placeholder (calibration pending server data; see ADR 0052). At band
> boundaries the midpoint may misclassify — the renderer applies the
> ≤45 %/≤25 % threshold on whatever `mp_pct` it receives. Mis-categorisation
> is visible (orange or red MP bar) and accepted; it is not hidden.

### ▌ marker

When `fill >= bar_w` (visually full), the rightmost column renders `▌` in the
bar's FG colour with no background. Otherwise that column is a plain space
following the normal fill rule. Adjacent empty bars merge visually on any
terminal background.

### Name overlay (mana bar only)

The member `name` is centred horizontally in `bar_mana_w` columns, truncated
to `bar_mana_w` chars without an ellipsis:

```python
name_str = name[:bar_mana_w].center(bar_mana_w)[:bar_mana_w]
```

Per-column colour split against the mana fill boundary:

| Column position | FG        | BG           |
|-----------------|-----------|--------------|
| `col < fill`    | `#000000` | mana bar BG  |
| `col >= fill`   | `#cccccc` | terminal BG  |

When `fill >= bar_mana_w`, the last column shows `▌` in mana FG (no BG),
overriding any name character or space at that position.

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

Right column (top to bottom, planned): `status` → `buffs` → **`group`** →
`comm` → `ui` → `dev`. Fas 7 wires it between the buffs and comm panes.

## Default height

TBD in fas 7 (`group_height` key in `bridge/runtime/layout.conf`).

## Toggle

TBD in fas 7:

| Method                  | Mechanism                                        |
|-------------------------|--------------------------------------------------|
| `cp -g`                 | `toggle_pane.sh group --persist`                 |
| GROUP button            | `toggle_pane.sh group --persist`                 |
| Launcher Options        | `_save_conf` → `startup.conf show_group`         |
| In-game popup → Options | `toggle_pane.sh group --persist`                 |

---
Back to [architecture.md](../architecture.md).
