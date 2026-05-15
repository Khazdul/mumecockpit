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
`profile`, `profile_create_name`, `profile_create_choose`,
`profile_create_copy_picker`, `profile_delete_confirm`, `options`,
`scripts`, `about`, `history`, `history_detail`, `history_rate`,
`log_view`, `update_running`, `update_result`, and `exit_confirm`
containers, pushed and popped via `_push_frame` / `_pop_frame`. Each frame
owns its own `KeyBindings` filter (`_in_frame(name)`) so navigation, scroll,
and ESC behave per-frame. The popup architecture (ADR 0062) is the
reference; see `bridge/launcher/ingame_menu.py` for the same patterns.

| Feature | Detail |
|---------|--------|
| Session detect | `tmux has-session -t mume` + `list-clients` re-probed on every render → top item is "Enter game", "Resume game", or "Mirror game (attached elsewhere)" |
| Profile page | Lists `ttpp/profiles/*.tin`; select, create (blank / copy from existing), delete. `default` cannot be deleted. "Create blank" copies from `bridge/launcher/templates/blank_profile.tin` (single source of truth — see ADR 0042). Selected profile is written to `startup.conf` and consumed by `ttpp/core/config.tin` at tt++ startup. |
| Options page | Toggle Character pane / Buffs pane / Group pane / Comm pane / UI / Dev panes; Pane headers; connection mode. Flat minimalist list — no boxed layout-mockup, no progressive hide. Fresh-install defaults: status, buffs, group, comm, ui on; dev off; pane headers on |
| Scripts page | Reads `bridge/runtime/scripts.cache`; scrollable via UP/DOWN, PageUp/PageDown |
| About page | Reads `bridge/launcher/about.txt`; word-wrapped, cached per resize, scrollable. Current version on the right of the title; an "Update available: vX.Y.Z" line appears in `C_ACCENT` when `version.cache` contains a newer tag |
| Update flow | Selecting "Update" runs `bridge/release/update.sh` in a worker thread; result keyed off update.sh's exit codes (0/10/20/21/22/other → complete/no-update/aborted/failed). rc==0 re-execs `bridge/launcher/launcher.sh` to pick up the new code |
| Quit | Confirmation prompt; ESC cancels |
| Persistence | Options saved to `bridge/runtime/startup.conf` on Back / ESC; profile selection saved immediately on Enter |

## History sub-menu

Three frames: `history` (list + actions), `history_detail` (per-session
view), and `history_rate` (star picker). Opened from the main-menu entry
"History", inserted between "Profile" and "Options". Data is read by
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
     (no inter-button gap, no border): Stats, Rate, Run log, Save,
     Export, Delete, Back. Column width = longest button label + 2
     cells of padding (longest label: `Run log`, 7 chars).
     A centred `Options` header sits on the same line as the runs-
     table header row, painted `C_SECTION` when the widget is
     unfocused / `C_ACTIVE` when focused.
5. **Feedback rows** — two rows below the package. The first row is
   always blank (separator). The second row holds the Export action's
   transient `Saved to ~/<file>` (`C_ACCENT`) or `Export failed: …`
   (`C_HINT`) message centred on the package width for ~3 s, blank
   otherwise.
6. Footer hint line.

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

- **Stats** — always enabled (no-op when the table has no row).
- **Rate** — always enabled (no-op when the table has no row).
- **Run log** — always disabled in v1. Parked pending log-player
  wiring; the existing target lives alongside the WATCH LOG button
  on `history_detail` (`_hd_watch_log_handler` / `_kb_hd_watch_log`).
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
| table   | Enter / Space      | activate Stats for selected row       |
| options | ↑/↓                | move cursor button (skip disabled)    |
| options | Enter / Space      | activate selected button              |
| any     | Tab / Shift+Tab    | cycle focus (filter → table → options)|
| any     | ESC                | pop to main menu                      |

**Filter behaviour.** Cursor equals the active filter; moving the
cursor with ←/→ or clicking a pill re-filters immediately. Filter
resets to `All` on every frame push. Filter change resets table scroll
and cursor to 0; sort state is preserved.

**Mouse.** Click activates (and switches focus to that panel). Wheel
scrolls the table when hovered (`_HistScrollControl`, the same
`FormattedTextControl` subclass that intercepts `SCROLL_UP` /
`SCROLL_DOWN`); wheel over filter row or menu is a no-op. The table's
click-to-jump scrollbar uses `bridge/launcher/widgets/scrollbar.py`.

**Action handlers.** All operate on the row currently under the table
cursor (`_history_sessions[_history_table_cursor]`). With no row,
every action is disabled.

- **Stats** — pushes `history_detail` for the selected session. Same
  destination as pressing Enter on the table row.
- **Run log** — parked placeholder; always disabled in v1.
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

**Title.** `─── Rate the session ───` — matches the popup string so the
two surfaces read consistently.

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

Per-session statistics view. Opened by activating a row in
`history` (click or Enter). Data is aggregated on push via
`aggregate(character, summary.run_ids)` and stashed in
module-level state; the chain is already in `summary.run_ids`,
so no extra walk.

**Layout** (top to bottom): header line + WATCH LOG button ·
blank · ALLIES + ACHIEVEMENTS · blank · KILLS + PvPs · blank ·
sparklines (XP/h + TP/h) · blank · XP-linjal · blank · footer.

**Header.** `◆ Session detail — <Char> · <Date> · <Time> ·
<Dur.>` centred in `C_HEADER`. The WATCH LOG button is
right-aligned to the right edge of the table block underneath
(not the terminal edge), so the button and the tables read as
one column.

**WATCH LOG.** Appears iff `summary.has_log` is `True`; hidden
entirely otherwise. Styled `C_WATCH_LOG` idle, `C_WATCH_LOG_HOVER`
on hover. Click and the `L` keyboard shortcut both push the
`log_view` frame (Phase 3 skeleton; playback comes in later
prompts). The footer hint segment `L Watch log` appears under the
same `has_log` condition.

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
ESC Back     ↑↓ Scroll     Tab/Shift+Tab Switch table     L Watch log
```

The `L Watch log` segment is conditional on `has_log`.

### `log_view` frame

Chain log player. Opened from `history_detail` by clicking
WATCH LOG or pressing `L`. Reads the `.log` siblings of the
chain's `summary.run_ids` for the current character and renders
all events as one stacked, scrollable buffer. Phase 3, prompt 1
ships only the static load + render skeleton; playback clock,
cursor, run-boundary header, scrubber, and pause-mode highlights
arrive in later prompts.

**Load.** On push, `_enter_log_view()` builds a
`log_player.LogPlayback(summary.character, summary.run_ids)`.
For each `run_id`, the loader tries
`data/runs/<character>/<run_id>.log`; runs whose `.log` is
missing are silently skipped. `run_ids` retains the original
chain ordering so `LogPlayback.run_at(idx)` reports the correct
`(run_id, run_ordinal, total_runs)` (with `run_ordinal` measured
against the unfiltered chain — Phase 3 prompt 2 consumes this
for the run-boundary header). If every `.log` is missing the
push aborts; `has_log` should prevent that case in practice.

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
holds a `FormattedTextControl` over the full frame; the visual
lines are produced by wrapping each event's fragment list at
the terminal width and concatenating them. The wrapping cache
re-builds when the terminal width changes. The wrap is a
fragment-aware split, not `wrap_lines=True`, so style runs
remain stable across the wrap boundary.

**Keyboard.** ESC pops back to `history_detail` (filter / sort /
cursor state intact) and clears the playback so it can be
garbage-collected — chains are re-read on next push.
PgUp / PgDn scroll by a screen, Home / End jump to ends,
↑ / ↓ scroll one visual line. No Space / mouse-wheel / overlays
yet; those land in P2/P3.

**Frame focus.** Per ADR 0066, `_log_view_window` is the primary
focusable window and is dispatched by `_focus_current_frame()`
on push.

## Rendering conventions

All frames render through `prompt_toolkit` controls. Layout building blocks:

- **Frame stack** — single `DynamicContainer` whose getter routes
  `_current_frame` to one of the prebuilt container trees. Each frame's
  primary `Window` is stored at module level and focused on push so
  keyboard handlers fire reliably.
- **Centered frames** — `main`, `profile`, `options`, the profile-create
  sub-frames, `exit_confirm`, `update_running`, and `update_result` are
  wrapped in `HSplit([window], align=VerticalAlign.CENTER)` so they stay
  visually centred at any terminal height above the minimum.
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
| `C_WATCH_LOG`       | WATCH LOG button — black on accent background fill                                                  |
| `C_WATCH_LOG_HOVER` | WATCH LOG button on hover — lighter accent background variant                                       |
| `C_LOG_PLAYER_INPUT`| log_view outbound (player command) lines — muted grey with a faint light-cyan tint                  |

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
- **Handoff via `os.execvp`.** The Enter-game dispatch records a
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
