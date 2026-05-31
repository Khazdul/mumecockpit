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
| `label`      | `string\|null` | Player-facing name override (e.g. mercenary's given name); preferred by the renderer when non-null |
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
round-extra helper as the timers pane (adapted for 3 bars):

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
| HP   | `#0FA838` |
| Mana | `#0F38B0` |
| MP   | `#8A7838` |

### Name overlay (full row)

The member overlay text is left-aligned from column 0 across the row (`W`
columns), truncated to `W` chars without an ellipsis. The overlay prefers
`label` over `name` — labeled NPCs (key NPCs, hired mercenaries) display
their player-facing label rather than the generic `name`:

```python
overlay = member.get("label") or member.get("name") or ""
```

At narrow widths a long name visibly extends across HP / Mana / MP bar
boundaries. Per-character style is determined by which bar the column falls in
and whether that column is within the bar's fill:

| Column position         | FG        | BG           |
|-------------------------|-----------|--------------|
| `local < bar_fill`      | `#000000` | that bar's BG|
| `local >= bar_fill`     | `#cccccc` | terminal BG  |

When both `member.label` and `member.name` are `null` in the state file, no
overlay is rendered (all columns follow plain-bar fill rules with spaces).

### Overflow indicator

When the number of members exceeds the pane height `H`:

```
↓ N more members
```

rendered in `fg:#d4a04e italic` in a 1-row `ConditionalContainer` below the
member list. `N = total − (H − 1)`. The list shows the first `H − 1` members
(anchor-top). No upward-scroll variant in this phase.

When members is empty the pane renders nothing (empty space).

## Inactive run

When `bridge/runtime/connection.state` is absent, every text provider
(`_rows_text`, `_indicator_text`) returns blank fragments and the overflow
indicator is suppressed via the same `_run_active` flag. Pane structure
(size, splits, tmux borders, `cp -h` header status) is unchanged. The flag is
updated by the existing 100 ms poll loop on each tick.

## Polling cadence

`os.stat(group.state).st_mtime` is checked every **100 ms** via an asyncio
task. On mtime change: reload JSON, call `app.invalidate()`. Same pattern as
`timers_pane.py`. Atomic-write semantics (`.tmp` → `os.rename`) on the producer
side ensure no partial reads.

## Position

Right column (top to bottom): `status` → `timers` → **`group`** → `comm` →
`ui` → `dev`.

When a subset of right panes is open, ordering is preserved — group always
sits directly below timers (when timers is open) or below status (when timers is
closed and status is open), and above comm (when comm is open). Toggling other
right panes in any order does not break the vertical order.

## Default height

`desired_group=5` in `bridge/runtime/layout.conf` (content rows, excludes
title row). Cold start and WINCH size the pane from this value via the
per-pane allocation algorithm in [ADR 0071](decisions/0071-per-pane-desired-heights.md);
mid-session drag adjusts the height freely and the new value persists as
the next `desired_group` via `on_pane_resize.sh`. `cp -reset-heights`
restores the shipped default.

## Pane title and border

Pane title: `group`. The `pane-border-format` in
`bridge/launcher/tmux_start.sh` maps this to the label ` Group ` when headers
are on (`cp -h`).

## Toggle

| Method                  | Mechanism                                        |
|-------------------------|--------------------------------------------------|
| `cp -g`                 | `toggle_pane.sh group --persist`                 |
| Launcher Options        | `_save_conf` → `startup.conf show_group`         |
| In-game popup → Options | `toggle_pane.sh group --persist`                 |

## Persistence key

`show_group` in `bridge/runtime/startup.conf`. Fresh-install default is `1`
(pane open), seeded by `bridge/launcher/templates/startup.conf` (see
ADR 0101). Existing installs without the key fall through to the
`${show_group:-1}` runtime guard, so older `startup.conf` files that pre-date
this key will open the pane on the next cockpit start. This is no longer a
per-pane exception: as of ADR 0101 every right-column pane defaults on
except the developer pane, so the no-surprise-on-upgrade waiver is now
applied uniformly.

---
Back to [architecture.md](../architecture.md).
