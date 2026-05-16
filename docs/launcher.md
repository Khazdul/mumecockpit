# Launcher

Pre-tmux startup menu, rendering conventions, and the exec-chain that starts
or returns to the cockpit. Touch this file when changing launcher pages,
rendering behaviour, the startup command-line options, or the return-to-menu
flow.

## Startup

```bash
./start.sh            # show retro startup menu (default)
./start.sh --no-menu  # skip menu, use current bridge/runtime/startup.conf
./start.sh -d         # skip menu, force dev pane on for this run (not persisted)
./start.sh -u         # skip menu, force UI pane on for this run (not persisted)
```

`start.sh` is a thin wrapper that installs dependencies and then:
- Without bypass flags → `exec bash bridge/launcher/launcher.sh` (startup menu)
- With `--no-menu` / `-d` / `-u` → `exec bash bridge/launcher/tmux_start.sh` (direct start)

The return-to-menu path (in-game popup "Exit to main menu") is handled by an
exec-chain inside `tmux_start.sh`: after `tmux attach` returns, the script
checks for `bridge/runtime/.return_to_menu` (written by `ingame_menu.sh` just before
firing `cp -e`) and, if present, `exec`s back into `bridge/launcher/launcher.sh`.
No intermediate bash frame — no flash. `tmux_start.sh` also clears any stale
sentinel at the top of each run so a crash cannot mis-route a subsequent cold
start.

## Startup menu (`bridge/launcher/launcher.py`)

A `prompt_toolkit` full-screen `Application` rendered in the terminal before
tmux launches (ADR 0069). `bridge/launcher/launcher.sh` is a thin wrapper
that `exec`s the Python entry; every call site (start.sh, the return-to-menu
chain in `tmux_start.sh`, the Windows shortcut, the update flow's restart
path) goes through that wrapper unchanged.

The UI is a frame stack: a single `DynamicContainer` swaps between `main`,
`profile`, `profile_rename`, `profile_create_name`, `profile_create_choose`,
`profile_create_copy_picker`, `profile_delete_confirm`, `options`,
`options_panes`, `options_pane`, `options_connection`,
`options_connection_custom`, `options_coming_soon`, `scripts`, `about`,
`history`, `history_detail`, `history_rate`, `history_delete_confirm`,
`log_view`, `spotlights_empty`, `credits`, `update_running`,
`update_result`, and `exit_confirm` containers, pushed and popped via
`_push_frame` / `_pop_frame`. Each
frame owns its own `KeyBindings` filter (`_in_frame(name)`) so
navigation, scroll, and ESC behave per-frame. The popup architecture
(ADR 0062) is the reference; see `bridge/launcher/ingame_menu.py` for
the same patterns. There is one shared `options_pane` frame (the
target pane is selected via module state on push); per-pane subframes
do not have distinct names.

| Feature | Detail |
|---------|--------|
| Session detect | `tmux has-session -t mume` + `list-clients` re-probed on every render → top item is "Enter MUME", "Resume MUME", or "Mirror MUME (attached elsewhere)" |
| Profile page | Sortable table of `ttpp/profiles/*.tin` (Name + Selected columns) paired with a centred Options widget — Select, New, Edit, Rename, Delete, Export, Back. See the [Profile sub-menu](#profile-sub-menu) section below. `default` cannot be renamed or deleted. "Create blank" copies from `bridge/launcher/templates/blank_profile.tin` (single source of truth — see ADR 0042). The active profile is written to `startup.conf` and consumed by `ttpp/core/config.tin` at tt++ startup. |
| Options page | Navigation hub: **Panes**, **Scripts**, **Spotlights**, **Text layout** (placeholder), **Connection**, blank row, **Back**. See the [Options sub-menu](#options-sub-menu) section below for each child frame. All Options changes persist to `bridge/runtime/startup.conf` on Back / ESC. |
| Scripts page | Opened from Options → Scripts. Reads `bridge/runtime/scripts.cache`; scrollable via UP/DOWN, PageUp/PageDown |
| Spotlights | Cross-character reel of deaths, level-ups, pvp-kills, and achievements aggregated from every character's sealed runs. Opens `log_view` in spotlight mode; empty-state frame when nothing has been captured yet. See the [Spotlights sub-menu](#spotlights-sub-menu) section and ADR 0077. |
| About page | Reads `bridge/launcher/about.txt`; word-wrapped, cached per resize, scrollable. Current version on the right of the title; an "Update available: vX.Y.Z" line appears in `C_ACCENT` when `version.cache` contains a newer tag |
| Update flow | Selecting "Update" runs `bridge/release/update.sh` in a worker thread; result keyed off update.sh's exit codes (0/10/20/21/22/other → complete/no-update/aborted/failed). rc==0 re-execs `bridge/launcher/launcher.sh` to pick up the new code |
| Quit | Confirmation prompt; ESC cancels |
| Persistence | Options saved to `bridge/runtime/startup.conf` on Back / ESC; profile selection saved immediately on Enter |

## Profile sub-menu

Two interactive frames: `profile` (table + actions) and `profile_rename`
(name-entry sub-frame). Reuses the existing create / delete frames
(`profile_create_name`, `profile_create_choose`,
`profile_create_copy_picker`, `profile_delete_confirm`) unchanged.

### `profile` frame

Top-to-bottom:

1. Title row.
2. **Centred package: `[ profile table | scrollbar | gap | Options widget ]`.**
   Horizontally centred as one unit; the package drives all left/right
   positions on the frame and recentres on terminal resize.
   - **Profile table.** Two columns:
     - `Name` — dynamic width (longest profile name, floor = header
       width 4), left-aligned. Sortable: click toggles direction;
       default `Name ▲ asc`.
     - `Selected` — fixed width 8, centred. `✓` in `C_ACCENT` (gold)
       on the active profile, blank otherwise. Header is not
       clickable and shows no sort indicator.
     - One-space gap between columns.
   - **Gap.** 1 space between the table's scrollbar column and the
     Options widget's left edge.
   - **Options widget.** Vertical column of 7 connected flat buttons
     (no inter-button gap, no border): Select, New, Edit, Rename,
     Delete, Export, Back. Column width = longest button label + 2
     cells of padding. A centred `Options` header sits on the same
     line as the table header, painted `C_SECTION` when the widget
     is unfocused / `C_ACTIVE` when focused. Styling and state
     palette match the History → Options widget; see that section
     for the full state table.
3. **Feedback row** — single row directly below the package; doubles
   as the spacing row above the footer. Holds transient feedback
   from Edit / Rename / Export (`Exported to ~/<name>.tin.` and
   `Renamed to "<new>".` in `C_ACCENT`, `Editor coming soon.` and
   `Export failed: …` in `C_HINT`) centred on the package width for
   ~3 s. Select does not flash — the ✓ in the Selected column is the
   confirmation.
4. Footer hint: `↑↓ Cursor · Tab/←→ Cycle · Enter Activate · ESC Back`.
   A flex spacer below the footer absorbs leftover terminal rows.

**Focus.** Two focusable Windows per the focus-on-push contract
(ADR 0066): `_profile_table_window`, `_profile_options_window`.
`_profile_focused: int` (0/1) routes navigation. Tab / Shift+Tab
cycles between them (modulo 2). In addition, `→` focuses options
and `←` focuses the table — non-wrapping (← on table and → on
options are no-ops).

**Cursor and hover.** The cursor element in each panel paints
`C_SELECTED` in all focus states. Hover paints `C_HOVER` on
non-cursor selectable elements; hover never overrides `C_SELECTED`.

**Disabled rules.**

- **Select** — disabled when the cursor row is already the active profile.
- **Rename**, **Delete** — disabled when the cursor row is `default`.
- **Edit**, **New**, **Export**, **Back** — always enabled.

The Options cursor moves through enabled buttons only (↑/↓ skips
disabled), matching the History widget.

**Keyboard.**

| Focus   | Key                | Action                                  |
|---------|--------------------|-----------------------------------------|
| table   | ↑/↓                | move cursor row (clamp)                 |
| table   | PgUp/PgDn          | scroll 10                               |
| table   | Home/End           | jump to ends                            |
| table   | Enter / Space      | invoke Select (no-op if disabled)       |
| table   | →                  | focus options (no-op when on options)   |
| options | ↑/↓                | move cursor button (skip disabled)      |
| options | Enter / Space      | activate selected button                |
| options | ←                  | focus table (no-op when on table)       |
| any     | Tab / Shift+Tab    | cycle focus (table ↔ options)           |
| any     | ESC                | pop to main menu                        |

**Mouse.** Click activates (and switches focus to that panel).
Clicking a table row moves the cursor and focuses the table. Clicking
the `Name` header toggles sort direction. Clicking a button focuses
the Options widget and activates the button. The wheel scrolls the
table without moving the cursor (`_WheelScrollControl`, shared with
the History table); wheel over the gap / scrollbar / Options column
is a no-op.

**Action handlers.**

- **Select** — writes `_conf["profile"]` and re-renders so the ✓ in
  the Selected column moves to the new row. No feedback flash — the
  ✓ is the visual confirmation.
- **New** — pushes the existing `profile_create_name` chain
  (validation → blank-vs-copy choice → optional copy picker). The
  ADR 0042 blank-template seeding is unchanged.
- **Edit** — flashes `Editor coming soon.` in `C_HINT` for ~3 s and
  pushes no frame (placeholder until the editor frame ships).
- **Rename** — pushes `profile_rename` (see below). Disabled on
  `default`.
- **Delete** — pushes the existing `profile_delete_confirm` frame.
  Disabled on `default`.
- **Export** — copies `ttpp/profiles/<name>.tin` to `~/<name>.tin`,
  overwriting without confirmation. On success flashes
  `Exported to ~/<name>.tin.` in `C_ACCENT`; on `OSError` flashes
  `Export failed: <reason>` in `C_HINT`.
- **Back** — pops to the launcher main menu (same effect as ESC).

### `profile_rename` frame

Single-input sub-frame pushed by the Rename Options button. Mirrors
the shape of `profile_create_name`: title `─── Profile ───`,
`Rename "<old>" to:` head, single-line input prompt, inline error
on validation failure, footer `Enter  Confirm · ESC  Cancel`.

- Input is validated with `_validate_profile_name` — same rules as
  Create (must start with a letter; letters, digits, `_` only; max
  32 chars; no collision with an existing `.tin`).
- If the new name equals the old, the frame pops silently (no-op).
- On confirm: renames the `.tin` file in `ttpp/profiles/`. If the
  renamed profile was the active one in `startup.conf`, the conf
  is rewritten with the new name. The table re-sorts and the
  cursor re-anchors to the renamed row's new index. The frame
  pops and the profile frame flashes `Renamed to "<new>".` in
  `C_ACCENT`.
- ESC cancels without touching files.

## Options sub-menu

Navigation hub pushed by activating "Options" on the main frame. Children:

- **Panes** → `options_panes` — per-pane enable/disable + colour selection.
- **Scripts** → `scripts` — opens the same Scripts frame documented in the
  feature table above. ESC returns to `options`.
- **Spotlights** → `options_spotlights` — per-kind toggles for the
  Spotlights reel (deaths, level-ups, PvP kills, achievements).
- **Text layout** → `options_coming_soon` — placeholder for future
  layout/typography options. The row paints in `C_HINT` (dim grey) in its
  inactive state to signal "not ready yet"; active and hover states look
  normal.
- **Connection** → `options_connection` — MMapper / Direct / Custom
  selector; Custom pushes a host/port input subframe.

ESC inside `options` saves any pending edits to `bridge/runtime/startup.conf`
and pops back to `main`.

### `options_panes` frame

Lists the six right-column panes (Character / Buffs / Group /
Communication / UI / Developer), then a blank row, then a `Display pane
headers` toggle (`[x]` when on), then a blank row, then `Back`. Selecting
a pane row pushes the per-pane subframe (`options_pane`) with the chosen
target stashed on `_options_pane_target`.

The headers toggle flips `show_pane_dividers` in `startup.conf` and is
read by the cockpit's tmux border-status setup at next start. It does
not call `toggle_pane.sh` from the launcher — the change is deferred-
persistence only, in line with the rest of the launcher Options.

### `options_pane` frame

One shared frame, re-rendered per render against
`_options_pane_target`. Title takes the form `─── <Name> pane ───`
(e.g. `─── Character pane ───`). Content (top-to-bottom):

- `[x] Enabled` — toggles the pane's `show_<key>` value in
  `startup.conf`. Effect is deferred — the new state takes hold on next
  cockpit start; nothing live happens at the launcher.
- blank row
- `Pane color` section label (`C_SECTION`)
- Seven radio rows: `( ) Black`, `Red`, `Green`, `Blue`, `Grey`,
  `Orange`, `Purple`. The current selection is rendered with `(•)`. Each
  row trails three full-block glyphs (`███`) as a colour swatch.
- blank row
- `Back`

Swatch styling: tinted entries paint `bg:<hex> fg:<hex>` so the cells
fill solid; `Black` paints `bg:#000000 fg:#000000` — solid black even on
a black terminal. The swatch reflects the actual pane bg one would get
on next start — except for `Black`, where the runtime mapping is
`bg=default` (the terminal background shows through, not literal
`#000000`). Selecting a colour writes `pane_color_<key>` to
`startup.conf` on Back / ESC; nothing live happens at the launcher
(the popup's per-pane subframe re-tints live — see
[docs/popup-menu.md](popup-menu.md#panes-submenu)).

### Per-pane colour palette

Source of truth: `PANE_COLORS` in `bridge/launcher/palette.py`.
Mirrored in `_pane_bg_for` in `bridge/launcher/open_pane.sh` (the cold-
start path that applies the colour to a freshly opened tmux pane). The
two lists must stay in sync; an unknown name in `startup.conf` falls
back to `bg=default` and logs a debug line.

| Name     | Hex       | tmux bg          |
|----------|-----------|------------------|
| `black`  | —         | `bg=default`     |
| `red`    | `#1a0e0e` | `bg=#1A0E0E`     |
| `green`  | `#0e1a0e` | `bg=#0E1A0E`     |
| `blue`   | `#0e141c` | `bg=#0E141C`     |
| `grey`   | `#161616` | `bg=#161616`     |
| `orange` | `#1c140a` | `bg=#1C140A`     |
| `purple` | `#16101c` | `bg=#16101C`     |

`PANE_COLOR_ORDER` in `palette.py` defines the radio presentation order.

### `options_connection` frame

Three radios — MMapper (`localhost:4242`), Direct (`mume.org:4242`,
TLS), Custom — followed by `Back`. The active radio reflects the
current `connection_mode` in `startup.conf`. Selecting MMapper or
Direct writes `connection_mode` and pops on Back/ESC. Selecting Custom
writes `connection_mode=custom` and pushes `options_connection_custom`.

`bridge/launcher/read_config.sh` consumes the resulting keys at tt++
startup and produces the `_host`, `_port`, `_ses_cmd` tt++ variables
(MMapper and Custom use `ses` / plain telnet; Direct uses `ssl` / TLS).

### `options_connection_custom` frame

Two-field input (Host, Port). Tab / Shift+Tab cycles fields; backspace
edits; Enter saves; ESC cancels. Port is validated against 1–65535;
invalid input keeps the frame open with the field highlighted. On
save, writes `connection_host` / `connection_port` to `startup.conf`
and pops back to `options_connection`.

### `options_spotlights` frame

Per-kind toggles for the [Spotlights reel](#spotlights-sub-menu). Four
`[x]` / `[ ]` rows followed by a blank row and `Back`, styled identically
to the `Display pane headers` toggle in `options_panes`. Enter / Space /
click flips the row; ESC or `Back` saves and pops back to `options`.

| Row              | `startup.conf` key                | JSONL `event`  |
|------------------|-----------------------------------|----------------|
| `Deaths`         | `spotlights_show_deaths`          | `char_death`   |
| `Level-ups`      | `spotlights_show_levelups`        | `level_up`     |
| `PvP kills`      | `spotlights_show_pvp`             | `pkill`        |
| `Achievements`   | `spotlights_show_achievements`    | `achievement`  |

All four keys default to `1` (enabled) when absent — fresh installs and
pre-feature `startup.conf` files behave as before. A value of `0`
disables the kind; anything else reads as enabled.

`bridge/launcher/spotlights.py:load_filter_settings()` returns the
`{event_name: bool}` dict at the start of each `aggregate_spotlights()`
call, and `_extract_events()` drops disabled kinds during the JSONL
walk — before spotlight construction, rotation, and per-character
grouping. The [`credits` frame](#credits-frame) inherits the filter
automatically since it consumes the same reel.

### `options_coming_soon` frame

Single-message placeholder pushed by Text layout. Any key (or ESC)
returns to `options`.

### Persistence asymmetry vs. the popup

Launcher Options writes to `startup.conf` on Back / ESC (deferred,
batch-saved). Cockpit panes are unaffected during the edit — changes
take effect on next cockpit start. The popup's equivalent submenus
(see [docs/popup-menu.md](popup-menu.md)) write each change immediately
and live re-tint the open pane via `tmux select-pane -P bg=<…>` /
`toggle_pane.sh <pane> --persist` so the player sees the result without
restarting. Both surfaces ultimately write the same keys.

## History sub-menu

Three frames: `history` (list + actions), `history_detail` (per-session
view), and `history_rate` (star picker). Opened from the main-menu entry
"History", which sits immediately after the dynamic Enter/Resume/Mirror
row (or the optional "Update" row). Data is read by
`bridge/launcher/run_stats.py` — see ADR 0065 for the aggregator,
ADR 0056 for the stitching primitive.

`SessionSummary` carries the per-chain saved state used by the History
surfaces: `saved` is true iff any run in the chain has a
`<run-id>.meta.json` with `"saved": true`; `rating` is the maximum
rating across saved runs in the chain (chain-consensus rule, locks in
"max" so a future divergent case shows the best rating the user ever
gave the session). Both fields are `None`/`False` when no meta sidecar
is present. See [docs/runs.md](runs.md#meta-sidecar-saved-runs) for the
sidecar schema.

### `history` frame

Top-to-bottom:

1. Title row.
2. `Filter` header label (`C_ACTIVE` when the filter row is focused,
   `C_SECTION` otherwise) — left-aligned with the runs table's
   leftmost cell.
3. **Filter pill row.** `All` followed by one pill per character
   returned by `list_characters_with_runs()` (alphabetical).
   Characters without sealed JSONLs are excluded. Each pill is
   `" <name> "` (single-cell padding each side); pills are adjacent
   with no extra spacer between them. The cursor pill paints
   `C_SELECTED`. Hover paints `C_HOVER` on non-cursor pills; hover
   never overrides cursor. The pill row's leftmost cell sits flush
   with the runs table's leftmost column.
4. **Centred package: `[ runs table | scrollbar | gap | Options widget ]`.**
   Horizontally centred as one unit. The package is what drives all
   left/right positions on the frame — the filter header and pill row
   align flush with the package's left edge.
   - **Runs table.** Columns: Char · Date · Time · Dur. · Expires ·
     Rating. The header row is click-to-sort; an active column shows
     ` ▲` / ` ▼` after its label. Default sort `Char asc` with
     `start_ts desc` as the stable secondary key.
   - **Gap.** 1 space of visual breathing room between the table's
     scrollbar column and the Options widget's left edge.
   - **Options widget.** Vertical column of 7 connected flat buttons
     (no inter-button gap, no border): Run log, Stats, Rate, Save,
     Export, Delete, Back. Column width = longest button label + 2
     cells of padding (longest label: `Run log`, 7 chars).
     A centred `Options` header sits on the same line as the runs-
     table header row, painted `C_SECTION` when the widget is
     unfocused / `C_ACTIVE` when focused.
5. **Feedback row** — single row directly below the package, doubling
   as the spacing row between the table and the footer. Holds the
   Save / Rate / Export / Delete transient feedback message
   (`Saved to ~/<file>` in `C_ACCENT`, `Export failed: …` in
   `C_HINT`, etc.) centred on the package width for ~3 s, blank
   otherwise.
6. Footer hint line. Sits one row below the feedback row; any
   remaining vertical space lives below the footer via a flex
   spacer, not above it, so the footer hint is anchored to the
   package and rises/falls with the data-fit table.

Each row is a stitched chain (one session). Stitching uses the default
`max_gap_seconds = 3600` from `list_sessions()`. The live
`current.jsonl` is never listed; only sealed JSONLs.

**Expires cell.** `"Saved"` in `C_ACCENT` (gold) when `summary.saved`,
otherwise `"<N> days"` in `_S_LABEL` where `N = ceil((oldest_run_start_ts
+ 14*86400 - now) / 86400)`, floored at 0. The oldest run is
`run_ids[0]` (`list_sessions` returns the chain oldest-first). `0 days`
renders literally — the run is in its last day before the next launcher
boot prunes it.

**Rating cell.** `summary.rating` ★ glyphs in `_S_STAR` (gold),
left-aligned. Blank when `summary.saved` is false or rating is 0.

**Sort defaults.** Expires and Rating both default to numeric desc.
Sorting either column groups Saved sessions above any "N days" value
in either direction (stable: Saved sessions stay together, then
numerics order normally within the unsaved group).

**Focus.** Three focusable Windows per the focus-on-push contract
(ADR 0066): `_history_filter_window` (pill row),
`_history_table_window`, `_history_options_window` (button column).
`_history_focused: int` (0/1/2) routes navigation. Tab / Shift+Tab
cycles forward / backward; `_focus_current_frame()` re-focuses the
right window after push/pop and on focus changes within the frame.

**Cursor and hover.** The cursor element in each panel paints
`C_SELECTED` (black on light grey) in all focus states. Hover paints
`C_HOVER` on non-cursor selectable elements; hover never overrides
`C_SELECTED`. Hover clears on `MOUSE_MOVE` over any non-row fragment
(title, footer, gap, padding, scrollbar track, disabled button) via
the per-frame `_hover_at(panel, idx)` helper.

**Options widget styling.** Flat-button style — no border; the
background colour distinguishes each button from surrounding space.

| State                    | Style                                       |
|--------------------------|---------------------------------------------|
| Normal                   | `C_BUTTON` — near-black bg, just above bg   |
| Hover (non-cursor)       | `C_BUTTON_HOVER` — subtle lift over normal  |
| Cursor (widget focused)  | `C_SELECTED` — black on light-grey bg       |
| Disabled                 | `C_BUTTON_DISABLED` — dim fg, near-bg fill  |

`C_BUTTON`, `C_BUTTON_HOVER`, and `C_BUTTON_DISABLED` are defined in
`palette.py`. The widget is intentionally subdued so the surrounding
backdrop dominates; only `C_SELECTED` is allowed to pop. Cursor state
takes precedence over hover. Disabled buttons take no click and no
hover highlight.

**Disabled rules.**

- **Run log** — disabled when `summary.has_log` is false. Otherwise
  pushes `log_view` for the selected chain directly (no detour
  through `history_detail`). Primary action on the surface — the
  same destination as activating the row from the runs table.
- **Stats** — always enabled (no-op when the table has no row).
- **Rate** — always enabled (no-op when the table has no row).
- **Save** — disabled when `summary.saved` is true.
- **Export** — disabled when `summary.has_log` is false.
- **Delete** — always enabled when a row is selected. Saved sessions
  are not gated; the `history_delete_confirm` frame is the safety net.
- **Back** — always enabled. Pops to the launcher main menu (same
  effect as ESC).

The Options cursor moves through enabled buttons only (↑/↓ skips
disabled). Back is always enabled, so the cursor always has a
landing spot even with an empty table.

**Keyboard.**

| Focus   | Key                | Action                                |
|---------|--------------------|---------------------------------------|
| filter  | ←/→                | move cursor pill (wrap)               |
| filter  | Enter / Space      | re-apply cursor pill's filter         |
| table   | ↑/↓                | move cursor row (clamp)               |
| table   | PgUp/PgDn          | scroll 10                             |
| table   | Home/End           | jump to ends                          |
| table   | Enter / Space      | open Run log when row has a log; otherwise no-op |
| options | ↑/↓                | move cursor button (skip disabled)    |
| options | Enter / Space      | activate selected button              |
| any     | Tab / Shift+Tab    | cycle focus (filter → table → options)|
| any     | ESC                | pop to main menu                      |

**Filter behaviour.** Cursor equals the active filter; moving the
cursor with ←/→ or clicking a pill re-filters immediately. Filter
resets to `All` on every frame push. Filter change resets table scroll
and cursor to 0; sort state is preserved.

**Mouse.** Click activates (and switches focus to that panel).
Clicking a runs-table row with `has_log` true opens `log_view` for
that chain (same destination as Enter / Space on the row, or the
Run log Options button); clicking a row with no log moves the
cursor only — Stats is reachable from the Options widget. Wheel
scrolls the table when hovered (`_WheelScrollControl`, the shared
`FormattedTextControl` subclass that intercepts `SCROLL_UP` /
`SCROLL_DOWN` and forwards them to a per-frame callback); wheel
over filter row or menu is a no-op. The table's
click-to-jump scrollbar uses `bridge/launcher/widgets/scrollbar.py`.

**Action handlers.** All operate on the row currently under the table
cursor (`_history_sessions[_history_table_cursor]`). With no row,
every action is disabled.

- **Run log** — disabled when `summary.has_log` is false. Opens
  `log_view` for the chain (`_enter_log_view(summary)`), bypassing
  `history_detail`. Same destination as Enter / Space / click on the
  runs-table row when `has_log` is true.
- **Stats** — pushes `history_detail` for the selected session.
- **Save** — disabled when `summary.saved`. Otherwise calls
  `run_meta.save_run_chain(character, run_ids, 0)`, then re-reads each
  run's meta sidecar to refresh `summary.saved` / `summary.rating` in
  place so the row's Expires cell flips to `Saved` and `Save` greys
  immediately.
- **Rate** — pushes the `history_rate` frame for the selected session
  (always enabled when a row is selected).
- **Export** — disabled when `summary.has_log` is false. Concatenates
  `data/runs/<character>/<run-id>.log` for each `run_id` in
  `summary.run_ids` (chronological; missing files are skipped). Per
  line: strips the `^\d+ ` timestamp prefix, the leading `> `
  outbound marker, and any ANSI SGR escape (`\x1b\[[0-9;]*m`). One
  blank line separates successive run logs. Writes to
  `~/mume-<character>-<first-run-id>.txt`, with `-2.txt` / `-3.txt`
  suffixes on collision. Result flashes for ~3 s on the centred
  feedback row two lines below the package: `Saved to ~/<file>` in
  `C_ACCENT` on success, `Export failed: <reason>` in `C_HINT` on
  `OSError`.
- **Delete** — pushes `history_delete_confirm` anchored to the
  cursor row. On `Y` the chain's `.jsonl` / `.log` / `.meta.json`
  files are removed (per-file `OSError` swallowed; no rollback on
  partial failure), the session list is rebuilt via
  `_history_refresh_sessions()`, and `_history_table_cursor` is held
  at the deleted row's index (clamped to `max(0, len(sessions) - 1)`
  if the chain was at the end). The Options widget keeps focus after
  pop. Any other key cancels without touching files. Saved sessions
  are deletable through the same flow — the confirm frame is the
  only safety net (see ADR 0075).
- **Back** — pops to the launcher main menu. Same effect as ESC.

ESC is the keyboard back-out path from any of the three panels and is
equivalent to activating the Back button.

Saving / re-rating writes meta files for **every** run-id in the
stitched chain, matching the popup's chain-save semantics
(`docs/popup-menu.md`#chain-save-semantics). After the write the row's
saved/rating fields are recomputed from disk rather than locally
mutated, so the row stays in sync with the meta sidecar truth.

**Empty state.** No characters with archived runs → table area renders
`"No runs recorded yet."` centred; the filter row shows only the `All`
pill; every Options button except Back is disabled.

### `history_rate` frame

Star-picker for setting / changing the rating on a session's chain.
Modeled on the popup's `rate_session` (`docs/popup-menu.md`#rate-session-frame):
same `★` widget, same key bindings (`0..5`, ←/→, Enter, ESC), same
gold (`_S_STAR`) / grey (`C_HINT`) contrast.

**Title.** `─── Rate the session ───`. The popup's equivalent reads
"Rate the run" — different scope (popup rates the just-finished run;
the launcher rates a saved session's chain).

**Initial rating.**

- `summary.rating` if the session is already saved (re-rate starts at
  the current value).
- `0` if not yet saved.

**Key bindings** (filter: `_in_frame("history_rate")`):

| Key      | Action                                                    |
|----------|-----------------------------------------------------------|
| `0`..`5` | Set `_history_rate_rating` to that value                  |
| `Left`   | `rating = max(0, rating - 1)`                             |
| `Right`  | `rating = min(5, rating + 1)`                             |
| `Enter`  | Save and pop back to history                              |
| `Space`  | Save and pop back to history                              |
| `ESC`    | Pop back to history without saving                        |

Mouse: clicking star N (1-indexed) sets the rating to N.

**Save.** Walks the session's `summary.run_ids` and calls
`run_meta.save_run_chain(character, run_ids, rating)`, refreshes the
row's `saved` / `rating` from disk, then pops. The `history` row's
Expires and Rating cells repaint on the next render. Re-rating an
already-saved session updates only `rating` + `saved_ts` in the meta
files; `saved` stays true.

**Module state.** `_history_rate_rating: int` (0..5),
`_history_rate_window: Window` (focus-on-push), and
`_history_rate_summary: SessionSummary | None` set on push and cleared
on pop. The frame builder follows ADR 0066: the single focusable
Window is registered in `_focus_current_frame()` so per-star click
handlers route correctly.

### `history_delete_confirm` frame

Modal confirmation pushed by the Options widget's Delete button (see
ADR 0075). Centred, single focusable Window built via `_centered`,
registered in `_focus_current_frame()` per ADR 0066. Anchored to the
session under `_history_table_cursor` at push time.

**Body** (top to bottom):

- Title `─── Delete session ───` in `C_HEADER`.
- A label/value block (labels `C_HINT`, values `C_ITEM`): Character,
  Date, Time, Duration, Runs (`len(summary.run_ids)`).
- `Saved: yes — ★★★★★` painted `C_ACCENT` (gold) — only present when
  `summary.saved` is true; the stars repeat `summary.rating` times.
  Omitted entirely when the session is unsaved.
- Two warning lines in `C_HINT`:
  `This will permanently delete the session's logs and run data.` /
  `This cannot be undone.`
- Footer `Y  Delete       Any other key  Cancel` in `C_HINT`.

**Key bindings** (filter: `_in_frame("history_delete_confirm")`):

| Key            | Action                                       |
|----------------|----------------------------------------------|
| `y` / `Y`      | Confirm — delete + refresh + pop             |
| `escape`       | Cancel (eager) — pop, no files touched       |
| `<any>`        | Cancel — any other key pops the frame        |

Mirrors the `exit_confirm` and `update_result` patterns.

**Confirm.** `_history_delete_confirm_yes()` calls
`_history_delete_session(summary)` (removes `.jsonl` / `.log` /
`.meta.json` for every `run_id` in the chain; per-file `OSError`
swallowed), then `_history_refresh_sessions()` and clamps the table
cursor so it lands on a sensible row. The frame pops and focus
returns to the Options widget (`_history_focused == 2`).

**Cancel.** `_history_delete_confirm_cancel()` clears
`_history_delete_summary` and pops. No filesystem side-effects.

**Module state.** `_history_delete_summary: SessionSummary | None`
(set on push, cleared on pop), `_history_delete_confirm_window:
Window` for the focus contract.

### `history_detail` frame

Per-session statistics view. Opened from the `history` frame via
the **Stats** Options button. The Run log entry point lives on the
`history` frame (Run log Options button, or Enter / click on a row
when `has_log`) — there is no log-player surface on
history_detail. Data is aggregated on push via
`aggregate(character, summary.run_ids)` and stashed in
module-level state; the chain is already in `summary.run_ids`,
so no extra walk.

**Layout** (top to bottom): header line · blank · ALLIES +
ACHIEVEMENTS · blank · KILLS + PvPs · blank · sparklines (XP/h +
TP/h) · blank · XP-linjal · blank · footer.

**Header.** `◆ Session detail — <Char> · <Date> · <Time> ·
<Dur.>` centred in `C_HEADER`.

**Section parity with popup Statistics.** ALLIES (`♦` in
`_S_ALLY`), ACHIEVEMENTS (`★` in `_S_STAR`), KILLS (sortable),
PvPs (sortable, `⚔` in `_S_PVP`), sparklines, and XP-linjal
mirror the popup's visual conventions. Sort defaults, focus
cycling (Tab / Shift+Tab across the four tables,
`_history_detail_focused: int`), per-table scrollbars, and the
data-row glyph palette are identical.

**Differences from the popup.**

- **Data-fit KILLS/PvPs sizing.** The section renders
  `min(max(kills_count, pkills_count), max_available)` data rows;
  the Total row sits directly under the last data row instead of
  pinning to the bottom. Sparklines, XP-linjalen, and the footer
  rise to fill the freed space; any leftover slack lives between
  the XP-linjal and the footer.
- **Total per side is hidden when that side's count is 0.** The
  opposite side's Total still renders if its count > 0; the empty
  side pads with a blank row so sparkline alignment is preserved.
- **Row hover on data tables.** ALLIES / ACHIEVEMENTS / KILLS /
  PvPs data rows paint `C_ROW_HOVER` (a background fill that
  composes with each cell's foreground colour) under the cursor.
  The popup intentionally has no row hover.

**Rendering source.** `launcher.py`'s history_detail rendering is
fresh-written rather than shared with the in-game popup's
Statistics frame. The two surfaces have different hosts and
different use cases; the duplication is accepted as recorded
technical debt. Conditions under which consolidation might later
become worth doing (Phase 3 Log Player reuse; schema change
forcing double work; layout overhaul) are recorded in
[ADR 0073](decisions/0073-statistics-rendering-duplicated.md).

**Footer.**

```
ESC Back     ↑↓ Scroll     Tab/Shift+Tab Switch table
```

## Spotlights sub-menu

Cross-character reel of significant events. The launcher main menu entry
sits between `History` and `Profile`. Two surfaces:

- `spotlights_empty` — shown when no spotlights have been captured yet
  (fresh install or every character's sealed runs lack tracked events).
- `log_view` in spotlight mode — the reel itself, sharing the chain log
  player's playback engine, overlays, and scrubber.

The data layer lives in `bridge/launcher/spotlights.py`:
`aggregate_spotlights()` walks `data/runs/<character>/*.jsonl` for every
character (skipping `current.jsonl` and runs without a sibling `.log`),
extracts the four tracked event kinds (`char_death`, `level_up`, `pkill`,
`achievement`), and builds one `Spotlight` per event
([ADR 0077](decisions/0077-spotlight-reel-scope-rotation-per-event.md)
covers the cross-character aggregation scope, the newest-first
round-robin rotation, and why each event is its own spotlight rather
than being merged with nearby ones). Each spotlight gets a nominal
`[event - 10 s, event + 5 s]` window — clamped to the `.log`'s actual
`ts_us` range at lazy load time, then pre-roll-trimmed to the first log
line within the window (see "Lazy log loading" below and
[ADR 0079](decisions/0079-spotlight-pre-roll-trim-post-roll-unclamped.md)
for why the post-roll is deliberately not clamped). Two close events
from the same character produce two back-to-back spotlights for that
character when no other character has a more recent pending spotlight;
the rotation algorithm handles that gracefully.

**Rotation.** Per-character queues are sorted newest-first
(`spotlight.events[0].ts` descending). The interleaving algorithm picks
the queue whose head spotlight has the most recent first-event
timestamp, but skips the just-picked character when an alternative
exists — so no two adjacent spotlights share a character unless only
one character has remaining entries at that point.

**Lazy log loading.** Each `.log` is parsed exactly once via
`log_player._parse_log_file` (wrapped to return the full event list);
the parsed list is cached in a dict keyed by `log_path` so a chain of
spotlights sharing a run share the parse. `load_spotlight_log_events`
slices the cached events to the spotlight's clamped window, then
trims `window_start_us` forward to the first log line's `ts_us` when
the nominal pre-roll begins with a silence gap — so the user never
stares at an empty countdown while real content has yet to begin. The
post-roll end is unaffected by the trim. The countdown duration the
overlay displays is recomputed from the (possibly trimmed) window
start. Spotlights whose 15 s window contains zero log lines are
dropped by the caller. The function populates
`spotlight.event_offsets_us` (each event's offset from
`window_start_us`, clamped to `>= 0`) and is idempotent.

**SpotlightPlayback.** A `LogPlayback`-compatible adapter over a list
of loaded spotlights. Concatenates every spotlight's `log_events` into
a single timeline; per-event `playback_offset_us` is computed
explicitly so each spotlight starts immediately after the previous
spotlight ends (zero inter-spotlight gap — the chain-mode
`_PLAYBACK_GAP_CAP_US` gap-collapsing logic is not used). Exposes
`run_at(idx)` returning `(spotlight, ordinal, total)` — the header
renderer's only entry point — plus spotlight-specific lookups
(`spotlight_at_offset`, `spotlight_start_offsets_us`,
`event_progress`).

**Phantom wipe rows.** At construction time, `_LOG_SPOTLIGHT_WIPE_ROWS
= 100` zero-duration phantom `LogEvent`s are inserted at every
spotlight boundary (and 100 more at the very start of the reel, before
spotlight 0). Each phantom carries `fragments = [("", " ")]` so it
wraps to exactly one blank visual row; all phantoms in a transition
share the same `playback_offset_us` (the boundary offset) and consume
zero playback time. This is what gives spotlight transitions their
scroll-clear feel — see the "Scroll-clear transitions" section under
`log_view` in spotlight mode and
[ADR 0078](decisions/0078-spotlight-scroll-clear-via-phantom-rows.md)
for the design rationale (including the rejected black-frame flash
alternative). `phantom_event_indices` (a set) and `is_phantom(idx)`
(the helper used by the launcher's cursor navigation) identify these
events.

`_enter_spotlights()` is the launcher entry point. It aggregates the
reel, eagerly loads every spotlight's log events (acceptable: total
volume is bounded — N spotlights × ~15 s each), drops spotlights whose
clamped window left zero log events, and either pushes
`spotlights_empty` (zero playable spotlights) or pushes `log_view` in
spotlight mode via `_enter_log_view_spotlight(playback)`.

### `spotlights_empty` frame

Single-message placeholder pushed when the aggregator returns an empty
reel. Mirrors the layout of `options_coming_soon`: title `─── Spotlights
───`, centred body text in `C_BODY`, `Any key to return` footer in
`C_HINT`. Any key (or ESC) pops back to the launcher main menu.

The body has two variants, picked by `_enter_spotlights()` before the
frame is pushed and stored on `_spotlights_empty_reason`:

- **`"no_data"`** — all four
  [Options → Spotlights](#options_spotlights-frame) toggles are
  enabled. The reel is empty because no character has yet produced any
  tracked event.

  > No spotlights yet. Play a session and your highlights — kills,
  > deaths, level-ups, and achievements — will be captured here, ready
  > to replay.

- **`"filtered"`** — at least one per-kind toggle is `0`. The user is
  pointed at the toggle frame as the likely fix:

  > All matching event kinds are disabled. Enable some in Options →
  > Spotlights to see content here.

The branch uses the cheap "any toggle is off → filtered copy"
shortcut documented in the FEAT spec — a user could have all kinds
enabled and still no data (correctly handled), or have some kinds
disabled but the remaining enabled kinds produce no data either
(falls into the filtered-copy branch, which is mildly less precise
but still nudges them toward the right place). The precise
"unfiltered would have content" check is intentionally not run, since
a second full JSONL walk for a marginal copy improvement isn't
worthwhile.

### `log_view` in spotlight mode

A second mode of the same `log_view` frame, selected by the module
state `_log_view_mode == "spotlight"` and reading its playback from
`_log_view_reel` (a `SpotlightPlayback`). The chain-mode entry point
is `_enter_log_view(summary)`; the spotlight-mode entry point is
`_enter_log_view_spotlight(playback)`. Both share the same
`_log_view_window`, the same playback engine (anchor + offset,
auto-pause-at-end, 30 Hz tick task), the same bottom controls overlay,
and the same scrubber drag plumbing.

Unlike chain mode the spotlight entry point auto-plays: it initialises
state then calls `_log_resume()` so the reel starts rolling immediately
on push. The 100-row phantom block in front of spotlight 0 (see "Scroll-clear
transitions" below) keeps the viewport blank while the first spotlight's
pre-roll counts down, so the user sees the upcoming spotlight's info box
on an empty backdrop before content begins — no Space needed.

The top header and bottom-controls overlays are **hidden on entry**:
`_enter_log_view_spotlight` clears `_log_overlays_visible` after the
`_log_resume()` call (which would otherwise arm them), so the user
sees a clean scene with only the spotlight info box overlaid. Mouse
activity in the frame re-arms the overlays via the regular
`_log_touch_overlays()` path; they fade again after
`_LOG_OVERLAY_HIDE_DELAY`. The spotlight info box itself stays
visible at all times — that rule is unchanged.

**Header.** When in spotlight mode `_log_header_text` dispatches to
`_log_spotlight_header_text`. The centre/left section reads:

```
<active_spotlight.character>[ (L<level>)]  ·  SPOTLIGHT <N> / <TOTAL>  ·  <YYYY-MM-DD>
```

`L<level>` appears only when the active spotlight contains a `death`
event whose JSONL row carried a `level` field. Date is
`spotlight.events[0].ts` formatted as local time (date only — chain
mode's `HH:MM` and `<elapsed>` segments are intentionally dropped in
spotlight mode: the floating info box already surfaces the active
spotlight's countdown and the freed left-side budget makes room for
the keyboard hint on the right). The right-aligned hint is
`ESC Back  ·  ←/→ Prev/next`.

**Floating info box (top-right).** A 30×8 framed rectangle pinned to
`top=2, right=2` — a 2-cell margin from both the top and right edges
of `log_view`. The frame is the half-block outline `█▀▄▌▐` rendered in
black on the bright cyan BG: top row `█` + `▀` × `interior_width` +
`█`, bottom row `█` + `▄` × `interior_width` + `█`, side columns `▌`
(left) and `▐` (right) on each of the 6 interior rows. Interior width
is `_SPOTLIGHT_BOX_W - 2 = 28`. Palette:

- `C_SPOTLIGHT_BOX_BG` — bright banner-hue fill (same hue as `C_TITLE`)
  painted under every cell of the box.
- `C_SPOTLIGHT_FRAME` — black on the BG, for the `█▀▄▌▐` outline
  glyphs.
- `C_SPOTLIGHT_TEXT_PRIMARY` — near-black, on the BG. Used for the
  nav row, the character name, and the event label.
- `C_SPOTLIGHT_TEXT_SECONDARY` — muted grey, on the BG. Lighter than
  primary, visibly subordinate. Used for the countdown.

Row layout (8 rows: 2 frame + 6 interior):

```
█▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀█
▌         ◄ 1 of 3 ►         ▐
▌           BERIT            ▐
▌                            ▐
▌      Reached level 3       ▐
▌                            ▐
▌       In 8 seconds..       ▐
█▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█
```

- Frame rows: top and bottom — black `█▀▄` outline on the BG.
- Row 2: nav row — `◄ <idx> of <total> ►`, centred,
  `C_SPOTLIGHT_TEXT_PRIMARY`. Built as separate fragments by
  `_log_spotlight_nav_row` so `◄` and `►` each carry a mouse handler
  over a 3-cell click region (` ◄ ` / ` ► `); the index text in
  between is inert. Click semantics mirror the `←` and `→` keys:
  `◄` calls `_log_spotlight_seek_relative(-1)` (restart-vs-previous
  follows the 1.5 s rule); `►` calls `_log_spotlight_seek_relative(1)`,
  which at the last spotlight delegates to
  `_log_spotlight_jump_to_credits()` — the same transition
  `_log_auto_pause_at_end()` uses. On the last spotlight the row
  reads `◄ <idx> of <total> ► CREDITS` (the suffix in the same
  primary style) to surface that altered destination; the
  next-click handler covers the full ` ► CREDITS` fragment so
  clicking the label triggers the same jump. The centring
  recomputes per spotlight so the row stays balanced in both modes.
- Row 3: `<CHAR>` — uppercased character name, centred,
  `C_SPOTLIGHT_TEXT_PRIMARY`. (The date used to live here; it's been
  dropped — the top header still carries it.)
- Row 4: blank.
- Row 5: event label (or its first wrapped line), centred,
  `C_SPOTLIGHT_TEXT_PRIMARY`.
- Row 6: blank when the event label fits on row 5; the wrapped
  continuation of the event label when it doesn't (centred, primary
  text). Wrapping uses `textwrap.wrap(..., break_long_words=False,
  break_on_hyphens=False)` so words stay intact. Labels that wrap to
  three or more lines have their second line ellipsised (`…`) — rare
  for the event-label phrases we surface.
- Row 7: countdown — `In <N> seconds..` while counting down (two
  trailing periods), `C_SPOTLIGHT_TEXT_SECONDARY`, centred. Collapses
  to a blank row when no next event remains in this spotlight.

The "SPOTLIGHT N" line is not rendered inside the box — that
information lives in the top header (the in-box nav row uses the
shorter `<idx> of <total>` form).

**Visibility.** The spotlight info box stays visible at all times in
spotlight mode — it does **not** participate in the top header / bottom
controls auto-hide. The only fallback is narrow terminals: if
`cols < _SPOTLIGHT_BOX_W + _SPOTLIGHT_BOX_MARGIN * 2` (i.e. the box
plus its 2-cell margin doesn't fit with some breathing room),
`_log_spotlight_overlay_visible()` returns False and the box is
suppressed for that frame; playback continues without it.

**Scroll-clear transitions.** Spotlight transitions (and the initial
entry into the reel) use a scroll-clear approach: 100 phantom blank
events are inserted at every boundary by `SpotlightPlayback`. Each
phantom wraps to one blank visual row, carries zero playback duration,
and shares the boundary's `playback_offset_us`. See
[ADR 0078](decisions/0078-spotlight-scroll-clear-via-phantom-rows.md)
for the rationale behind the phantom model (and the rejected
black-frame flash that preceded it).

The play-mode auto-scroll places the playhead event at the bottom of
the viewport. When the playhead crosses onto a new spotlight, the 100
phantom rows immediately above it are part of the visible buffer, so
the viewport fills with blank — the previous scene is pushed above the
viewport top. Effectively a clean wipe. No black render branch, no
playback-clock freeze: the first real event of a fresh spotlight fires
exactly `_PRE_ROLL_S` seconds after the spotlight begins, identical to
the no-transition case.

`←` / `→` seeks target spotlight start offsets, which sit at the end of
a phantom block, so the wipe occurs automatically on those seeks.

**Pause mode.** Scrolling backwards through a boundary reveals the
phantom rows as a block of blank rows between spotlights — acceptable
scene separation, no special handling. The cursor, however, skips
phantoms: `_log_set_cursor` calls `_log_skip_phantoms` which snaps the
landing index to the nearest non-phantom event in the direction of
travel (forward for `↓`/`PgDn`/`End`/click/scrubber-seek, backward for
`↑`/`PgUp`). `_log_is_phantom(idx)` delegates to the
`SpotlightPlayback.is_phantom(idx)` helper; chain mode is unaffected
because the helper short-circuits when `_log_view_mode != "spotlight"`.

**Keybinds.** All chain-mode keys still apply (`Space` play/pause,
`ESC` return, `↑/↓/PgUp/PgDn/Home/End` cursor — chain-mode pause-mode
behaviour). Two spotlight-mode-only additions:

| Key   | Action                                                          |
|-------|-----------------------------------------------------------------|
| `→`   | Seek to next spotlight start; **at the last spotlight, jump straight into credits** (same transition `_log_auto_pause_at_end` uses) |
| `←`   | Seek to previous spotlight start; if `> ~1.5 s` into current, restart current; at the first spotlight, restart it |

Both route through `_log_spotlight_seek_relative`; intermediate seeks
go through `_log_scrubber_seek` targeting
`reel.spotlight_start_offsets_us[idx]`, so the play/pause mode and
overlay timer behave as for any other seek. The "next past the last"
branch calls `_log_spotlight_jump_to_credits()` directly (cancel
playback, pop `log_view`, push `credits`). The mouse equivalents are
the `◄` / `►` glyphs in the info box's top nav row.

**Scrubber scope.** The bottom-controls scrubber drag continues to
scrub the entire reel timeline (each spotlight is ~15 s, so the global
scrubber stays usable). A per-spotlight scrubber was considered but
rejected for v1: the rotation already chunks playback into discrete
spotlights, and ←/→ provides per-spotlight seeking.

**End of reel.** At `total_duration_us` the existing
`_log_auto_pause_at_end()` hook fires. In chain mode it parks on the
final event and flips to pause; in spotlight mode it delegates to
`_log_spotlight_jump_to_credits()` which cancels playback, pops
`log_view`, and pushes the `credits` frame with the reel's spotlight
list. The keyboard `→` and the info-box `►` click at the last
spotlight take the same path — see the
[`credits` frame section](#credits-frame) below and
[ADR 0080](decisions/0080-end-of-reel-credits.md).

**ESC.** Returns to the launcher main menu (Spotlights is pushed from
`main`, not from `history`, so the frame stack's previous entry is
`main`).

### `credits` frame

End-of-reel scrolling chronicle. Pushed automatically by
`_log_auto_pause_at_end()` when the spotlight reel finishes
([ADR 0080](decisions/0080-end-of-reel-credits.md)). Full-screen,
black canvas (`bg:#000000`); narrative lines scroll bottom-to-top with
linear fade bands at the top and bottom of the viewport.

**Content.** Built once on frame entry by
`bridge/launcher/credits.py`:
`generate_credits_lines(spotlights, text_width) -> list[str]`. Each
spotlight event becomes one complete narrative sentence chosen
deterministically from a per-kind template list (PvP, death,
level-up, achievement); the same event reads the same way across
multiple runs of the credits, because template selection hashes
`(character, run_id, event.ts, event.kind)` modulo the list length.
Events are grouped by character with a chapter header per character
(also deterministic on character name); characters appear in
oldest-first order. Dates render as `"<ordinal> of <Month>, <Year>"`
(e.g. `"first of May, 2026"`). Fixed opening (`Herein are recorded
the deeds of your characters.`) and closing (`The End.`) lines bracket
the content with 5 blank-row pads. `text_width = min(60, max(40,
term_cols - 8))` keeps the centred column readable on wide
terminals; `textwrap.wrap(..., break_long_words=False,
break_on_hyphens=False)` preserves word boundaries.

**Scroll mechanics.** `_CREDITS_SCROLL_ROWS_PER_SEC = 1.0` row/sec;
the integer scroll offset is `int((monotonic() - start) *
_CREDITS_SCROLL_ROWS_PER_SEC)`, so the visible step advances once
per second. The redraw tick runs at `_CREDITS_TICK_HZ = 15` — well
above the visible step rate, so the integer-row transition is
observed promptly on every terminal. Auto-exit fires when
`offset_floor >= len(_credits_lines) + term_rows`; the trailing pad
of `term_rows` blank rows appended at frame-entry time is what
guarantees the closing line clears the top before the frame pops.

**Fade bands.** `_CREDITS_FADE_BAND_FRAC = 0.35`. Bottom 35% of the
viewport ramps brightness from 0 to 1 (`tr / fb`); top 35% ramps
from 1 to 0 (`(n - 1 - tr) / fb`); middle ~30% is solid white.
Brightness is collapsed to a hex `#vvvvvv` SGR string per row by
`_credits_brightness_to_hex`; the same hex is reused as both fg and
bg-companion fg in `fg:<hex> bg:#000000`. Combined with the
1 row/sec scroll, each row spends ~35% × `term_rows` seconds in each
band — long enough for the gradient to read as cinematic rather than
as a sharp cutoff.

**`Escape to exit` hint.** Rendered as a Float above the scroll
content, pinned at `top=1, right=2`, `fg:#555555 bg:#000000`. Not
affected by the fade band — the float paints above the scroll text so
a credit line in row 0 doesn't clobber it.

**Input.** ESC pops back to the launcher main menu (via
`_reset_to_main()` — the previous frame stack entry is `main` because
`_log_auto_pause_at_end()` pops `log_view` before pushing `credits`).
Mouse activity does nothing — the credits control has no mouse
handler. No other keys are bound.

### `log_view` frame

Chain log player. Opened from `history` (Run log button, or
Enter / click on a row when `has_log`). Reads the `.log` siblings of the
chain's `summary.run_ids` for the current character and replays
them as a single timeline with play / pause, a scrubber, and a
pause-mode cursor.

**Load.** On push, `_enter_log_view(summary)` builds a
`log_player.LogPlayback(summary.character, summary.run_ids)`,
initialises the playback engine in pause mode at event 0 with
overlays visible (so Space, the scrubber, and the buttons are
discoverable on the first frame), and pushes the frame. The active
summary is stashed on the module-level `_log_view_summary` slot so
the frame survives independently of the `history_detail` state.
For each `run_id`, the loader tries
`data/runs/<character>/<run_id>.log`; runs whose `.log` is missing
are silently skipped. `run_ids` retains the original chain
ordering so `LogPlayback.run_at(idx)` reports the correct
`(run_id, run_ordinal, total_runs)` (with `run_ordinal` measured
against the unfiltered chain — consumed by the top header). If
every `.log` is missing the push aborts defensively; the
`has_log` gating on the `history` row normally prevents that
case.

**Event model.** Each parsed line becomes a `LogEvent` with
`ts_us`, `direction` (`"in"`/`"out"`), `text` (raw body, prefix
and `> ` stripped, CR trimmed), `run_id`, and pre-parsed
`fragments`. Inbound lines run through a 16-colour SGR parser
(plus bold/underline); 256-colour and truecolour escapes are
dropped so the affected run renders uncoloured rather than
crashing the player. Outbound lines render as a single fragment
in `C_LOG_PLAYER_INPUT` (no `>` prefix in the rendered output).
Events are merged into one list sorted by `ts_us` — within-file
order is preserved, the cross-file sort defends against clock
skew on chain rollover.

**Render.** A single focusable `Window` (`_log_view_window`)
holds a `_LogViewControl` (a `FormattedTextControl` subclass)
over the full frame. The visual lines are produced by wrapping
each event's fragment list at the terminal width and
concatenating them; the wrap is a fragment-aware split, not
`wrap_lines=True`, so style runs remain stable across the wrap
boundary. The wrapping cache re-builds when the terminal width
changes, alongside the parallel `_log_view_event_rows` map
(event index → `(visual_start, visual_end_exclusive)`) used by
pause-mode cursor painting and click-to-cursor row resolution.
In **play** mode the view auto-scrolls so the playhead event
sits at the bottom of the viewport (`_log_view_text_play`
slices `_log_view_lines[start_row:end_excl]` with
`end_excl = rows[playhead][1]`). In **pause** mode
(`_log_view_text_pause`) the view renders the full buffer at
`_log_view_scroll` with a `C_LOG_CURSOR` background highlight
on every visual row in the cursor event's row range — each
painted row is padded to `_log_view_cols` so the highlight spans
the trailing area past the line's text.

**Playback engine.** Two modes: `play` and `pause`.

- **Play** uses a monotonic anchor plus an offset:
  `_log_play_anchor_wall = monotonic()` at the last play-start
  and `_log_play_anchor_offset_us` the playback time at that
  moment. `_log_current_playback_us()` returns
  `anchor_offset + (monotonic() - anchor_wall) * 1e6`, clamped to
  `[0, total_duration_us]`. A 30 Hz asyncio tick task
  (`_LOG_TICK_HZ`, started by `_log_start_tick_task` /
  cancelled by `_log_cancel_tick_task`) invalidates the frame
  only when `_log_playhead_index()` advances to a new event or
  when the overlay hide-deadline expires; on reaching
  `total_duration_us` it calls `_log_auto_pause_at_end()` to
  park the cursor on the final event.
- **Pause** freezes the playback clock at
  `_log_paused_offset_us` and snaps `_log_cursor_index` to the
  current playhead. Resume (`_log_resume`) always snaps to the
  cursor's event timestamp — even if the cursor hasn't moved
  since the pause — by setting
  `_log_play_anchor_offset_us = pb.playback_offset_us[cursor]`
  and re-anchoring `_log_play_anchor_wall`.

**Overlays.** Two row-tall overlays float over the log: the top
header (`_LOG_OVERLAY_HEADER_W = 80` inner cells, centred)
showing `<character> (L<level>)  ·  Run X of Y  ·  YYYY-MM-DD HH:MM
·  <elapsed>` on the left and `ESC to return` on the right, and
the bottom controls (`_LOG_OVERLAY_CONTROLS_W = 70` inner cells,
centred) carrying a rewind button, a play/pause button (icon
reflects the action a click would take), a 30-cell scrubber
(`_LOG_OVERLAY_SCRUBBER_W`) with filled / thumb / empty
segments, and a `MM:SS / MM:SS` time field. `_log_format_mmss`
emits minutes verbatim and does not wrap to hours, so a
78-minute chain reads `78:34`. Overlays are permanent in pause
mode; in play they auto-hide after `_LOG_OVERLAY_HIDE_DELAY =
3.0` seconds. Any mouse activity in the frame calls
`_log_touch_overlays()` to re-arm the deadline and re-reveal
overlays if they had faded. The overlay palette
(`C_LOG_OVERLAY_BG` / `C_LOG_OVERLAY_FG` / `C_LOG_OVERLAY_HINT`,
`C_LOG_SCRUBBER_FILLED` / `_EMPTY` / `_THUMB`,
`C_LOG_BUTTON_IDLE` / `_HOVER`) lives in
[`palette.py`](../bridge/launcher/palette.py). The overlay bg is a
deep-shadow variant of the spotlight box hue (`C_SPOTLIGHT_BOX_BG`),
so both bars read as part of the same theme family in spotlight mode
and in chain mode from history.

**Keyboard.**

- `ESC` — pop back to the previous frame (typically `history`,
  with filter / sort / table cursor / Options cursor state
  intact) and clear the playback so the chain's parsed events
  can be garbage-collected. Chains are re-read on next push.
- `Space` — toggle play / pause.
- `↑ / ↓` — move the cursor by one event (routes through
  `_log_move_cursor`, which auto-pauses first if currently
  playing, then routes through `_log_set_cursor` for clamping
  and scrubber/time sync).
- `PgUp / PgDn` — move the cursor by `_LOG_PAGE_STEP = 20`
  events; same auto-pause behaviour.
- `Home / End` — jump the cursor to the first / last event;
  same auto-pause behaviour.

Every binding calls `_log_touch_overlays()` first so the
controls flash back into view on any keypress in play mode.

**Mouse.** Routed through `_LogViewControl.mouse_handler`.

- **Pause mode:** wheel up/down moves the cursor by one event
  (per spec — wheel moves the cursor, not just the viewport, so
  the resume point stays predictable). MOUSE_DOWN on a rendered
  event row sets the cursor to that event via
  `_log_event_row_to_index(_log_view_scroll + ev.position.y)`;
  it does **not** resume playback (Space is the resume action).
- **Play mode:** wheel and click on log content refresh the
  overlay-visibility timer only — they do not move the cursor or
  switch modes.
- **Scrubber drag:** MOUSE_DOWN on any scrubber cell sets
  `_log_dragging_scrubber = True` and performs the initial seek.
  While the flag is set, `_log_maybe_handle_drag` intercepts
  every mouse event anywhere in the frame — MOUSE_MOVE seeks
  (`_log_handle_drag_event` maps `ev.position.x - _log_scrubber_left`
  to a cell index against `_log_scrubber_width`, both published
  by `_log_controls_text` on each render), MOUSE_UP or a
  MOUSE_MOVE with the button released ends the drag. The
  rightmost scrubber cell maps exactly to `total_duration_us` so
  end-of-session click/drag triggers `_log_auto_pause_at_end`.

**Frame focus.** Per ADR 0066, `_log_view_window` is the primary
focusable window and is dispatched by `_focus_current_frame()`
on push.

## Rendering conventions

All frames render through `prompt_toolkit` controls. Layout building blocks:

- **Frame stack** — single `DynamicContainer` whose getter routes
  `_current_frame` to one of the prebuilt container trees. Each frame's
  primary `Window` is stored at module level and focused on push so
  keyboard handlers fire reliably.
- **Centered frames** — `main`, `profile_rename`, the profile-create
  sub-frames, `profile_delete_confirm`, `options`, `options_panes`,
  `options_pane`, `options_connection`, `options_connection_custom`,
  `options_coming_soon`, `history_detail`, `history_rate`,
  `history_delete_confirm`, `update_running`, `update_result`, and
  `exit_confirm` are wrapped in
  `HSplit([window], align=VerticalAlign.CENTER)` so they stay visually
  centred at any terminal height above the minimum.
- **Package-layout frames** — `history` and `profile` use a centred
  `[ table | scrollbar | gap | Options ]` package anchored at the top
  with a feedback row and footer below; a flex spacer absorbs leftover
  rows so the package, feedback row, and footer hug together at the top
  of the frame.
- **Scrolling frames** — `scripts` and `about` use a three-row split
  (`title` fixed height, `content` `Dimension(weight=1)`, `footer` fixed
  height) with the content control slicing by a scroll offset.
- **Minimum-size gate** — when `cols < 60` or `rows < 18`, the root getter
  returns a single "Terminal too small" container instead of the active
  frame. A `<any>`-filter binding swallows key input while the gate is
  on; Ctrl-C / Ctrl-Q still exit. Resizing past the threshold restores
  the normal UI transparently because the gate is checked on every
  render.
- **Mouse hover / click** — every selectable row carries a per-fragment
  `mouse_handler`. `MOUSE_DOWN` selects-and-activates in a single click.
  `MOUSE_MOVE` updates a hover index that paints the row in `C_HOVER`
  (between `C_ITEM` and `C_ACTIVE`) — best-effort on terminals that
  report cell-motion mouse events; keyboard navigation is the
  documented fallback. Keyboard-selected rows keep their `C_ACTIVE`
  highlight regardless of hover state.

**Colour palette.** All styles live in
[`bridge/launcher/palette.py`](../bridge/launcher/palette.py) and are
shared with the in-game popup. Roles:

| Name           | Role                                              |
|----------------|---------------------------------------------------|
| `C_TITLE`      | Page banners, ASCII logo, section titles          |
| `C_ACTIVE`     | Focused/selected row, emphasis in prompts         |
| `C_ITEM`       | Inactive selectable menu rows                     |
| `C_HOVER`      | Mouse-hovered row (between `C_ITEM` and `C_ACTIVE`) |
| `C_BODY`       | Body text — About prose, script summaries         |
| `C_HINT`       | Footer nav hints, secondary prompt labels         |
| `C_QUOTE`      | Italic quote text on the main menu                |
| `C_QUOTE_ATTR` | Quote attribution line (sage green)               |
| `C_ACCENT`     | Call-to-action rows, script alias headings        |
| `C_YELLOW`     | Warnings (non-fatal errors, can't-delete notices) |
| `C_ERR`        | Hard errors                                       |
| `C_SELECTED`        | History cursor row — black on light-grey background fill (sidebar active filter, table cursor row) |
| `C_ROW_HOVER`       | History detail data-table row hover — subtle background fill that composes with cell foreground colours |
| `C_LOG_PLAYER_INPUT`| log_view outbound (player command) lines — muted grey with a faint light-cyan tint                  |
| `C_LOG_OVERLAY_BG`  | log_view top header + bottom controls fill — deep-shadow variant of the spotlight box hue so chain and spotlight modes read as one theme family |
| `C_SPOTLIGHT_BOX_BG`         | Spotlight info-box fill — bright banner hue (same as `C_TITLE`) painted under every cell of the floating overlay |
| `C_SPOTLIGHT_FRAME`          | Spotlight info-box outline glyphs (`█▀▄▌▐`) — black on the box bg |
| `C_SPOTLIGHT_TEXT_PRIMARY`   | Spotlight info-box primary text — near-black on box bg (character name, event label) |
| `C_SPOTLIGHT_TEXT_SECONDARY` | Spotlight info-box secondary text — muted grey on box bg (countdown), visibly subordinate |

**Alignment convention (Profile / Options / Scripts pages).** Menu rows
are left-aligned on a shared column inside a centred block. The widest
label is computed on every render so the block re-centres after a
resize.

**About page three-colour scheme.** Each wrapped line is classified
before printing: all-uppercase lines → `C_TITLE` (headings); lines
starting with whitespace → `C_ACCENT` (key/command lines such as
`  cp -e`); all other non-empty lines → `C_BODY` (prose). Indented lines
pass through `_wrap_text` unchanged.

- **Alt screen / cursor / mouse modes.** `Application(full_screen=True,
  mouse_support=True)` manages alt-screen entry and exit, cursor
  visibility, and mouse-mode toggles itself. The launcher emits no
  manual ANSI escapes for layout or styling; the sole exception is
  the alt-screen-continuity write at handoff (see below).
- **Resize.** prompt_toolkit invalidates the layout on SIGWINCH; every
  text function reads terminal dimensions afresh, so the centred block
  recentres immediately.
- **One-second refresh.** `refresh_interval=1.0` drives periodic
  re-renders so the version-cache mtime check, session-status re-probe,
  and About update-available line track external state without a
  keypress.
- **ttimeoutlen / timeoutlen.** Both lowered to 50 ms so bare ESC fires
  near-instantly instead of waiting prompt_toolkit's 500 ms
  disambiguation timeout (same tuning as the popup).
- **Handoff via `os.execvp`.** The Enter-MUME dispatch records a
  deferred exec command, calls `app.exit()`, and then the main entry
  runs `os.execvp(...)` after `run_async` returns — so prompt_toolkit
  has a chance to restore the terminal before tmux or the new launcher
  takes over. The launcher → `tmux_start.sh` handoff itself is
  `execvp`'d, so there is no intermediate bash flash between menu and
  cockpit.
- **Alt-screen continuity across the handoff.** Immediately before
  every `os.execvp`, the launcher writes `\e[?1049h\e[?25l` to stdout
  to re-enter alt-screen and hide the cursor — bridging the brief gap
  between prompt_toolkit's terminal restore and the next program
  taking over. `tmux_start.sh` writes the same sequence at the top of
  the script and again on the return-to-menu branch (after `tmux
  attach` returns and before re-execing `launcher.sh`), so the
  alt-screen stays continuous in both directions and the user never
  sees a flash of the normal shell.

**Initial layout build.** `bridge/launcher/build_initial_layout.sh` is invoked in one of two modes (ADR 0070, supplementing ADR 0041), chosen by `bridge/launcher/tmux_start.sh` based on whether `LAUNCHER_COLS` / `LAUNCHER_ROWS` are set in the environment. In both modes the script splits panes, applies divider styling, and finally touches `bridge/runtime/.layout_ready`; meanwhile pane 0 runs `bridge/launcher/wait_for_layout.sh`, which polls `.layout_ready` at 50 ms intervals (2 s timeout) and then execs `tt++`. The sentinel handshake guarantees tt++ starts only after the layout is in place, so the first lines of tt++/Lua output are never lost into scrollback.
- **Pre-attach build (launcher path).** When `tmux_start.sh` is invoked from `launcher.py` the launcher exports `LAUNCHER_COLS` and `LAUNCHER_ROWS` from `prompt_toolkit`'s known terminal size — it just rendered a full-screen UI, so the dimensions are authoritative. `tmux_start.sh` then creates the detached session with explicit `-x` / `-y`, runs `build_initial_layout.sh` synchronously against the detached session, and only then calls `tmux attach`. The user sees a single frame transition from launcher to a fully-built cockpit — no visible cascade of pane splits.
- **Post-attach build (fallback).** Without the env vars (`--no-menu`, Windows shortcut → `bridge/launcher/launch.sh`), there is no reliable pre-attach dimension source: `stty size` is stale on terminals that haven't synced their PTY size when bash starts. `tmux_start.sh` registers a one-shot `client-attached` hook that fires `build_initial_layout.sh` after the first client attaches, at which point `tmux display-message -p '#{window_width}'` is authoritative. The script disarms its own hook on completion via `tmux set-hook -u client-attached` (idempotent — a no-op in the pre-attach path). The brief single-pane state after attach is visible but acceptable; see ADR 0041 for the full rationale that still governs this path.

`build_initial_layout.sh` itself is idempotent in both modes — a `PANE_COUNT > 1` guard at the top makes detach/re-attach a no-op. Its dimension source block prefers the env vars when present and falls back to `tmux display-message` otherwise, so the same script services both paths.

**Ctrl+C hardening (ui/dev panes).** Focusing a UI or DEV pane and pressing Ctrl+C would send SIGINT to the `tail -f` foreground process, kill it, and close the pane — breaking the layout for inexperienced users. Both panes are now launched with a hardened wrapper:

```
bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f <PATH>; printf "\n[pane kept alive — use cp-u/cp-d to close]\n"; sleep 0.2; done'
```

`stty -isig` disables signal generation (INTR/QUIT/SUSP) for the pane's tty, so Ctrl+C never produces SIGINT in the first place. `trap "" INT` is a belt-and-braces fallback in case stty is unavailable. The `while true` loop restarts `tail -f` if it exits for any other reason (log rotation, truncation). The input pane (`python3 bridge/panes/input_pane.py`) is deliberately unwrapped — it needs signals to function correctly.

---
Back to [architecture.md](../architecture.md).
