# Group Pane

A `prompt_toolkit` full-screen application that renders `state.group.members`
as three horizontal bars per member (HP / Mana / Moves), with the member name
left-aligned as an overlay starting from column 0. Anchor-top; overflow
indicator when the pane is shorter than the member list.

## Architecture

```
lua/core/group_collector.lua ──► state.group.members ──────────────────┐
                              └──► state.group.unlabeled ───────────────┤
                                         │                              │
                             group_changed / char_reset events          │
                                         │                              ▼
                                         └───────────► lua/core/group_state.lua ──► bridge/runtime/group.state (JSON)
                                                                                │   (members + unlabeled_npcs)
                                                                      mtime poll (100 ms)
                                                                                │
                                                                                ▼
                                                                    bridge/panes/group_pane.py
```

`group_state.lua` serialises `state.group.members` (and `state.group.unlabeled`
as a separate `unlabeled_npcs` array) to `bridge/runtime/group.state` on every
`group_changed` or `char_reset` event, and once at load time. `group_pane.py`
polls that file and renders the member list, appending the unlabeled NPCs only
in `group_npc_mode == "all"`.

## State-file schema (`bridge/runtime/group.state`)

Source of truth: [`lua/core/group_state.lua`](../lua/core/group_state.lua).

The file is a JSON object with two top-level arrays:

```json
{"members": [ ... ], "unlabeled_npcs": [ ... ]}
```

`members` is the canonical renderable set (allies and labeled NPCs).
`unlabeled_npcs` is the serialised projection of `state.group.unlabeled` —
the unlabeled group-NPCs (charmies, pets, mounts, not-yet-labeled mercenaries)
held off the membership set. Both arrays carry the **same per-member shape**
(`id`, `type`, `name`, `label`, raw vitals, and `*_pct` / `*_known` fields)
and are independently id-sorted, produced by the shared
`serialize_member` / `serialize_set` in
[`group_state.lua`](../lua/core/group_state.lua). The renderer appends
`unlabeled_npcs` to the displayed set only in `group_npc_mode == "all"`
(see [Display options](#display-options)).

Each entry contains the raw vitals (`hp`, `maxhp`, `mana`, `maxmana`,
`mp`, `maxmp`), their band-string equivalents (`hp_string`, `mana_string`,
`mp_string`), and the pre-computed percentages used by the renderer. The
table below is **non-exhaustive** — it lists the fields the renderer reads,
all already serialised by [`group_state.lua`](../lua/core/group_state.lua):

| Field        | Type           | Meaning                                                  |
|--------------|----------------|----------------------------------------------------------|
| `id`         | `number`       | Transient GMCP presence handle; members are sorted ascending by it (ADR 0096) |
| `type`       | `string`       | `"ally"` (player) or `"npc"`; the renderer keys on it both to choose the displayed subset and to gate the `(LABEL)` overlay |
| `name`       | `string\|null` | Generic name (species string for NPCs, character name for allies); the overlay base |
| `label`      | `string\|null` | NPC player-facing name (e.g. mercenary's given name); appended as `Name (LABEL)` for `type=="npc"` only — never for allies |
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
| HP   | `#005A18` |
| Mana | `#0000AA` |
| MP   | `#5A3C1E` |

**Light-terminal bar fills.** On a light ("paper") terminal the three deep
default fills above read as heavy saturated blocks. When
`pane_frame.pane_is_light("group")` is true the three `*_DEFAULT_BG` values are
run through `pane_frame.washout()` — hue kept, saturation scaled down, lightness
raised — so they render as soft pastels (`#90d5a2` / `#9090d5` / `#c4b2a1`) that
sit gently on the canvas. The threshold `RED_BG` / `ORANGE_BG` are **left vivid**
so a low-vital bar still pops. On a dark terminal `pane_is_light` is false and all
bar colours pass through byte-for-byte unchanged. The washout decision and the
washed fills are resolved **per render** by `_resolve_colors()` (top of
`_rows_text`, stored in `_bar_bgs` for `_member_frags`), so a **live** pane-colour
change (popup → tmux re-applies bg; `pane_frame.start_poll` refreshes the cached
colours and invalidates) flips the treatment within a frame.
See [docs/pane-frame.md](pane-frame.md#washouthexcolor-l_target70-s_scale045).

### Name overlay (full row)

The member overlay text is left-aligned from column 0 across the row (`W`
columns), truncated to `W` chars without an ellipsis. The overlay text is
keyed on `type`:

- `type == "npc"` with a non-empty string `label` → `Name (LABEL)`, so a
  labeled NPC (key NPC, hired mercenary) shows both its generic species
  `name` and its player-facing `label` (e.g. `citizen mercenary (Aragorn)`).
- every other member — allies, and NPCs whose `label` is `null`, empty, or
  not a string → the bare `name`. **Players are never labeled.**

```python
name = member.get("name") or ""
if member.get("type") == "npc":
    label = member.get("label")
    if isinstance(label, str) and label:
        name = f"{name} ({label})"
```

At narrow widths a long name visibly extends across HP / Mana / MP bar
boundaries. Per-character style is determined by which bar the column falls in
and whether that column is within the bar's fill:

| Column position         | FG       | BG           |
|-------------------------|----------|--------------|
| `local < bar_fill`      | `C_NAME` | that bar's BG|
| `local >= bar_fill`     | `C_NAME` | terminal BG  |

The FG is intentionally uniform across both regions; only the BG distinguishes
name characters on the fill from those past it. The earlier black-on-fill /
light-grey-on-empty cutout was abandoned because black lost contrast on the
deeper default bar colours.

`C_NAME` is derived **per render** (in `_resolve_colors`, top of `_rows_text`)
from the group pane's shade ramp —
`"fg:" + pane_frame.pane_shades("group")["vtext"]` — rather than a flat grey, so a
live pane-colour change re-resolves it within a frame. The ramp's `vtext` role is
light on a dark terminal and a dark, bg-tinted shade on a light terminal, so a
single style gives both variants automatically: on a dark
terminal the name reads as the familiar light grey; on a "paper" terminal it
reads as a dark shade tinted toward the canvas (legible on both the pastel-filled
and empty regions) instead of a washed-out flat `#aaaaaa`.

When `member.name` is `null` or empty in the state file, no overlay is
rendered (all columns follow plain-bar fill rules with spaces).

### Overflow indicator

When the number of **displayed** members (see [Display options](#display-options))
exceeds the pane height `H`:

```
↓ N more members
```

rendered in `fg:#d4a04e italic` in a 1-row `ConditionalContainer` below the
member list. `N = total − (H − 1)`, where `total` is the count of the
displayed set. Both the list slicing and this overflow count operate on the
displayed set, not the raw `members`. The list shows the first `H − 1`
displayed members (anchor-top). No upward-scroll variant in this phase.

When the displayed set is empty the pane renders nothing (empty space).

## Display options

The renderer applies a user-controlled display filter over the raw member
set. Two `startup.conf` keys drive it:

| Key                  | Values                          | Default     | Effect |
|----------------------|---------------------------------|-------------|--------|
| `group_show_players` | `1` / `0`                       | `1`         | `0` hides allies (players) |
| `group_npc_mode`     | `labeled` / `off` / `all`       | `labeled`   | `off` hides NPCs; `all` additionally shows unlabeled group-NPCs; any unknown value normalises to `labeled` |

**Live re-read.** The pane stat-s `startup.conf`'s mtime on its 100 ms poll
(alongside the existing `connection.state` check); on change it calls
`_read_display_options()`, which re-parses the two keys and invalidates the
app. A missing file or missing key falls through to the runtime defaults
(players-on / NPC-labeled), so edits from either Options surface show within
a tick — no restart.

**Renderer-side subset.** The displayed set is computed by
`_displayed_members()`, a presentation-only filter over `members`:

- `type == "ally"` — kept iff `group_show_players` is on;
- `type == "npc"` — kept iff `group_npc_mode` is not `off`;
- any other / unknown type — kept (defensive parity with the collector).

In `group_npc_mode == "all"`, `_displayed_members()` additionally appends the
unlabeled set (`_unlabeled`, loaded from the state file's `unlabeled_npcs`
array) to the displayed members. The combined set is then id-sorted, so
members and unlabeled NPCs interleave by `id`. Unlabeled NPCs render as the
bare `name` (no `(LABEL)` overlay) — by definition they have no label.

Membership stays canonical in the collector: `state.group.members` (and the
serialised `members` list) is the full renderable set — the filter never
changes it, only what this pane draws. The unlabeled set is a separate
serialised list, never merged into `members`. See
[ADR 0139](decisions/0139-group-pane-display-filter-renderer-side.md) and
[ADR 0140](decisions/0140-unlabeled-npcs-for-all-mode.md). All list slicing
and the overflow count above run on the displayed set.

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

`desired_group=6` in `bridge/runtime/layout.conf` (content rows, excludes
title row). Cold start and WINCH size the pane from this value via the
per-pane allocation algorithm in [ADR 0071](decisions/0071-per-pane-desired-heights.md);
mid-session drag adjusts the height freely and the new value persists as
the next `desired_group` via `on_pane_resize.sh`. `cp -reset-heights`
restores the shipped default.

## Pane frame

Pane title: `group`. The pane carries an in-pane frame (a header row plus a
half-block border) drawn by `pane_frame`, replacing the old tmux
`pane-border-status` header. Content renders within `inner_width` /
`inner_height` (`W-2` / `H-2` when the border is on, full size when off); the
header label is `Group`; the border is per-pane, toggled by `border_group` in
`startup.conf`. See [docs/pane-frame.md](pane-frame.md) for the frame shape,
border colour, and the `border_<key>` contract.

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

The two [Display options](#display-options) keys (`group_show_players`,
`group_npc_mode`) live in the same `startup.conf`, written by the
**Options → Panes → Group** page on both surfaces — the in-game popup
persists each edit immediately and live (the running pane re-reads on its
poll), while the launcher defers the write to Back / ESC and the effect to
the next cockpit start. Both are seeded in
`bridge/launcher/templates/startup.conf` (`group_show_players=1`,
`group_npc_mode=labeled`); a missing key falls through to the runtime
defaults. See [docs/popup-menu.md](popup-menu.md#group-submenu) and
[docs/launcher.md](launcher.md#group-options-model).

---
Back to [architecture.md](../architecture.md).
