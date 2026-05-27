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

Both `display-popup` invocations pass `-S fg=#008787` so the popup
border paints in section cyan (matching the `C_SECTION` chrome tone)
on the ESC-opened popup and the disconnect-auto-opened popup alike.

The UI is a frame stack: a single `DynamicContainer` swaps between
`main`, `options`, `panes`, `readability`, `scripts`, `statistics`,
`rate_session`, `exit_confirm`, `profile_editor`,
`profile_editor_macro_keybind`, and `profile_apply_confirm` containers,
pushed and popped via `_push_frame` / `_pop_frame`. Each frame owns its
own `KeyBindings` filter so navigation, scroll, and ESC behave
per-frame. The Panes submenu is a single `panes` frame backed by the
shared `panes_grid` module (ADR 0086); there is no per-pane subframe.
The profile editor frames use `DynamicContainer` lambdas keyed off the
live `_profile_editor_instance`, and the editor's own key bindings are
merged via `DynamicKeyBindings` — matching the launcher's wiring
pattern (ADR 0109).

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
  (`options`, `panes`, `readability`, `scripts`, `statistics`,
  `rate_session`, `exit_confirm`), pops one frame back toward `main`.
  The frame stack is honoured: ESC inside `panes` or `scripts` returns
  to `options`; ESC inside `readability` routes through save-and-pop
  (writes conf + fires reload if dirty, then pops two frames to main);
  ESC inside `options` returns to `main`. ESC bindings use `eager=True`
  to bypass
  prompt_toolkit's key-disambiguation timeout; `app.ttimeoutlen` /
  `app.timeoutlen` are also lowered to 50 ms so bare ESC feels instant.
- **Arrow keys** — navigate within the current frame's selectable rows
  (wrap-around). In the two-column Scripts frame, `↑` / `↓` moves the
  browse cursor through the list; `PgUp` / `PgDn` scrolls the detail
  panel by one body's worth of rows.
- **Enter / Space** — activates the highlighted row. In `exit_confirm`,
  Y confirms; any other key cancels back to main.
- **Mouse click** — clicks on a row both select and activate it in a
  single click. Implemented as per-fragment `mouse_handler` callbacks
  on `MouseEventType.MOUSE_DOWN`.
- **Mouse hover** — main and options rows light up in `C_HOVER` on hover,
  matching the launcher (see [docs/launcher.md](launcher.md) "Mouse
  hover / click"). Best-effort on terminals that report cell-motion
  mouse events; click-to-activate is the documented fallback. The
  save-success `C_ACCENT` flash wins over hover for its ~1 s window.
  The Panes submenu's grid does not use a separate hover style —
  hovering a cell moves the cursor to that cell instead, so the gold
  cursor highlight is the only visible response.
- **Mouse wheel** — not used inside the popup. See Scope trims.

## Status header

The status header is the topmost row of the popup — above the starfield
+ wordmark banner on `main`, below the title row on `rate_session` — and
shows Profile · Mode · Link. Backed by `bridge/runtime/connection.state`
(connection status) and `bridge/runtime/ping.cache` (link quality).
Example:

    Profile: default  ·  MMapper  ·  Link: 38ms (stable)

State is re-probed from the files on every render — never cached.

The header paints in `C_HINT` (the same muted grey as the footer
shortcut row) so it reads as chrome, not content. The link-quality
suffix only departs from `C_HINT` when something needs attention:
`jittery` / `spiking` render in `C_YELLOW`, and `timeout` / `dead` /
unknown quality render in `C_ERR`.

The popup invalidates itself once per second while open, so the Link readout
(and any other on-render state like connection mode or the Statistics row's
visibility) tracks the underlying files without requiring a keypress.

## Profile frame

The **Profile** row on the main frame opens the shared `ProfileEditor`
(ADR 0109) inside the popup. The row is always present — connected and
disconnected — and its behaviour branches on connection state.

### Connected path (snapshot / apply handshake)

1. Clean up stale runtime files (`profile_snapshot.tin`,
   `profile_edit.tin`, `.profile_snapshot_result`,
   `.profile_apply_result`).
2. `_send_to_game("cp -profile-snapshot")` — the tt++ alias writes the
   live profile class to `bridge/runtime/profile_snapshot.tin` and echoes
   `ok` into `.profile_snapshot_result`.
3. Poll for `.profile_snapshot_result` with a 2 s timeout (50 ms tick),
   running in a worker thread so the prompt_toolkit event loop stays
   responsive.
4. On `ok`: parse `profile_snapshot.tin` via `profile_io.load_profile`.
   Stash `_profile_editor_original_text = profile_io.serialize_profile(profile)`
   for dirty detection. Construct `ProfileEditor` with the popup's
   `_PopupEditorHost`. Push `profile_editor` frame.
5. On `fail` / timeout / parse error: flash the reason in `C_HINT` on
   main for ~3 s. Do not push.

### Disconnected path (disk-only, launcher-style)

Read profile name from `bridge/runtime/startup.conf` (`profile=` line).
Resolve `ttpp/profiles/<name>.tin`. Parse via `profile_io.load_profile`.
Stash original text the same way. Construct `ProfileEditor`. Push
`profile_editor` frame.

The `on_exit` callback for this path saves directly to the `.tin` via
`profile_io.save_profile` and runs `sanitize_profile.sh` — matching
launcher behaviour exactly.

### on_exit — dirty detection

```python
final_text = profile_io.serialize_profile(profile)
dirty = (final_text != _profile_editor_original_text)
```

- **Clean** (no edits): pop silently back to main, clean up instance.
- **Dirty + disconnected**: save to disk, flash confirmation, pop.
- **Dirty + connected**: stash pending profile, push
  `profile_apply_confirm` frame.

### profile_apply_confirm frame

Modal three-action confirmation:

```
   Apply changes to your profile?

   Y to apply · N to discard · ESC to keep editing
```

- **Y** — serialize the pending profile to `bridge/runtime/profile_edit.tin`
  via `profile_io.save_profile`, append the canary line
  `#var {_profile_load_canary} {ok}`, send `cp -profile-apply` to the game,
  poll `.profile_apply_result` (2 s timeout, 50 ms tick, worker thread).
  On `ok`: flash "Profile updated." in `C_ACCENT` on main.
  On `fail` / timeout: flash rollback message in `C_HINT`.
  Either way: clean up instance, pop confirm + editor → main.
- **N** — discard pending profile, clean up, pop back to main.
- **ESC** — pop one frame, back into the editor with edits intact.

While polling, the frame shows "Applying…" in place of the prompt; a
single re-render is enough. The `<any>` binding is a no-op so
extraneous keys during the poll are swallowed.

### tt++ aliases — cp -profile-snapshot / cp -profile-apply

Both live in `ttpp/core/system.tin` and follow the `_save_profile`
discipline (must run in the session that owns the profile class):

- `cp -profile-snapshot` — writes the live class to
  `bridge/runtime/profile_snapshot.tin` via `#class write`, echoes
  `ok` / `fail` into `.profile_snapshot_result`.
- `cp -profile-apply` — kills the class, reads
  `bridge/runtime/profile_edit.tin` using the explicit
  `#class open` + `#read` + `#class close` pattern (mirroring
  SESSION CONNECTED, because `#class read`'s shorthand does not
  class-tag `#highlight` and `#macro` entries), checks the canary
  variable `_profile_load_canary`. On success: unsets the canary, runs
  `_save_profile` (persists to disk + sanitize), reopens the profile
  class, echoes `ok`. On failure: kills the broken class, reads back
  the snapshot via the same explicit pattern, reopens the profile class,
  echoes `fail`. The reopen mirrors the `SESSION CONNECTED` final-open
  step — without it, the explicit `#class close` leaves subsequent
  `#alias` / `#action` commands in the default class.

Both aliases are routed through the player's input pane via
`tmux send-keys` — the same path the popup already uses for reconnect.

**Canary rationale.** The popup appends `#var {_profile_load_canary} {ok}`
as the last line of `profile_edit.tin`. If `#class read` reaches the end
of the file the canary is set globally (variables are not class-scoped
per ADR 0064), so `#class write` on the next `_save_profile` does not
emit it. If the read aborts mid-file the canary is never set and the
alias rolls back to the snapshot.

### EditorHost implementation

`_PopupEditorHost` in `ingame_menu.py` mirrors the launcher's
`_LauncherEditorHost`. `terminal_bg` is read from
`bridge/runtime/layout.conf` (persisted by the launcher's background-
detect probe). `push_overlay_frame()` pushes
`profile_editor_macro_keybind`. The two new frames use `DynamicContainer`
lambdas keyed off `_profile_editor_instance`.

### Runtime tempfile hygiene

The popup's `atexit` cleanup (alongside `.popup_open` sentinel removal)
removes `profile_snapshot.tin`, `profile_edit.tin`,
`.profile_snapshot_result`, and `.profile_apply_result`. These are
runtime-only — no value across popup sessions.

## Options grouping

Between **Save run** (when present) and **Exit session** sit
**Profile** and **Options**. Profile opens the shared `ProfileEditor`
(ADR 0109) — see the [Profile frame](#profile-frame) section below.
Options pushes a thin index frame whose sole purpose is to group
**Panes** and **Scripts** under one slot, so the main menu stays short.

```
--- Options ---
                   (blank row)
Panes
Readability
Scripts
                   (blank row)
Back
```

`Options → Panes` reaches the Panes submenu described below; `Options
→ Readability` reaches the interactive Readability frame (see
[Readability submenu](#readability-submenu) below); `Options → Scripts`
reaches the Scripts frame (unchanged from previous versions). ESC
inside `options` pops back to `main`; ESC inside `panes` or `scripts`
pops back to `options`; ESC inside `readability` routes through
save-and-pop (see below). Source of truth is `_OPTIONS_ROWS` in
`ingame_menu.py`.

Frame titles in `options` and `panes` emit a blank row between the
centred title and the first content row, matching the launcher's
title spacing.

Title, footer, menu-row, and three-state button chrome are shared with
the launcher via `bridge/launcher/menu_chrome.py` — see
[docs/launcher.md](launcher.md#shared-menu-chrome) for the helper
contracts and [ADR 0085](decisions/0085-shared-menu-chrome.md) for
the rationale. The popup's `main`, `options`, and `scripts` frames are
all single `FormattedTextControl` Windows emitting `title_block` (with
`blank_above=1`) + body + `footer_block` in one fragment list — the
footer is anchored to the popup's final row. The `main` frame's
animated starfield + wordmark banner is shared with the launcher via
`bridge/launcher/launcher_banner.py` (the logo, not a section title —
so it does not go through `title_block`); see the
[Shared banner](launcher.md#shared-banner) section in `docs/launcher.md`
for the call contract and ADR 0100 for the unification rationale. The
popup runs its own main-frame-gated `_banner_tick_task` at
`_BANNER_TICK_HZ = 6` (alongside the existing 1 Hz `_tick` that
refreshes the status header), so the twinkle redraws only while the
popup is open and on `main`; submenus and the closed popup do not
invalidate. The launcher's redraw loop runs at 12 Hz — the popup's
slower rate is deliberate, because it runs as an overlay over a live
game. Selectable menu rows render
through `menu_chrome.menu_row`: gold `<< >>` on the cursor row, hover
lightens the label (`C_HOVER`). The dead-grey "Save run" row reuses
the `menu_row` "inactive" state with `inactive_style=C_HINT` and no
row handler. The `rate_session` frame also anchors its
`0-5 Set · ←→ Adjust · Enter Save · ESC Cancel` shortcut row via
`menu_chrome.footer_block` — title row + status header + star row
stay top-anchored, the shortcut row sits on the popup's last row, and
the title adopts `C_SECTION` to match the swept menu chrome. The
`exit_confirm` modal keeps its vertical layout — no footer anchoring —
and adopts `C_SECTION` for the title row.

**Hover-clear invariant.** Each frame with hover state attaches a
small clear-hover handler (resets the frame's hover index on
MOUSE_MOVE) to its `title_block` / `footer_block` chrome, blank
separator rows, status header (on `main`), banner rows, dead-grey
"Save run" row, and per-row left/right padding so the hover highlight
clears the moment the pointer moves off a selectable row — above the
top, below the bottom, between rows, or to the side. Selectable rows
own their own MOUSE_MOVE handler that sets hover to that row instead.
Mirrors the launcher's hover-clear contract.

## Panes submenu

`Options → Panes`. Source of truth is `_PANE_TARGETS` in
`ingame_menu.py`; the grid render and toggle logic live in
`bridge/launcher/panes_grid.py` (shared with the launcher — see the
[Panes colour grid model](launcher.md#panes-colour-grid-model) section
in `docs/launcher.md` and ADR 0086).

The `panes` frame renders a **pane × colour grid**: rows are the six
right-column panes (Character / Buffs / Group / Communication / UI /
Developer), columns are the seven palette entries (Black / Red /
Green / Blue / Grey / Orange / Purple). Each cell renders as `[X]███`
or `[ ]███` — a 3-cell checkbox and a 3-cell colour swatch. Below the
grid sit a blank row, a `[X] Display pane headers` toggle, a blank
row, and `Back`. The frame uses `menu_chrome.title_block` /
`footer_block` (`blank_above=1` for the popup) and the
`menu_chrome.button_fragment` three-state grammar for the headers
toggle and `Back`. The inactive state of `button_fragment` is
foreground-only (no background fill) — at rest those two cells fall
through to the host terminal background; only the cursor-row and
hover states paint a fill.

Per row, **0 or 1 cells are checked**: zero checked means the pane is
off (and the row paints dim end-to-end via `C_PANE_OFF`); one checked
means the pane is on with that colour. Pane open-state is re-probed
from tmux on every render; the current colour for each row comes from
`startup.conf`.

Click / Enter semantics (`panes_grid.apply_cell_toggle`):

- On a grid cell — if the cell is the pane's currently-checked colour,
  uncheck it (the pane closes); otherwise check it (the pane opens
  with that colour, clearing any other checked cell in the row). The
  delta drives `toggle_pane.sh <target> --persist` (when the pane's
  open/closed state changes) and `tmux select-pane -t
  mume:cockpit.<idx> -P bg=<hex|default>` (when the pane is — or has
  just become — open). The colour name is also written to
  `startup.conf` via the in-place `_persist_conf_key` helper so it
  survives the next cold start (the cockpit's `open_pane.sh`
  `_pane_bg_for` reads the same key).
- On the headers toggle row — `toggle_pane.sh headers --persist`
  (live tmux border status + `show_pane_dividers` in `startup.conf`).
- On `Back` — pops back to `options`.

This is the persistence asymmetry vs. the launcher: the popup writes
each cell click immediately and live-applies to tmux, while the
launcher Options batches writes to Back / ESC and defers the visible
effect to the next cockpit start. Both surfaces write the same
`startup.conf` keys.

Cell render rules per the shared model: cursor cell brackets paint
gold (`C_CURSOR_CELL`); on an enabled row, checked brackets paint
bright (`C_ACTIVE`), unchecked paint dim (`C_HINT`); on a disabled
row every cell paints `C_PANE_OFF` except the cursor cell's brackets
which stay gold. Swatches paint solid `bg:<hex> fg:<hex>` on enabled
rows (Black is a literal `#000000` swatch even though the actual
pane behaviour for `Black` is `bg=default`) and `C_PANE_OFF` on
disabled rows. The colour name → hex mapping lives in `PANE_COLORS`
(`bridge/launcher/palette.py`); see
[docs/launcher.md](launcher.md#per-pane-colour-palette) for the
table and the `palette.py` ↔ `open_pane.sh` mirror convention.

**Cursor / navigation.** Eight navigable rows: the six grid rows, the
headers-toggle row, and the `Back` row. `↑` / `↓` move between them
(clamped). `←` / `→` move the column only while the cursor is on a
grid row, clamped 0..6; the column persists across grid rows and
across visits to the headers / Back rows. Mouse hover on any
selectable target moves the cursor there — there is no separate hover
style on the grid. Footer: `↑↓←→ Move · Enter Toggle · ESC Back`.

Connection mode (MMapper / Direct / Custom) and profile switch are
deliberately **not** present in the popup — they require a restart and
are launcher-only.

`cp -u`, `cp -d`, `cp -m`, `cp -c`, `cp -b`, `cp -g`, and `cp -h` are thin wrappers
around `bridge/layout/toggle_pane.sh`, each passing `--persist`. All toggle paths —
popup, launcher Options, and `cp -X` aliases — are equivalent and write to
`startup.conf`. Colour selections do **not** have `cp -X` equivalents
today — they are reachable from the launcher Options page and the
popup's Panes submenu only.

## Readability submenu

Two-column `[ list | detail ]` interactive browser of readability modules.
Frame name: `readability`. Frame stack path: `main` → `options` →
`readability`. Layout is rendered through the shared
`bridge/launcher/readability_view.py` module (the same module used by the
launcher's Readability page), so the popup and launcher paint pixel-for-pixel
the same body region — only the title-block chrome differs (`blank_above=1`
in the popup, `blank_above=2` in the launcher).

**Source — live filesystem scan.** On every push of the frame the popup
scans `ttpp/readability/modules/*.tin`, reads the `readability_enabled`
key from `bridge/runtime/startup.conf`, and builds the catalog. Each
module row shows `[X]` (enabled) or `[ ]` (disabled) with its name. The
detail panel shows description + before/after preview (with ANSI colour
rendering) when a `.meta` companion file exists; otherwise just the
module name and status.

**Interactive toggling.** Unlike the read-only Scripts submenu, the
Readability view is fully interactive: Space/Enter on a module row
toggles its enabled state in place (updating the `[X]` / `[ ]` glyph),
and clicking a row jumps the cursor and toggles in one motion. Toggling
alone updates the UI without touching tt++ — changes are batched.

**Save-and-pop semantics.** Both ESC and Back-row activation route
through `_readability_save_and_pop()`:

- **If dirty** (at least one toggle was made):
  1. `readability_view.write_enabled(STARTUP_CONF_PATH, enabled_set)` —
     atomic write of the `readability_enabled` key; all other keys are
     preserved byte-identical.
  2. `_send_to_game("#lua {scripts.readability.reload()}")` — fires the
     existing hot-reload path via `tmux send-keys`, so changes apply
     immediately without a restart.
  3. `_flash_main("Readability updated.", C_ACCENT)` — schedules a brief
     flash on the main frame using the existing profile-apply success
     flash helper.
  4. Pops two frames (readability → options → main), so the flash lands
     on the main frame the user will see.

- **If clean** (no toggles):
  1. Pops two frames silently — no conf write, no reload dispatch, no
     flash. Symmetric exit behaviour.

**No apply-confirm modal.** The snapshot/canary/result-poll/worker-thread
machinery from ADR 0110 is deliberately not mirrored. Readability module
`.tin` files are static developer-authored content, not user-edited text —
there is no "user corrupts the class with a parse error" failure mode to
guard against. Toggles are non-destructive and reversible.

**Keyboard.**

| Key | Action |
|-----|--------|
| ↑/↓ | Move cursor (skips spacer to Back) |
| Space/Enter | Toggle module or activate Back (save-and-pop) |
| PgUp/PgDn | Scroll detail panel |
| ESC | Save-and-pop (write + reload if dirty, then pop to main) |

**Mouse.** Hover lights the row under the pointer (`C_HOVER` on module
rows; light `<< Back >>` on Back). Click on a module row jumps the
cursor and toggles in one motion. Click on the list or detail scrollbar
gutter page-steps in the click direction. Mouse wheel is not wired
(tmux `display-popup` limitation). The hover-clear invariant applies.

**Empty state.** When no `.tin` files exist the detail area shows the
shared "No readability modules found" message; the cursor lands on Back
(the only navigable row). Footer collapses to `ESC Back`.

## Scripts submenu

Two-column `[ list | detail ]` browser of the brain's currently-loaded
script catalog. Layout is rendered through the shared
`bridge/launcher/scripts_view.py` module (precedent: `panes_grid`, ADR
0086) so the popup and the launcher's Scripts page paint pixel-for-pixel
the same body region — only the title-block chrome differs (`blank_above=1`
in the popup, `blank_above=2` in the launcher).

**Source — `scripts.cache`, frozen at brain startup.** The popup reads
`bridge/runtime/scripts.cache` once on every frame push and renders that
catalog verbatim. `scripts.cache` is written by the brain's two-tier
loader once at startup with every script in `lua/scripts/` — both
enabled and disabled — including each script's `@summary`, `@alias`,
and `@help` metadata. Disabled scripts therefore appear in the popup's
list with `[ ]` and dimmed styling, and clicking a disabled row updates
the detail panel just like an enabled row. A mid-session addition to
`lua/scripts/` is intentionally **not** shown — the popup must agree
with the brain's loaded set, which only changes on the next cockpit
start. See [docs/scripts.md](scripts.md) and [ADR 0093](decisions/0093-script-metadata-headers-and-opt-in-loading.md)
for the cache format and the loader's design.

**Read-only by design.** The popup never toggles a script's enabled
state. An enabled script's aliases, triggers, and event subscriptions
have no universal teardown contract, so toggling mid-session would
leave phantom registrations; the launcher's Scripts page (reached via
the Exit-to-main-menu path) is the intended toggle workflow. The
footer omits the Toggle key — `↑↓ Move · PgUp/PgDn Scroll · ESC Back` —
and the absence is the read-only signal. Clicks on script rows are
select-only; they move the browse cursor without flipping the
checkbox.

**Left column — Back inline.** The body layout matches the
launcher's Scripts page: script rows, then a blank spacer, then an
in-column `<< Back >>` row rendered through `menu_chrome.menu_row`
(`selected` / `hover` / `inactive` grammar — gold arrows on the
cursor, light `C_HOVER` label on mouse hover, `C_ITEM` label
otherwise). The browse cursor traverses script rows and Back via
`↑` / `↓`; while the cursor sits on Back the detail panel keeps
showing the latched script (`detail_idx=_scripts_cursor` is passed
to the shared renderer). Clicking Back pops the frame, same as ESC.

**Keyboard.** `↑` / `↓` steps the browse cursor through script rows
and Back, skipping the blank spacer (mirrors the launcher).
`Home` / `End` jumps to the first / last script. `Enter` on Back
pops the frame; `Enter` on a script row is a no-op (the popup is
read-only). `PgUp` / `PgDn` scrolls the detail panel by one body's
worth of rows (clamped to the detail content total). Mouse wheel is
intentionally not wired here — tmux `display-popup` only forwards
click events, so keyboard is the documented scroll path. ESC pops
back to `options`.

**Mouse.** Hover lights the row under the pointer (`C_HOVER` on
script rows; light `<< Back >>` on Back). A click on a script row
moves the browse cursor to that row and resets the detail scroll —
read-only, no toggle. A click on the list or detail scrollbar gutter
page-steps in the click direction (no wheel branch — the popup is
wheel-free). The hover-clear invariant applies: title / footer
chrome, blank spacer, and per-row padding around `<< Back >>` carry
a clear-hover handler so the highlight does not stick when the
pointer moves off a selectable row.

**Empty state.** When the cache is missing or empty (e.g. before the
first brain startup of a fresh install) the body region shows the
shared centred *"No scripts found — drop a .lua file in lua/scripts/"*
message with a dim *"see docs/scripts.md"* pointer; the cursor lands
on Back automatically (it's the only navigable row), so `Enter` /
click on Back / `ESC` all pop. The footer collapses to `ESC Back`.

Not covered: live script state (IDLE/RUNNING/FIRING) and a
stop-all-scripts button — both parked.

## Statistics frame

A read-only view of the current run, opened from a "Statistics" row on the
main frame. The row sits between **Save run** and **Options** and is
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

**Header line.** `◆ STATISTICS  —  <char>  ·  Lvl N  ·  Run <duration>`.
`Lvl N` is derived from `stats.xp_current` via `_level_from_xp`
against `_TABLE_XP` — i.e. the player's actual current level, not
the peak level reached during the run. It tracks the run symmetrically
on both positive progression (level-ups) and negative progression
(death penalty taking the character below the run-start level). When
`xp_current` is missing or non-positive it falls back to
`status["level"]` from `bridge/runtime/status.state`.

When `stats.saved` is true and `stats.rating` is non-zero, the stars
are appended to the header as the last `·`-separated field in the
same `_S_HINT` (muted grey) the rest of the banner uses:
`◆ STATISTICS — <char> · Lvl N · Run <duration> · ★★★`. The stars are
exactly `stats.rating` `★` glyphs. Unsaved runs
and 0-rating saved runs omit the trailing ` · ` and stars entirely —
no `Rating:` label, no placeholder glyphs, no floating right-edge
element. The whole header is a single left-padded centred line.
`stats.saved` / `stats.rating` are read on every tick from the meta
sidecar via `run_meta.read_meta(character, run_ids[-1])`, so saving
the session while Statistics is open paints the stars on the next
tick.

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
The focused table's title row paints en bloc in `C_CURSOR_CELL` (gold)
instead of `C_SECTION` (cyan) — every fragment in the row (section
name, column headers, sort indicators) switches together.

**Palette.** The Statistics frame paints the `◆ STATISTICS …` banner
in `_S_HINT` (muted grey — same tone as the footer shortcut row);
the six section titles (KILLS, PvPs, ALLIES, ACHIEVEMENTS, XP/h,
TP/h) use `C_SECTION` (dark cyan); the frame uses `C_HEADER` nowhere
anymore. The focused KILLS / PvPs / ALLIES / ACHIEVEMENTS title row
paints en bloc in `C_CURSOR_CELL` (gold). Divider rules under section
titles and
sparkline frame strokes (`──┬──` under XP/h / TP/h, axis `│`, bottom
`└──`) render in `C_DIVIDER`, a muted gray aliased to `C_HINT`.
KILLS / PvPs data rows render in `_S_LABEL` (medium gray) so the
`_S_TOTAL` (bold white) sticky Total row visually anchors the
aggregate; ALLIES / ACHIEVEMENTS data rows stay in `_S_VALUE`. The
data-cell palette (`_S_VALUE`, `_S_LABEL`, `_S_GAINED`, `_S_TP_BAR`,
`_S_LEVEL`, `_S_TRACK`, `_S_THUMB`, `_S_TOTAL`, `_S_ARROW`, `_S_HINT`,
`_S_PVP`, `_S_ALLY`, `_S_STAR`) is private to the frame so main /
panes / scripts palettes are unaffected.

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
in `_S_LEVEL` and flow off the glyph. The marker range is
`[level(min(xp_at_start, xp_current)),
level(max(xp_at_start, xp_current)) + 1]` — bracketed by the actual
XP endpoints regardless of direction, derived via `_level_from_xp`
against `_TABLE_XP`. It does not reflect the peak level reached
during the run. Row 4 is a trailing blank line.

**XP-linjalen — negative session gain.** When `xp_current < xp_at_start`
(typically after a death penalty whose loss exceeds the post-death XP
gained back), the band's direction is inverted: it runs from the
post-death XP column up to the pre-run-start XP column. Both endpoints
are mapped through `_xp_to_bar_col` and the lo/hi columns anchor the
▌ / ▐ markers the same way as in the positive case, so the band
occupies the same visual slot regardless of direction. The row 2 band
cells render in `_S_LOSS` (red) instead of `_S_GAINED`; row 1's bracket
label flips to `-N XP` (absolute value of the loss in k-formatted form
with a leading minus and an explicit ` XP` suffix), with the digits
and the suffix rendered in `_S_LOSS` — brackets, arrowheads, and `▬`
filler keep `_S_ARROW`. The narrow-band fallback (plain centred label)
applies symmetrically. Row 3 (level markers) and row 4 (trailing
blank) are unchanged.

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

Footer: `ESC Back · ↑↓ Scroll · Tab/Shift+Tab Switch table`.

**Parked.** Export of the current run to a file (the placeholder `E`
keybinding was removed when the feature was cancelled); drag-to-scroll
on the scrollbar track (click-to-jump and keyboard scroll are the
supported paths).

The aggregation library backing this frame lives at
`bridge/launcher/run_stats.py` and is shared with the future launcher
run-browser. See [ADR 0065](decisions/0065-run-stats-python-aggregator.md)
for the rationale.

## Save run

A "Save run" row sits above Statistics on the main frame, gated on the
same `_statistics_character()` check as the Statistics row: it appears
only while an active run is being tracked (`status.state` names a
character and `data/runs/<character>/current.jsonl` exists). When no
active run is being tracked the row is not emitted at all.

The row is one-shot per active run and has two visual states, decided on
every render from the meta sidecar:

- **Not saved** — normal `C_ITEM` style, selectable; activation (Enter /
  Space / click) pushes the `rate_session` frame.
- **Saved** — dead-grey: just the label `"Save run"` painted in
  `C_HINT` (no `<<>>` decoration, no star suffix, no hover highlight);
  no mouse handlers are attached, and keyboard navigation
  (`_main_selectable_indices`) skips the index, so Enter and click are
  both no-ops. The rating itself surfaces on the Statistics header,
  not this row. The saved state is read fresh on each render from
  `data/runs/<character>/<run-id>.meta.json` (`run_meta.is_saved`), so
  closing and reopening the popup within the same run preserves the
  dead state.

### Rate-session frame

Pushing the row presents the `─── Rate the run ───` title row
(`title_block` with `blank_above=1`), the same Profile · Mode · Link
status header used on the main frame directly below it, and a centred
row of five `★` glyphs (single-space separated; gold for the first
`_rate_session_rating` stars, grey for the rest). The
`0-5 Set · ←→ Adjust · Enter Save · ESC Cancel` shortcut row is
anchored to the popup's final row via `menu_chrome.footer_block` —
title / status / stars stay top-anchored while the shortcut row sits
at the bottom. The frame follows the focus-on-push contract (ADR
0066): `_rate_session_window` is registered in `_focus_current_frame()`
so per-star click handlers route correctly.

`_rate_session_rating` resets to `0` on every push of the frame —
unrated by default — so opening the rating screen never carries over
a prior session's stars.

Key bindings (filter: `_in_frame("rate_session")`):

| Key      | Action                                                    |
|----------|-----------------------------------------------------------|
| `0`..`5` | Set `_rate_session_rating` to that value                  |
| `Left`   | `rating = max(0, rating - 1)`                             |
| `Right`  | `rating = min(5, rating + 1)`                             |
| `Enter`  | Save and pop back to main                                 |
| `Space`  | Save and pop back to main                                 |
| `ESC`    | Pop back to main without saving                           |

Mouse: clicking star N (1-indexed) sets the rating to N.

### Chain save semantics

Enter walks the stitched run chain via
`run_stats.previous_run_chain(character, current_run_id)` (the
[ADR 0056](decisions/0056-previous-run-id-linking.md) definition,
default `max_gap_seconds=3600`) and calls
`run_meta.save_run_chain(character, chain, rating)`, which writes one
atomic `<run-id>.meta.json` sidecar per run in the chain — including
the current (still-`current.jsonl`) run, whose meta uses its computed
run-id. There is no on-screen confirmation flash or banner; the
re-rendered main frame's dead-grey "Save run" row is the
user-visible confirmation. The chosen rating surfaces on the
Statistics frame's header as an inline ` · <stars>` field at the end
of the centred header line.

The keyboard alias `cp -s` (profile save) is independent of the popup
row and unchanged: it still runs
`#class {$_profile} {write} {ttpp/profiles/$_profile.tin}` inside the
profile's tt++ session and works after link loss. The popup's
"Save run" is a separate concept — saving the *play session*'s
run logs from the 14-day retention sweep, not saving the tt++ profile.

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
- **Profile switch / connection mode / profile creation** — launcher-only; requires restart.
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
   `_panes_window`, `_scripts_window`, `_readability_window`,
   `_profile_apply_confirm_window`, `_statistics_window`,
   `_exit_confirm_window`, `_rate_session_window`.
   The
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
