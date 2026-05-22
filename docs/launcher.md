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
`profile_create_copy_picker`, `profile_delete_confirm`, `profile_editor`,
`profile_editor_macro_keybind`, `options`,
`options_panes`, `options_connection`,
`options_connection_custom`, `options_coming_soon`, `scripts`, `about`,
`history`, `history_detail`, `history_rate`, `history_delete_confirm`,
`log_view`, `spotlights_empty`, `credits`, `update_running`,
`update_result`, and `exit_confirm` containers, pushed and popped via
`_push_frame` / `_pop_frame`. Each
frame owns its own `KeyBindings` filter (`_in_frame(name)`) so
navigation, scroll, and ESC behave per-frame. The popup architecture
(ADR 0062) is the reference; see `bridge/launcher/ingame_menu.py` for
the same patterns. The Panes submenu is a single `options_panes`
frame backed by the shared `panes_grid` module (ADR 0086); there is
no longer a per-pane subframe.

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

Top-to-bottom (P4 layout — see ADR 0088):

1. Title row — routed through `menu_chrome.title_block(...,
   blank_above=2)` so the title paints `C_SECTION`.
2. **Centred package: `[ button column | gap | profile table | scrollbar ]`.**
   Horizontally centred as one unit; the package drives all left/right
   positions on the frame and recentres on terminal resize.
   - **Button column.** Vertical column of 7 `button_fragment` cells
     (no inter-button gap, no border, no header): SELECT, NEW, EDIT,
     RENAME, DELETE, EXPORT, BACK. Labels are uppercase so the
     control surface reads as commands. Column width = longest
     button label + 2 cells of padding. The first button top-aligns
     with the table's header row — there is no `Options` header in
     P4. State mapping per ADR 0085's button-cell grammar: cursor +
     button zone focused → `selected_focused` (gold bg); cursor +
     button zone unfocused → `selected_unfocused` (grey bg); hover
     on a non-cursor enabled button → `hover` (previews the
     unfocused-selected look); disabled → `disabled` (dim grey
     foreground with no background block, so disabled buttons read
     as inert space rather than dark slots); else `inactive`.
   - **Gap.** 2 cells between the button column and the table's
     left edge.
   - **Profile table.** Two columns:
     - `Name` — dynamic width (longest profile name, floor = header
       width 4), left-aligned. Sortable: click toggles direction;
       default `Name ▲ asc`.
     - `Selected` — fixed width 8, centred. `✓` in `C_OK` (green) on
       the active profile, blank otherwise. Header is not clickable
       and shows no sort indicator. The green ✓ is a persistent
       active marker; gold is reserved for the transient focused
       cursor.
     - One-space gap between columns.
     - Column-header row paints `C_HINT` (muted grey) at all times,
       regardless of focus. The sort-indicator glyph (`▲` / `▼`)
       carries the active-column signal; focus is signalled by the
       cursor-row background, not the header row. Matches the
       panes-grid header row and the LITE editor's "headers stay
       muted grey" rule.
3. **Feedback row** — single row directly below the package; doubles
   as the spacing row above the footer. Holds transient feedback
   from Edit / Rename / Export (`Exported to ~/<name>.tin.` and
   `Renamed to "<new>".` in `C_ACCENT`, `Could not open <name>.tin: …`,
   `Save failed: …`, and `Export failed: …` in `C_HINT`) centred on
   the package width for ~3 s. Select does not flash — the ✓ in the
   Selected column is the confirmation.
4. Footer hint: `↑↓ Cursor · Tab/←→ Cycle · Enter Activate · ESC Back`,
   anchored to the final terminal row via a flex_spacer between the
   feedback row and the footer Window (matching the footer-anchoring
   contract used elsewhere on the launcher).

**Focus.** Two focusable Windows per the focus-on-push contract
(ADR 0066): `_profile_table_window`, `_profile_options_window`.
`_profile_focused: int` (0 = table, 1 = options) routes navigation.
Tab / Shift+Tab cycles between them (modulo 2). In addition, `←`
focuses the button column and `→` focuses the table —
non-wrapping (← on options and → on table are no-ops). The arrow
semantics follow the new spatial layout: the button column is on
the left, the table is on the right.

**Cursor and hover.** The cursor row in each panel adopts the same
focused / unfocused grammar as the buttons: gold background
(`C_BUTTON_ACTIVE_FOCUSED`) when its zone is focused, grey
(`C_BUTTON_ACTIVE_UNFOCUSED`) when not. Hover paints `C_HOVER` on
non-cursor selectable elements; cursor always wins over hover.

**Disabled rules.**

- **Select** — disabled when the cursor row is already the active profile.
- **Rename**, **Delete** — disabled when the cursor row is `default`.
- **Edit**, **New**, **Export**, **Back** — always enabled.

The button-column cursor moves through enabled buttons only (↑/↓
skips disabled), matching the History widget.

**Keyboard.**

| Focus   | Key                | Action                                  |
|---------|--------------------|-----------------------------------------|
| table   | ↑/↓                | move cursor row (clamp)                 |
| table   | PgUp/PgDn          | scroll 10                               |
| table   | Home/End           | jump to ends                            |
| table   | Enter / Space      | invoke Select (no-op if disabled)       |
| table   | ←                  | focus button column (no-op when there)  |
| options | ↑/↓                | move cursor button (skip disabled)      |
| options | Enter / Space      | activate selected button                |
| options | →                  | focus table (no-op when on table)       |
| any     | Tab / Shift+Tab    | cycle focus (options ↔ table)           |
| any     | ESC                | pop to main menu                        |

**Mouse.** Click activates (and switches focus to that panel).
Clicking a table row moves the cursor and focuses the table. Clicking
the `Name` header toggles sort direction. Clicking a button focuses
the button column and activates the button. The wheel scrolls the
table without moving the cursor (`_WheelScrollControl`, shared with
the History table); wheel over the gap / scrollbar / button column
is a no-op.

**Action handlers.**

- **Select** — writes `_conf["profile"]` and re-renders so the ✓ in
  the Selected column moves to the new row. No feedback flash — the
  ✓ is the visual confirmation.
- **New** — pushes the existing `profile_create_name` chain
  (validation → blank-vs-copy choice → optional copy picker). The
  ADR 0042 blank-template seeding is unchanged.
- **Edit** — parses the cursor row's `.tin` via `profile_io.load_profile`
  and pushes the `profile_editor` frame on success. On parse / I/O
  failure flashes `Could not open <name>.tin: <reason>` in `C_HINT`
  for ~3 s and does not push.
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

### `profile_editor` frame

Pushed by the Edit Options-button on `profile`. The editor has two
mutually exclusive views over the same in-memory `Profile`, flipped
via a LITE/EDITOR toggle on the title row:

- **Lite mode** — form-based browse + edit. Vertical kind column
  on the left, sorted entry list in the middle, per-kind detail
  panel on the right.
- **Editor mode** — full-frame plain-text view of the serialised
  profile file, with line numbers, soft wrap, current-line
  highlight, and an inline scrollbar.

Both modes live-bind to the same `Profile`: lite→editor serialises
the items into the buffer; editor→lite parses the buffer back. ESC
in either mode parses if needed, then `save_profile`s and pops to
the `profile` frame. Mode is **not** remembered across pushes —
every `_enter_profile_editor` lands on lite mode.

The flow took five earlier phases to reach this point: phase 1
shipped the shell + round-trip parser; phase 2 made the Aliases tab
a read-only list + detail browser; phase 3 added the create flow
and editable detail; phase 4 generalised the tab machinery across
the four other kinds (with a dedicated colour palette for
highlights); phase 5 brought Macros online with a key-capture
overlay. Phase 6 replaced the horizontal tab strip with the
vertical kind column, introduced the three-state colour grammar,
capped the body field at 10 rows, and added the editor-mode text
view + toggle (ADR 0083). Phase 6.2 polish: alphabetical sort with
group separation on parse + serialize (ADR 0084), dropped the
list-view sort header, redesigned the highlight palette (28-cell
checkbox swatches with selection decoupled from cursor), stepwise
Left-arrow fall-through across detail zones, Left/Right activates
the LITE/EDITOR toggle (renamed from MENU/EDITOR in Phase 6.4), and
footer hints stripped of arrow + Enter tokens. Phase 6.3 moved the
kind buttons from a vertical left column to a horizontal row above
the body (alphabetical order, Left/Right traverses), widened the
list (23 → 38) and detail (30 → 35), normalised tt++'s
`#write`-rewritten multi-line bodies on load for `action` / `alias`
/ `macro`, and dropped Bold from the highlight Style row.

#### Three-state colour grammar

A uniform background-driven indicator applied across the kind
buttons, the LITE/EDITOR toggle, the entry-list cursor row, the
detail-panel frame borders, and the focused-cursor cell inside every
detail-panel zone (Style toggles, Text/BG swatches, Macro Key cell).
Defined in `palette.py`.

| State                      | Token                       | Used for                                                                          |
|----------------------------|-----------------------------|-----------------------------------------------------------------------------------|
| Inactive (not selected)    | `C_BUTTON_INACTIVE`         | Non-active kind buttons; non-active mode button                                   |
| Active, zone unfocused     | `C_BUTTON_ACTIVE_UNFOCUSED` | Selected kind when kind-buttons row unfocused; active mode when toggle unfocused; entry-list cursor row when list unfocused |
| Active, zone focused       | `C_BUTTON_ACTIVE_FOCUSED`   | Selected kind when kind-buttons row focused; active mode when toggle focused; entry-list cursor row when list focused; detail-panel frame borders; cursor cell inside a focused detail zone — Style toggle, Text/BG swatch checkbox slot, Macro Key cell |

Governing principle: wherever keyboard focus sits in the editor, the
focused element paints amber (`C_BUTTON_ACTIVE_FOCUSED`). The cursor +
focused branch always wins over hover and over the existing
active / selected treatment in every detail-panel zone.

**Grey "out of focus" applies only to persistent selections.** The
`C_BUTTON_ACTIVE_UNFOCUSED` (grey) state marks something the user has
chosen that stays relevant while they work in another zone — the
**current kind tab** and the **entry being edited** in the list. Both
have no other glyph to carry that meaning, so the grey background
does it.

A cursor position inside a multi-cell palette zone (Style toggles,
Text swatches, BG swatches) is *not* a persistent selection — it only
records "where the cursor was last in this zone" and is irrelevant
once focus leaves. So palette zones are **amber-or-nothing**: amber on
the cursor cell when the zone is focused, default styling everywhere
else. The cursor index is still retained internally and reappears as
amber when the zone regains focus; `[X]` / `[ ]` continues to show
on/selected state in every case. The macro Key cell follows the same
rule — amber when focused, default otherwise; it is a single-cell
field, not a list cursor.

Hover on an inactive button paints the active-unfocused state — a
preview of how it would look if selected. Hover on chrome
(gaps, padding, blank rows) clears all hover state.

Headers (`Pattern  Body`, `Pattern`, `Commands`, `─── Hint ───`)
stay in muted grey (`C_HINT`) at **all** times — the cursor row and
button states carry the focus signal. The Pattern column header is
non-interactive (Phase 6.2: sorting is canonical, no toggle).

#### Layout

Top-to-bottom (lite mode — Phase 6.3):

1. **Title row** — `─── Profile Editor: <name> ───` in `C_SECTION`,
   centred on the terminal, with the LITE/EDITOR toggle
   right-aligned on the same row.
2. Blank row.
3. **Kind-buttons row** — five 3-row-tall BG-filled blocks
   (`ACTIONS`, `ALIASES`, `HIGHLIGHTS`, `MACROS`, `SUBSTITUTES`)
   separated by 3-cell gaps, the whole group centred on the
   terminal.
4. Blank row.
5. **Body** — two columns (`[ list+scrollbar | detail ]`); the
   kind column moved into the row above in Phase 6.3.
6. **Footer hint** — text depends on focus zone and mode (see
   *Focus model*).

Editor mode is identical except step 3 (the kind row) is omitted —
the buffer fills the space directly after the title's blank row,
all the way down to the footer's blank + hint row. The vertical
chrome budget in editor mode is `2 blanks + title + 1 blank +
buffer + 1 blank + footer hint` (6 chrome rows around a buffer
sized to `term_rows - 6`), so there are no dead rows at the
bottom.

The frame itself is `HSplit([body, flex_spacer, footer])` (built by
`_build_profile_editor`, not `_build_simple`): the body emits
chrome + body region, the footer Window emits the blank + hint
row, and the flex_spacer absorbs leftover terminal rows so the
footer hint sits on the final terminal row in both modes — the
same anchoring contract the `profile` / `history` frames use. In
editor mode the body + footer sum to `term_rows` exactly so the
spacer collapses to zero and the existing editor anchoring is
preserved. In lite mode the body is shorter than the terminal and
the spacer absorbs the slack between body and footer.

Because the frame no longer runs through `_centered`, the body
anchors to the top of the available space and the leading blank
rows above the title are emitted explicitly in both modes — two
in editor mode (body fills exactly so there is no slack to
distribute), one in lite mode (matching the leading blank that
vertical centering used to supply "for free"). The overhead
constants in `_editor_body_h` count these blanks — sync them
together. `_editor_body_h()` branches on `_editor_mode` for this
— lite keeps the wider lite-mode chrome budget; editor uses the
smaller one.

Centred kind-buttons row width: 5 × 13 + 4 × 3 = **77** cells.
Centred body widths: list 38 + scrollbar 1 + gap 3 + detail 35 =
**77** cells — both rows nominally align. Phase 6.3 widened the
list (23 → 38), detail (30 → 35), and inter-panel gap (2 → 3) to
reclaim the space freed by removing the kind column.

#### LITE/EDITOR toggle

Two 1-row blocks on the title row, uppercase, padded by one cell
on each side (`LITE` becomes 6 cells, `EDITOR` becomes 8). A
single space separates the blocks. The whole toggle is right-
aligned so the `R` in `EDITOR` sits directly above the right `┐`
of the lite-mode detail-panel Pattern frame below. If the centred
title would collide with the toggle on a narrow terminal, the
title's right-side decorative dashes truncate; the toggle is
never sacrificed.

- Activation (Phase 6.2): `Left` selects LITE, `Right` selects
  EDITOR when the toggle has keyboard focus — no-op when the
  requested mode is already active. `Enter` and `Space` are no
  longer toggle activators (they're free for the buffer and other
  zones). Mouse click on the inactive block flips; click on the
  active block is a no-op. Mouse hover on the inactive block
  paints `C_BUTTON_ACTIVE_UNFOCUSED` (preview).
- Focus: `_editor_toggle_focused` is a separate flag — when True,
  no lite-mode editing zone responds to keys. `↑` on any
  kind-buttons row button falls through to the toggle (Phase 6.3);
  the entry-list top row and detail.Pattern fall through to the
  kind-buttons row, not to the toggle. `↓` from the toggle drops
  into the first zone of the current mode (kind-buttons row in
  lite, buffer in editor).

**No keystroke binds mode switching.** Pressing `m`, `e`, `M`, or
`E` on any text-editing context (Pattern, Body, editor buffer,
sentinel hint, kind-list cursor) inserts the literal character.
Mode flip is exclusively via toggle activation (focus + Left /
Right, or click).

#### Lite mode

**Kind buttons (horizontal row).** Phase 6.3 replaced the vertical
left column with a single 3-row-tall row of five buttons that sits
between the title and the body. Buttons in **alphabetical** order:
`ACTIONS`, `ALIASES`, `HIGHLIGHTS`, `MACROS`, `SUBSTITUTES`. Each
button's background fills its full 13-cell × 3-row footprint (wide
enough for "SUBSTITUTES"); the label is centred on the middle row.
Buttons are separated by 3-cell gaps and the whole group is centred
on the terminal. Mouse click on any button switches the active kind
and focuses the kind-buttons zone.

Keyboard within the kind-buttons row:
- `←` / `→` move between buttons. No wrap — `←` on `ACTIONS`
  and `→` on `SUBSTITUTES` are no-ops.
- `↑` falls through to the LITE/EDITOR toggle.
- `↓` falls through to the entry list.

The row sits between the toggle and the body in the new physical
stacking, so the up-arrow fall-through from the entry list top row
and from detail.Pattern lands on the kind-buttons row (not on the
toggle, as in Phase 6.2).

**Entry list (middle).** Header row `<pat_label>  <body_label>` in
`C_HINT` (muted grey) at all times. Labels come from
`DETAIL_LABELS[active_kind]` so Highlights shows `Pattern + Color`,
Substitutes shows `Text + New text`, etc. Pattern column is a fixed
8 chars; Body column flexes. The Body cell skips leading
blank/whitespace-only lines so a body whose first real content sits
below empty lines still previews (the detail panel keeps the body
verbatim — this only affects the list cell). A trailing `…` is
appended whenever the displayed cell does not show the body in
full — either the first non-blank line had to be truncated to fit
the column, *or* additional non-blank content follows it (Phase
6.4). Example: a two-line body `testcommand1;\ntestcommand2` whose
first line fits the column still renders as `testcommand1;…` so
the list signals "there's more". `_list_body_preview` is the pure
helper backing this and is unit-tested in
`test_profile_editor.py:TestListBodyPreview`. The cursor row paints
per the colour grammar (amber when list focused, grey when
unfocused); hover paints `C_HOVER`. The reusable scrollbar
(`bridge/launcher/widgets/scrollbar.py`) renders in the 1-cell
column to the right of the list, with page-step click-to-jump
support; the track appears only when entries overflow the visible
window. Wheel ticks anywhere on a list row or its scrollbar cell
shift the viewport by `±3` rows through `_editor_list_wheel`
without moving the list cursor; a click-and-hold on a track row
above or below the thumb arms the shared auto-scroll controller
documented under Editor mode.

A `+ New entry` sentinel row is rendered at the bottom of the list
in `C_HINT`. The sentinel is selectable like any row; pressing
`Enter` on it — or pressing `n` from anywhere on list focus, or
clicking it once with the mouse — appends a blank Entry of the
active kind and focuses the detail panel's Pattern field. The list
cursor's index range spans `[0, len(view)]`, with `len(view)`
denoting the sentinel.

Mid-session create appends to `Profile.items` without re-sorting,
so the new entry lands at the bottom of its kind group in the list
view until the next save / mode-flip (which re-sorts via
serialize → parse). The list-view sort itself is presentation-only
ascending by pattern (case-sensitive for non-macro kinds; macros
sort by display name so F-keys cluster before numpad before Alt).

**Detail panel (right).** Per-kind labels from `DETAIL_LABELS`:
`alias`/`action` → `(Pattern, Commands)`, `substitute` →
`(Text, New text)`, `highlight` → `(Pattern, Color)`, `macro` →
`(Key, Commands)`. The builder is chosen by
`_editor_dispatch_detail_builder(kind)`:
`_editor_build_text_detail` for the three text-bodied kinds,
`_editor_build_palette_detail` for highlights,
`_editor_build_macro_detail` for macros (Key cell + text body).

- **Pattern field** — single-line bordered field bound to
  `entry.pattern`. Pattern is required; see *Validation*.
  Double-click selects the same-class run under the pointer;
  triple-click selects the whole field (Pattern is single-line, so
  word-vs-line behave identically once the run covers the field).
- **Body field** (text-bodied kinds) — multi-line bordered field
  bound to `entry.body`. **Capped at 10 visible rows** via
  `_EDITOR_BODY_CAP_ROWS`; bodies that exceed the cap render with
  an inline scrollbar in the rightmost inner cell of the box, and
  the viewport tracks the cursor on cursor moves and keystrokes.
  `Enter` splits the current line at the cursor; `←`/`→` traverse
  line boundaries; `↑`/`↓` move the cursor between lines while
  preserving column (clamped to the destination line's length).
  Double-click and triple-click select the same-class run or the
  body line under the pointer — same `_editor_click_tick` plumbing
  as the editor buffer; the trailing `\n` is excluded from a
  triple-click line selection. Mouse-wheel ticks scroll the body
  viewport when content overflows the 10-row cap (no-op
  otherwise); the body cursor stays put and the next cursor-
  moving keystroke pulls the viewport back. The inline scrollbar
  honours click-and-hold auto-scroll on its track. (Alt+↑ / Alt+↓
  is editor-mode-only — bare `↑` / `↓` is already the cursor
  move inside Body, so there is no lite-mode swap-lines analogue.)
- **Detail-panel frame borders** transition colour with field
  focus: unfocused → `C_HINT` (muted grey); focused → `C_ACCENT`
  (amber). This is the sole focus indicator for the field's
  bounding box — the in-buffer cursor inside the field is the
  fine-grained indicator.
- **Highlight palette** (highlights only) — Phase 6.4 layout
  replaces the Body field with an inline row of three style toggles
  `[ ]Undersc. [ ]Blink [ ]Reverse` (Phase 6.3 dropped Bold — tt++
  doesn't list it as a `#highlight` modifier, and surfacing it
  produced bodies tt++ would reject or silently drop), then
  `── Text ──` / `── BG ──` headers (U+2500 box-drawing glyphs,
  matching the `─── Hint ───` divider styling) over a 2×7 grid of
  checkbox swatches. Phase 6.4 removed the `Style` label row that
  used to sit above the toggles and added one blank row above and
  one blank row below the toggle row, so the Style toggle breathes
  visually. Each swatch renders as `[X]██` or `[ ]██` where `██`
  is a two-cell color band; the checkbox reflects whether THAT
  swatch is the currently-selected text/bg colour.
  Cursor and selection are decoupled (see ADR 0084): cursor moves
  navigate the grid without changing the body; `Enter` (or mouse
  click) on a swatch toggles its selection — selecting it (and
  clearing any previously selected swatch in the same dimension)
  if it was unselected, deselecting it if it was already selected.
  Exactly zero or one swatch per dimension is selected at any time.
  A persisted body containing `bold` falls through `_hl_parse_body`
  as unknown so the original `_raw` survives byte-exact on save
  (no Bold control surfaces in the palette).
- **Body serialisation.** Composed as
  `[<styles>] [<text-colour>] [b <bg-colour>]` — styles emitted
  in stable order (`bold`, `underscore`, `blink`, `reverse`);
  colour tokens use the cell label as-is; the `b <bg>` clause is
  omitted when no BG swatch is selected; the text colour is
  omitted when no Text swatch is selected. The parser
  (`_hl_parse_body`) accepts the lowercase, capitalised, and
  `light <colour>` forms equivalently.
- **Unparseable bodies** persist verbatim in `entry.body` until
  the user toggles a swatch (no Custom slot in Phase 6.2 — see
  ADR 0084). Cursor parks at `(0, 0)` on both dimensions with no
  selection.
- **Macro Key cell** — focusable one-line button rendered as
  `[ Numpad 0 ]` / `[ F1 ]` / `[ Alt+a ]` for known escapes,
  `[ Custom: <raw> ]` in `C_HINT` for unknown ones, and
  `[ Press to bind… ]` in `C_HINT` for an empty pre-capture
  entry. `Enter` (or a mouse click) pushes the
  `profile_editor_macro_keybind` overlay. Phase 6.4 dropped the
  `(Enter to rebind)` hint line that used to render directly
  below the Key cell — the row remains blank so the macro layout
  height is unchanged.
- An inline-error slot below the body widget (`C_DANGER`), then a
  blank row, a centred `─── Hint ───`, and the per-kind two-line
  hint below it (see *Hint content* below).

##### Hint content

Each kind has a fixed two-line hint shown beneath the centred
`─── Hint ───` divider in the detail panel, styled in `C_HINT`.
Line 1 is a short syntax reminder; line 2 is a single-line example
phrased for lite-mode input (pattern and body cells, not the full
`#command` line) — `→` separates the pattern side from the command
side. The hints live in the `_EDITOR_HINTS` dict in `launcher.py`:

| Kind         | Line 1                              | Line 2                                |
|--------------|-------------------------------------|---------------------------------------|
| `alias`      | `%1 %2 capture words · ; chains`    | `gv %1  →  get %1;value %1`           |
| `action`     | `%1 %2 match text · ^ anchors line` | `^%1 raises %2 hand  →  group %1`     |
| `highlight`  | `%1 matches text · ^ anchors line`  | `^%1 enters  colours whole line`      |
| `substitute` | `%1 %2 capture & reuse in New text` | `%1 massacres %2 → %1 MASSACRES %2`   |
| `macro`      | `Enter on Key cell to bind a key`   | `$var inserts variable · ; chains`    |

Hint lines must fit the detail panel's inner width
(`_EDITOR_DETAIL_W = 35`, target ~33 chars). Shorten examples
(drop a word, tighten spacing) rather than letting them wrap or
truncate mid-token. Source for syntax accuracy: the ACTION,
HIGHLIGHT, SUBSTITUTE, and ALIAS sections of `ttpp_manual.txt`.

**Sentinel-cursor state.** When the list cursor sits on the
sentinel row the detail panel shows a centred prompt — `Press
Enter to create a new <kind>.` (or `No <kinds> yet. Press n to add
one.` when the active kind has zero entries).

**Per-kind new-entry defaults.** Aliases, actions, and substitutes
start blank; highlights default to `body='light yellow'`. Macros
also start blank, but `+ New entry` immediately auto-pushes the
key-capture overlay so the user never sees `[ Press to bind… ]`
in the wild.

**Display ordering.** Phase 6.2: `parse_profile` sorts items into
command groups, alphabetical within each group; `serialize_profile`
emits groups separated by a single blank line. The list view
mirrors this — sorted ascending by pattern (case-sensitive for
non-macro kinds; macros sort by display name). There is no
sort-direction toggle anymore — the canonical sort is the only
order. While the user types in Pattern the displayed list re-sorts
live and the cursor follows the edited entry. Mid-session creates
append to the bottom of their kind group; the next save / mode-flip
re-sorts via serialize → parse.

**Live binding.** Every keystroke in a detail field updates the
bound `Entry` field immediately. Field mutation routes through
`Entry.__setattr__`, which clears `_raw` whenever any of `pattern`,
`body`, or `priority` change — guaranteeing canonical
serialisation on save while untouched entries continue to emit
`_raw` byte-exact.

**Validation.** Same as phase 3: at most one inline message at a
time, precedence `Pattern required > Unbalanced braces in Pattern
> Unbalanced braces in Commands`. Empty Pattern is allowed while
typing; the error arms once the user leaves the field. The
brace-balance primitive (`_braces_balanced`) ignores `\{` and
`\}` and is unit-tested directly. Save is never blocked;
empty-pattern entries are dropped before write.

#### Editor mode

A full-frame plain-text view of the serialised profile. No frame
border around the buffer. Three regions stacked horizontally:

1. **Line-number column** — 4 cells: 3 digits, right-aligned, plus
   1-cell gap. Style `fg:#585858` (muted grey, same tone as the
   scrollbar track). Numbering starts at 1. Soft-wrap continuation
   rows show no number (blank cells in the column). When the file
   exceeds 999 lines the column widens by one cell per extra digit.
2. **Text buffer** — fills the remaining width minus the
   scrollbar. Soft line wrap on; hard newlines insert real
   newlines. The line containing the cursor renders with a subtle
   background tint (`bg:#1f1f1f` when the buffer has focus,
   `bg:#141414` when the toggle has focus — a dimmer follow-along
   so the user keeps context while navigating the toggle).
3. **Scrollbar** — 1-cell column on the right edge. Visible only
   when content exceeds the viewport. Page-step click semantics
   match the rest of the editor.

**Cursor model.** `_editor_buffer_cursor` is an absolute character
offset into `_editor_buffer_text` (range `0..len(text)`). Helpers
convert to `(line, col)`:
- `_editor_buffer_line_starts()` — table of logical line start
  offsets. Always at least one entry (`[0]`). When the buffer
  ends with `\n`, a phantom line is added so end-of-buffer is a
  valid cursor position.
- `_editor_buffer_cursor_to_line_col()` — `(line, col)` walk.
- `_editor_buffer_line_text(idx)` — text of a logical line
  (without trailing `\n`).

**Soft wrap.** `_editor_buffer_visual_layout(cols)` computes
`(wrap_w, total_visual_rows, line_to_visual)` — the per-row width
of the buffer area, the total number of visual rows after wrap,
and a table mapping each logical line to its starting visual row
and wrap count. Empty logical lines still occupy one visual row.

**Editing keys.** All scoped to `_in_pe_editor()`:
- `←` / `→` — move cursor by one character.
- `↑` / `↓` — move by one logical line, preserving column.
- `↑` at top of buffer — fall through to the toggle.
- `Alt` + `↑` / `↓` — swap the cursor's logical line with the one
  above / below. The cursor follows the moved line with its
  column preserved (clamped to the new line's length); no-op at
  the buffer ends. Recorded as a single atomic undo transaction,
  clears any pending auto-close offsets, and drops any active
  selection — multi-line block move is out of scope.
- `Home` / `End` — line start / end.
- `PgUp` / `PgDn` — viewport-sized vertical move.
- `Shift` + `←` / `→` / `↑` / `↓` / `Home` / `End` — extend
  selection from anchor. See **Selection** below.
- `Backspace` / `Delete` — character deletion, or selection delete
  when a selection is active.
- `Enter` — insert `\n`. Replaces any active selection first.
- `Tab` — cycle focus to the toggle (does **not** insert a literal
  tab).
- `c-z` / `c-y` — undo / redo. Snapshot-based, with typing
  coalescing. See **Undo / redo** below.
- Printable `<any>` — insert at cursor. Replaces any active
  selection first.

The `profile_editor` frame's bare `escape` binding is registered
*without* `eager=True` so prompt_toolkit waits briefly for a
follower key before firing ESC. Alt+↑ / Alt+↓ arrive as the
escape-prefix chords `(escape, up)` / `(escape, down)`, and an
eager bare ESC would save-and-close before the arrow could
disambiguate; the cost is a short, terminal-dependent delay on
bare ESC (capped by `timeoutlen` / `ttimeoutlen`, both lowered to
50 ms). The same trade-off applies to the macro-keybind overlay's
ESC binding so Alt+letter capture works there too.

**Mouse.** Single click in the buffer positions the cursor on the
clicked `(line, col)`, clears any active keyboard selection, and
clears toggle focus (so the buffer responds to the next
keystroke). Double-click selects the same-class run under the
pointer (word / whitespace / punctuation); triple-click selects
the logical line — see **Double / triple-click selection** below.
Wheel ticks scroll the viewport without moving the cursor — see
**Mouse-wheel scrolling** below. Click on the inline scrollbar's
track above the thumb pages up by one viewport; click below pages
down; click on the thumb itself is a no-op. Holding the button on
a track row above or below the thumb arms click-and-hold
auto-scroll — see **Click-and-hold auto-scroll** below. Drag-to-
select is still not wired (see the
[Mouse-drag selection is not wired](#mouse-drag-selection-is-not-wired)
note further down for the constraint).

**Selection.** `_editor_buffer_anchor` (`int | None`) is the anchor
char offset; `None` means no selection. Pressing any
`Shift`+movement key plants the anchor at the current cursor (if
unset) and moves; the selection range is
`[min(anchor, cursor), max(anchor, cursor))`. The selection band
paints with `C_SELECTED` styling on every covered cell, spanning
multiple visual rows when the selection crosses wraps or logical
lines. Plain (unshifted) cursor movement, a single content click,
mode flip, or any successful mutation clears the anchor. Typing
or `Backspace`/`Delete` with an active selection replaces or
deletes the selection as a single operation. The clipboard
triplet (`c-c` / `c-x` / `c-v`) operates on whichever selection
is active, including selections produced by double/triple-click —
see **Clipboard** below. Double-click and triple-click set the
anchor and cursor directly to the run / line bounds; the same
clear-on-plain-move rule then applies.

**Double / triple-click selection.** prompt_toolkit only delivers
single MOUSE_DOWN events, so the editor rebuilds the click count
itself. `_editor_click_tick` compares each click's `(t, x, y)`
against the previous one, cycles the count `1 → 2 → 3 → 1` while
the click falls within `_EDITOR_CLICK_WINDOW` (0.4 s) at the same
cell, and resets to 1 outside the window or at a different cell —
no timer or debounce, the count is rebuilt on every click. The
clock source is indirected via `_editor_click_now` so tests drive
the count deterministically rather than sleeping.

Double-click calls `_editor_buffer_select_word_at`, which expands
the selection to the same-class run that contains the clicked
character. `_editor_word_class` is a three-way classifier:
`word` (alphanumerics + `_`), `ws` (space / tab), and `other`
(everything else — punctuation, symbols, non-latin printables);
the run is extended in both directions while neighbouring
characters share the click's class. A double-click at or past
end-of-line places the cursor at line-end with no selection —
word selection never crosses a line boundary. Triple-click calls
`_editor_buffer_select_logical_line`, which anchors at the line's
start offset and parks the cursor at the last character of the
line; the trailing `\n` is deliberately excluded so the highlight
stops at end-of-line instead of bleeding onto the first cell of
the next line. The classification is deliberately plain lexical —
double-click ignores the syntax tokeniser, so a click inside
`${var}` selects `var` and not the full `${...}` token.

The same click-count plumbing drives double/triple-click in the
lite-mode Pattern and Body fields (see **Lite mode → Detail
panel** below). Editor-mode and lite-mode counts share
`_editor_click_count`; a click in Pattern after a double-click in
the editor buffer resets to 1 because the `(x, y)` differs.

**Scroll decoupling.** `_editor_buffer_scroll_into_view` is invoked
only from cursor-mutating actions (keystrokes, content clicks,
shift-arrow selection moves, mutations) — never unconditionally
on render. Scrollbar clicks, wheel ticks, and click-and-hold
auto-scroll therefore move the viewport away from the cursor and
the viewport stays where they placed it across subsequent renders
until the user moves the cursor with the keyboard or clicks in
the buffer (the next cursor move pulls the viewport back to the
cursor, matching the convention in code editors).

**Mouse-wheel scrolling.** Wheel ticks on the editor buffer route
through `_editor_buffer_wheel`, which shifts `_editor_buffer_scroll`
by `±3` visual rows per `SCROLL_UP` / `SCROLL_DOWN` event. The
buffer cursor stays put; the next cursor-moving keystroke pulls
the viewport back via `_editor_buffer_scroll_cursor_into_view`,
matching the scrollbar-click decoupling. Wheel events delivered
over the line-number gutter forward to the same handler so the
gutter edge is not a dead zone. Lite-mode equivalents share the
same `±3` step: `_editor_list_wheel` drives the entry list's
Scrollbar widget so its internal offset stays authoritative;
`_editor_body_wheel` shifts `_editor_body_scroll` on the
multi-line Body field and is a no-op when the body fits inside
the 10-row cap. All three keep the cursor decoupled — viewports
move freely, the next keystroke pulls the viewport back to the
cursor.

**Click-and-hold auto-scroll.** Holding the mouse button on a
scrollbar **track** row above or below the thumb pages the
viewport once immediately (the same step a single click would
take), then — after `_AUTOSCROLL_INITIAL_DELAY` (~300 ms) —
auto-repeats the page-step toward the held row roughly every
`_AUTOSCROLL_REPEAT_INTERVAL` (~100 ms), stopping when the thumb
covers the held row. A click-and-hold on the thumb itself is a
no-op (drag is out of scope; arming only fires on track rows). A
launcher-level controller — `_autoscroll_arm` / `_autoscroll_tick`
/ `_autoscroll_set_target` / `_autoscroll_disarm` — owns the
single in-flight handle through `_app_loop.call_later`; each
scrollbar contributes its own `step_fn`
(`_editor_buffer_autoscroll_step`, `_editor_list_autoscroll_step`,
`_editor_body_autoscroll_step`) that re-reads the live thumb
geometry against `_autoscroll_target` and pages one viewport
toward it. `MOUSE_UP` on the track disarms early as a fast path;
`MOUSE_MOVE` updates the target so the held position can drift,
best-effort because terminals don't all surface motion under a
button hold. A missed `MOUSE_UP` degrades to "scrolled to the
clicked position and stopped" rather than running forever — the
self-terminating target is the load-bearing invariant. Auto-scroll
moves only the viewport offset, never the cursor, consistent with
the wheel/scrollbar cursor decoupling, and is disarmed on
`_enter_profile_editor`, `_profile_editor_save_and_close`, and
every `_editor_flip_mode` so it never outlives the editor frame.
See
[ADR 0092](decisions/0092-profile-editor-scrollbar-autoscroll.md)
for the self-terminating-target design and the rejected
"repeat until `MOUSE_UP`" / "fixed budget" alternatives.

**Layout caches.** `_editor_buffer_line_starts_cache`,
`_editor_buffer_visual_cache`, and `_editor_buffer_syntax_cache`
are keyed off the buffer text's *identity* (`is` compare); Python
strings are immutable, so every mutator allocates a fresh string
and invalidates all three caches automatically. Without them, the
three layout passes per render (one direct, two via
`_editor_buffer_cursor_visual_row`) would each be O(N·L) over the
full buffer — visibly laggy on files of ~20+ lines. The renderer
also emits per-row style runs (line-num cell + 1–5 content runs +
scrollbar) with a single per-row mouse handler instead of one
fragment + closure per cell.

**Syntax highlighting.** Editor mode renders five token classes in
muted colours on top of the C_ITEM base — tt++ commands
(`#alias`), braces, `;` delimiters, variables (`$x`, `${x}`,
`&x`, `%1`, `%*`), and `<>` colour codes / `\`-escapes. The
tokeniser lives in [`ttpp_syntax.py`](../bridge/launcher/ttpp_syntax.py);
it is purely lexical (no grammar awareness) and single-pass, so
an occasional `;` inside an action body or a `#` inside a string
literal will be coloured — accepted as a harmless cost for the
much simpler implementation (see ADR 0089). The palette tokens
are `C_SYN_COMMAND`, `C_SYN_BRACE`, `C_SYN_DELIM`, `C_SYN_VAR`,
`C_SYN_CODE`; they compose with the current-line tint and the
`C_SELECTED` selection band. Lite mode is untouched, and the
lite ↔ editor round-trip is unaffected.

**Brace assistance.** Editor mode only; the lite-mode Pattern /
Commands fields are not affected. Three coupled features.

1. **Auto-close `{`.** Typing `{` inserts `{}` and leaves the
   cursor between them — but only when the character immediately
   after the cursor is end-of-buffer, whitespace, or `}`. Otherwise
   a literal `{` is inserted. The guard prevents auto-close from
   firing when the user is editing into existing non-whitespace
   text. The auto-inserted `}` is *tentative*: typing `}` next, or
   pressing `→`, steps over it instead of inserting a second
   `}`. Pressing `Backspace` immediately after the auto-insert
   removes both braces as one operation. `()` and `[]` are not
   auto-closed — `{` only.

   Tracking lives in `_editor_pending_closers` (a list of absolute
   offsets of every tentative `}`). The four buffer mutators
   (`_editor_buffer_insert`, `_editor_buffer_backspace`,
   `_editor_buffer_delete`,
   `_editor_buffer_consume_selection`) shift the list across
   inserts/deletes so the offsets stay valid. Any editor action
   other than a printable insert, `Backspace`/`Delete`, the `}`
   overtype, and `→` clears the list — arrows up/down/left,
   `Home`/`End`, `PgUp`/`PgDn`, shift-selection, mouse click, and
   the lite ↔ editor flip all end tracking. `→` itself only drops
   offsets now strictly behind the cursor — stepping over a
   tentative closer ends its tracking without flushing the rest.
   The auto-close logic sits in the `{`/`}` *key* handlers, not
   in `_editor_buffer_insert`, so a future paste path can never
   trigger it.

2. **Matching-brace highlight.** When the cursor is adjacent to a
   structural brace — the character at or just before the cursor
   is a `{`/`}` that appears as a `"brace"`-kind token — its
   partner is found via a depth scan over the brace-kind offsets
   only and both cells are painted with `C_SYN_BRACE_MATCH` (a
   subtle background lift). Braces inside `${...}` and `\{` are
   not structural — the tokeniser excludes them, so they never
   match. An unbalanced brace highlights nothing. Compose order
   for a brace cell's final style: selection bg (if selected) >
   match bg > current-line bg tint.

3. **Balance indicator.** A short right-aligned segment on the
   editor-mode footer row reports unclosed `{` (final depth > 0)
   and/or stray `}` (depth ever went negative) — e.g. `3 unclosed
   {` or `2 stray }`. Rendered in `C_DANGER`. When braces
   balance, no indicator is shown.

**Footer Ln/Col indicator.** The editor-mode footer row carries an
always-on `Ln <N>, Col <N>` segment (1-indexed; converted from
`_editor_buffer_cursor_to_line_col`'s 0-indexed pair by
`_editor_line_col_text`) right-aligned to the terminal edge. The
brace-balance segment, when present, sits immediately to its left
joined by `  ·  `; Ln/Col stays at column
`cols - len(lc_text)` regardless of whether the brace segment is
present, so the cursor coordinates do not jitter as braces come
in and out of balance. A live `c-c` / `c-x` flash takes over the
centred message slot and suppresses the brace-balance segment for
the duration of the flash, but Ln/Col remains pinned to the right
edge — the brace indicator yields, the cursor coordinates do not.
Lite mode does not render the indicator: Pattern is single-line
and Body is capped at 10 rows, so position is obvious from the
field's own cursor.

**Undo / redo.** Editor mode only; the lite-mode Pattern / Commands
fields are not affected.

- `c-z` undoes the most recent transaction; `c-y` redoes. Empty stack
  → no-op.
- A snapshot is the whole buffer state: `(text, cursor, anchor)`.
  Strings are immutable, so snapshots store references — full-buffer
  history of a few-KB profile is cheap. Two module-level stacks
  (`_editor_undo_stack`, `_editor_redo_stack`) hold the snapshots;
  the undo stack is capped at `_EDITOR_UNDO_MAX_DEPTH` (200) with
  the oldest entry dropped on overflow.
- Both stacks reset on `_enter_profile_editor` and on every
  lite ↔ editor flip — undo history never survives leaving the
  editor or a mode change.
- **Coalescing** keeps a word's worth of typing under a single c-z.
  Consecutive single-character `<any>` inserts merge into one
  transaction; consecutive Backspace / Delete keystrokes likewise
  merge. A boundary (the current run ends, the next edit starts a
  fresh transaction) is forced by any of: a newline insert, any
  cursor move (arrow / Home / End / PgUp / PgDn / mouse click), a
  switch between insert and delete edit kinds, a paste / cut /
  auto-close `{}` / `}` overtype / pair-delete (each its own unit),
  or a focus change / mode flip. The boundary rule is a kind-and-
  flag check — not a wall-clock typing timeout — so behaviour is
  deterministic and testable. See ADR 0091.
- A fresh edit after one or more undos clears the redo stack — the
  future you didn't take is gone. Undo or redo close any open
  coalescing run, clear `_editor_pending_closers` (offsets aren't
  valid against the restored text), and scroll the cursor into
  view.

#### Focus model

Two orthogonal axes:
- `_editor_mode ∈ {"lite", "editor"}` selects the rendered view.
- `_editor_toggle_focused` is a flag: when True, only the toggle
  responds to keys; when False, the active mode's zones respond.

Within lite mode, `_editor_focus ∈ {0=kind, 1=list, 2=detail}`
selects the editing zone, and `_editor_detail_field` selects which
detail field is under input (`0 = Pattern/Key`, `1 = Body` for
text-bodied + macro; `0..3` for highlights).

**Tab cycle:**
- Lite mode: `toggle → kind → list → Pattern → Body → toggle`
  (highlights extend to `Pattern → Style → Text → Background`).
- Editor mode: `toggle → buffer → toggle`.

**Up-arrow fall-through (Phase 6.3):**
- `↑` from any kind button → toggle (kind row sits below toggle).
- `↑` on top row of the entry list → kind-buttons row.
- `↑` from detail.Pattern → kind-buttons row.
- `↑` on the topmost line of the editor buffer → toggle (no kind
  row in editor mode).

**Down-arrow:**
- From toggle, lite mode → kind-buttons row.
- From any kind button → entry list (cursor at row 0).
- From toggle, editor mode → buffer (cursor at offset 0).

**Left / Right within the kind-buttons row** (Phase 6.3): step to
the previous / next button. No wrap — `←` on the first button
(ACTIONS) and `→` on the last (SUBSTITUTES) are no-ops.

**Stepwise Left-arrow fall-through** (Phase 6.2). When the cursor
is at position 0 of a detail-panel zone, `←` falls through one
zone to the left:
- Text-bodied Pattern at pos 0 → entry list
- Body at line 0 col 0 → Pattern (cursor at end of Pattern)
- Macro Key cell → entry list
- Macro Body at line 0 col 0 → Key cell
- Highlight Pattern at pos 0 → entry list
- Highlight Style.Undersc. (leftmost toggle after Phase 6.3
  dropped Bold) → Pattern (cursor at end)
- Highlight Text col 0 → Style.Reverse (rightmost toggle)
- Highlight BG col 0 → Text col 1 (same row)

`←` at non-zero positions moves within the zone (or extends the
selection when Shift is held). Fall-through clears any active text
selection.

**Existing per-zone arrow behaviour preserved otherwise** (palette
zones, macro key cell, body cursor inside Commands, etc. — see
phase-5 doc).

**Dynamic footer** (Phase 6.2 — arrow + Enter tokens removed since
they're intuitive from layout; kept tokens are the non-obvious
ones). The Tab token is uniformly `Tab Cycle` everywhere — it
describes what the key does, not the size of the focus chain:
- Toggle: `Tab Cycle  ·  ESC Save & back`
- Editor mode: `Tab Cycle  ·  ESC Save & back`
- Lite / kind: `Tab Cycle  ·  ESC Save & back`
- Lite / list: `n New  ·  Del Delete  ·  Tab Cycle  ·  ESC Save & back`
- Lite / detail: `Tab Cycle  ·  ESC Save & back`

The footer hint sits on the final terminal row in both modes,
anchored via a flex_spacer between the body Window and the footer
Window (matching the `profile` / `history` footer-anchoring
contract). See *Layout* for the chrome budget.

#### Mode flip semantics

- **Lite → editor.** `serialize_profile(_editor_data)` →
  `_editor_buffer_text`. Cursor lands at offset 0; scroll resets to
  0.
- **Editor → lite.** `parse_profile(_editor_buffer_text, path)` →
  replaces `_editor_data.items[:]` in place (the same `Profile`
  object) and re-attaches the parsed path. The entry-list cursor
  resets to 0; `_editor_refresh_buffers()` re-anchors the detail
  panel's in-buffer cursors and palette zones. The parser is
  lenient: unrecognised lines fall through to `Passthrough` and
  round-trip byte-exact. No parse-error flash — the worst case is
  a previously-known entry becoming a `Passthrough` until
  reformatted.

Both modes are live-bound to the same in-memory `Profile`. Edits
in lite-mode fields commit on each keystroke via
`Entry.__setattr__`. Edits in the editor buffer commit on flip-out
via the parse step. ESC in either mode runs the parse-if-editor
path then calls `save_profile`.

#### Save semantics

ESC writes the profile back to its `.tin` file via
`profile_io.save_profile` (temp file + atomic rename). Unmodified
entries emit their original source line verbatim; edited entries
(via lite or editor mode) serialise canonically as
`#<kind> {pattern} {body}[ {priority}]`. The priority slot is
preserved by the serializer even though it's not surfaced in the
lite-mode UI, so loading a profile with `#alias {test} {body} {7}`
and editing `body` emits `#alias {test} {new body} {7}` with the
priority intact. Entries whose `pattern.strip()` is empty are
dropped before write (abandoned create attempts). `Passthrough`
lines (`#var`, `#event`, blank lines, malformed entries) survive
untouched; `#nop` lines are dropped (ADR 0042). After a successful
save the `profile` frame flashes `Saved <name>.tin.` in `C_ACCENT`;
on `OSError` the frame still pops and flashes
`Save failed: <reason>` in `C_HINT`.

#### Round-trip identity

Phase 6.2 changed the canonical form: load + save with no edits
produces an output that is sorted into command groups
(alphabetical by command name, alphabetical within each group by
first brace-arg, single blank line between groups) — see ADR 0084.
Individual entries' `_raw` round-trips byte-exact **only for
entries already in flat form**. Phase 6.3 added a per-entry
post-parse normalisation for `action` / `alias` / `macro` bodies
that tt++ has rewritten on `#write` (logout) into its indented
multi-line form: leading and trailing whitespace-only lines are
stripped, and every line that starts with at least four spaces
has the leading four spaces removed. Bodies that change clear
their `_raw`, so they regenerate canonically on save
(`#<kind> {pattern} {body}` — the body keeps its `;\n` newlines
but is no longer indented). Bodies already in flat form compare
equal and keep their `_raw`. Highlights and substitutes are not
normalised — tt++ doesn't reformat them and their bodies may
contain intentional whitespace. The cycle is stable: tt++
re-expands a saved flat body to its multi-line form on the next
`#write`; the editor re-normalises on the next load.

The *order* also changes from source order to canonical order on
parse. `#nop` lines are dropped (ADR 0042). Blank lines, free
text, and malformed Passthrough lines are dropped during the sort
pass. Multi-line Passthrough forms (a `#class {x} { ... \n ... }`
block split across physical lines) lose their continuation lines
on sort — documented limitation. Covered by
`bridge/launcher/tests/test_profile_io.py` and
`bridge/launcher/tests/test_profile_editor.py`.

#### `profile_io` string helpers

The pure string-mode helpers underlying load/save expose the same
invariants without disk I/O — useful for the editor's mode flip:
- `serialize_profile(profile) -> str` — renders the full file
  content as a string.
- `parse_profile(src, path) -> Profile` — parses a source string,
  attaching `path` to the result.
- `load_profile(path)` / `save_profile(profile)` — thin disk
  wrappers around the above.

#### Mouse-drag selection is not wired

The editor's mouse event model is per-cell click handlers that
fire on `MOUSE_DOWN` plus `MOUSE_MOVE` for hover and best-effort
auto-scroll target tracking. Drag-to-select would require
distinguishing motion-with-button-held from hover-without-button,
plus a coordinator that anchors at `MOUSE_DOWN` and extends
across the run of `MOUSE_MOVE` events before `MOUSE_UP` — and
prompt_toolkit's terminal mouse pipeline doesn't reliably surface
the button state on motion reports in every host. The wired
alternatives cover the common cases: double-click selects the
word / whitespace / punctuation run under the pointer,
triple-click selects the logical line (newline excluded), and
`Shift+arrow` / `Shift+Home` / `Shift+End` extend the keyboard
selection — all three work in editor mode and in the lite-mode
Pattern / Body fields.

#### Clipboard

All three editor text contexts — Editor-mode buffer, Lite Pattern,
Lite Body — share a single in-app register (`_editor_clipboard`) for
copy/cut/paste, and use the same key triplet:

- `c-c` — copy selection; with no selection, copy the current logical
  line including its trailing newline. Cursor and buffer unchanged.
- `c-x` — cut selection; with no selection, cut the current line.
  Removes one adjacent newline so no blank line is left behind.
- `c-v` — insert the in-app register at the cursor, replacing any
  active selection. Pattern is a single-line field, so a paste that
  contains newlines flattens them to spaces; Body and Editor mode
  preserve them.

Copy and cut additionally emit an OSC 52 sequence so the text lands
on the system clipboard on terminals that implement it (most modern
ones do — the sequence is silently discarded otherwise). Pasting
from another application uses the **terminal's own paste shortcut**
(`Cmd-V` / `Ctrl-Shift-V` / right-click, depending on the terminal),
which arrives as bracketed paste — the launcher normalises CRLF /
lone CR to `\n`, then routes the text through the same insert paths
as `c-v`. `c-v` itself deliberately does NOT read from the system
clipboard; the asymmetry, and the trade-offs, are
documented in `docs/decisions/0090-profile-editor-clipboard-osc52.md`.

The palette zones in the Highlights tab and the macro Key cell are
selection-only — they ignore `c-c`/`c-x`/`c-v` and bracketed paste.
The global `c-c` quit binding is suppressed inside the
`profile_editor` frame so the same key can copy text; ESC remains
the documented way to exit the editor.

**Confirmation flash.** A successful `c-c` / `c-x` writes a transient
"Copied" / "Cut" message into the centred footer slot in `C_ACCENT`,
auto-clearing after ~1.5 s (`_editor_flash` / `_editor_clear_flash`,
mirroring the `profile`-frame feedback pattern). `c-v` and bracketed
paste never flash. The text is terminal-independent — on terminals
without OSC 52 the bytes reached only the in-app register, so a
clipboard-specific claim would mislead.

While the flash is live, the editor-mode brace-imbalance indicator
yields the row (no overlap); both the static hint tokens and the
indicator return on the next render after the timer fires. A
`c-c` / `c-x` in a no-op context (kind buttons, list, palette zone,
macro Key cell) does not flash — the lite-mode dispatcher returns
before the flash call runs. The flash is also cleared on
`_enter_profile_editor`, on the lite ↔ editor flip, and on
`_profile_editor_save_and_close`, so it never outlives the frame.

#### Delete: no confirmation

`Del` on a selected list row removes the cursor Entry from
`Profile.items` immediately via `list.remove(entry)`, clamps
`_editor_list_cursor` to the new active-kind length, and scrolls the
cursor back into view. The next save reflects the deletion. There is
no confirmation step — the friction-reduction trade-off is accepted
(`Del` is significantly harder to press accidentally than a letter
key, and the previous `d` letter binding was retired for the same
reason).

#### `profile_editor_macro_keybind` overlay

Centred modal pushed from the macro detail's Key cell (Enter or
mouse click) or auto-pushed by `+ New entry` on the Macros tab.
Each entry in `macro_keys.KNOWN_KEYS` is registered as an explicit
binding on this overlay; a `<any>` wildcard catches everything else.
Both paths route through `bridge/launcher/macro_keys.py`:

- **Match.** The explicit binding for the pressed key (or
  `match_pressed(event)` from the wildcard fallback) returns a
  `MacroKey`. The overlay writes `match.tin_escape` into
  `entry.pattern`, re-sorts the display view, re-anchors the
  cursor, pops, and flashes `Bound to <display name>.` in
  `C_ACCENT` for ~2 s below the editor footer. Focus returns to
  Commands when the overlay was auto-opened (so the user keeps
  typing); otherwise to the Key cell.
- **No match.** `rejection_reason(event)` returns the single
  message `"That key isn't available."` — the forwarded set is
  large and terminal-dependent, so any short hint would be
  misleading. The overlay stays open with that message in
  `C_DANGER`; the next keypress replaces or accepts.
- **ESC.** Pops without changing the entry. When the overlay
  was auto-pushed by `+ New entry`, the just-created Entry is
  removed from `_editor_data.items` so the list stays visually
  consistent. (`save_profile` would drop the empty-pattern
  entry on ESC out of the editor anyway, but cleaning up now
  prevents an out-of-place blank row in the list.) The ESC
  binding is registered *without* `eager=True` so prompt_toolkit
  waits briefly for a follower key — without that disambiguation,
  Alt+letter (delivered as `escape`, then letter) would fire
  Cancel before the letter arrived.

Layout (centred):

```
─── Bind key ───

Press the key to bind…

   <error line — only when an attempt failed, in C_DANGER>

   ESC  Cancel
```

The known-keys set is the single source of truth for what
`#macro` patterns the GUI can produce. It mirrors the
forwardable-key bindings in `bridge/panes/input_pane.py` — F1–F12,
SS3 numpad sequences (`\eOp` … `\eOy`, `\eOn`, `\eOM`, `\eOj`,
`\eOk`, `\eOm`, `\eOo`), Alt+letter (excluding b/d/f/o), and the
Ctrl+letter subset (g/l/o). Bind a key here that input_pane
doesn't forward and the macro will silently never fire in-game;
the two modules are cross-referenced in docstrings and called
out in ADR 0082.

## Options sub-menu

Navigation hub pushed by activating "Options" on the main frame. Children:

- **Panes** → `options_panes` — per-pane enable/disable + colour selection.
- **Scripts** → `scripts` — opens the same Scripts frame documented in the
  feature table above. ESC returns to `options`.
- **Spotlights** → `options_spotlights` — per-kind toggles for the
  Spotlights reel (deaths, level-ups, PvP kills, achievements).
- **Text layout** → `options_coming_soon` — placeholder for future
  layout/typography options. The row's inactive label paints in
  `C_HINT` (dim grey) to signal "not ready yet"; selected / hover
  states pick up the normal `<< label >>` menu-row grammar.
- **Connection** → `options_connection` — MMapper / Direct / Custom
  selector; Custom pushes a host/port input subframe.

ESC inside `options` saves any pending edits to `bridge/runtime/startup.conf`
and pops back to `main`.

### `options_panes` frame

Single frame for the Panes submenu. Renders a **pane × colour grid**
where rows are the six right-column panes (Character / Buffs / Group /
Communication / UI / Developer) and columns are the seven palette
entries (Black / Red / Green / Blue / Grey / Orange / Purple). Below
the grid sit a blank row, a `[X] Display pane headers` toggle, a blank
row, and `Back`. The frame uses the `menu_chrome.title_block` /
`footer_block` helpers (`blank_above=2`) and the shared
`panes_grid` module — see ADR 0086 and the
[Panes-colour-grid model](#panes-colour-grid-model) section below.

Each grid cell renders as `[X]███` or `[ ]███` — a 3-cell checkbox and
a 3-cell colour swatch. Per row, **0 or 1 cells are checked**: zero
checked means the pane is off (and the row paints dim end-to-end); one
checked means the pane is on with that colour.

Enter / click semantics (per `panes_grid.apply_cell_toggle`):

- On a grid cell — if the cell is the pane's currently-checked colour,
  uncheck it (the pane goes off); otherwise check it (the pane goes on
  with that colour, clearing any other checked cell in the row).
- On the headers toggle row — flips `show_pane_dividers` in `_conf`.
  The cockpit's tmux border-status setup reads the key at next start;
  nothing live happens at the launcher.
- On `Back` — saves and pops (same as ESC).

The headers toggle and `Back` use the **`<< label >>` menu-row
grammar** (`menu_chrome.menu_row`, gold *arrows* on the cursor row),
left-aligned in their own centred block below the grid; grid cells
use the **swatch-cell grammar** (gold *foreground* on the cursor
cell's `[ ]` / `[X]` glyphs).

Persistence is **deferred**: cell clicks mutate `_conf`; `_save_conf`
fires on Back / ESC. This is the persistence asymmetry vs. the popup —
the popup's equivalent frame writes immediately and live-applies via
`toggle_pane.sh` and `tmux select-pane -P bg=…`. Both surfaces ultimately
write the same `startup.conf` keys (`show_<key>`, `pane_color_<key>`,
`show_pane_dividers`).

**Cursor / navigation.** Eight navigable rows: the six grid rows, the
headers-toggle row (`_PANES_HEADERS_ROW`), and the `Back` row
(`_PANES_BACK_ROW`). `↑` / `↓` move between them (clamped, no wrap).
`←` / `→` move the column **only while the cursor is on a grid row**,
clamped 0..6; the column persists across grid rows and across visits
to the headers / Back rows. Mouse hover on any selectable target moves
the cursor to that target — there is no separate hover style. Footer:
`↑↓←→ Move · Enter Toggle · ESC Back`.

### Panes colour grid model

Source: `bridge/launcher/panes_grid.py` — a pure (no prompt_toolkit
import, no global state) module shared between the launcher and the
popup. Three entries:

- `panes_grid_fragments(rows, term_cols, cursor, cell_handler=None)` —
  fragments for the colour-name header row plus one row per pane.
  `rows` is a list of `(label, enabled, colour_index)`; `cursor` is
  `(row_idx, col_idx)` or `None` when the cursor sits outside the grid.
  Cell-colour precedence: cursor cell `[ ]` / `[X]` →  `C_CURSOR_CELL`
  (gold fg); else on an enabled row, checked `[X]` → `C_ACTIVE`,
  unchecked `[ ]` → `C_HINT`; on a disabled row, label / brackets /
  swatch all paint `C_PANE_OFF`, except the cursor cell's brackets
  which stay gold. The colour-name header row paints in `C_HINT`.
  When `cell_handler` is provided the cell fragments are emitted as
  3-tuples carrying the returned mouse handler; otherwise as 2-tuples.
- `apply_cell_toggle(enabled, colour_index, col)` — pure state
  transition. Returns `(False, colour_index)` when the clicked column
  matches the active colour of an on pane; otherwise `(True, col)`.
- `grid_width()` — total horizontal width of the grid (used for
  centring callers).

The launcher and the popup both read / write the existing
`startup.conf` keys — `show_<key>` and `pane_color_<key>`. The grid
model maps `show_<key>=1` with an empty or unknown `pane_color_<key>`
to the Black column.

Tests live in `bridge/launcher/tests/test_panes_grid.py` and run
without prompt_toolkit installed.

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

`PANE_COLOR_ORDER` in `palette.py` defines the grid's column order.

The `C_PANE_OFF` palette token (also in `palette.py`) is the dim grey
painted across every cell of a disabled grid row — label, brackets,
and swatch all share it so the row reads as unmistakably off. The
cursor cell's brackets escape the dim treatment so a disabled row
stays navigable.

### `options_connection` frame

Three radios — MMapper (`localhost:4242`), Direct (`mume.org:4242`,
TLS), Custom — followed by `Back`. The active radio reflects the
current `connection_mode` in `startup.conf`. Selecting MMapper or
Direct writes `connection_mode` and pops on Back/ESC. Selecting Custom
writes `connection_mode=custom` and pushes `options_connection_custom`.

Each row's full label (`(•) MMapper  (localhost:4242)`, etc.) is
rendered through `menu_chrome.menu_row` — the leading `(•)` / `( )`
glyph carries the persistent on / active state, and the cursor row's
gold `<<` / `>>` arrows + `C_ACTIVE` label carry the transient
selection. All four rows are left-aligned on a shared column inside
a centred block so the radio glyphs stack vertically.

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
`[X]` / `[ ]` rows followed by a blank row and `Back`, rendered through
`menu_chrome.menu_row` so the leading `[X]` / `[ ]` glyph carries the
persistent on / active state and the cursor row's gold `<<` / `>>`
arrows carry the transient selection — identical grammar to the
`Display pane headers` toggle in `options_panes`. All five rows share
one centred block, left-aligned on the widest label so the `[X]` /
`[ ]` glyphs and `Back` stack vertically. Enter / Space / click flips
the row; ESC or `Back` saves and pops back to `options`.

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
"History", which sits below `Profile` and `Options` and above
`Spotlights` (the dynamic Enter/Resume/Mirror row, and the optional
"Update" row when present, remain at the top of the menu). Data is read by
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

Top-to-bottom (P4.1 layout — see ADR 0088 and its P4.1 amendment):

1. Title row — routed through `menu_chrome.title_block(...,
   blank_above=2)` so the title paints `C_SECTION`.
2. **Filter pill row.** Horizontal row of pills — `All` first, then
   one pill per character returned by `list_characters_with_runs()`
   (alphabetical). Characters without sealed JSONLs are excluded.
   Visual grammar matches the table cursor row and the button columns:
   cursor + filter row focused → `C_BUTTON_ACTIVE_FOCUSED` (gold);
   cursor + focus elsewhere → `C_BUTTON_ACTIVE_UNFOCUSED` (grey,
   ≡ `C_SELECTED`); hover → `C_HOVER`; otherwise `C_ITEM`. Selecting a
   pill applies its filter immediately. There is no `Filter` header.
   - **Fits.** Total pill width ≤ terminal width → the row is centred
     on the terminal with no arrows.
   - **Overflows.** Total > terminal width → the row paints across the
     full terminal width with a 2-cell slot reserved at each edge. `‹`
     appears in the left slot when pills are hidden to the left, `›`
     in the right slot when pills are hidden to the right; the slot
     stays blank on the side that hides nothing, so pill positions
     never jump as the arrows appear and disappear. Edge arrows paint
     in `C_BODY`. The visible window always contains whole pills —
     never a clipped pill; trailing slack inside the window is blank.
   - **Cursor follows.** Keyboard `←` / `→` move the cursor pill and
     scroll the window by whole pills, the minimum needed to keep the
     cursor pill fully visible. Clicking `‹` / `›` pans the window one
     pill *without* moving the cursor (mouse browsing); clicking a
     visible pill selects it as today.
   - The windowing computation is the pure
     `bridge/launcher/history_filter.py` module (`compute_window` /
     `scroll_to_cursor` / `pan`); unit-tested by
     `tests/test_history_filter.py`.
3. Blank row.
4. **Centred package:
   `[ button column | gap | runs table | scrollbar ]`.** Horizontally
   centred as one unit; the package drives the left/right positions
   of the table area and recentres on terminal resize.
   - **Button column (left).** Vertical column of 7
     `button_fragment` cells (no inter-button gap, no border, no
     header): RUN LOG, STATS, RATE, SAVE, EXPORT, DELETE, BACK.
     Labels are uppercase so the control surface reads as commands.
     Column width = longest button label + 2 cells of padding
     (longest label: `RUN LOG`, 7 chars). The first button
     top-aligns with the runs-table header row — there is no
     `Options` header. State mapping per ADR 0085's button-cell
     grammar: cursor + button zone focused → `selected_focused`
     (gold bg); cursor + button zone unfocused → `selected_unfocused`
     (grey bg); hover on a non-cursor enabled button → `hover`
     (previews the unfocused-selected look); disabled → `disabled`
     (dim grey foreground with no background block, so disabled
     buttons read as inert space rather than dark slots); else
     `inactive`.
   - **Gap.** 2 cells between the button column and the runs table.
   - **Runs table (right).** Columns: Char · Date · Time · Dur. ·
     Expires · Rating. Click on a column header toggles sort; an
     active column shows ` ▲` / ` ▼` after its label. Default sort
     `Char asc` with `start_ts desc` as the stable secondary key.
     The column-header row paints `C_HINT` (muted grey) at all
     times, regardless of focus — the sort-indicator glyph
     carries the active-column signal; focus is signalled by the
     cursor-row background, not the header row.
5. **Feedback row** — single row directly below the package, doubling
   as the spacing row between the table and the footer. Holds the
   Save / Rate / Export / Delete transient feedback message
   (`Saved to ~/<file>` in `C_ACCENT`, `Export failed: …` in
   `C_HINT`, etc.) centred on the package width for ~3 s, blank
   otherwise.
6. Footer hint line, anchored to the final terminal row via a
   flex_spacer between the feedback row and the footer Window.

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
(ADR 0066): `_history_filter_window` (filter pill row),
`_history_table_window`, `_history_options_window` (button column).
`_history_focused: int` (0/1/2) routes navigation. Tab / Shift+Tab
cycles forward / backward; `_focus_current_frame()` re-focuses the
right window after push/pop and on focus changes within the frame.
The filter pill row sits above the table, the button column to the
table's left.

**Cursor and hover.** The cursor row in each panel adopts the same
focused / unfocused grammar as the buttons: gold background
(`C_BUTTON_ACTIVE_FOCUSED`) when its zone is focused, grey
(`C_BUTTON_ACTIVE_UNFOCUSED`) when not. Hover paints `C_HOVER` on
non-cursor selectable elements; cursor always wins over hover.
Hover clears on `MOUSE_MOVE` over any non-row fragment (title,
footer, gap, padding, scrollbar track, disabled button) via the
per-frame `_hover_at(panel, idx)` helper.

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

The button-column cursor moves through enabled buttons only (↑/↓
skips disabled). Back is always enabled, so the cursor always has a
landing spot even with an empty table.

**Keyboard.**

| Focus   | Key                | Action                                |
|---------|--------------------|---------------------------------------|
| filter  | ←/→                | move pill cursor (clamp, no wrap; window scrolls minimally) |
| filter  | Enter / Space      | re-apply cursor pill's filter         |
| filter  | ↑                  | no-op (filter is the top zone)        |
| filter  | ↓                  | focus options column at the topmost enabled button |
| table   | ↑                  | move cursor up; falls through to the filter row when on row 0 |
| table   | ↓                  | move cursor down (clamp)              |
| table   | PgUp/PgDn          | scroll 10                             |
| table   | Home/End           | jump to ends                          |
| table   | Enter / Space      | open Run log when row has a log; otherwise no-op |
| table   | ←                  | focus button column                   |
| options | ↑                  | move cursor button (skip disabled); falls through to the filter row when on the topmost enabled button |
| options | ↓                  | move cursor button (skip disabled, wraps to top) |
| options | Enter / Space      | activate selected button              |
| options | →                  | focus table                           |
| any     | Tab / Shift+Tab    | cycle focus (filter → table → options)|
| any     | ESC                | pop to main menu                      |

`←` / `→` move the pill cursor while on the filter row (clamped, no
wrap, re-filters immediately) and pan the visible window minimally
when it overflows. On the table they focus the button column (`←`
only — `→` is a no-op since nothing sits right of the table). On the
button column `→` focuses the table; `←` is a no-op.

The filter row is reached above each zone below it via the spatial
arrow path: `↑` at row 0 of the table, or `↑` on the topmost enabled
button of the options column (`RUN LOG` when enabled), focuses the
filter row. `↓` from the filter row reciprocates by focusing the
options column at the topmost enabled button.

**Filter behaviour.** Cursor equals the active filter; moving the
cursor with ←/→ or clicking a pill re-filters immediately. Filter
resets to `All` on every frame push. Filter change resets table scroll
and cursor to 0; sort state is preserved.

**Mouse.** Click activates (and switches focus to that panel).
Clicking a runs-table row with `has_log` true opens `log_view` for
that chain (same destination as Enter / Space on the row, or the
Run log button); clicking a row with no log moves the cursor only —
Stats is reachable from the button column. Clicking a visible filter
pill selects it (focus → filter, cursor → pill); clicking `‹` / `›`
on the filter row pans the visible window one pill without moving
the cursor. Wheel scrolls the table when hovered
(`_WheelScrollControl`, the shared `FormattedTextControl` subclass
that intercepts `SCROLL_UP` / `SCROLL_DOWN` and forwards them to a
per-frame callback); wheel over the filter pill row or button column
is a no-op. The table's click-to-jump scrollbar uses
`bridge/launcher/widgets/scrollbar.py`.

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
sits between `History` and `About`. Two surfaces:

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
  sub-frames, `profile_delete_confirm`,
  `profile_editor_macro_keybind`, `options`,
  `options_panes`, `options_connection`,
  `options_connection_custom`, `options_coming_soon`, `history_detail`,
  `history_rate`, `history_delete_confirm`, `update_running`,
  `update_result`, and `exit_confirm` are wrapped in
  `HSplit([window], align=VerticalAlign.CENTER)` so they stay visually
  centred at any terminal height above the minimum.
- **Package-layout frames** — `history` and `profile` use a centred
  `[ table | scrollbar | gap | Options ]` package anchored at the top
  with a feedback row and footer below; a flex spacer absorbs leftover
  rows so the package, feedback row, and footer hug together at the top
  of the frame. `profile_editor` uses the same body + flex_spacer +
  footer-Window contract (see `_build_profile_editor`) to anchor its
  footer hint to the final terminal row in both lite and editor mode.
- **Scrolling frames** — `scripts` and `about` are single-window
  frames that render `title_block` (4 rows), a viewport-sized body
  (always emits `_term_rows() - 5` lines, padding with blanks when the
  content list is shorter), and `footer_block` on the final terminal
  row. The body slices its lines list by `_scripts_scroll` /
  `_about_scroll`; scroll keybinds key off the same viewport height.
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
| `C_OK`              | Persistent "selected / active" marker (e.g. the profile-table ✓) — green, never gold. |
| `C_CURSOR_CELL`     | Focused-cursor foreground on swatch / checkbox cells in palette zones — gold, applied to the `[ ]` glyphs only; the swatch keeps its own colour. Separate token from `C_ACCENT` so the two can diverge later. |

The two states share the same underlying grammar, expressed by which
attribute carries the gold:

- Focused cursor on a *filled button* → gold *background*
  (`C_BUTTON_ACTIVE_FOCUSED`).
- Focused cursor on a *swatch / checkbox cell* → gold *foreground*
  (`C_CURSOR_CELL`), no background. Palette / swatch zones are
  gold-or-nothing — they have no unfocused carry-over.
- Selected but owning zone unfocused → grey background
  (`C_BUTTON_ACTIVE_UNFOCUSED`). Applies only to persistent
  selections (active kind, active mode, edited list row); never to
  palette / swatch cursors.
- Persistent active marker → green (`C_OK`).

The legacy near-black `C_BUTTON` / `C_BUTTON_HOVER` constants are
retained for the popup's Options widgets and retire when P5 adopts
the three-state grammar there. The launcher's Profile and History
button columns moved to the `button_fragment` grammar in P4 (ADR
0088) and no longer use those tokens.

### Shared menu chrome

`bridge/launcher/menu_chrome.py` is a small pure-function module that
both `launcher.py` and `ingame_menu.py` import for the title block,
footer anchoring, and three-state button cell. It returns
prompt_toolkit-style fragment lists / tuples but does not itself
import prompt_toolkit — the caller appends the fragments into its own
`frags` list and attaches mouse handlers if needed.

| Helper | Contract |
|--------|----------|
| `title_block(title, term_cols, blank_above)` | Fragments for `blank_above` blank rows, then `title` centred in `term_cols` styled `C_SECTION`, then one trailing blank row. `title` is passed already decorated (e.g. `"─── Panes ───"`). `blank_above = 2` for the launcher, `1` for the popup. |
| `title_block_height(blank_above)` | Returns `blank_above + 2` — the visual-row count produced by `title_block`. |
| `footer_block(footer_text, term_cols, term_rows, content_rows)` | `content_rows` is the row count above the footer (title block + body). Emits `max(0, term_rows - content_rows - 1)` blank rows then `footer_text` centred in `term_cols` styled `C_HINT`, so the footer lands on the final terminal row. When content fills or overflows the terminal the pad clamps to zero — never negative. |
| `menu_row(label, state, mouse_handler=None, inactive_style=C_ITEM)` | Fragment list for one `<< label >>` selectable menu row: a fixed 3-cell prefix (`<< ` or `   `) + the raw `label` + a fixed 3-cell suffix (` >>` or `   `). Row width is `len(label) + 6` and symmetric, so the arrows hug the label (`<< Enter MUME >>`, never `<< Enter MUME      >>`) and the label never shifts horizontally between states. `state ∈ {"inactive", "hover", "selected"}`: `selected` → arrows in `C_CURSOR_CELL` (gold), label in `C_ACTIVE`; `hover` → blank arrows, label in `C_HOVER`; `inactive` → blank arrows, label in `inactive_style` (default `C_ITEM`; `C_HINT` for the "Text layout" placeholder). Selection wins over hover. The caller is responsible for centring — see the Alignment convention below for the two cases. When `mouse_handler` is given, every fragment carries it as a 3-tuple. |
| `button_fragment(label, width, state)` | A single `(style, text)` 2-tuple. `label` is centred in `width` cells (truncated when longer). `state ∈ {"inactive", "hover", "selected_unfocused", "selected_focused", "disabled"}` maps to: `C_BUTTON_INACTIVE` / `C_BUTTON_ACTIVE_UNFOCUSED` (hover deliberately previews the unfocused-selected look) / `C_BUTTON_ACTIVE_UNFOCUSED` / `C_BUTTON_ACTIVE_FOCUSED` / `C_BUTTON_DISABLED`. Used by the Profile / History button columns and the editor's LITE kind-buttons; vertical menu lists use `menu_row` instead. |

`title_block` and `footer_block` both accept an optional `mouse_handler`
keyword: when given, every emitted fragment is a 3-tuple carrying that
handler. Menu frames pass their frame-specific clear-hover handler so
MOUSE_MOVE events above the first menu row or below the last clear the
stuck hover instead of leaving the previous row highlighted. See the
"Hover-clear invariant" note below.

Every frame in the launcher's startup-menu surface uses these helpers
for its title row, footer anchoring, and selectable-row styling —
`main`, the full Options chain (`options`, `options_panes`,
`options_connection`, `options_connection_custom`,
`options_spotlights`, `options_coming_soon`), `scripts`, `about`,
`spotlights_empty`, and the two modal dialogs (`update_result`,
`exit_confirm`). The `profile` and `history` chains keep their
bespoke widget grammars; `log_view` keeps its own `C_LOG_*` palette.
See [ADR 0085](decisions/0085-shared-menu-chrome.md).

**Title / footer placement.** Sub-menu titles render in `C_SECTION`
(darker cyan) via `title_block(..., blank_above=2)`. The main page's
ASCII banner is the launcher's logo, not a section title, and stays
in `C_TITLE`; the banner is top-anchored, the menu rows and quote sit
in the middle, and the footer is bottom-anchored via `footer_block`.
Every other swept frame's shortcut row also sits on the final terminal
row — the footer no longer shifts vertically when the user moves
between sibling frames. The two modal dialogs (`exit_confirm`,
`update_result`) deliberately opt out of footer anchoring and stay
vertically centred; they still adopt `C_SECTION` for their title /
message line.

**Button-cell grammar.** The launcher's chrome carries three distinct
cell grammars; which one applies depends on the zone, not on the
state:

- **Gold-background filled buttons** (`button_fragment`) — the Profile
  and History entry-list / button columns and the profile editor's
  LITE kind-buttons. Cursor row → gold *background*
  (`selected_focused`), unfocused-selected → grey
  (`selected_unfocused`), hover previews the unfocused-selected look,
  other rows → `inactive` near-black fill.
- **Gold-foreground swatch cells** (`panes_grid_fragments`) — the
  Panes submenu's pane × colour grid. The cursor cell's `[ ]` / `[X]`
  brackets paint in `C_CURSOR_CELL` (gold *foreground*) while the
  swatch keeps its own colour. Palette / swatch zones are
  gold-or-nothing: no unfocused carry-over.
- **Gold-arrow `<< label >>` menu rows** (`menu_row`) — every vertical
  menu list in the launcher's startup-menu surface (`main`,
  `options`, the headers-toggle / `Back` rows of `options_panes`,
  `options_connection`, `options_spotlights`, and the popup-side
  equivalents under P5). Cursor row → gold `<<` / `>>` arrows
  (`C_CURSOR_CELL`) with the label in `C_ACTIVE`; mouse hover →
  blank arrows with the label lightened to `C_HOVER`; inactive
  rows → blank arrows with the label in `C_ITEM`. Selection (the
  keyboard cursor) wins over hover. Radio / toggle rows (`(•)` /
  `( )` / `[X]` / `[ ]`) keep their leading glyph as part of the
  composed label; the glyph shape carries the persistent on /
  active state so colour stays reserved for the transient cursor
  and hover. The Options frame's "Text layout" placeholder is the
  one exception — its inactive label paints in dim `C_HINT` to
  signal "not ready yet"; selected / hover states still pick up
  the normal menu-row grammar.

**Alignment convention.** The choice is per-row, not per-frame: a
row carrying a leading `[ ]` / `( )` glyph that must stack with its
neighbours uses the **glyph-block** rule; every other plain
`<< label >>` row — `Back` included — uses the **per-row centring**
rule.

- **Per-row centring** — plain `<< label >>` rows. Each row centres
  *independently* on its own width (`len(label) + 6`), so the menu
  is ragged-centred. Because the prefix and suffix are the same
  width (3 cells) in every state, the label sits at the same column
  within the row in inactive / hover / selected — it does not shift
  when a row is selected. Applied throughout `main` and `options`,
  and to the `Back` row of `options_panes`, `options_spotlights`,
  and `options_connection`.
- **Glyph-block left-alignment** — rows whose leading `[ ]` / `( )`
  glyph must stack vertically with sibling rows. Every row in the
  block left-aligns on a shared column inside a single centred
  block. The block is `label_col_w + 6` cells wide, where
  `label_col_w` is the widest composed label across the block's
  rows; the caller prepends the same left margin to every row so
  the glyphs stack at one column. `menu_row` does not pad the label,
  so the per-row right pad is computed from each row's actual width
  to fill out to the right screen edge (and carries the clear-hover
  handler). Applied to the `(•) / ( )` mode rows of
  `options_connection`, the `[X] / [ ]` toggle rows of
  `options_spotlights`, and the `[X] / [ ]` headers-toggle row of
  `options_panes`. `Back` is not part of these blocks — it is
  always per-row centred, even when it sits below a glyph block.

In both rules, the row geometry re-centres on every render so a
resize is immediate, and the `<< >>` arrows hug the label with one
space of breathing room — no trailing pad before the closing arrow.
The `options_panes` frame is the one place where two centred zones
coexist on the same page: the colour grid sits in its own centred
block above, and the headers-toggle row sits in a (degenerate,
single-row) glyph block below, with `Back` per-row centred beneath.

**Hover-clear invariant.** In a menu frame, every emitted fragment is
either a selectable row (carries a MOUSE_MOVE handler that sets the
frame's hover index to that row's index) or chrome (carries a
clear-hover handler that resets the hover index to the no-hover
sentinel). The clear-hover handler is attached to the title-block and
footer-block fragments (via the `mouse_handler` keyword), to every
blank-separator row inside the frame, and to the per-row centring
left / right padding around each `menu_row` call. Without this
invariant, MOUSE_MOVE above the first row or below the last row never
fires a handler, the previous row's hover sticks, and the highlight
trails the actual pointer position. The `options_panes` frame is the
exception: its keyboard cursor and mouse hover share the same
`_options_panes_row` (there is no separate hover index), so its
clear-hover handler is a deliberate no-op that exists only to keep
the invariant well-formed.

**About page three-colour scheme.** Each wrapped line is classified
before printing: all-uppercase lines → `C_TITLE` (headings); lines
starting with whitespace → `C_ACCENT` (key/command lines such as
`  cp -e`); all other non-empty lines → `C_BODY` (prose). Indented lines
pass through `_wrap_text` unchanged. The page's section title row
(`─── About ─── 0.X.Y`) renders in `C_SECTION` like other sub-menu
titles; the right-aligned version string and any "Update available"
suffix keep their `C_BODY` / `C_ACCENT` colours.

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
