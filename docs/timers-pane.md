# Timers Pane

A `prompt_toolkit` full-screen application that renders `state.char.affects`,
`state.char.stored_spells`, `state.char.blinds`, `state.char.charms`, and
`state.char.herblores` as a colour-coded grid grouped by type (spells, buffs,
debuffs, stored, blinds, charms; herblores fold into the buffs/debuffs groups),
with bar-drain animation, optional per-type countdown overlay, and row-based
scroll. Each group's colour, per-group column count, and visibility are read
from [`bridge/runtime/timers_layout.conf`](#layout-config-timers_layoutconf);
with no config file present every value falls back to the historic hardcoded
behaviour. Touch this file when changing the renderer, the pane position, or the
toggle wiring.

## Architecture

```
lua/core/affects.lua ──► state.char.affects ──────────────────────┐
                                │                                  │
                    affects_changed event                          │
                                │                                  ▼
lua/core/stored_spells.lua ──► state.char.stored_spells    lua/core/timers_state.lua ──► bridge/runtime/timers.state (JSON)
                                │                                  ▲           │
                    stored_spells_changed event ───────────────────┤    mtime poll (100 ms)
                                                                   │            │
lua/core/blinds.lua ──► state.char.blinds                          │            ▼
                                │                                  │  bridge/panes/timers_pane.py
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

`timers_state.lua` serialises `state.char.affects`,
`state.char.stored_spells`, `state.char.blinds`, `state.char.charms`, and
`state.char.herblores` to `bridge/runtime/timers.state` on every
`affects_changed`, `stored_spells_changed`, `blinds_changed`, `charms_changed`,
or `herblores_changed` event, on character reset (disconnect), and on login.
`timers_pane.py` polls that file and renders the grid.

## State file schema (`bridge/runtime/timers.state`)

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
    {"id": 7, "name": "orc",              "started_at": 1714000000, "expires_at": 1714005940, "expected_duration": 5940},
    {"id": 8, "name": "enslaved shadow",  "started_at": 1714000300, "expires_at": null,       "expected_duration": null}
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
The serialiser emits both fields (mirroring blinds), `null` for permanent
entries. **Permanent** control-without-charm entries (`enslaved shadow`,
`dreadful warg`) carry `expires_at: null`; the pane keys off its absence to show
no minutes and let the name reclaim the time block's columns (see "Charm
group"). `id` is the monotonic per-session id the click-to-drop × targets. A
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

## Layout config (`bridge/runtime/timers_layout.conf`)

Per-group colour, column count, and visibility are read from a small
`key=value` file (one pair per line, same trivial format as
`bridge/runtime/startup.conf`). The `TIMERS_LAYOUT_PATH` env var overrides the
path (mirroring `TIMERS_STATE_PATH`). The file is **optional** — with no file
present, or any individual key missing, the renderer falls back to the defaults
below, which reproduce the historic hardcoded grid exactly. The
companion launcher/popup "Timers layout" menu writes this file; the pane
only reads it. The menu's grid + stepper render and its copy of the
defaults / cols-clamp live in `bridge/launcher/timers_layout_grid.py` —
the defaults below are deliberately restated there because the
`bridge/launcher` and `bridge/panes` packages share no import path (see
[docs/launcher.md](launcher.md#timers-layout-submenu) and
[ADR 0126](decisions/0126-timers-layout-menu.md)). Keep the two copies
in sync.

Type tokens: `spell`, `buff`, `debuff`, `stored`, `blind`, `charm`. Keys per
type:

```
timers_<type>_enabled = 0 | 1
timers_<type>_color   = #rrggbb
timers_<type>_cols    = <int>
timers_<type>_clock   = 0 | 1     # per-type, default 0
timers_headers        = 0 | 1     # global, not per-type (default 1)
timers_compact        = 0 | 1     # global, not per-type (default 1)
```

`timers_headers` and `timers_compact` are **independent global** toggles, not
per-type keys. Because neither has a second underscore, every reader branches on
the exact key *before* the type-split (which would otherwise drop it); absent or
unparseable → default `1`.

- `timers_headers` (default `1`) governs the per-group dim `Group:` label row:
  `1` renders it above each rendered group, `0` omits it.
- `timers_compact` (default `1`) governs the blank separator between groups:
  `1` is compact (no blank lines), `0` inserts one blank row between consecutive
  rendered groups (none above the first or below the last).

The four combinations:

| headers | compact | layout |
|---------|---------|--------|
| 1 | 1 | header + content per group, no blank lines (the default / historic look) |
| 1 | 0 | header + content per group, blank line between groups |
| 0 | 1 | content only, fully dense |
| 0 | 0 | content + blank line between groups, no headers |

Defaults (reproduce today's behaviour exactly):

| type   | enabled | color     | cols | clock |
|--------|---------|-----------|------|-------|
| spell  | 1       | `#66b2ff` | 4    | 0     |
| buff   | 1       | `#00d900` | 4    | 0     |
| debuff | 1       | `#d90000` | 4    | 0     |
| stored | 1       | `#ff66ff` | 4    | 0     |
| blind  | 1       | `#00cccc` | 2    | 0     |
| charm  | 1       | `#B388FF` | 1    | 0     |

**Parse rules.** Per-type `cols` clamps on read: `charm` → `[1, 2]`; all others →
`[1, 6]`; floor `1`. Per-type `clock` parses `0`/`1` like `enabled` (absent /
unparseable → `0`). Unknown keys are ignored. An unparseable value (bad hex, a
non-integer `cols`, an `enabled` or `clock` that is not `0`/`1`) falls back to
that key's default rather than failing the whole file. Note: `charm` carries the
`clock` key in the defaults but the pane never reads it (Charmies show no
countdown — they have their own count-up).

**Live re-read.** The poll loop tracks `timers_layout.conf`'s mtime alongside
`timers.state`'s; on change it re-reads and invalidates, so a colour / cols /
enabled / headers / compact edit re-colours, re-lays-out, toggles headers or the
blank separators, or hides the matching group within ~100 ms with no restart. An
absent file is treated as defaults, no crash.

**What the colour drives.** Each group's filled-cell style is `fg:#000000 bg:<hex>`
and its separator is `fg:<hex>`. The charm group has no bar — its `color` themes
only the **name** foreground; the drop × stays `#CC5555` and the minutes stay
grey. Untracked Stored cells stay fixed grey (`#cccccc`) regardless of the
`stored` colour — the grey is a degraded-state signal (post magic-blast), not a
theme choice.

**Disabling a group** (`enabled = 0`) drops all of its rows. Because herblores
fold into the buff/debuff groups, disabling `buff` or `debuff` also hides their
herblores.

## Rendering

`bridge/panes/timers_pane.py` is a `prompt_toolkit` full-screen `Application`.

### Grouping

Groups are rendered top-to-bottom (a group renders iff enabled and non-empty).
Empty groups produce no rows. Two independent global toggles shape the layout
(see [Layout config](#layout-config-timers_layoutconf)):

- `timers_headers` — when on (the default), a single dim `Group:` label row
  (`C_GROUP_HEADER_FG`, `fg:#606060`, fg only so it renders on the pane bg tint —
  the same mid grey as the status pane's data-row labels, `status_pane.C_LABEL`;
  keep the two in sync) is emitted immediately above each rendered group's
  content, including the first.
- `timers_compact` — when off, a single blank row is emitted before each rendered
  group except the first (`n_rendered - 1` separators), so consecutive groups are
  visually separated. When on (the default), no blank rows.

Per rendered group, `_build_all_rows` emits in order: the blank separator (if
compact is off and not the first group), the header row (if headers are on), then
the content rows. `_build_all_rows` and `_total_rows` derive their placement and
counts from the same `_rendered_groups` list:

```
content = sum(content rows per rendered group)
headers = n_rendered          if headers on    else 0
blanks  = n_rendered - 1      if compact off   else 0   (and n_rendered > 0)
_total_rows = content + headers + blanks
```

so the overflow indicator, scroll clamp, and charm-corner yield stay in lockstep.
The charm corner-yield is unaffected: `charm_content_rows` stays content-only, and
since charm is the last rendered group, its header (if on) and the blank before it
(if compact off) are counted in `_total_rows` and sit before the charm content, so
`_scroll_offset >= first_charm_row` still means a charm content row is topmost.

| Group   | Source          | Condition                                          |
|---------|-----------------|----------------------------------------------------|
| Spells  | `affects`       | `type == "spell"`                                  |
| Buffs   | `affects` + `herblores` | `type` is neither `"spell"` nor `"debuff"` |
| Debuffs | `affects` + `herblores` | `type == "debuff"`                         |
| Stored  | `stored_spells` | all entries (tracked and untracked)                |
| Blinds  | `blinds`        | all entries                                        |
| Charm   | `charms`        | all entries (one per row, after Blinds)            |

Each group lays out up to `layout[type].cols` entries per row. The configured
`cols` is a **ceiling, not a fixed division**: a group renders
`effective_cols = min(layout[type].cols, max(1, n_items))` columns, so a group
with fewer items than its cap fills the width with that many columns (a lone item
spans the full width); only at or above the cap does it use the full cap, with
extra rows. `effective_cols` is computed once per rendered group inside
`_rendered_groups` (via `_effective_cols`) and returned as the third tuple field,
so `_build_all_rows`, `_total_rows`, and the charm-corner yield all share the same
value and stay in lockstep. The shipped caps are 4 for spells/buffs/debuffs/stored,
2 for **Blinds**, and 1 for **Charm** (see
[Layout config](#layout-config-timers_layoutconf)); the layout menu's "Cols" digit
shows the cap even when the pane currently renders fewer columns because there are
fewer items — that is expected, not a bug. A group with
`layout[type].enabled == 0` produces no rows at all.

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

Terminal width `W = _term_cols()`, height `H = _term_rows()`, `n` cells per row
(`n = effective_cols` for the group — the cap min the item count; see
[Grouping](#grouping)).

Cell width distribution (left to right) is computed by the shared `_cell_widths(W, n)`:

```
base   = W // n
rem    = W % n
widths = [base + 1] * rem + [base] * (n - rem)
```

This single parameterised helper replaces the former 4-hardcoded path and the
2-hardcoded blind helper; every group (including Blinds and Charm) lays out
through it with its own `n`.

Each cell occupies `cell_w` columns: `(cell_w - 1)` characters of
`NAME.upper()[:cell_w-1].ljust(cell_w-1)` followed by the `▌` separator —
**with two exceptions** (see [Right edge and corner](#right-edge-and-corner)):
the rightmost-**column** timed clock cell drops the trailing separator and uses
the full `cell_w` so the countdown reaches the cell's right edge, and the
topmost-visible row's rightmost-column cell keeps a one-column trailing blank so
the corner `+` Float floats over the blank rather than over the countdown.
Empty slots on a partial last row are omitted — the row ends after the last
populated cell's separator.

### Countdown (Clock)

When `timers_<type>_clock` is on, each **timed** cell of that type overlays a
right-justified countdown on the existing drain bar; the name stays left.
`_clock_content` composes the two over the cell's content columns via a Tier
A/B/C width ladder:

- **Tier A** — full name + a gap + the time (name and time both fit with a
  separating space).
- **Tier B** — clipped name + time flush, no gap (the time still fits but the
  gap does not).
- **Tier C** — name only, time dropped (the cell is too narrow for any time).

The countdown characters inherit the same fill-aware styling as the name (black
on the filled portion of the bar, depleted grey past the fill) — no new colour.

**Format (`_countdown_str`).** Remaining `<= 90 s` → whole seconds (`"Ns"`:
`3s`, `90s`). Remaining `> 90 s` → minutes rounded to the **nearest** minute,
half up, via integer `(secs + 30) // 60` (`"Nm"`). Examples: `91s → 2m`,
`130s → 2m`, `150s → 3m`. `"1m"` never appears (91 s is the first value above
the 90 s seconds-band, and it already rounds to `2m`). Clamped at `0s`.

Only timed cells show a countdown. Charm (its own count-up), indefinite
affects, and untracked entries never do, even with their type's clock on.

### Right edge and corner

Two layout exceptions to the standard `(cell_w - 1)` chars + `▌` separator cell
shape, both for clock cells reaching the pane's right edge:

- **Rightmost column.** The rightmost-**column** timed clock cell uses the full
  `cell_w` (no trailing separator) so the countdown reaches the cell's right
  edge. A **lone** last cell that is **not** in the rightmost column keeps its
  separator and right-aligns its countdown with the column above it.
- **Corner reserve.** The topmost-visible row's rightmost-column cell sits under
  the corner `+` Float (pinned at `top=0, right=0`; see "The corner control"
  below). It keeps a one-column trailing
  blank so the `+` floats over the blank, not over the countdown. The reserve is
  **scroll-aware** — it follows whichever row is topmost, threaded as
  `corner_row` through `_grid_text → _build_all_rows → _group_rows →
  _cell_frags`.

### Blinds two-up layout

The Blinds group ships with a **2-cell cap** (the `blind` cols default) so the
wider mob names fit. The cell content is identical to every other group's, so the
Blinds branch of `_build_all_rows` reuses the shared `_cell_frags` renderer and
the shared `_cell_widths(W, n)` helper; it just passes `n = effective_cols`. The
cap is configurable like every other group (clamped to `[1, 6]`); 2 is only the
default. Because the cap is a ceiling, a **lone blind spans the full width**
(`effective_cols = min(2, 1) = 1`) rather than taking a half-width cell with a
blank beside it.

Each block occupies `cell_w` columns with the standard cell content —
`NAME.upper()[:cell_w-1].ljust(cell_w-1)` plus the `▌` separator — and inherits
the timed-cell drain (`filled = int(pct * cell_w + 0.5)`), the Blinds palette
(`#00cccc` fill / `#000000` fg / `#00cccc` separator), the depleted-grey
(`#C0C0C0`, the status-pane value grey `status_pane.C_VALUE`, RGB 192,192,192),
and the separator rule, all unchanged.

Narrowing the pane truncates the name from the right
(`PACK HORSE` → `PACK HO` → `PA`). An odd blind count leaves a single block on
the last row; the row ends after that block's separator.

### Charm group

The Charm group renders **with no bar**, up to `layout["charm"].cols` cells per
row (default cap 1, clamped to `[1, 2]`). Each cell (`_charm_cell_frags(entry,
cell_w, name_fg)`) is laid out, over its `cell_w` from
`_cell_widths(W, effective_cols)`, as:

```
<name, left-justified>  <mins, right-justified width 3>  ×
```

At an effective 1 column each cell spans the full width and the result is
identical to the historic one-per-row layout — so a **lone charm** at cap 2 also
spans the full width (`effective_cols = min(2, 1) = 1`). At an effective 2 columns
charmies lay out two per row
(mirroring the blinds two-up branch); each cell's × carries its own drop handler
for that charm's id, with per-cell hover via `_hover_charm_id`.

- **Name** — themed from `layout["charm"].color` (default light violet `#B388FF`).
  The **first letter is capitalised** and the inner case is preserved (mob
  long-names like `huge stone troll` → `Huge stone troll`), unlike the grid
  groups which upper-case the whole label.
- **Minutes** — light grey `#C0C0C0` (fixed, not themed; matches the depleted-bar
  text `C_NAME_DEPLETED`), a count-**up** rendered
  as `Nm` right-justified in 3 columns (`" 0m"` … `"99m"`), computed as
  `min(99, int((now - started_at) // 60))` and capped at 99. Shown only for
  **timed** entries. A **permanent** controlled mob (`expires_at: null`) shows
  **no** minutes block at all — its name reclaims those columns (see "Layout
  split" below), so there is no blank gap (`Enslaved shadow ×`, not
  `Enslaved sh    ×`).
- **×** — a clickable drop control in muted red `#CC5555` (fixed, not themed),
  brightening to `#E88888` while the pointer hovers over it (the
  `_hover_charm_id` cue).

**Layout split.** The cell layout branches on **timed vs permanent**, not on
width. The × always sits in the cell's right-most column in both branches (the
charm-corner yield depends on the rightmost cell's × at `top=0,right=0`):

- **Timed** (`expires_at` present) and `cell_w >= 7`: `name_w = cell_w - 6`, then
  `name · " " · Nm · " " · ×`. The count-up is always shown; the name truncates
  from the right as the cell narrows
  (`Pack horse 21m ×` → `Pac 21m ×` → `P 21m ×`).
- **Permanent** (`expires_at: null`), OR timed but `cell_w < 7` (rare degenerate):
  `name_w = max(0, cell_w - 2)`, then `name · " " · ×`. No time block — the name
  reclaims the 4 columns the time would have used, so there is no blank gap. In
  practice `cell_w >= ~16` (charm caps at 2 cols; the right column is `>= 33`), so
  a timed cell always takes the count-up branch and the `cell_w < 7` fallback is
  effectively unreachable.

**Click-to-drop.** Clicking the × calls `_send_charm_drop(id)`, which invokes
`_cp_charm_drop <id>` in the game/tt++ pane over the **same** `tmux send-keys`
channel `input_pane.py` forwards keystrokes through (target `mume:cockpit.0`,
one send-keys call with the line and `Enter`). The render loop never blocks on
it; the state file stays authoritative, so the row clears only once tt++ has
run the drop and `timers_state.lua` rewrites `timers.state`. See
[docs/charm.md](charm.md) for the drop handler.

**Known limitation (parked):** the `_cp_charm_drop` command shows up as a
persistent line in the tt++ game scrollback — a tt++ command-echo behaviour not
yet solved. The drop itself works correctly.

The fill/separator BG values below are the **defaults** — each is the
`layout[type].color` for that group and is overridable via
[`timers_layout.conf`](#layout-config-timers_layoutconf). Cell FG is always
`#000000`; the separator FG always tracks the fill colour.

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
| Minutes         | `#C0C0C0` | light grey — count-up `Nm` (matches depleted bar) |
| Drop ×          | `#CC5555` | muted red                                      |
| Drop × (hover)  | `#E88888` | brighter than `#CC5555` — pointer-hover cue    |

Overflow indicator style: `fg:#d4a04e italic`.

## Herblore add-view

The pane has two view modes, held in the module global `_view_mode`
(`"grid"` | `"add"`, default `"grid"`). The `ListControl`'s text provider
(`_list_text`) dispatches: `add` → `_add_view_frags()`, else the grid renderer.
Both modes are mouse-driven — there are **no** keybindings, mirroring the charm
X's click model and authoritative-state rule (see [docs/charm.md](charm.md)).

### Accent colour

The grid + and the add-view × share one accent — a gold foreground glyph on the
terminal/pane background. `C_ACCENT_FG` (`fg:#d4a04e`, the gold of the
overflow indicator), brightening the foreground to `C_ACCENT_HOVER_FG`
(`fg:#f0c070`) on hover. They deliberately do **not** reuse the charm-X red —
only the charm row's drop × is red.

### The corner control (+ / ×)

Both corner glyphs are owned by a single **position-pinned `Float`** at
`top=0, right=0`, not by any row. The root is a `FloatContainer` wrapping the
`HSplit([grid_window, indicator_container])` with one `corner_float`. Its content
is a `ConditionalContainer(filter=Condition(_corner_visible))` wrapping a 1×1
`Window` (`dont_extend_width`/`dont_extend_height`) whose `FormattedTextControl`
calls `_corner_text`. Pinning to the pane's top-right (rather than overlaying the
last cell of the first visible row) keeps the glyph in the true corner even when
a partial first row omits its trailing cells, or the grid is empty.

`_corner_text()` returns:

- `[]` (nothing) when not `_run_active`.
- `[(C_ACCENT_FG, "×", _close_handler)]` in add mode.
- `[]` in grid mode **when the topmost visible row is a charm row** — see below.
- `[(C_ACCENT_FG, "+", _open_handler)]` in grid mode otherwise.

**Yielding the corner to a charm's drop ×.** The + Float pins to `top=0, right=0`,
the same cell a charm row's own × occupies when that row sits at the top of the
grid window. A fixed-size 1×1 `Window` always reserves and paints its cell — even
when `_corner_text` returns `[]`, the blank default-bg surface would sit over the
charm's × and swallow the click. So **visibility is owned by the
`_corner_visible` filter**, not by `_corner_text`: when the filter is `False` the
`ConditionalContainer` collapses to zero size, the Float paints nothing, and the
charm row's own × (already rendered by the grid beneath, with its drop handler)
shows through and stays clickable. `_corner_text` still returns `[]` in the
suppressed case as a belt-and-braces guard.

`_corner_visible()` returns `False` when not `_run_active`, `True` in add mode,
and in grid mode `not _charm_row_at_top()`. The charm-row-at-top test is factored
into `_charm_row_at_top()`, shared by `_corner_visible` and `_corner_text` so the
two never diverge: with `charm_row_count = ceil(len(charms) / charm_cols)` —
where `charm_cols = _effective_cols("charm", len(charms))`, the same cap-min-count
value `_rendered_groups` feeds `_total_rows` — and
`first_charm_row = total_rows - charm_row_count`, it is `True` when charms exist
(and the charm group is enabled) and `_scroll_offset >= first_charm_row`. The +
reappears automatically once the charm group empties, is disabled, or is scrolled
away from the top. The add-view × is unaffected — the add view has no charm rows.
This also covers the case of a player with **only** charmies active (no other
timers): `first_charm_row == 0`, so the corner yields to their first charm × from
the start.

+ (ASCII, U+002B) and × (U+00D7) are single-width, so the 1×1 corner never
over- or under-flows its cell; the close × is the same glyph the charm row uses
to drop.

The fragment carries a gold **foreground** and no background, so the Float
renders the glyph on the terminal/pane background (no filled button). The
underlying bar colour is still not shown in that one corner column — the Float
paints the default bg (accepted). The click handler rides the Float's own
fragment stream.

- + hover via `_hover_plus`; × hover via `_hover_close`. Each handler's
  `MOUSE_MOVE` sets its own hover flag and clears the other's. Hover brightens
  the glyph (gold foreground).
- `_open_handler` (+) `MOUSE_DOWN`: switches `_view_mode` to `"add"`, resets
  `_scroll_offset` to 0, invalidates. `_close_handler` (×) `MOUSE_DOWN`:
  switches back to `"grid"`, resets `_scroll_offset` to 0, invalidates.

### The add-view (`_add_view_frags`)

- **One row per `herblore_catalog` key**, in catalog order: `[+] Name` when the
  key is **not** in the active set, `[-] Name` when it **is**. The active set is
  `{e["key"] for e in herblores}`. The **label** (brackets + sign + name) carries
  `_row_handler` and so is clickable, brightening on hover (`_hover_herblore_key`,
  `C_ADD_ROW_FG` → `C_ADD_ROW_HOVER_FG`). Click: active → remove, else add. The
  trailing right-pad to full width is a **separate, handler-less fragment**: that
  bare surface is what the `ListControl.mouse_handler` fallthrough clears
  `_hover_herblore_key` on, so moving the pointer off a label (sideways into the
  pad, onto another row, or into blank space) clears the highlight — matching the
  grid view. Clicking the empty pad is a no-op. (Leaving the pane via the top edge
  still freezes the last hover — the terminal sends no off-pane events.)
- **The close "×"** is **not** drawn here — the top-right corner `Float` owns it
  (see "The corner control" above). `_add_view_frags` builds only the catalog
  rows; an empty/absent `herblore_catalog` yields no rows (the Float still shows
  the × over a blank pane).
- The view paginates by `_scroll_offset` exactly like `_grid_text` (build all
  rows, slice `[offset : offset + list_height]`).

### Send helper and authoritative state

`_send_herblore(action, key)` mirrors `_send_charm_drop`: one fire-and-forget
`tmux send-keys -t mume:cockpit.0 "<alias> <key>" Enter`, where `<alias>` is
`_cp_herblore_add` (add) or `_cp_herblore_remove` (remove). Catalog keys are
single tokens, so no quoting is needed. There is **no** optimistic UI update —
the `[+]/[-]` label flips on the next poll (~100 ms) once `herblores.lua`
rewrites `timers.state`, same as the charm X.

### Hover and reset

`ListControl.mouse_handler`'s "non-fragment move clears hover" branch clears
`_hover_plus`, `_hover_herblore_key`, and `_hover_close` alongside
`_hover_charm_id`. When `_run_active` transitions True→False (disconnect), the
poll loop resets `_view_mode` to `"grid"`, `_scroll_offset` to 0, and clears
every hover global, so a disconnect mid-add-view returns to the grid.

**Known limitation — off-pane edge.** Leaving the pane via an edge (e.g. moving
up off the corner "+") freezes the last hover cue, because the terminal sends no
mouse events once the pointer is off-pane. This is unavoidable and applies to
every pane; moving anywhere within the pane clears it.

### Untracked affect cells

An affect entry with `tracked == false` (reconciled from `stat`/`info` but
never seen via a real init/refresh string) renders as:

- **Bar fill:** none — no filled cell at all.
- **Name FG:** `#3a3a3a` (darker than the depleted-name grey, so it is
  clearly distinguishable from a tracked timed affect whose bar has
  drained).
- **Separator:** unstyled space (same as the depleted-cell separator).

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

When `filled < cell_w` the name characters render as `fg:#C0C0C0` (the status
pane's `C_VALUE` grey, RGB 192,192,192) on the terminal background. This is
deliberately lighter than the `#606060`
group-header / label grey so a drained bar's name stays clearly legible and
distinct from the headers.

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

- **State poll:** `os.stat(bridge/runtime/timers.state).st_mtime` checked every 100 ms.
  On mtime change: reload JSON, call `app.invalidate()`. The renderer clamps
  `_scroll_offset` on the next frame.
- **Layout-config poll:** `os.stat(bridge/runtime/timers_layout.conf).st_mtime`
  checked on the same 100 ms loop. On change (or first read): re-run
  `_load_layout()` and `app.invalidate()`, so a colour / cols / enabled edit
  takes effect within ~100 ms. An absent file resolves to the defaults.
- **Second tick:** `asyncio` task that sleeps `1.0 - frac + 0.01` seconds,
  waking just after each wall-clock second boundary. Calls `app.invalidate()`
  every cycle so the drain bars **and** the countdowns advance at a uniform
  1 Hz cadence synchronised to wall-clock seconds.

## Position

Right column (top to bottom): `status` → `timers` → `comm` → `ui` → `dev`.

When a subset of right panes is open, ordering is preserved — timers always
sits directly below status (when status is open) and above comm (when comm
is open). Toggling other right panes in any order does not break the
vertical order.

## Default height

`desired_timers=8` in `bridge/runtime/layout.conf` (content rows, excludes
title row). Cold start and WINCH size the pane from this value via the
per-pane allocation algorithm in [ADR 0071](decisions/0071-per-pane-desired-heights.md);
mid-session drag adjusts the height freely and the new value persists as
the next `desired_timers` via `on_pane_resize.sh`. `cp -reset-heights`
restores the shipped default.

## Toggle

| Method                  | Mechanism                                        |
|-------------------------|--------------------------------------------------|
| `cp -t`                 | `toggle_pane.sh timers --persist`                 |
| Launcher Options        | `_save_conf` → `startup.conf show_timers`         |
| In-game popup → Options | `toggle_pane.sh timers --persist`                 |

Persistence key: `show_timers` in `bridge/runtime/startup.conf`. Fresh-install
default is `1` (pane open), seeded by `bridge/launcher/templates/startup.conf`
(see ADR 0101). Upgraded installs that pre-date the key fall through to the
aligned `${show_timers:-1}` runtime guard in
`bridge/launcher/build_initial_layout.sh`, so the timers pane will open on the
next cockpit start.

## Pane title and border

Pane title: `timers`. The `pane-border-format` in `bridge/launcher/tmux_start.sh`
maps this to the label ` Timers ` when headers are on.

## Data layer

`state.char.affects` and the supporting disk files under
`data/characters/<character>/` continue to be maintained by
`lua/core/affects.lua` regardless of whether the timers pane is open. The data
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
