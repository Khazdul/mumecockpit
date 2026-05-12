# In-Game Popup Menu

Implementation details for `bridge/launcher/ingame_menu.py` — the ESC-triggered
overlay that appears during play. Touch this file when changing popup
submenus, the status header, `cp -s` internals, or toggle-pane persistence
behaviour.

## Overview

ESC from any pane opens a tmux `display-popup` overlay via a tmux root
keybinding in `tmux_start.sh` — this works regardless of pane focus.
The popup body is `bridge/launcher/ingame_menu.py`, a `prompt_toolkit`
full-screen `Application`. `bridge/launcher/ingame_menu.sh` is a thin
wrapper that `exec`s the Python entry; both the tmux root binding and
the Lua auto-open path in `lua/brain/connection.lua` invoke the wrapper.

The UI is a frame stack: a single `DynamicContainer` swaps between
`main`, `options`, `scripts`, `statistics`, and `exit_confirm` containers,
pushed and popped via `_push_frame` / `_pop_frame`. Each frame owns its
own `KeyBindings` filter so navigation, scroll, and ESC behave per-frame.

The top menu items are context-aware, rebuilt from `bridge/runtime/connection.state`
on every render:

- **Connected:** Continue (dismisses popup) and Reconnect (fires `reconnect`
  alias then dismisses). Continue is pre-highlighted. Reconnect is exposed
  even when connected so the player has a UX path for silent disconnects
  (half-open TCP), where `connection.state` still exists but the link is
  dead.
- **Disconnected:** Reconnect only (no Continue). Pre-highlighted so the
  player can hit Enter immediately.

Selecting Reconnect from either state routes through the same `reconnect`
alias in `ttpp/core/system.tin`, which sets the user-reconnect sentinel
before the disconnect step — see "Auto-open on disconnect" below.

## Input

- **ESC** — on the main frame, dismisses the popup. On any submenu
  (`options`, `scripts`, `exit_confirm`), pops one frame back toward
  `main`. ESC bindings use `eager=True` to bypass prompt_toolkit's
  key-disambiguation timeout; `app.ttimeoutlen` / `app.timeoutlen` are
  also lowered to 50 ms so bare ESC feels instant.
- **Arrow keys** — navigate within the current frame's selectable rows
  (wrap-around). PageUp/PageDown in the Scripts frame scrolls by ten
  rows.
- **Enter / Space** — activates the highlighted row. In `exit_confirm`,
  Y confirms; any other key cancels back to main.
- **Mouse click** — clicks on a row both select and activate it in a
  single click. Implemented as per-fragment `mouse_handler` callbacks
  on `MouseEventType.MOUSE_DOWN`.
- **Mouse wheel** — not used inside the popup. See Scope trims.

## Status header

The status header at the top of the popup shows Profile · Mode · Link.
Backed by `bridge/runtime/connection.state` (connection status) and
`bridge/runtime/ping.cache` (link quality). Example:

    Profile: default  ·  MMapper  ·  Link: 38ms (stable)

State is re-probed from the files on every render — never cached.

## Options submenu

Seven toggles (Character pane / Buffs pane / Group pane / Comm pane / UI pane /
Dev pane / Pane dividers) + Back. Source of truth is `_PANE_TOGGLES` in
`ingame_menu.py`. State is re-probed from tmux on every render — never
cached. Toggling calls `toggle_pane.sh --persist` directly; toggles do
**not** route through tt++ so no `cp -X` lines appear in the game pane.

Connection mode (MMapper / Direct) and profile switch are deliberately
**not** present in the popup Options — they require a restart and are
launcher-only.

The input-pane menu bar (CHR / BUF / GRP / COM / UI buttons in the bottom row)
is a sibling surface for the same five pane toggles. Both surfaces write
`startup.conf` via `toggle_pane.sh --persist`; each reflects changes made by
the other within ≤ 250 ms.

`cp -u`, `cp -d`, `cp -m`, `cp -c`, `cp -b`, `cp -g`, and `cp -h` are thin wrappers
around `bridge/layout/toggle_pane.sh`, each passing `--persist`. All toggle paths —
popup, launcher Options, input-pane menu buttons, and `cp -X` aliases — are
equivalent and write to `startup.conf`.

## Scripts submenu

Ports the launcher's Scripts page into the popup. Reads `bridge/runtime/scripts.cache`
on each render — always reflects the cache as written at the most recent
brain startup. Scroll is keyboard-only: UP/DOWN moves one row, PageUp/PageDown
moves ten. **Mouse wheel does not scroll** the Scripts list — see Scope trims
for the cause. A scroll hint appears in the footer only when content exceeds
the visible rows. Rendering matches the launcher (A:/S:/H:/B:/M: tags,
60-col block centred); the parser is reimplemented in Python rather than
extracted into a shared helper, to keep the launcher's bash renderer stable.
Not covered: live script state (IDLE/RUNNING/FIRING) and a stop-all-scripts
button — both parked.

## Statistics frame

A read-only view of the current run, opened from a "Statistics" row on the
main frame. The row sits between **Save profile** and **Options** and is
gated on two conditions, re-checked on every render of `_main_items()`:

1. `bridge/runtime/status.state` exists, parses as JSON, and contains a
   `character` field.
2. `data/runs/<character>/current.jsonl` exists.

If either disappears mid-session the row vanishes from the main frame.

Selecting the row reads the cached aggregator output via
`run_stats.load_current_run_stats(character)` once, stores it in
module-level globals, and pushes the `statistics` frame. The frame
renders a single `FormattedTextControl`. Header, XP-linjalen, and
sparklines emit plain styled fragments; the KILLS / PvPs / ALLIES /
ACHIEVEMENTS tables emit per-cell fragments with mouse handlers (sort,
focus, scrollbar click) using the shared `widgets/scrollbar.py` widget.

**Section order** (top to bottom): header line · ALLIES + ACHIEVEMENTS
row · KILLS + PvPs row · sparklines (XP/h + TP/h) · XP-linjalen ·
footer.

Four tables, each with its own `Scrollbar` instance: KILLS (auto-fit,
2 minimum), PvPs (same auto-fit count), ALLIES (3 fixed),
ACHIEVEMENTS (3 fixed). KILLS/PvPs render a merged title row (section
name + sort-trigger column labels in their data-column positions), a
divider rule, a window of data rows, and a sticky Total row.
ALLIES/ACHIEVEMENTS pad with blank rows when data is shorter than 3
entries. The per-row scrollbar cell sits in the rightmost column of
each table. PvPs / ALLIES / ACHIEVEMENTS data rows carry a semantic
glyph prefix (`⚔` red, `♦` cyan, `★` gold) absorbed into the existing
left padding of the name/message column: the visible name shifts right
by 2 cells, but the N / XP columns and the right edges of all tables
stay at their original positions. Title rows and the PvPs Total row
have no glyph.

**KILLS/PvPs auto-fit.** `_compute_kills_pvps_visible()` reads the
popup height at render time and subtracts `_STATS_FIXED_LINES` (the
counted overhead of header, dividers, titles, sparklines, XP-linjalen,
and footer). Both KILLS and PvPs render the same `visible` row count,
and `Scrollbar.update(total, visible, height=visible)` is called on
each so the thumb geometry matches. Errs toward fewer rows so the
footer stays pinned to the bottom of the popup.

**Sort.** KILLS and PvPs have a `(column, direction)` sort state.
Defaults at frame push: KILLS `("XP tot", "desc")`, PvPs `("XP",
"desc")`. Clicking any title-row cell sets focus and updates the sort:
the section name (KILLS / PvPs) sorts by `Mob` / `Player`, the column
labels (N / XP/N / XP tot, or N / XP) sort by that column. The clicked
column toggles direction if it's already active, otherwise switches
with the column-type default (text asc, numeric desc). The active
column shows ` ▲` (asc) or ` ▼` (desc) immediately after its label —
KILLS / PvPs themselves carry the indicator when sorting by name.
Switching column resets that table's scroll offset to 0. ALLIES and
ACHIEVEMENTS are fixed (alphabetical / chronological) and have no
sort UI.

**Focus.** A module-level `_stats_focused` integer (0..3) tracks which
table receives keyboard scroll. Tab / Shift+Tab cycle. Mouse click
anywhere in a table (title, row, scrollbar) sets focus to that table.
The focused table's title row paints en bloc in `C_ACTIVE` (bold
white) instead of `C_SECTION` (cyan) — every fragment in the row
(section name, column headers, sort indicators) switches together.

**Palette.** The Statistics frame uses `C_HEADER` (gold) only for the
`◆ RUN STATISTICS …` banner; all six section titles (KILLS, PvPs,
ALLIES, ACHIEVEMENTS, XP/h, TP/h) use `C_SECTION` — an alias to the
module-level `C_TITLE` cyan that the popup banner also uses. The
focused KILLS / PvPs / ALLIES / ACHIEVEMENTS title row paints en bloc
in `C_ACTIVE` (bold white). Divider rules under section titles and
sparkline frame strokes (`──┬──` under XP/h / TP/h, axis `│`, bottom
`└──`) render in `C_DIVIDER`, a muted gray aliased to `C_HINT`.
KILLS / PvPs data rows render in `_S_LABEL` (medium gray) so the
`_S_TOTAL` (bold white) sticky Total row visually anchors the
aggregate; ALLIES / ACHIEVEMENTS data rows stay in `_S_VALUE`. The
data-cell palette (`_S_VALUE`, `_S_LABEL`, `_S_GAINED`, `_S_TP_BAR`,
`_S_LEVEL`, `_S_TRACK`, `_S_THUMB`, `_S_TOTAL`, `_S_ARROW`, `_S_HINT`,
`_S_PVP`, `_S_ALLY`, `_S_STAR`) is private to the frame so main /
options / scripts palettes are unaffected.

**Sparklines.** XP/h and TP/h each fill their column above (KILLS and
PvPs widths respectively). A `──┬──` divider rule sits directly below
the title, with the `┬` glyph placed at the column where the chart's
`│` axis and the bottom rule's `└` sit. Inside each chart the layout
is `<y-label>` (right-aligned, 5 cells) · space · `│` · bucket
columns, then a `└────` bottom rule and a `00:00 … MM:SS` x-axis.

**XP-linjalen.** Four rows. Row 1 is the bracketed gain label
`▌◄▬▬ N XP ▬▬►▐` with the two half-block glyphs (`▌` / `▐`) anchored
to the green segment's start / end columns — the same glyphs used for
the level boundary markers in row 3. The number and the ` XP ` label
both render in `_S_GAINED` (green); the brackets, arrowheads, and `▬`
filler render in `_S_ARROW`. When the green segment is too narrow to
fit the arrows, the label falls back to a plain `N XP` centred on the
green segment. Row 2 is the bar
itself (`_S_TRACK` for unfilled, `_S_GAINED` for the gained segment).
Row 3 is the level markers: `▌<level>` per boundary (except the last)
and `<level>▐` on the final boundary. The half-block glyphs `▌` / `▐`
render in `_S_TRACK` (same dark gray as the untraversed bar segment),
sitting on the boundary column; the level digits beside them render
in `_S_LEVEL` and flow off the glyph. Row 4 is a trailing blank line.

**Live tick.** When the frame is pushed an `asyncio` task starts; it
sleeps 1 s, re-invokes `load_current_run_stats(character)`, updates
the scrollbars, and invalidates the app. The task exits when the
statistics frame is no longer on top of the stack. ESC cancels it
explicitly. JSONL re-read is microsecond-range on local disk, so 1 Hz
keeps the duration counter and live data ticking visibly without
straining I/O.

**Run-end-mid-view.** If a tick refresh sees `is_active` flip from True
to False, the run ended while the user was viewing. The cached data
stays on screen, the tick stops, and the header gets ` · Run ended`
appended in `_S_HINT` dim style. R remains live: it leaves the cached
data in place unless the load returns a new active run (e.g. the
player reconnected and a new run started), in which case it adopts
that and restarts the tick.

Key bindings on the frame:

- **ESC** (eager) — stop the tick, pop back to the main frame.
- **↑ / ↓** — scroll the focused table by one row.
- **PageUp / PageDown** — scroll the focused table by `visible_items` rows.
- **Tab / Shift+Tab** — cycle focus across the four tables.
- **R / r** — immediate refresh. Re-invokes the aggregator and re-reads
  `status.state` (or, after run-end, only adopts a freshly active run).

Footer: `ESC Back     ↑↓ Scroll     R Refresh`.

**Parked.** Export of the current run to a file (the placeholder `E`
keybinding was removed when the feature was cancelled); drag-to-scroll
on the scrollbar track (click-to-jump and keyboard scroll are the
supported paths).

The aggregation library backing this frame lives at
`bridge/launcher/run_stats.py` and is shared with the future launcher
run-browser. See [ADR 0065](decisions/0065-run-stats-python-aggregator.md)
for the rationale.

## Save profile (`cp -s`)

The "Save profile" row is always visible — save works even after link loss,
since tt++ keeps the disconnected session alive. Selecting it triggers
`cp -s` via `tmux send-keys`; an inline "Saved ✓" flashes in `C_ACCENT`
for ~1 s (a `loop.call_later` re-invalidates the app at the end of the
flash window).

`cp -s` runs `#class {$_profile} {write} {ttpp/profiles/$_profile.tin}`
inside the profile's tt++ session via a `#gts { #$_profile { ... } }`
wrapper. Uses `$_profile` (stable, set once at tt++ startup from
`startup.conf`) rather than `$game_session` (cleared on disconnect) so
save works after link loss as well as during a live connection. Success
and error messages are routed to the UI pane via `#lua {system_ui(...)}`
and `#lua {ui_err(...)}` respectively, not `#showme` to the game pane.

## Auto-open on disconnect

The popup opens automatically whenever `mark_mume_disconnected()` transitions
the state from connected to disconnected (i.e. removes `bridge/runtime/connection.state`).
All disconnect signals route through this single function:

- `Core.Goodbye` GMCP (graceful quit, both modes)
- `"Status: MUME closed the connection."` tt++ action (MMapper abrupt drop)
- `SESSION DISCONNECTED` → `clear_game_session()` → `mark_mume_disconnected()`
  (direct-mode abrupt drop and MMapper-process death)

**Dedup:** The transition guard in `mark_mume_disconnected()` returns early
when `connection.state` is already absent, so a second signal for the same
disconnect event never reaches the popup trigger.

**User-reconnect suppression:** The `reconnect` alias deliberately produces
a transient disconnect signal (MMapper `_disconnect` or direct-mode `#zap`)
before issuing the follow-up connect. To prevent that transient from
opening a spurious popup mid-reconnect, the alias writes
`bridge/runtime/.user_reconnecting` before the disconnect step.
`mark_mume_disconnected()` checks for this sentinel and, if present,
removes it and skips the popup auto-open (single-shot eat). The alias
also clears the sentinel from the post-`#delay` body as belt-and-braces.
A second, genuine disconnect after the sentinel has been eaten opens the
popup normally. See [docs/session-lifecycle.md](session-lifecycle.md) and
ADR 0058 for full semantics.

**Double-open guard:** `bridge/launcher/ingame_menu.py` writes `bridge/runtime/.popup_open`
on start and removes it on exit (via `atexit` plus SIGTERM/SIGHUP/SIGINT
signal handlers). The trigger checks for this sentinel before calling
`tmux display-popup` and skips if present, so a popup already on screen
is never disturbed.

**Bootstrap protection:** On fresh start `connection.state` is absent, so
`mark_mume_disconnected()` is a no-op and no popup fires during the ~0.5–2 s
window before `Char.Name` arrives.

**Reconnect pre-highlighted:** `_main_items()` places Reconnect at index 0
when `connection.state` is absent and `_sel_main = 0` is the default, so the
user can hit Enter immediately.

**Stale sentinel cleanup:** `bridge/launcher/tmux_start.sh` removes `bridge/runtime/.popup_open`
at the top of each run, guarding against a crashed popup from a previous
cockpit session leaving the sentinel behind.

## Scope trims

Deliberately NOT in the popup:
- **About** — not enough value to justify the code.
- **Profile switch / connection mode** — launcher-only; requires restart.
- **Layout mockup** — saves vertical space in the popup.
- **Mouse wheel scroll in the popup** — tmux `display-popup` does not
  forward wheel events to the popup application (only click events).
  A global rebind of `WheelUpPane`/`WheelDownPane` to `send-keys -M`
  would forward them, but breaks wheel scrollback in the game pane and
  other non-mouse-mode panes. The tradeoff is unacceptable; keyboard
  navigation (UP/DOWN, PageUp/PageDown) is the documented path. See
  [ADR 0062](decisions/0062-popup-menu-prompt-toolkit.md).

## Adding a new frame

The popup is a frame stack pushed and popped through `_push_frame` /
`_pop_frame` (see [Overview](#overview)). Frame builders must observe
one contract for mouse routing to work:

1. **Each frame builder constructs at least one focusable `Window` and
   stores it at module level.** Today: `_main_window`, `_options_window`,
   `_scripts_window`, `_statistics_window`, `_exit_confirm_window`. The
   "primary" window of a frame is the one that receives keyboard focus
   while that frame is on top of the stack — usually the window whose
   control owns the frame's mouse handlers.

2. **`_push_frame` calls `app.layout.focus()` on the new frame's primary
   window** after updating `_current_frame`. The dispatch is factored
   into `_focus_current_frame()` — a small switch over `_current_frame`.
   Add an entry there when adding a frame. `_pop_frame` re-runs the same
   dispatch on the way back so the previous frame regains focus.

3. **Frames whose interactivity is keyboard-only can technically skip
   this**, but should not. Marking the primary control `focusable=True`
   and wiring one line into `_focus_current_frame` costs nothing; the
   silent mouse-routing failure that follows if a future contributor
   adds a mouse handler to a frame outside the dispatch is exactly what
   this contract prevents.

If a new frame's mouse handlers seem to fire on the wrong control or
not at all, check the dispatch switch first. See
[ADR 0066](decisions/0066-popup-frame-focus-on-push.md) for the failure
mode that motivated the contract.

---
Back to [architecture.md](../architecture.md).
