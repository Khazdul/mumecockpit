# MUD Client Architecture

A fast, terminal-based MUD client with clean separation between real-time I/O
and scripting logic. Designed for performance and extensibility — minimal
latency for input/output, with Lua handling advanced automation, state
tracking, and UI feedback.

## Stack

| Component | Role                                        |
|-----------|---------------------------------------------|
| TinTin++  | Core client — triggers, keybinds, I/O       |
| Lua       | Brain — logic, state, timers, comms         |
| tmux      | Window orchestration                        |

## Project Structure

```
~/MUME/
├── start.sh              # Entry point — starts entire system
├── VERSION               # Semantic version string (read by launcher)
├── architecture.md       # This file
├── ttpp_manual.txt       # TinTin++ reference manual
│
├── ttpp/
│   ├── main.tin          # tt++ entry point — auto-loads all of core/
│   ├── core/             # System modules (.tin files), auto-loaded
│   │                     #   affects.tin    — affect trigger registration (per session)
│   │                     #   stat_reconcile.tin — stat/info "Affected by:" block parser
│   │                     #   clock.tin      — 4 Hz clock ticker + game-time sync actions
│   │                     #   config.tin     — reads startup.conf → _profile/_host/_port/_ses_cmd
│   │                     #   gmcp.tin       — GMCP telnet negotiation and Lua dispatch
│   │                     #   mud_events.tin — core MUD triggers → Lua event bus (priority 3)
│   │                     #   system.tin     — connection aliases, cp commands, session events
│   │                     #   welcome.tin    — clean boot banner + auto-connect
│   ├── readability/      # Drop-in readability modules — see docs/readability.md
│   │   └── modules/      #   <name>.tin loaded into {readability} class on session start
│   └── profiles/         # Per-profile personal settings (.tin files)
│                         #   default.tin is runtime-seeded from
│                         #   bridge/launcher/templates/blank_profile.tin (ADR 0042)
│
├── lua/
│   ├── brain.lua         # Lua brain — entry point: globals, dofile sequence,
│   │                     #   handle_event, main loop. ~60 lines.
│   ├── brain/            # Brain submodules (auto-loaded by brain.lua in fixed order)
│   │                     #   ui.lua         — loggers, colour constants, ui()/script_ui()/system_ui()/...
│   │                     #   io.lua         — tt++ command relay (tintin/send/game_cmd/session_cmd)
│   │                     #   events.lua     — event bus (subscribe/emit/unsubscribe/trace)
│   │                     #   gmcp.lua       — GMCP namespace, dispatch, module_to_event
│   │                     #   connection.lua — MUME connection state, popup helpers
│   │                     #   registry.lua   — cp help box drawing, scripts.cache writer
│   │                     #   loader.lua     — lua/core + lua/scripts auto-loader
│   │                     #                    (parses @-tagged headers, resolves scripts.conf)
│   ├── lib/              # Bundled Lua libraries (on package.path)
│   │                     #   dkjson.lua  — pure-Lua JSON parser (MIT, David Kolf)
│   ├── core/             # Always-on infrastructure — GMCP collectors, serializers,
│   │                     # and loaders. No alias, no @-header. Examples:
│   │                     #   char_state.lua    — Char.* → state.char.*
│   │                     #   comm_log.lua      — Comm.Channel.* → state.comm.*
│   │                     #   readability.lua   — readability module loader (startup.conf → session_cmd)
│   │                     #   status_state.lua  — state.char → bridge/runtime/status.state (runtime)
│   │                     # See CLAUDE.md and per-area docs/*.md for the full list.
│   └── scripts/          # Opt-in automation modules — see docs/scripts.md. Each
│                         #   file carries an @-tagged metadata header parsed
│                         #   statically by the loader; enable state in
│                         #   bridge/runtime/scripts.conf (shadows template).
│
├── bridge/
│   ├── launcher/             # Pre-tmux menu, tmux orchestration, Windows entry
│   │   ├── launcher.py       # Pre-tmux startup menu (prompt_toolkit Application)
│   │   ├── launcher.sh       # Thin exec wrapper for launcher.py
│   │   ├── palette.py        # Shared prompt_toolkit colour palette (launcher + popup)
│   │   ├── launcher_banner.py # Shared animated starfield + wordmark banner (launcher main page + in-game popup); ADR 0100
│   │   ├── profile_editor.py # Self-contained ProfileEditor class (extracted from
│   │   │                     #   launcher.py); host access via EditorHost protocol
│   │   │                     #   so the same editor can run inside the popup (ADR 0109)
│   │   ├── foot_config.py    # Pure foot.ini reader/writer + fc-list monospace
│   │   │                     #   font enumerator; backs Options → Terminal (ADR 0104)
│   │   ├── tmux_start.sh     # tmux session creation, hooks, keybinds
│   │   ├── ingame_menu.sh    # In-game ESC popup menu
│   │   ├── profile_io.py     # Parser / serializer for tt++ profile .tin files; backs
│   │   │                     #   the launcher's profile editor (ADR 0042 round-trip
│   │   │                     #   contract, see docs/launcher.md)
│   │   ├── macro_keys.py     # Bidirectional macro-key map (tt++ escape ↔ prompt_toolkit
│   │   │                     #   key ↔ display name) for the editor's Macros tab;
│   │   │                     #   mirrors input_pane's forwardable-key set (ADR 0082)
│   │   ├── ttpp_syntax.py    # Lexical tokeniser for the profile editor's Editor-mode
│   │   │                     #   syntax highlighting (commands, braces, delimiters,
│   │   │                     #   variables, colour codes / escapes — ADR 0089)
│   │   ├── run_stats.py      # JSONL run-statistics aggregator — shared by the popup
│   │   │                     #   Statistics frame and the future launcher run-browser (ADR 0065)
│   │   ├── spotlights.py     # Cross-character spotlight reel aggregator + playback
│   │   │                     #   adapter for log_view spotlight mode (ADR 0077)
│   │   ├── credits.py        # End-of-reel scrolling credits content generator (ADR 0080)
│   │   ├── run_retention.py  # 14-day retention sweep for run logs (ADR 0074)
│   │   ├── launch.sh         # Former Alacritty desktop-shortcut target (ADR 0028);
│   │   │                     #   obsolete after the foot/WSLg switch — kept for
│   │   │                     #   one release of grace, removable in the next pass.
│   │   ├── build_initial_layout.sh  # Builds pane layout on first client-attach
│   │   ├── wait_for_layout.sh       # Blocks tt++ start until layout is ready
│   │   ├── open_pane.sh      # Opens/manages tmux panes dynamically
│   │   ├── read_config.sh    # Emits tt++ #var assignments from startup.conf
│   │   ├── about.txt         # About page body text
│   │   ├── quotes.txt        # Tolkien quotes shown on main menu (pipe-sep format)
│   │   ├── templates/        # New-profile content templates
│   │   │                     #   blank_profile.tin — seeded into
│   │   │                     #   ttpp/profiles/default.tin and used by
│   │   │                     #   the launcher's "Create blank profile" (ADR 0042)
│   │   └── widgets/          # Reusable prompt_toolkit widgets for the popup
│   │                         #   scrollbar.py — click-to-jump scrollbar widget
│   ├── panes/                # Python prompt_toolkit pane renderers
│   │   ├── input_pane.py     # Input pane — CLI, forwards to TT++, right-aligned clock
│   │   ├── comm_pane.py      # Comm pane — clickable channel-filter header + scrollable history
│   │   ├── buffs_pane.py     # Buffs pane — affect grid (grouped, bar drain, blink)
│   │   ├── group_pane.py     # Group pane — member HP/Mana/Moves bars with name overlay
│   │   ├── status_pane.py    # Status pane — polls status.state
│   │   └── ui_pane.py        # UI pane — tails logs/ui.log
│   ├── layout/               # Pane/layout state mutations
│   │   ├── apply_layout.sh   # Re-applies saved layout after resize or pane toggle
│   │   ├── apply_border_style.sh  # Single authority for tmux pane-border-style — paints
│   │   │                     #   the separator row to match layout.conf:terminal_bg
│   │   ├── on_window_resize.sh  # Fired on terminal resize — re-applies stored layout
│   │   ├── on_pane_resize.sh    # Fired on border drag — saves new layout values
│   │   ├── toggle_pane.sh    # Toggle ui/dev/comm/status/buffs panes and pane headers
│   │   │                     #   (called by cp aliases and in-game popup)
│   │   └── focus_input.sh    # Resolves input pane index at click time (MouseUp1Pane target)
│   ├── release/              # Release/update operations
│   │   ├── update.sh         # Safe self-update runner (fetch, unpack, install)
│   │   ├── check_release.sh  # Pre-tag sanity check — verifies VERSION matches intended tag
│   │   └── sanitize_profile.sh  # Strips #class wrappers; called by cp -s/-r after save
│   ├── services/             # Cockpit-spawned background tasks
│   │   ├── version_check.sh  # Queries GitHub for latest tag; updates
│   │   │                     #   bridge/runtime/version.cache with 6h TTL
│   │   ├── ping_monitor.sh   # Session-scoped background ping monitor
│   │   │                     #   (spawned by tmux_start.sh + launcher.sh; self-terminates)
│   │   └── read_version.sh   # Emits _client_version tt++ var from VERSION file
│   ├── ipc/                  # IPC temp files written by tintin_cmd,
│   │                         #   consumed by tt++ via tintin_read action
│   ├── runtime/              # All runtime-generated files (ADR 0047; gitignored except .gitkeep)
│   │   ├── startup.conf      # Persisted startup-menu state
│   │   ├── layout.conf       # Persisted layout state (keys: ui_width, window_cols, desired_<pane>, terminal_bg)
│   │   ├── status.state      # Character status JSON written by status_state.lua
│   │   ├── buffs.state       # Affect grid snapshot written by buffs_state.lua
│   │   ├── group.state       # Group member vitals JSON written by group_state.lua
│   │   ├── comm.state        # Comm history + channel projection
│   │   ├── comm_filters.conf # Persisted channel filter overrides, sparse map
│   │   ├── connection.state  # Runtime state written by Lua on SESSION CONNECTED
│   │   ├── version.cache     # Cached latest-release tag (6h TTL)
│   │   ├── ping.cache        # Ping ring buffer: latest, quality, 60-sample history
│   │   ├── scripts.cache     # Full script catalog (enabled + disabled) written at brain startup
│   │   ├── .layout_ready     # Sentinel: build_initial_layout.sh → wait_for_layout.sh
│   │   ├── .layout_lock      # Lockfile: prevents resize feedback loop
│   │   ├── .ping_pid         # Single-instance guard for ping_monitor.sh
│   │   ├── .popup_open       # Sentinel: in-game popup is open
│   │   ├── .collapsed_panes  # Narrow-terminal collapse state
│   │   ├── .return_to_menu   # Sentinel: return to launcher after session exits
│   │   ├── .relaunch_terminal # Sentinel: ask bridge/supervisor.sh to respawn foot
│   │   │                     #   (WSLg deployment; written by Options → Terminal Apply, ADR 0104)
│   │   ├── .launcher_resume  # One-shot resume hint consumed by the fresh launcher
│   │   │                     #   post foot-relaunch to land back on options_terminal
│   │   │                     #   with the cursor restored (ADR 0105)
│   │   └── .update_preserve/ # Preserved user files during self-update
│   ├── dev/                  # Developer fixtures (not runtime state)
│   ├── smoke.sh              # Syntax-check runner (bash/lua/python + core file checks); run with bash bridge/smoke.sh
│   ├── supervisor.sh         # Windows/WSLg entry point — owns the foot terminal
│   │                         #   lifecycle, exports MUME_TERMINAL=foot-managed,
│   │                         #   loops on .relaunch_terminal sentinel. Invoked by
│   │                         #   install/mume-cockpit.desktop. Native Linux/macOS
│   │                         #   do not use it.
│   ├── launcher.sh           # COMPAT SHIM → bridge/launcher/launcher.sh (v0.7.0, ADR 0045)
│   └── tmux_start.sh         # COMPAT SHIM → bridge/launcher/tmux_start.sh (v0.7.0, ADR 0045)
│
├── data/
│   ├── runs/             # Per-run XP/TP snapshots (one file per run)
│   ├── comm/             # Per-character comm archive JSONL files
│   ├── characters/       # Per-character subdirs: affects, stored spells, etc.
│   └── shared/           # Shared cross-session state (clock.state)
│
└── logs/
    ├── ui.log            # Persistent UI output (shown in ui pane)
    └── debug.log         # Lua debug output (shown in dev pane)
```

## Architecture Overview

```
┌──────────────────────────────────────────┐
│               MUD SERVER                 │
└─────────────────┬────────────────────────┘
                  │ telnet (mmapper) / TLS (direct)
                  ▼
┌──────────────────────────────────────────┐
│              TinTin++                    │
│  - #action triggers parse server output  │
│  - #macro keybinds for instant actions   │
│  - cp command system                     │
│  - spawns Lua via #run                   │
└──────────┬───────────────────┬───────────┘
           │ #lua handle_event │ print("tintin (gts) cmd")
           ▼                   ▼
┌──────────────────────────────────────────┐
│              Lua Brain                   │
│  - communication library (tells, says)   │
│  - spell/ability timer system            │
│  - event handlers                        │
│  - sends commands back via stdout        │
│  - writes to logs/ui.log + debug.log     │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│            tmux Cockpit                  │
│  pane 0 (top-left):  TinTin++ — game I/O │
│  pane 1 (top-right): status — status_pane.py  │
│  pane 1b (right):    buffs — buffs_pane.py    │
│  pane 1c (right):    group — group_pane.py    │
│  pane 1d (right):    comm — comm_pane.py      │
│  pane 1e (right):    ui  — ui_pane.py         │
│  pane 2 (right):     dev — tail debug.log     │
│  pane 0b (full-width bottom):             │
│                      input — prompt_toolkit│
└──────────────────────────────────────────┘
```

## Auto-Loading

### tt++ modules (`ttpp/core/`)

`main.tin` automatically loads all `.tin` files from `core/` using `#script`
without a variable argument — this causes tt++ to execute each line of shell
output as a tt++ command. Files are loaded in alphabetical order. No manual
registration in `main.tin` is needed when adding a new module.

```tintin
#script {ls ttpp/core/*.tin 2>/dev/null | sed 's/^/#read /'}
```

### Lua scripts (`lua/core/` and `lua/scripts/`)

`brain.lua` performs a two-tier load at startup via `io.popen("ls ...")` +
`dofile()`, in alphabetical order within each tier:

1. **`lua/core/`** — always-on infrastructure: GMCP collectors, serializers,
   and loaders. No alias, no metadata header. Every file is loaded
   unconditionally.
2. **`lua/scripts/`** — opt-in automation modules. Each file carries an
   `@`-tagged metadata header (`@summary`, `@alias`, `@help`) parsed
   statically by the loader; only files enabled via `scripts.conf` are
   `dofile()`'d. The loader writes the full catalog (enabled + disabled)
   to `bridge/runtime/scripts.cache` so the launcher and in-game popup
   can list every installed script. See [docs/scripts.md](docs/scripts.md)
   for the header format, conf-file resolution, and ADR 0093 for the
   rationale.

Rule for new files: if a file is always-on infrastructure with no alias and
no opt-in toggle, it belongs in `lua/core/`. If it provides a player-facing
feature the user might want to toggle, add the metadata header and drop it
in `lua/scripts/`.

Each script runs in the global environment and has access to all infrastructure
functions from `brain.lua`:

    dbg(msg)                  — write to debug.log
    ui(msg)                   — write to ui.log (mirrors to debug.log)
    ui_var(v)                 — wrap a dynamic value in highlight style for ui messages
    script_ui(name, msg)      — script lifecycle status line (▶ NAME: msg.)
    system_ui(msg)            — infrastructure event status line (● SYSTEM: msg.)
    ui_warn(msg)              — warning surfaced to the UI pane (⚠ WARN: msg.)
    ui_err(msg)               — error surfaced to the UI pane (✖ ERROR: msg.)
    tintin(ses, cmd)          — send simple command to tt++ session
    tintin_cmd(ses, cmd)      — send brace-containing command via temp file
    tintin_show(ses, msg)     — #showme in a specific session
    send(cmd)                 — send MUD command to game session
    game_cmd(cmd)             — register in gts + GAME_SESSION
    session_cmd(cmd)          — register in GAME_SESSION only
    set_game_session(ses)     — called by SESSION CONNECTED event
    clear_game_session(ses)   — called by SESSION DISCONNECTED event
    scripts                   — namespace for script public APIs
    state.char/.room/.comm    — namespace for shared game state
    gmcp                      — GMCP subsystem (handlers, dispatch, modules)

See [docs/ipc.md](docs/ipc.md) for startup ordering constraints (relay
actions must be registered before `#run {lua}`).

## Namespaces

**`scripts.<name>`** — each script's public API. Functions called from tt++
via `#lua` must live here; private helpers stay file-local.

**`state.*`** — shared game and world data: `state.char`, `state.room`,
`state.comm`, `state.world`, `state.core`, `state.run`. Populated by
GMCP collectors; field schemas documented in [docs/gmcp.md](docs/gmcp.md).
`state.run` is owned by `lua/core/run_state.lua` and tracks run XP/TP
deltas and the per-kill list. `state.world.clock` is owned by
`lua/core/clock.lua` — see [docs/clock.md](docs/clock.md) for API.

**`gmcp`** — GMCP subsystem: `gmcp.handlers`, `gmcp.modules`,
`gmcp.dispatch`, `gmcp.trace`. Dispatch model: one primary writer per module
owns `gmcp.handlers[module]` and writes `state.*`; `gmcp.dispatch` always
emits `gmcp_<module_snake>` after the primary writer so downstream code uses
`events.subscribe` instead of handler wraps. See [docs/gmcp.md](docs/gmcp.md)
for subscription, dispatch, and scripting patterns.

**`events`** — Lua event bus: `events.handlers`, `events.subscribe`,
`events.unsubscribe`, `events.emit`, `events.trace`. See
[docs/events.md](docs/events.md) for the event catalogue and adding new
events.

## Communication Protocol

TinTin++ communicates with Lua via two IPC patterns. **Pattern 1** (shared
dispatch): permanent tt++ triggers send structured events to brain.lua's stdin
in the form `TYPE:arg1:arg2:...`; scripts register handlers in the shared
`handlers` table. **Pattern 2** (script-owned): scripts register their own
aliases and triggers directly via `tintin_cmd()` at load time and call their
own public functions from tt++.

Lua communicates back to tt++ via two mechanisms: `tintin()` for simple
commands without braces, and `tintin_cmd()` (file-based) for commands
containing `{}`.

Scripts must never hardcode session names. Use the wrapper functions
(`game_cmd`, `session_cmd`, `send`) which resolve the current game session
automatically.

See [docs/ipc.md](docs/ipc.md) for the full IPC contract, relay action
registration, startup ordering, and brace-handling details.

## Registration Functions

Scripts must never hardcode a session name. Use these functions:

| Function | Registers in | Use for |
|----------|-------------|---------|
| `game_cmd(cmd)` | gts + GAME_SESSION | `#alias`, `#substitute`, `#highlight` |
| `session_cmd(cmd)` | GAME_SESSION only | `#action`, `#unaction`, `#delay`, `#undelay` |
| `send(cmd)` | GAME_SESSION | MUD commands |
| `tintin_cmd(ses, cmd)` | specific session | internal use only |
| `tintin(ses, cmd)` | specific session | internal use only, no braces |

Registrations made via `game_cmd()` / `session_cmd()` are placed in the permanent
`{core}` class, separate from the user's profile class (`{<profile>}`). The profile
class contains only what is loaded from `ttpp/profiles/<profile>.tin` plus any
runtime user-typed additions. `cp -s` only serializes the profile class, so script
registrations never leak into saved profiles.

## Lua Namespace Conventions

**Global (always accessible, no prefix):** short-name hot-path utilities
(`dbg`, `ui`, `ui_var`, `script_ui`, `system_ui`, `ui_warn`, `ui_err`,
`tintin`, `tintin_cmd`, `tintin_show`, `send`, `game_cmd`, `session_cmd`),
session identity (`GAME_SESSION`, `set_game_session`, `clear_game_session`),
and the tt++/Lua contract surface (`handle_event`). These stay global because
they are called from everywhere and short names reduce noise.

**`scripts.<name>.<fn>`** — the script's public API. Any function called from
tt++ via `#lua` must live here. Private helpers remain in file-local `local`
scope.

**`state.*`** — shared game and world data. Each sub-namespace has a defined owner:

- `state.char` — populated by `lua/core/char_state.lua` from `Char.Name` / `StatusVars` / `Vitals`; extended by `lua/core/affects.lua` (`affects`, `affect_times`), `lua/core/stored_spells.lua` (`stored_spells`, `stored_spell_times`), and `lua/core/blinds.lua` (`blinds` — session-only); `wimpy` field set by `lua/core/wimpy.lua`. Reset function defined by `char_state.lua`.
- `state.room` — currently unused; reserved.
- `state.comm` — owned by `lua/core/comm_log.lua` (`history`, `channels`, `max_size`). `lua/core/comm_state.lua` adds the `serialize()` entry point.
- `state.world` — owned by `lua/core/world_state.lua` (`sun`, `moon`, `moved`, `darkness`) and `lua/core/clock.lua` (`state.world.clock`).
- `state.run` — owned by `lua/core/run_state.lua`; tracks per-run XP/TP deltas, kill list, baselines.
- `state.core` — owned by `lua/core/core_state.lua`; `Core.Goodbye` / `Core.Ping`.

**Private state** continues to live in `local` file-scope tables (e.g. `local as`
in autostab, `local ab` in autobow).

```lua
-- Script module pattern
local M = {}
scripts.myscript = M

local function helper() ... end       -- private

function M.start(args) ... end        -- public

game_cmd('#alias {...} {#lua {scripts.myscript.start(...)}}')
```

## Design Principles

1. **tt++ handles reflexes** — triggers and keybinds execute with
   minimal overhead. No Lua involvement for latency-critical actions.
2. **Lua handles cognition** — state tracking, spell timers, comms,
   and complex logic that is not timing-critical.
3. **No polling** — Lua communicates via `#run` stdout/stdin,
   not via polling loops or file watchers.
4. **Persistent UI** — output written to log files so history
   survives pane toggles and restarts.
5. **Single source of truth** — Lua owns all game state.
6. **Self-contained Lua modules** — every file in `lua/core/` and
   `lua/scripts/` is a single `.lua` file with no paired `.tin` file.
   `lua/core/` files are always-on infrastructure: no alias, no metadata
   header.
   `lua/scripts/` files are opt-in automation: they declare themselves
   via an `@`-tagged metadata header (parsed without execution by the
   loader) and register their own aliases via `game_cmd()`, triggers
   via `session_cmd()`, and MUD commands via `send()` at load time.
   Never hardcode session names in either tier. See
   [docs/scripts.md](docs/scripts.md).
7. **Anchored core actions** — every `#action` registered from
   `ttpp/core/*.tin` or `lua/core/*.lua` that matches a single complete
   server-emitted line uses `^...$`. Anchoring blocks false triggers
   from tells, says, narrates, and social emotes that quote the same
   line. Exceptions (intentional fragments) must be commented inline
   at the registration site.

## Cockpit System

Unified window and system management via `cp` commands:

| Command       | Action                          |
|---------------|---------------------------------|
| `cp`          | Show help                       |
| `cp -c`       | Toggle status pane              |
| `cp -b`       | Toggle buffs pane               |
| `cp -g`       | Toggle group pane               |
| `cp -m`       | Toggle comm pane                |
| `cp -u`       | Toggle UI pane                  |
| `cp -d`       | Toggle dev pane                 |
| `cp -h`       | Toggle pane title headers       |
| `cp -s`       | Save profile to disk            |
| `cp -e`       | Full shutdown                   |
| `cp -<alias>` | Show help for installed script  |

The `cp` help box is dynamically generated by Lua after all scripts load,
so the Scripts section always reflects enabled scripts. Each script
declares itself via the `@`-tagged metadata header at the top of its file
(see [docs/scripts.md](docs/scripts.md)) — no changes to core needed.

See [docs/popup-menu.md](docs/popup-menu.md) for Options/Scripts submenu
implementations, `cp -s` internals, and toggle-pane persistence details.

## Current Work

See the project board on GitHub for active work and parked ideas. The
cross-character Spotlights feature (launcher main menu → Spotlights,
ADR 0077–0080) is complete: rotation/per-event windows, scroll-clear
transitions, pre-roll trim, and the end-of-reel scrolling credits all
shipped.

The launcher's profile editor is GUI-complete for all five tt++
command kinds (aliases, actions, macros, highlights, substitutes):
five-tab navigation, per-kind detail panels, click + keyboard editing,
the key-capture overlay for macros, and a round-trip parser /
serializer that preserves unknown commands and entry priorities
byte-exact. The code-editor (Editor) mode is also feature-complete:
LITE↔EDITOR toggle for direct `.tin`-text editing, syntax highlight
+ matching-brace highlight + balance indicator (ADR 0089), shift-
arrow selection + clipboard with OSC 52 system-clipboard write
(ADR 0090), snapshot-based undo / redo with typing coalescing
(ADR 0091), Alt+↑/↓ line move, an always-on `Ln/Col` footer
indicator, double/triple-click word and line selection,
mouse-wheel scrolling on all three scrollables, and click-and-hold
auto-scroll on the three editor scrollbars (ADR 0092). The in-game popup's Profile row opens the same editor over the live
tt++ profile class via a snapshot/apply handshake (ADR 0110); the
disconnected path reads/writes disk directly (launcher-style). See
[ADR 0082](docs/decisions/0082-macro-keys-duplicates-input-pane.md)
for the deferred unification of `bridge/launcher/macro_keys.py` and
`bridge/panes/input_pane.py`.

The menu visual pass is complete. The launcher and the in-game popup
now share one chrome grammar — `menu_chrome.title_block` /
`footer_block` for frame chrome and `menu_chrome.menu_row` for `<<
label >>` selectable rows, with the three-state `button_fragment`
grammar for filled-button cells (ADR 0085). The popup's `main`,
`options`, and `scripts` frames join `panes` as single
`FormattedTextControl` Windows with footer anchored to the popup's
final row; the modal `exit_confirm` / `rate_session` dialogs adopt
`C_SECTION` for the title row to match. The main-page logo is now
the shared animated starfield + wordmark banner rendered via
`bridge/launcher/launcher_banner.py` (one source for both
prompt_toolkit surfaces — the launcher main page and the in-game
popup's `main` frame; ADR 0100). The tt++ welcome screen deliberately
does **not** share that module: it keeps its own hardcoded `#showme`
lines and prints a static, starless wordmark only.

The Windows deployment runs on **foot under WSLg** and is fully
shipped. `bridge/supervisor.sh` owns the foot lifecycle and loops on
the `bridge/runtime/.relaunch_terminal` sentinel; `install/mume-cockpit.desktop`
is the WSLg `.desktop` entry the Windows Start Menu surfaces; the
Windows installer drops `install/examples/foot.ini` into WSL and
provisions a small set of monospace fonts; the supervisor exports
`MUME_TERMINAL=foot-managed` so the launcher can gate the Terminal
Settings entry. Options → Terminal is a complete settings page (font,
size, window mode and size, padding, transparency, background, cursor
style and blink) backed by `bridge/launcher/foot_config.py`, a
managed-keys read/modify/write over `~/.config/foot/foot.ini` that
preserves every unmanaged line verbatim. Apply writes the file, drops
the relaunch sentinel and a one-shot `bridge/runtime/.launcher_resume`
hint, then exits so the supervisor relaunches foot with the new
config and the fresh launcher restores the user's cursor. If a user
picks `windowed` with a font large enough to drop the cockpit below
the minimum-size gate, the gate itself binds R/Shift+R to a
self-healing reset that rewrites only the window mode and font size
back to safe defaults and reuses the same relaunch tail — the escape
hatch lives where the user is stuck. See
[ADR 0103](docs/decisions/0103-windows-flicker-terminal.md) for the
flicker investigation that drove the move off Windows-Alacritty,
[ADR 0104](docs/decisions/0104-windows-deployment-foot-wslg.md) for
the deployment shape, and
[ADR 0107](docs/decisions/0107-terminal-settings-managed-keys.md) for
the managed-keys foot.ini contract and the user-selectable window
mode.

## See also

- [docs/ui-messaging.md](docs/ui-messaging.md) — UI helpers, colour constants, and style rules. Touched when writing almost any script.
- [docs/gmcp.md](docs/gmcp.md) — GMCP module reference, schemas, negotiation. Touched when adding a GMCP collector or subscribing to a new module.
- [docs/events.md](docs/events.md) — Event bus API and catalogue. Touched when adding a core MUD trigger or subscribing a script to a Lua-side event.
- [docs/ipc.md](docs/ipc.md) — tt++ ↔ Lua IPC contract, relay actions, startup ordering. Touched when changing how tt++ and Lua communicate.
- [docs/scripts.md](docs/scripts.md) — Scripting guide for `lua/scripts/`: metadata header format, enable/disable via `scripts.conf`, `scripts.cache` schema, infrastructure surface available to a script. Touched when changing the script contract or adding a new opt-in module.
- [docs/session-lifecycle.md](docs/session-lifecycle.md) — Session connect/disconnect, connection.state, settings persistence. Touched when changing session handling or startup flow.
- [docs/input-pane.md](docs/input-pane.md) — Input pane key forwarding, Enter semantics, history navigation, clock strip. Touched when changing input behaviour, forwarded keys, or the clock strip.
- [docs/tmux-bindings.md](docs/tmux-bindings.md) — tmux root-table bindings, mouse model, clipboard. Touched when changing tmux key bindings or mouse behaviour.
- [docs/launcher.md](docs/launcher.md) — Pre-tmux startup menu, rendering conventions, exec-chain. Touched when changing launcher pages or startup options. The [Spotlights sub-menu](docs/launcher.md#spotlights-sub-menu) section covers the cross-character highlights reel; see [ADR 0077](docs/decisions/0077-spotlight-reel-scope-rotation-per-event.md) (scope/rotation/per-event), [ADR 0078](docs/decisions/0078-spotlight-scroll-clear-via-phantom-rows.md) (scroll-clear transitions), [ADR 0079](docs/decisions/0079-spotlight-pre-roll-trim-post-roll-unclamped.md) (pre-roll trim, unclamped post-roll), and [ADR 0080](docs/decisions/0080-end-of-reel-credits.md) (end-of-reel scrolling credits).
- [docs/popup-menu.md](docs/popup-menu.md) — In-game ESC popup: submenus, status header, save-profile flow. Touched when changing the in-game overlay.
- [docs/bridge-services.md](docs/bridge-services.md) — Ping monitor, version check, self-update, layout and config file formats. Touched when changing background services or persisted config.
- [docs/release-process.md](docs/release-process.md) — Release runbook: version bump, tagging, GitHub release. Touched when changing the release process.
- [docs/comm-pane.md](docs/comm-pane.md) — Communication pane: renderer, comm.state schema, filter persistence, scroll semantics, width-responsive header layout. Touched when changing the comm pane.
- [docs/status-pane.md](docs/status-pane.md) — Character status pane: renderer, state-file schema, field layout, colour scheme, layout integration. Touched when changing the status pane.
- [docs/clock.md](docs/clock.md) — Game clock: sync sources, state schema, persistence, seed handling, degradation rules. Touched when changing clock sync or consuming game time.
- [docs/affects.md](docs/affects.md) — Affect tracker: data flow, state schemas, persistence, pattern-conversion rules, tick lifecycle. Touched when changing affect tracking or adding new affect entries.
- [docs/stored-spells.md](docs/stored-spells.md) — Stored spells tracker: data flow, schemas, spell-name resolver, persistence, SENT OUTPUT snooping. Touched when changing stored-spell tracking or the spells data table.
- [docs/blinds.md](docs/blinds.md) — Blinds tracker: 90 s fixed-duration timers, two-layer (inbound landing + outgoing cast snoop FIFO), failure-pattern queue cleanup. Touched when changing blind tracking or the cast-snoop heuristics.
- [docs/readability.md](docs/readability.md) — Readability modules: drop-in `.tin` loader, `.meta` format spec, startup.conf toggle, cold/hot reload lifecycle. Touched when adding a module, changing the loader contract, or modifying the `.meta` format.
- [docs/runs.md](docs/runs.md) — Run log contract: file layout, event schema (run_start/level_up/run_end), lifecycle, schema versioning. Touched when changing run-log behaviour or adding new row types.
- [docs/buffs-pane.md](docs/buffs-pane.md) — Buffs pane: renderer, scroll, blink, layout integration. Touched when changing the buffs pane renderer or the buffs.state schema.
- [docs/group-pane.md](docs/group-pane.md) — Group pane: renderer, state-file schema, bar fill, threshold colours, name overlay, overflow indicator. Touched when changing the group pane renderer or the group.state schema.
- [docs/ui-pane.md](docs/ui-pane.md) — UI pane: renderer, scroll, log-tail mechanics. Touched when changing the UI pane.
- [docs/install-bootstrap.md](docs/install-bootstrap.md) — Cross-platform install: macOS/Linux bootstrap scripts and the Windows foot/WSLg installer. Touched when changing installation or the bootstrap/installer scripts.
