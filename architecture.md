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
│   │                     #   comm.tin    — comm_toggle alias (calls state.comm.toggle)
│   │                     #   config.tin  — reads startup.conf → _profile/_host/_port/_ses_cmd
│   │                     #   gmcp.tin    — GMCP telnet negotiation and Lua dispatch
│   │                     #   system.tin  — connection aliases, cp commands, session events
│   │                     #   welcome.tin — clean boot banner + auto-connect
│   └── sessions/         # Per-profile personal settings (.tin files)
│
├── lua/
│   ├── brain.lua         # Lua brain — infrastructure, event loop, auto-loads core/ then scripts/
│   ├── lib/              # Bundled Lua libraries (on package.path)
│   │                     #   dkjson.lua  — pure-Lua JSON parser (MIT, David Kolf)
│   ├── core/             # Always-on GMCP collectors — no alias, no register_script
│   │                     #   comm_log.lua   — Comm.Channel.Text/List → state.comm history/channels
│   │                     #   comm_state.lua — wraps comm_log handlers; owns state.comm.filters;
│   │                     #                   serialises to bridge/comm.state
│   └── scripts/          # Opt-in automation modules — must call register_script(meta)
│
├── bridge/
│   ├── launcher.sh           # Pre-tmux startup menu (DOS-style, pure bash)
│   ├── menu_render.sh        # Render/input helpers sourced by launcher.sh
│   ├── tmux_start.sh         # tmux session creation (extracted from start.sh)
│   ├── toggle_pane.sh        # Toggle ui/dev/input panes and pane headers
│   │                         #   (called by cp aliases and in-game popup)
│   ├── version_check.sh      # Queries GitHub for latest tag; updates
│   │                         #   bridge/version.cache with 6h TTL
│   ├── read_config.sh        # Emits tt++ #var assignments from startup.conf
│   ├── quotes.txt            # Tolkien quotes shown on main menu (pipe-sep format)
│   ├── about.txt             # About page body text
│   └── scripts.cache         # Script registry written by brain.lua (gitignored)
│   ├── open_pane.sh          # Opens/manages tmux panes dynamically
│   ├── input_pane.py         # Input pane — prompt_toolkit CLI, forwards to TT++
│   ├── comm_pane.py          # Comm pane — clickable channel-filter header + scrollable history
│   ├── status_pane.py        # Status pane — flicker-free ANSI renderer, polls status.state
│   ├── focus_input.sh        # Resolves input pane index at click time (MouseUp1Pane target)
│   ├── on_window_resize.sh   # Fired on terminal resize — re-applies stored layout
│   ├── on_pane_resize.sh     # Fired on border drag — saves new layout values
│   ├── ping_monitor.sh       # Session-scoped background ping monitor
│   │                         #   (spawned by tmux_start.sh + launcher.sh; self-terminates)
│   ├── ping.cache            # Ping ring buffer: latest, quality, 60-sample history (gitignored)
│   ├── layout.conf           # Persisted layout state (gitignored)
│   │                         #   keys: ui_width, window_cols, ui_height, comm_height, status_height
│   ├── session.state         # Runtime state written by Lua on SESSION
│   │                         #   CONNECTED; cleared on DISCONNECTED and
│   │                         #   at brain startup (gitignored)
│   ├── comm.state            # Comm history + channel + filter projection (gitignored)
│   ├── comm_filters.conf     # Persisted channel filter overrides, sparse map (gitignored)
│   ├── status.state          # Character status JSON written by status_state.lua (gitignored)
│   ├── version.cache         # Cached latest-release tag (gitignored)
│   └── startup.conf          # Persisted startup-menu state (gitignored)
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
│  pane 0 (left):   TinTin++ — game I/O    │
│  pane 0b (bot):   input — prompt_toolkit  │
│  pane 1 (top):    ui  — tail ui.log       │
│  pane 1b (mid):   comm — comm_pane.py     │
│  pane 1c (mid):   status — status_pane.py │
│  pane 2 (bot):    dev — tail debug.log    │
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

1. **`lua/core/`** — always-on GMCP collectors. These have no alias and never
   call `register_script()`. They populate `state.*` fields that other code
   may read at load time.
2. **`lua/scripts/`** — opt-in automation modules. Each must call
   `register_script(meta)` so it appears in `cp` help and the launcher's
   Scripts page.

Rule for new files: if a file has no alias and only listens to GMCP to write
`state.*`, it belongs in `lua/core/`. If it provides a player-facing feature
and calls `register_script()`, it belongs in `lua/scripts/`.

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
    register_script(meta)     — register script in cockpit help system
    scripts                   — namespace for script public APIs
    state.char/.room/.comm    — namespace for shared game state
    gmcp                      — GMCP subsystem (handlers, dispatch, modules)

See [docs/ipc.md](docs/ipc.md) for startup ordering constraints (relay
actions must be registered before `#run {lua}`).

## Namespaces

**`scripts.<name>`** — each script's public API. Functions called from tt++
via `#lua` must live here; private helpers stay file-local.

**`state.*`** — shared game and world data: `state.char`, `state.room`,
`state.comm`, `state.world`, `state.core`, `state.session`. Populated by
GMCP collectors; field schemas documented in [docs/gmcp.md](docs/gmcp.md).
`state.session` is owned by `lua/core/sess_kills.lua` and tracks session
XP/TP deltas and the per-kill list. `state.world.clock` is owned by
`lua/core/clock.lua` — see [docs/clock.md](docs/clock.md) for API.

**`gmcp`** — GMCP subsystem: `gmcp.handlers`, `gmcp.modules`,
`gmcp.dispatch`, `gmcp.trace`. See [docs/gmcp.md](docs/gmcp.md) for
subscription, dispatch, and scripting patterns.

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

## Lua Namespace Conventions

**Global (always accessible, no prefix):** short-name hot-path utilities
(`dbg`, `ui`, `ui_var`, `script_ui`, `system_ui`, `ui_warn`, `ui_err`,
`tintin`, `tintin_cmd`, `tintin_show`, `send`, `game_cmd`, `session_cmd`),
session identity (`GAME_SESSION`, `set_game_session`, `clear_game_session`),
and the tt++/Lua contract surface (`handle_event`, `register_script`).
These stay global because they are called from everywhere and short names
reduce noise.

**`scripts.<name>.<fn>`** — the script's public API. Any function called from
tt++ via `#lua` must live here. Private helpers remain in file-local `local`
scope.

**`state.*`** — reserved for shared game/world data. `state.char`,
`state.room`, and `state.comm` are empty tables in this iteration; populated
when GMCP lands.

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
   `lua/core/` files are always-on collectors: no alias, no
   `register_script()`, only GMCP handlers that write `state.*`.
   `lua/scripts/` files are opt-in automation: they register their own
   aliases via `game_cmd()`, triggers via `session_cmd()`, and MUD
   commands via `send()` at load time, and call `register_script(meta)`.
   Never hardcode session names in either tier.

## Cockpit System

Unified window and system management via `cp` commands:

| Command       | Action                          |
|---------------|---------------------------------|
| `cp`          | Show help                       |
| `cp -i`       | Toggle input pane               |
| `cp -u`       | Toggle UI pane                  |
| `cp -m`       | Toggle comm pane                |
| `cp -c`       | Toggle status pane              |
| `cp -d`       | Toggle dev pane                 |
| `cp -h`       | Toggle pane title headers       |
| `cp -s`       | Save profile to disk            |
| `cp -r`       | Full reload                     |
| `cp -e`       | Full shutdown                   |
| `cp -<alias>` | Show help for installed script  |

The `cp` help box is dynamically generated by Lua after all scripts load,
so the Scripts section always reflects installed scripts. Each script
registers itself via `register_script(meta)` — no changes to core needed.

See [docs/popup-menu.md](docs/popup-menu.md) for Options/Scripts submenu
implementations, `cp -s` internals, and toggle-pane persistence details.

## Current Work

Active work and pending features. Completed infrastructure is not listed
here — it's described in the relevant `docs/*.md` and visible in the
"See also" block at the bottom.

- [ ] GMCP disconnect flow (Core.Goodbye + SESSION DISCONNECTED →
      popup with mode-aware reconnect)
- [ ] Live-server connection and real-server trigger mapping
- [ ] Spell timer system
- [ ] Affect tracker
- [ ] Tells history UI
- [ ] PvP keybinds finalized

## Parked

Deferred until there's a concrete use case:

- Reset-layout-to-defaults option in launcher Options
- Live script dashboard (IDLE / RUNNING / FIRING tags)
- Stop-all-scripts emergency button
- Pane dimming for inactive panes
- Cross-platform one-click installer (Windows WSL2 + Alacritty bootstrap, macOS/Linux helper scripts) — see `docs/install-bootstrap.md`.

## See also

- [docs/ui-messaging.md](docs/ui-messaging.md) — UI helpers, colour constants, and style rules. Touched when writing almost any script.
- [docs/gmcp.md](docs/gmcp.md) — GMCP module reference, schemas, negotiation. Touched when adding a GMCP collector or subscribing to a new module.
- [docs/events.md](docs/events.md) — Event bus API and catalogue. Touched when adding a core MUD trigger or subscribing a script to a Lua-side event.
- [docs/ipc.md](docs/ipc.md) — tt++ ↔ Lua IPC contract, relay actions, startup ordering. Touched when changing how tt++ and Lua communicate.
- [docs/session-lifecycle.md](docs/session-lifecycle.md) — Session connect/disconnect, session.state, cp -r, settings persistence. Touched when changing session handling or startup flow.
- [docs/input-pane.md](docs/input-pane.md) — Input pane key forwarding, Enter semantics, history navigation. Touched when changing input behaviour or adding new forwarded keys.
- [docs/launcher.md](docs/launcher.md) — Pre-tmux startup menu, rendering conventions, exec-chain. Touched when changing launcher pages or startup options.
- [docs/popup-menu.md](docs/popup-menu.md) — In-game ESC popup: submenus, status header, save-profile flow. Touched when changing the in-game overlay.
- [docs/bridge-services.md](docs/bridge-services.md) — Ping monitor, version check, self-update, layout and config file formats. Touched when changing background services or persisted config.
- [docs/comm-pane.md](docs/comm-pane.md) — Communication pane: renderer, comm.state schema, filter persistence, scroll semantics, label-collision policy. Touched when changing the comm pane.
- [docs/status-pane.md](docs/status-pane.md) — Character Status pane: renderer, state-file schema, field layout, colour scheme, layout integration, phase 2–4 extension points. Touched when changing the status pane.
- [docs/clock.md](docs/clock.md) — Game clock: sync sources, state schema, persistence, seed handling, degradation rules. Touched when changing clock sync or consuming game time.
- [docs/install-bootstrap.md](docs/install-bootstrap.md) — Cross-platform install and bootstrap plan. Touched when scheduling installer work or when a platform constraint (WSL, Alacritty, package versions) changes.
