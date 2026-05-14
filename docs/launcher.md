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
`scripts`, `about`, `history`, `history_detail`, `log_view`,
`update_running`, `update_result`, and `exit_confirm`
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

Two frames: `history` (list) and `history_detail` (per-session
view). Opened from the main-menu entry "History", inserted between
"Profile" and "Options". Data is read by
`bridge/launcher/run_stats.py` — see ADR 0065 for the aggregator,
ADR 0056 for the stitching primitive.

### `history` frame

Horizontally-centred two-column body:

- **Left sidebar.** First row is the literal `Filter` header
  (focus-coloured: `C_ACTIVE` when the sidebar is focused,
  `C_SECTION` otherwise). Below the header: `All`, then one row
  per character returned by `list_characters_with_runs()`,
  alphabetical. Characters without sealed JSONLs are excluded.
  Sidebar width is recomputed on every render from
  `max(len("Filter"), len("All"), max character-name length) + 2`.
- **Right table, sortable.** Columns: Char · Date · Time · Dur. ·
  PK · XP. The header row is click-to-sort; an active column
  shows ` ▲` / ` ▼` after its label. Default sort `Char asc` with
  `start_ts desc` as the stable secondary key, so within a tied
  primary key, newest sessions appear first.

Each row is a stitched chain (one session). Stitching uses the
default `max_gap_seconds = 3600` from `list_sessions()`. The live
`current.jsonl` is never listed; only sealed JSONLs.

XP gain is rendered in `_S_GAINED` for positive, `_S_LOSS` for
negative, `_S_LABEL` for zero or sub-1k magnitudes.

**Focus.** One focusable Window per the focus-on-push contract
(ADR 0066). `_history_focused: int` routes navigation
(0 = sidebar, 1 = table). Tab cycles. Each panel header paints
`C_ACTIVE` when focused, `C_SECTION` otherwise.

**Cursor and hover.** The cursor row in each panel paints
`C_SELECTED` (black on light grey) in all focus states. Hover
paints `C_HOVER` on non-cursor rows; hover never overrides
`C_SELECTED`. Hover clears on `MOUSE_MOVE` over any non-row
fragment (title, footer, gap, padding, scrollbar track) via a
per-frame `_hover_at(panel, idx)` helper.

**Keyboard.** Tab / Shift+Tab cycles focus; ↑ / ↓ moves cursor
(sidebar wraps; table clamps); PgUp / PgDn scrolls by 10;
Home / End jumps to ends; Enter activates (sidebar: apply filter;
table: push `history_detail`); ESC pops to main.

**Filter behaviour.** Selecting a sidebar row is immediate
(cursor equals selection). Filter resets to `All` on every frame
push. Filter change resets table scroll and cursor to 0; sort
state is preserved.

**Mouse.** Click activates; wheel scrolls the panel under the
cursor (`FormattedTextControl` subclass overriding `mouse_handler`,
same pattern as the popup's `_ScrollControl`); two click-to-jump
scrollbars use `bridge/launcher/widgets/scrollbar.py`.

**Empty state.** No characters with archived runs → table area
renders `"No runs recorded yet."` centred; sidebar shows only
`All`.

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
