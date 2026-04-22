# MUD Client Architecture

## Purpose
A fast, terminal-based MUD client with a clean separation between
real-time I/O and scripting logic. Designed for performance and
extensibility — minimal latency for input/output, with Lua handling
advanced automation, state tracking, and UI feedback.

## Stack
| Component | Role                                        |
|-----------|---------------------------------------------|
| TinTin++  | Core client — triggers, keybinds, I/O       |
| Lua       | Brain — logic, state, timers, comms         |
| tmux      | Window orchestration                        |

## Project Structure
~/MUME/
├── start.sh              # Entry point — starts entire system
├── VERSION               # Semantic version string (read by launcher)
├── architecture.md       # This file
├── ttpp_manual.txt       # TinTin++ reference manual
│
├── ttpp/
│   ├── main.tin          # tt++ entry point — auto-loads all of core/
│   ├── core/             # System modules (.tin files), auto-loaded
│   │                     #   config.tin  — reads startup.conf → _profile/_host/_port/_ses_cmd
│   │                     #   gmcp.tin    — GMCP telnet negotiation and Lua dispatch
│   │                     #   system.tin  — connection aliases, cp commands, session events
│   │                     #   welcome.tin — clean boot banner + auto-connect
│   └── sessions/         # Per-profile personal settings (.tin files)
│
├── lua/
│   ├── brain.lua         # Lua brain — infrastructure, event loop, auto-loads scripts/
│   ├── lib/              # Bundled Lua libraries (on package.path)
│   │                     #   dkjson.lua  — pure-Lua JSON parser (MIT, David Kolf)
│   └── scripts/          # Self-contained Lua automation scripts (.lua files)
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
│   ├── focus_input.sh        # Resolves input pane index at click time (MouseUp1Pane target)
│   ├── on_window_resize.sh   # Fired on terminal resize — re-applies stored layout
│   ├── on_pane_resize.sh     # Fired on border drag — saves new layout values
│   ├── ping_monitor.sh       # Session-scoped background ping monitor
│   │                         #   (spawned by tmux_start.sh + launcher.sh; self-terminates)
│   ├── ping.cache            # Ping ring buffer: latest, quality, 60-sample history (gitignored)
│   ├── layout.conf           # Persisted layout state (gitignored)
│   ├── session.state         # Runtime state written by Lua on SESSION
│   │                         #   CONNECTED; cleared on DISCONNECTED and
│   │                         #   at brain startup (gitignored)
│   ├── version.cache         # Cached latest-release tag (gitignored)
│   └── startup.conf          # Persisted startup-menu state (gitignored)
│
└── logs/
    ├── ui.log            # Persistent UI output (shown in ui pane)
    └── debug.log         # Lua debug output (shown in dev pane)

## Architecture Overview
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
│  pane 0 (left):   TinTin++ — game I/O   │
│  pane 0b (bot):   input — prompt_toolkit │
│  pane 1 (top):    ui  — tail ui.log      │
│  pane 2 (bot):    dev — tail debug.log   │
└──────────────────────────────────────────┘

## Auto-Loading

### tt++ modules (`ttpp/core/`)
`main.tin` automatically loads all `.tin` files from `core/` using `#script`
without a variable argument — this causes tt++ to execute each line of shell
output as a tt++ command. Files are loaded in alphabetical order. No manual
registration in `main.tin` is needed when adding a new module.

```tintin
#script {ls ttpp/core/*.tin 2>/dev/null | sed 's/^/#read /'}
```

### Lua scripts (`lua/scripts/`)
`brain.lua` automatically loads all `.lua` files from `lua/scripts/` via
`io.popen("ls ...")` + `dofile()` at startup. Each script runs in the global environment and has access to all infrastructure
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

### Startup order in `main.tin`
Relay actions that catch Lua stdout **must be registered before `#run {lua}`**.
Lua begins executing scripts immediately on startup and emits output before
`main.tin` finishes — if the actions aren't in place, that output is lost.

```tintin
#action {tintin (%1) %2}      {#%1 %2}      -- registered first
#action {tintin_read %1}      {#read %1}    -- registered first
#run {lua} {lua lua/brain.lua}              -- Lua starts after
```

**Startup order in `brain.lua`.** The brain logs its own start via `dbg()` before calling `load_scripts()`, and emits an `N scripts loaded.` summary via `dbg()` after. Both are dev-pane-only — the UI pane stays clean of plumbing events and shows only user-relevant state transitions (game session connect/disconnect, etc.).

## Communication Protocol

### tt++ → Lua: two patterns

The Lua brain runs as an external subprocess named `lua`
(`#run {lua} {lua lua/brain.lua}`). brain.lua's main loop reads from stdin
and dispatches each line to `handle_event`.

**IPC mechanism — `#lua` as session reference**

`#lua` addresses the session named `lua` created by `#run`. In a `#run`
session, any text that is not a tt++ command is forwarded to the subprocess
stdin. `brain.lua`'s main loop reads this via `io.lines()`.

`#{session} {text}` executes `text` as a tt++ command in that session.
For the `lua` `#run` session: function-call syntax like
`autostab_start("w", "troll")` is not a tt++ command, so tt++ passes it
directly to brain.lua's stdin. `handle_event` then dispatches it.

```tintin
#lua {autostab_start("w", "$target")}   -- sends to brain.lua stdin
#lua {TELL:Aragorn:hello}               -- same path, structured event
```

**Pattern 1 — Shared event dispatch** (for MUD server output)

Permanent triggers in tt++ parse server output and send structured events to
`brain.lua` via `handle_event`. Scripts register handlers into the shared
`handlers` table at load time — no changes to `brain.lua` needed:

```tintin
-- triggers.tin
#action {%1 tells you '%2'} {#lua {TELL:%1:%2}}
```
```lua
-- lua/scripts/comms.lua
handlers["TELL"] = function(parts)
    local from, msg = parts[1], parts[2]
    -- ...
end
```

Event format: `TYPE:arg1:arg2:...`

Event types are defined as features are built. Each type maps to a handler
registered by the relevant script. Unknown types are logged to dev.

**Pattern 2 — Script-owned aliases and triggers**

Scripts register their own aliases and triggers directly via `tintin_cmd()` at
load time, and call their own public functions from tt++. These scripts are
fully self-contained and have no involvement with `handle_event`:

```lua
-- lua/scripts/autostab.lua (at load time)
-- Alias in gts + GAME_SESSION — available immediately, works after connect
game_cmd('#alias {as%1} {#lua {autostab_start("%1", "$target")}}')
-- Actions registered dynamically when autostab activates
session_cmd("#action {You successfully escaped the fight!} {#lua {autostab_on_success()}}")
```

Triggers may be permanent or managed dynamically (registered on activation,
unregistered on deactivation). Dynamic lifecycle keeps the action list clean
and avoids stale triggers firing outside their intended context.

### Lua → tt++
Two mechanisms, depending on whether the command contains braces:

**`tintin_cmd(ses, cmd)`** — for TT++ commands that contain `{}` (actions, aliases, delays):
Writes `#ses cmd` to a unique `logs/cmd_N.tin` file, prints `tintin_read <path>`.
TT++ reads the file via `#read` and the `#ses` prefix dispatches to the target session.
Braces in the file are never passed through wildcard substitution — they survive intact.
Unique filenames prevent race conditions when multiple calls happen in rapid succession.

```lua
tintin_cmd("gts",  "#alias {name} {body}")  -- registers alias in gts
session_cmd("#action {pat} {body}")          -- registers trigger in GAME_SESSION
session_cmd("#delay {name} {cmd} {seconds}") -- delay in GAME_SESSION
```
```tintin
#action {tintin_read %1} {#read %1}
```

**Wrapper functions (preferred):**
Scripts should never call `tintin_cmd` with a session name directly.
Use the wrapper functions instead:
- `game_cmd(cmd)` — registers in gts + GAME_SESSION (`#alias`,
  `#substitute`, `#highlight`)
- `session_cmd(cmd)` — registers in GAME_SESSION only (`#action`,
  `#unaction`, `#delay`, `#undelay`)
- `send(cmd)` — sends MUD commands to GAME_SESSION

Direct `tintin_cmd(ses, cmd)` and `tintin(ses, cmd)` calls are for
infrastructure internals only (e.g. `set_game_session`,
`clear_game_session`).

| Function | Registers in | Use for |
|----------|-------------|---------|
| `tintin(ses, cmd)` | specific session | simple commands without braces |
| `tintin_cmd(ses, cmd)` | specific session | commands containing braces |
| `tintin_show(ses, msg)` | specific session | `#showme` in a session |
| `game_cmd(cmd)` | gts + GAME_SESSION | `#alias`, `#substitute`, `#highlight` |
| `session_cmd(cmd)` | GAME_SESSION only | `#action`, `#unaction`, `#delay`, `#undelay` |
| `send(cmd)` | GAME_SESSION | sending commands to the MUD server |

**`tintin_show(ses, msg)`** — for `#showme` display (messages rarely contain braces):
```lua
tintin_show(GAME_SESSION, "some message")
```
```tintin
#action {tintin_show (%1) %2} {#%1 #showme %2}
```

### Lua → UI pane
Lua appends to `logs/ui.log` — persists across pane toggles:
```lua
ui_log_fh:write(msg .. "\n")
```

### Lua → Dev pane
Timestamped debug output to `logs/debug.log`:
```lua
debug_fh:write(os.date("[%H:%M:%S] ") .. msg .. "\n")
```

## Session Management

The client uses three tt++ sessions:

| Session | Role |
|---------|------|
| `gts`   | Global — always exists, entry point, alias pool |
| `lua`   | Lua subprocess — created by `#run`, never interacted with directly |
| game    | Active game connection — name is dynamic, default `default` |

### Dynamic game session tracking

The game session name is never hardcoded. It is tracked in two
places kept in sync:

- `GAME_SESSION` — Lua global, nil when no game session is active
- `$game_session` — tt++ variable in gts, unset when no session active

Both are set when SESSION CONNECTED fires for a non-internal session,
and cleared on SESSION DISCONNECTED.

**SESSION CONNECTED** filters out `gts` and `lua`, then:
- If `&game_session` is set: zaps the new session immediately
  (only one game session allowed) and shows a warning
- Otherwise: calls `set_game_session()` which sets both
  `GAME_SESSION` and `$game_session`

**SESSION DISCONNECTED** filters out `gts` and `lua`, then:
- If `$_zapping_intruder` flag is set: intruder zap —
  clear flag, show message, return to game session
- Otherwise: real disconnect — return to gts, call
  `clear_game_session()` which clears both via `#unvar`

**Critical:** `clear_game_session()` uses `tintin()` not
`tintin_cmd()` — using `tintin_cmd()` inside SESSION DISCONNECTED
interferes with socket cleanup and prevents MMapper from releasing
the connection.

### Runtime session state (`bridge/session.state`)

Lua writes this plain key=value file at the end of `set_game_session()`,
clears it inside `clear_game_session()` (matched session only), and
clears it unconditionally at brain startup as belt-and-braces recovery
from crashes or `cp -r`.

Format:
    connected_at=<epoch seconds>
    connection_mode=<mmapper|direct>

Written atomically via temp-file + rename; readers must treat missing
or malformed values as "Disconnected" and never block.

Consumer: `bridge/ingame_menu.sh` reads this file on every popup render
to drive the status header (connected vs disconnected). The Link fragment
is served from `bridge/ping.cache`, independent of session state.

**Known limitation:** `cp -r` clears and re-writes the file, so uptime
resets to 0 after a reload. Accepted.

### Registration functions

Scripts must never hardcode a session name. Use these functions:

| Function | Registers in | Use for |
|----------|-------------|---------|
| `game_cmd(cmd)` | gts + GAME_SESSION | `#alias`, `#substitute`, `#highlight` |
| `session_cmd(cmd)` | GAME_SESSION only | `#action`, `#unaction`, `#delay`, `#undelay` |
| `send(cmd)` | GAME_SESSION | MUD commands |
| `tintin_cmd(ses, cmd)` | specific session | internal use only |
| `tintin(ses, cmd)` | specific session | internal use only, no braces |

### Lua Namespace Conventions

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

### cp -r behaviour

- Always runs in gts context
- Kills all tt++ state (alias, action, substitute, highlight,
  macro, delay, event) and restarts Lua
- Re-syncs GAME_SESSION after reload via `set_game_session()`
  since SESSION CONNECTED does not fire for already-connected sessions
- After reload: always returns to game session via 1-second delay
  if one exists, otherwise stays in gts
- By design: always returns to game session regardless of where
  cp -r was invoked from

**Known limitation — .tin aliases not visible in existing game session
after reload:** `cp -r` re-registers aliases from `core/*.tin` in `gts`
only. An already-connected game session does not pick these up since
inheritance only happens at session creation. This is intentional —
`.tin` aliases are stable infrastructure that does not change during a
play session. If a new `.tin` file is added, restart the game session
once to inherit it. Lua-based aliases do not have this limitation
because `game_cmd()` registers in both `gts` and `GAME_SESSION`
simultaneously.

### Session Settings Persistence

Personal game settings live in `ttpp/sessions/<name>.tin`, named after
the session (default: `default.tin`). The file is loaded into a tt++ class
of the same name on SESSION CONNECTED, and the class is kept open for
the duration of the session so that any aliases, variables, or other
settings added at runtime are captured automatically.

The `mume` alias is retained as a legacy shortcut that connects as `default`
— the game session name is always `default` unless a profile is explicitly
selected (Phase 2).

**Save mechanism:** SESSION DEACTIVATED fires inside the game session
while it is still alive — whenever the session loses focus. This covers:
- `#zap` — user disconnects directly
- `cp -r` — `#gts` at the start of reload deactivates the game session
- `cp -e` — `#gts` at the start of shutdown deactivates the game session

PROGRAM TERMINATION does not save — by the time the event fires, the
game session has already been torn down by tt++ and `#class write` against
it is a no-op. The event is only used for tmux teardown (see Shutdown
Teardown below).

**Known limitation — settings modified from gts are not saved.** The save
hook is SESSION DEACTIVATED, which fires when the game session loses focus.
Commands that modify the session from outside (e.g. `#mume #alias {...}`
issued from gts) are applied to the session but do not re-trigger
DEACTIVATED. If the user exits without activating the session again, such
changes are lost. To persist them, either activate the session (`#mume`
then `#gts`) before exiting, or run
`#default #class {default} {write} {ttpp/sessions/default.tin}` manually.

**Shutdown Teardown:** PROGRAM TERMINATION runs
`tmux kill-session -t mume 2>/dev/null`. Any graceful tt++ exit — `cp -e`,
`#zap` from gts, or `#end` — closes the entire cockpit tmux session
including the ui, dev, and input panes. `cp -e` no longer kills tmux
directly; it goes through PROGRAM TERMINATION like any other exit path.
Standalone tt++ runs outside the cockpit are unaffected by the missing
tmux session (error is suppressed).

**Load sequence on SESSION CONNECTED:**
1. `#read ttpp/sessions/%0.tin` — loads settings, file opens and closes class
2. `#class {%0} {open}` — reopens class to capture runtime additions

**Load sequence on cp -r (already-connected session):**
1. `#read ttpp/sessions/$game_session.tin` — reloads settings
2. `#class {$game_session} {open}` — reopens class

**Conventions:**
- Never hardcode `mume` as the class name in system code — always use
  the session name variable (`%0` or `$game_session`)
- Scripts must not register permanent aliases via `session_cmd()` —
  use `game_cmd()` instead, or they will be written into the session file

## GMCP

### Overview

GMCP (Generic MUD Communication Protocol) delivers structured data from MUME out-of-band over telnet subnegotiation. The client negotiates via `Core.Hello` + `Core.Supports.Set` at connect; the server then pushes the modules we subscribed to as `IAC SB GMCP` events. Payloads are JSON.

### GMCP module reference

MUME supports the following GMCP modules. Cockpit currently subscribes to Char, Comm.Channel, Event, and Core. Others are documented here so future work can pick from a known map without re-reading help files.

#### Module overview

| Module            | Subscribed | Purpose                                   |
|-------------------|------------|-------------------------------------------|
| Core              | yes        | Handshake, keepalive, ping, goodbye       |
| Char              | yes        | Character name, stats, vitals             |
| Comm.Channel      | yes        | Communication channels (tells, says, ...) |
| Event             | yes        | World events (darkness, sun, moon, moved) |
| Client            | no         | Mudlet-specific client package / map      |
| External.Discord  | no         | MUME Discord channel integration          |
| Group             | no         | Group / party state                       |
| MUME.Client       | no         | Remote text editing                       |
| Room              | no         | Current room data                         |
| Room.Chars        | no         | Characters in current room                |
| Room.Known        | no         | Visited rooms                             |

The canonical subscription list lives in **two places** — keep them in sync:
- `gmcp.modules` in `lua/brain.lua` — Lua source of truth
- `Core.Supports.Set` payload in `ttpp/core/gmcp.tin` — sent to the server at handshake

#### Subscribed modules — message reference

**Core**

| Message           | Direction | Body                            | Handler               |
|-------------------|-----------|---------------------------------|-----------------------|
| Core.Hello        | → server  | `{client, version}`             | ttpp/core/gmcp.tin    |
| Core.Supports.Set | → server  | array of `"Module N"` strings   | ttpp/core/gmcp.tin    |
| Core.KeepAlive    | → server  | (none)                          | not sent              |
| Core.Ping         | → server  | optional avg ping ms            | not sent              |
| Core.Ping         | ← server  | (none)                          | core_state.lua        |
| Core.Goodbye      | ← server  | optional reason string          | core_state.lua (stub) |

**Char**

| Message         | Direction | Body                           | Handler        |
|-----------------|-----------|--------------------------------|----------------|
| Char.Login      | → server  | `{name, password}`             | not sent       |
| Char.Name       | ← server  | `{name, fullname}`             | char_state.lua |
| Char.StatusVars | ← server  | name/caption pairs (see below) | char_state.lua |
| Char.Vitals     | ← server  | flat object (see below)        | char_state.lua |

Char.Vitals fields:

    hp, hp-string, maxhp
    mana, mana-string, maxmana
    mp, mp-string, maxmp
    xp, tp
    carrying
    ridden, ride
    climb  (null | "c" | "C")
    sneak  (null | "s" | "S")
    hidden (bool)
    swim   (bool)
    light  ("*" | "!" | ")" | "o")
    fog    (null | "-" | "=")
    weather (" " | "~" | "'" | "\"" | "*" | null)
    alertness ("normal", "careful", ...)
    mood ("wimpy", "prudent", ...)
    spell-effort ("quick", "fast", ...)
    position (standing | fighting | sitting | resting | sleeping
              | stunned | incapacitated | dying)
    mount-moves ("rested", "slow", ...)
    opponent       (string | null)
    buffer         (string | null)
    opponent-hits  ("healthy", "fine", ...)
    buffer-hits    ("healthy", "fine", ...)

Note: hp/mana/mp may be rounded — the *-string variants carry a qualitative description when precision is limited.

Char.StatusVars fields:

    fullname, level, name, next-level-tp, next-level-xp,
    race, subclass, subrace

Kebab → snake note: all of the above arrive in `state.char.*` with dashes converted to underscores (e.g. `state.char.hp_string`, `state.char.next_level_xp`, `state.char.mount_moves`).

**Comm.Channel**

| Message              | Direction | Body                                | Handler                                                    |
|----------------------|-----------|-------------------------------------|------------------------------------------------------------|
| Comm.Channel.Enable  | → server  | channel name string                 | comm_log.lua → alias `gmcp_enable_channel` in gmcp.tin     |
| Comm.Channel.List    | ← server  | array of `{name, caption, command}` | comm_log.lua                                               |
| Comm.Channel.Text    | ← server  | see below                           | comm_log.lua                                               |

Comm.Channel.Text body:

    channel      — channel name
    destination  — recipient name (only for sent messages)
    talker       — sender name ("you" for sent messages)
    talker-type  — optional: npc | ally | neutral | enemy
    text         — text heard, may contain ANSI codes (preserved)

Channel-enable flow:
1. tt++ sends `Core.Supports.Set` including `"Comm.Channel 1"` at handshake.
2. Server auto-sends `Comm.Channel.List` with available channels.
3. `comm_log.lua` receives the list, stores it in `state.comm.channels`, and issues `Comm.Channel.Enable` for each channel by calling the `gmcp_enable_channel` alias.
4. Server begins streaming `Comm.Channel.Text` for those channels.

No channel list is hardcoded client-side — whatever the server advertises gets enabled.

**Event**

| Message        | Body                                                        | Handler         |
|----------------|-------------------------------------------------------------|-----------------|
| Event.Darkness | `{what: "start"\|"grow"\|"shrink"\|"end-soon"\|"end"}`      | world_state.lua |
| Event.Moon     | `{what: "rise"\|"set"}`                                     | world_state.lua |
| Event.Moved    | `{dir: "north"\|"east"\|...}` (dir optional)                | world_state.lua |
| Event.Sun      | `{what: "light"\|"rise"\|"set"\|"dark"}`                    | world_state.lua |

All Event handlers store the decoded body as-is under the corresponding `state.world.<event>` field.

#### Unsubscribed modules — one-liner per module

- **Client** — Mudlet-specific client package and map data; used by Mudlet's MUME plugin for room mapping.
- **External.Discord** — integrates with the MUME Discord channel; bridges in-game communication to Discord.
- **Group** — group/party state; tracks members, their positions and vitals for group displays.
- **MUME.Client** — remote text editing; allows the server to open an editor on the client for composing notes and mail.
- **Room** — current room data including vnum, name, description, and exits; the basis for any mapper.
- **Room.Chars** — characters present in the current room; used for room-level displays and targeting aids.
- **Room.Known** — previously visited rooms; used to sync a visited-room database with the client.

Subscription requires adding to both the `Core.Supports.Set` payload and `gmcp.modules`.

### Negotiation registration

IAC events are session-scoped — they fire in the session that received the bytes, and only if registered inside that session. We register via a `SESSION CREATED` handler that uses `#%0 #event` to install `IAC WILL GMCP` and `IAC SB GMCP` inside the connecting session.

`SESSION CONNECTED` is too late: it fires after the first telnet data swap, by which point tt++'s default `IAC DONT GMCP` has already shipped. `SESSION CREATED` fires when `#session` is executed, before TCP handshake, so our handler is in place when the server's first bytes arrive.

### Sending sub-negotiations

Syntax: `#send {$IAC$SB${GMCP}Package.Name JSON $IAC$SE\}`

- `${GMCP}` uses brace delimiters so no space leaks between the GMCP option byte and the package name. `$GMCP Package` (no braces) would include a literal space that servers parse as part of the package name and reject.
- Package name and JSON body separated by exactly one space.
- No whitespace before `$IAC$SE`.
- Trailing `\` before the closing `}` suppresses tt++'s automatic `\r\n` — required, otherwise every send injects a blank command into the MUD input stream.
- IAC byte values live in tt++ variables (`#var {IAC} {\xFF}` etc.) declared at file load time. `\x` escapes are evaluated on assignment; using them inline inside an `#event` body produces literal `\xFF` text, not byte 0xFF.

### Reception

`#event {IAC SB GMCP}` fires with `%0` = module name, `%1` = list-flattened body, `%2` = raw JSON string. Use `%2` — `%1` is tt++'s nested-brace representation and loses type information.

`%2`'s payload includes the leading package name (e.g. `Char.Vitals {...}`), so `gmcp.dispatch` strips the first whitespace-delimited token before JSON decode.

### Lua dispatch

`gmcp.dispatch(module, payload)` in `brain.lua` strips the leading package-name token, parses the remainder as JSON via dkjson, and calls `gmcp.handlers[module]` with the decoded Lua value (or `nil` for empty bodies such as `Core.Goodbye`). Handlers run under `pcall` — a crashing handler logs to dev via `dbg()` but doesn't take down the brain.

### Script integration pattern

Scripts subscribe at load time:

```lua
gmcp.handlers["Char.Vitals"] = function(body)
    state.char.hp = body.hp
    -- ...
end
```

Unknown modules log `GMCP no handler: <Module>` to dev and drop. Modules not listed in `gmcp.modules` will never fire regardless of handlers registered — the subscription list is the gate.

### Data collection (iteration 2a)

**Generic flat-copy pattern.** `char_state.lua` merges Char.Name /
Char.StatusVars / Char.Vitals into `state.char.*` by iterating the decoded
body and converting kebab-case keys to snake_case. No explicit field list —
consumers must treat every field as possibly nil. Field-specific formalisation
will follow in iteration 2b once we have observed traces of actual MUME payloads.

**Kebab → snake convention.** GMCP uses kebab-case keys (e.g. `hp-string`,
`next-level-xp`). Handlers convert to snake_case when assigning to `state.*`
fields so Lua access stays straightforward (`state.char.hp_string`, not
`state.char["hp-string"]`).

**`gmcp.trace`.** When true (default in development), every decoded GMCP body
is dumped to debug.log as `[GMCP] <Module> = <json>`. Flip to false in
brain.lua if volume becomes a problem. Expected load: tens of messages/minute
during active play, line length ~100–300 chars.

### JSON library

`lua/lib/dkjson.lua` — pure-Lua MIT-licensed JSON library (David Kolf, v2.8), bundled verbatim. `package.path` is extended in `brain.lua` at startup to include `lua/lib/` so no path juggling is needed. GMCP message bodies may be empty, a JSON string, a JSON number, an array, or an object depending on the module. Handlers receive whatever dkjson decodes — or `nil` for empty bodies.

### Debugging

Turn on telnet trace with `#config {debug telnet} {on}` in gts (NOT `#config {telnet} {info} {on}` — that is invalid syntax that puts TELNET in DEBUG mode and disables the telnet stack). Turn off with `#config {debug telnet} {off}`.

`GMCP no handler: <Module>` entries in `debug.log` are the health signal — if they appear, negotiation completed and the server is streaming the modules we subscribed to.

With `gmcp.trace = true`, the best way to discover a module's real body shape is to subscribe, reload, and grep debug.log for `[GMCP] <Module>`.

## Input Pane

A dedicated input pane (`bridge/input_pane.py`) replaces typing directly
in the TT++ pane. It runs as a separate tmux pane at the bottom of the
left column, 1 row tall.

**Behaviour:**
- Commands are typed here and forwarded to TT++ via `tmux send-keys`
- After sending, the command remains visible highlighted (black on white)
  to indicate it can be repeated
- Pressing Enter again repeats the last command
- Pressing any printable key or backspace clears the buffer and starts
  a new command
- Page Up / Page Down scroll the TT++ pane without leaving the input pane
- On startup, a tmux `MouseUp1Pane` binding is registered so that clicking
  any other pane returns focus to the input pane automatically. The binding
  calls `bridge/focus_input.sh`, which resolves the input pane's current
  index at click time — so pane index shifts caused by cp -u / cp -d
  close+open cycles never cause focus to land on the wrong pane

**Dependencies:**
- Python 3 (system)
- `prompt_toolkit` — install with:
  `pip install prompt_toolkit --break-system-packages`

**Recommended terminal config:** prompt_toolkit emits a steady-cursor
request that persists while the input pane is running and is inherited
by other panes when focus shifts. Terminals with app-override blinking
(e.g. Alacritty `blinking = "On"`) will therefore show a steady cursor
in the input pane, tt++ after `cp -i` off, and bash after `cp -e`. Set
the terminal to force blinking (Alacritty: `blinking = "Always"`) if
a blinking cursor is preferred. The client works fully without this
setting — it is purely cosmetic.

**Known limitation:** drag-select in the TT++ pane does not auto-return
focus to the input pane. Click once in the input pane to return.

## Layout System

Pane dimensions are persisted across restarts and adapt to terminal resizes.
State is stored in `bridge/layout.conf` (gitignored, recreated on first startup).

### layout.conf keys
| Key               | Default | Description                                      |
|-------------------|---------|--------------------------------------------------|
| `ui_width`        | 33      | Absolute column width of the right pane column   |
| `window_cols`     | 0       | Last known terminal width — used to distinguish terminal resize from pane drag |
| `ui_height_ratio` | 60      | ui pane height as % of total right column height |

### Behaviour
- **Terminal resize** — `window-resized` hook fires `on_window_resize.sh`, which re-applies `ui_width` and `ui_height_ratio` and re-pins input to 1 row.
- **Border drag** — `MouseDragEnd1Border` binding fires `on_pane_resize.sh`, which saves the new `ui_width` and recalculates `ui_height_ratio` from current pane heights.
- **Input pane** — always pinned to 1 row on every terminal resize. Never participates in layout calculations.
- **Dev toggle** — when dev is toggled back on, `open_pane.sh` applies `ui_height_ratio` to restore the saved split.
- **Loop prevention** — `bridge/.layout_lock` is used as a lockfile to prevent `on_window_resize.sh` triggering `on_pane_resize.sh` in a feedback loop.
- **`-f` on right-column splits.** When `open_pane.sh` creates the right column from scratch (no ui/dev exists), `split-window -h` must use `-f` (full-window). Otherwise, if the input pane already exists, the new right pane is inserted as main's sibling inside the left-column subtree, causing input to span the full window width.

### Gitignored files
```
bridge/layout.conf
bridge/session.state
bridge/version.cache
bridge/.layout_lock
bridge/.pane_resize_pid
bridge/ping.cache
bridge/.ping_pid
```

## Input Pane

The input pane (`bridge/input_pane.py`, prompt_toolkit) owns the command
line. All user keystrokes arrive here first. Complete command lines are
forwarded to the tt++ pane via `tmux send-keys`. Individual keypresses
that should trigger tt++ `#macro` bindings are forwarded as raw keys.

### Keypad application mode

On startup, the input pane writes DECKPAM (`\e=`) to stdout to enable
keypad application mode. An atexit handler writes DECKPNM (`\e>`) to
restore numeric mode on shutdown. This is unconditional — the terminal
protocol has no way to query current keypad state, and re-enabling is
idempotent.

Application mode causes numpad keys to emit SS3 escape sequences
(`\eOp`..`\eOy` for digits, `\eOj`..`\eOo` for operators, `\eOM` for
enter) which the input pane can bind individually.

### Key forwarding policy

Keys are split into three disjoint categories:

| Category  | Handled by         | Examples                                              |
|-----------|--------------------|-------------------------------------------------------|
| Editing   | prompt_toolkit     | printable chars, Backspace, Ctrl+E/W, Alt+Backspace   |
| History   | prompt_toolkit     | Up, Down, Ctrl+P, Ctrl+N, Ctrl+R                      |
| Scrollback| prompt_toolkit     | PageUp, PageDown (forwarded to tt++ pane's buffer)    |
| Terminal  | OS / terminal      | Ctrl+C, Ctrl+D, Ctrl+Z, Ctrl+S, Ctrl+Q                |
| Forwarded | tt++ via send-keys | F1–F12, numpad (SS3), Alt+letter (subset), Ctrl+letter (subset) |

Forwarded keys invoke `tmux send-keys -t mume:cockpit.0 <name>` with no
`Enter` appended — a single keypress is delivered to tt++, which then
consults its `#macro` table as if the key had been pressed directly.

### Command input behaviour

The input pane implements line editing, command history, and recall
highlighting on top of prompt_toolkit. The behaviour is designed to
match the rhythms of MUD play — fast repeat-sends, quick history
recall, and cancellation of delayed commands.

#### Enter semantics

| Buffer state | Action |
|--------------|--------|
| Non-empty    | Send text, append to history (consecutive-dedup), refill buffer with sent text in recalled state |
| Empty        | Send a bare newline to tt++. Do NOT re-send the previous command. |

Empty Enter sending a bare newline is load-bearing: MUME uses it to
cancel delayed commands (e.g. spell casts). Re-sending last_cmd on
empty Enter would silently break that.

#### Recall highlighting

A buffer is in "recalled" state when its text was set programmatically
rather than typed — either by the post-Enter refill or by Up/Down
history navigation. Recalled text is rendered with inverted colours
(black-on-white) to signal that the next keystroke will overwrite it.

Any of the following exits recall state and clears the highlight:
- Typing a printable character (resets buffer, inserts the char)
- Backspace or Delete (resets buffer)
- Left, Right, Home, End (buffer preserved, cursor moves)

Recall state can also be entered manually on the current buffer:
Shift+Home highlights the full buffer and moves the cursor to the
start; Shift+End highlights the full buffer and moves the cursor
to the end. Ctrl+A is an alias for Shift+End (full-buffer highlight,
cursor at end) — the standard GUI select-all convention. Any of these
provides a quick wipe — press Backspace, Delete, or any printable
character to clear the buffer. No-op on empty buffer.

#### History navigation

History is a list of previously-sent commands with **consecutive-dedup**
— identical commands sent back-to-back collapse to a single entry, but
non-consecutive duplicates are preserved. `look, north, look` keeps
both `look` entries; `look, look, look` collapses to one.

`Up` walks toward older entries, `Down` toward newer:

- **Up from refilled state** (just after Enter, buffer holds the
  last-sent command highlighted): steps directly to the entry before
  the newest, skipping the already-displayed entry.
- **Up from a typed draft**: saves the draft as `pending_input` and
  shows the newest entry.
- **Up during active browsing**: steps one entry older, clamped at
  the oldest.
- **Down during active browsing**: steps one entry newer. At the
  newest, one more Down restores `pending_input` (the saved draft or
  empty). One more Down after that clears the buffer entirely.
- **Down outside of browsing**: no-op.

Any text change or cursor movement during browsing exits recall state
and resets navigation — the next Up starts fresh from the newest entry.

History is in-memory only; it does not persist across restarts and
has no size cap.

### Forwarded key classes

- **F-keys:** F1–F12. Shift+F-keys are not forwarded (terminal-dependent,
  no uniform tmux send-keys representation).
- **Numpad:** 0–9, `.`, `+`, `-`, `*`, `/`, Enter. Bound as raw SS3
  escape tuples (`("escape", "O", "p")` etc.) since prompt_toolkit has
  no named keys for numpad. Requires DECKPAM and Num Lock on.
- **Alt+letter:** all letters except `b`, `d`, `f` (reserved for
  readline-style word editing) and `o` (see Known Limitations).
- **Ctrl+letter:** `g`, `l`, `o`, `v`, `x`. Other Ctrl+letters are
  either reserved by the terminal or used by prompt_toolkit editing.

`bridge/input_pane.py` is the source of truth for the exact lists.

### Design consequences

- tt++ sees forwarded keys as if pressed directly. `#macro` bindings
  work unchanged from standard tt++ usage — define them in `.tin` files
  or live in the session.
- tt++ `#macro` features that assume tt++ owns the input line have no
  equivalent here. Specifically, the `^` prefix ("trigger only at start
  of input line") is non-functional because the input line lives in
  prompt_toolkit.
- Shift+letter cannot be a macro target — terminals do not distinguish
  it from the uppercase form.
- Bare ESC is not available as a tt++ macro target. ESC is captured at
  the tmux root-keybinding level (`tmux bind-key -T root Escape`) to open
  the in-game popup menu uniformly from any pane (game, input, ui, dev).
  This bypasses prompt_toolkit's escape-disambiguation timer entirely.
  `escape-time` is set to 10 ms in `tmux_start.sh` for fast disambiguation
  of multi-character escape sequences (Alt+letter, numpad SS3) within tmux.

### Known limitations

- **Alt+o is not forwarded.** prompt_toolkit's key parser cannot
  reliably distinguish `("escape", "o")` from `("escape", "O", "o")`
  (numpad division). Other Alt+letters whose final character also
  appears as the third character of a numpad sequence have been
  verified not to collide — this bug is specific to lowercase `o`.
- **Numpad requires Num Lock on.** With Num Lock off, the numpad emits
  cursor/navigation sequences instead, which are not bound as macros.
- **Cursor flicker at popup open/close.** A single-frame cursor flash is
  visible when the popup opens and closes. Cause is the terminal emulator
  defaulting cursor-visible state on new pty creation; tmux display-popup
  spawns a fresh pty each open. Cursor-hide escapes fire as early as possible
  inside the popup but cannot preempt the emulator's initial state. Accepted
  as a cosmetic limitation.

## Cockpit System
Unified window and system management via `cp` commands:

| Command       | Action                          |
|---------------|---------------------------------|
| `cp`          | Show help                       |
| `cp -i`       | Toggle input pane               |
| `cp -u`       | Toggle UI pane                  |
| `cp -d`       | Toggle dev pane                 |
| `cp -h`       | Toggle pane title headers       |
| `cp -s`       | Save profile to disk            |
| `cp -r`       | Full reload                     |
| `cp -e`       | Full shutdown                   |
| `cp -<alias>` | Show help for installed script  |

`cp -s` runs `#class {$_profile} {write} {ttpp/sessions/$_profile.tin}`
inside the profile's tt++ session via a `#gts { #$_profile { ... } }`
wrapper. Uses `$_profile` (stable, set once at tt++ startup from
`startup.conf`) rather than `$game_session` (cleared on disconnect) so
save works after link loss as well as during a live connection. Success
and error messages are routed to the UI pane via `#lua {system_ui(...)}`
and `#lua {ui_err(...)}` respectively, not `#showme` to the game pane.

`cp -u`, `cp -d`, `cp -i`, and `cp -h` are thin wrappers around
`bridge/toggle_pane.sh`. Each alias passes its target (`ui`, `dev`,
`input`, or `headers`) to the script via `#system`. The script also
accepts an optional `--persist` flag; the `cp` aliases invoke it without
`--persist`, so they remain runtime-only and never modify `startup.conf`.

**In-game popup Options submenu** (`bridge/ingame_menu.sh`): four toggles
(UI / Dev / Input / Pane headers) + Back. State is re-probed from tmux
on every render — never cached. Toggling calls `toggle_pane.sh --persist`
directly; they do **not** route through tt++ so no `cp -X` lines appear in
the game pane. The popup submenu is therefore the persistent-toggle entry
point; `cp` aliases remain runtime-only.

**In-game popup Scripts submenu** (`bridge/ingame_menu.sh`): ports the
launcher's Scripts page into the popup. Reads `bridge/scripts.cache` on
each render — picks up cache changes if `cp -r` fires while the submenu
is open. Scrollable with UP/DOWN; scroll hint appears in the footer only
when content exceeds visible rows. Rendering is identical to the launcher
(A:/S:/H:/B:/M: tags, 60-col block centred). Parser and renderer are
duplicated from `launcher.sh` — not extracted into `menu_render.sh` — to
keep the shared helper stable. Not covered: live script state
(IDLE/RUNNING/FIRING) and a stop-all-scripts button — both parked.

The `cp` help box is dynamically generated by Lua after all scripts load,
so the Scripts section always reflects installed scripts. Each script
registers itself via `register_script(meta)` — no changes to core needed.

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
6. **Self-contained Lua scripts** — each script in `lua/scripts/` is a
   single `.lua` file with no paired `.tin` file. The script registers its
   own aliases via `game_cmd()`, triggers and delays via `session_cmd()`,
   and MUD commands via `send()` at load time. Never hardcode session names.
   This is the approved pattern for all automation features.

## Startup

```bash
./start.sh            # show retro startup menu (default)
./start.sh --no-menu  # skip menu, use current bridge/startup.conf
./start.sh -d         # skip menu, force dev pane on for this run (not persisted)
./start.sh -u         # skip menu, force UI pane on for this run (not persisted)
```

`start.sh` is a thin wrapper that installs dependencies and then:
- Without bypass flags → `exec bash bridge/launcher.sh` (startup menu)
- With `--no-menu` / `-d` / `-u` → `exec bash bridge/tmux_start.sh` (direct start)

The return-to-menu path (in-game popup "Exit to main menu") is handled by an
exec-chain inside `tmux_start.sh`: after `tmux attach` returns, the script
checks for `bridge/.return_to_menu` (written by `ingame_menu.sh` just before
firing `cp -e`) and, if present, `exec`s back into `bridge/launcher.sh`.
No intermediate bash frame — no flash. `tmux_start.sh` also clears any stale
sentinel at the top of each run so a crash cannot mis-route a subsequent cold
start.

### Startup menu (`bridge/launcher.sh`)
A DOS-style retro menu rendered in the terminal before tmux launches.
Pure bash + ANSI escapes; no external dependencies beyond coreutils.

| Feature | Detail |
|---------|--------|
| Session detect | `tmux has-session -t mume` + `list-clients` → top item is "Start new session", "Continue session", or "Mirror session (attached elsewhere)" |
| Profile page | Lists `ttpp/sessions/*.tin`; select, create (blank / copy from existing), delete. `default` cannot be deleted. Selected profile is written to `startup.conf` and consumed by `ttpp/core/config.tin` at tt++ startup (Phase 2). |
| Options page | Toggle UI / Dev / Input panes; pane dividers; connection mode; live layout mockup (updates on divider toggle). Content hides progressively at small heights: descriptions → mockup → section headings; menu items always render |
| Scripts page | Reads `bridge/scripts.cache`; scrollable |
| About page | Reads `bridge/about.txt`; word-wrapped, cached per resize, scrollable |
| Quit | Confirmation prompt; ESC cancels |
| Persistence | Options saved to `bridge/startup.conf` on Back / ESC |

### Version check (`bridge/version_check.sh` + `bridge/version.cache`)

On every launcher startup, `bridge/launcher.sh` fires `version_check.sh` in
the background (`&`, `disown`). The script queries the GitHub releases API for
`Khazdul/mumecockpit` with a 3-second timeout. On success it writes
`bridge/version.cache` atomically (temp-file + rename):

    latest=vX.Y.Z
    checked_at=<epoch seconds>

TTL is 6 hours — later invocations within the window exit silently without
hitting the network. `--force` bypasses the cache.

Only `/releases/latest` is used. If the repo has no formal GitHub releases,
the endpoint returns 404 and the script exits silently without writing the
cache — the About page then shows the current version only. Any other failure
(offline, rate-limit, parse) leaves the cache unchanged and exits silently.

If `bridge/version.cache` holds a stale or wrong value, delete the file and
restart the launcher to trigger a fresh check.

Consumers:
- Launcher About page: version is displayed top-right on the title row,
  always visible without scrolling. Shows current version always, appends
  "Update available: vX.Y.Z" in `_MR_ACCENT` when cache indicates a newer tag.

The consumer does not block on the network. If the cache is missing or stale
the UI still shows the current version; background refresh catches up within
seconds.

### Ping monitor (`bridge/ping_monitor.sh` + `bridge/ping.cache`)

A background process pings `mume.org` once per second and writes cache values
to `bridge/ping.cache`. The cockpit's in-game popup reads the cache each render
and shows the latency + a one-word quality label as part of the status header:

    Profile: default  ·  MMapper  ·  Link: 38ms (stable)

**Lifecycle.** The monitor is spawned by `bridge/tmux_start.sh` after the tmux
cockpit session is set up, and by `bridge/launcher.sh` on the Continue/Mirror
attach paths. A single-instance guard (`bridge/.ping_pid` lockfile) ensures
duplicate spawns are no-ops. The process self-terminates within ~1 s of the
`tmux:mume` session disappearing, so `cp -e`, SIGKILL, or any other shutdown
path stops it cleanly without explicit cleanup code.

**Cache format** (atomically written via temp-file + rename):

    latest=<integer ms or TIMEOUT>
    quality=<label or empty>
    samples=<comma-separated ring buffer, up to 60 entries>

**Quality algorithm.** Over the last 60 samples (1 minute):
- `loss%` = fraction of TIMEOUT samples
- `spread` = p95 − p50 of non-TIMEOUT samples (captures jitter and spikes
  without over-reacting to single outliers)

| Label   | Spread (ms) | Loss (%) | Colour in popup |
|---------|-------------|----------|-----------------|
| stable  | < 8         | = 0      | _MR_BODY        |
| ok      | < 20        | < 5      | _MR_BODY        |
| jittery | < 50        | < 15     | _MR_YELLOW      |
| spiking | < 120       | < 30     | _MR_YELLOW      |
| poor    | otherwise   | otherwise| _MR_ERR         |
| dead    | any         | >= 80    | _MR_ERR         |

Fewer than 10 samples → no label (buffer warming up).
"timeout" (current sample is TIMEOUT but history exists) shown in _MR_ERR
regardless of quality label.

Rationale for p95−p50: adapts to the user's own baseline (30 ms vs 300 ms
doesn't matter — the label describes *consistency*, not speed). Thresholds are
informed by the project owner's subjective calibration: ~20 ms deviation from
baseline is "noticeable unstable"; ~50 ms is "directly felt"; >100 ms is
"very bad."

**Failure modes.**
- `ping` binary missing / offline / DNS fails → samples are TIMEOUT, status
  header shows "Link: timeout (dead)" after buffer fills.
- SIGKILL'd monitor → stale PID file. Next launch detects dead PID (via
  `kill -0`) and takes over cleanly.
- Two cockpit sessions started simultaneously (rare) → only one monitor; the
  other's start call exits at the PID guard.

### Self-update (`bridge/update.sh`)

When `bridge/version.cache` indicates a newer tag than the VERSION file, the
launcher inserts an "Update" row into the main menu directly below the
Start/Continue/Mirror row. Selecting it runs `bridge/update.sh`, which:

1. Verifies `version.cache` actually indicates a newer version (comparison
   strips a single leading "v" from both operands, so "0.1.0" matches
   "v0.1.0").
2. Runs three safety guards — all must pass:
   - Developer fingerprint: `git config user.email` must NOT match any
     commit author in the repo history.
   - Working tree clean: no uncommitted changes, no untracked files
     outside `.gitignore`.
   - Local commits: zero commits ahead of `origin/main`.
3. `git fetch origin main --tags`
4. `git reset --hard origin/main`
5. Prompts user to restart the launcher. Any-key press re-execs
   `launcher.sh`, loading the fresh code.

Guard failure aborts with a specific exit code (20/21/22) and message.
Git failures exit 30.

The in-game popup does NOT expose an Update affordance. Update runs
pre-tmux, from the launcher only, so the cockpit never has to deal with
mid-session binary changes.

**Developer note:** the email fingerprint check is the primary protection
for active developers. If you clone on a fresh machine without setting
`git config user.email`, guards (b) and (c) still protect against
accidental damage. If all three guards somehow pass on a dev machine
(unlikely) and Update runs: `git reset --hard` discards nothing that
wasn't already pushed, but force-resets the branch pointer to
`origin/main`. Recovery: `git reflog` still contains your old HEAD.

### Clean client startup (`ttpp/main.tin` + `ttpp/core/welcome.tin`)

tt++ is launched with a CLI flag that suppresses its built-in greeting
banner (set in `bridge/tmux_start.sh`). The small residual flash is
eliminated by also having tmux start tt++ directly as the pane command
(`tmux new-session ... "cd ~/MUME && exec tt++ ..."`), bypassing an
intermediate bash prompt.

Inside tt++, `main.tin` does three things to keep the game window clean:

1. **Global message suppression.** `#message {aliases} {off}` and the
   equivalents for actions/variables/delays/macros/substitutes/
   highlights/classes/events. Turns off tt++'s `#OK.` confirmations
   for routine registrations. Errors still print. Applies permanently,
   not just at boot — the cockpit has its own logging via
   `ui()` / `dbg()` / `system_ui()`.

2. **Boot-only scrollback wipe.** `#buffer clear` + `#screen clear all`
   guarded by `#if {!&game_session}`. Wipes any residual tt++ chatter
   on initial boot. On `cp -r` mid-session the guard skips it, so the
   game's scrollback survives reloads.

3. **Silent Lua launch.** `#line quiet {#run {lua} {lua lua/brain.lua}}`
   suppresses the `#TRYING TO LAUNCH 'lua'` notice.

`welcome.tin` then owns the welcome screen and auto-connect:

- `_do_startup` runs 0.5 s after boot (time for tt++ and Lua to finish
  their own boot output). Same game_session guard — skips entirely on
  cp -r mid-session.
- Clears scrollback (tt++'s `#buffer clear`, terminal's `\e[3J`, and
  `tmux clear-history`).
- Prints the MUME + COCKPIT ASCII banner, a welcome line, a
  `Press <Esc> for menu.` hint, and `Connecting to MUME...`.
- Calls `connect`, which resolves to `#$_ses_cmd {$_profile} {$_host} {$_port}`
  via `config.tin` — `$_ses_cmd` is `ses` (mmapper/plain) or `ssl` (direct/TLS).
  User lands directly in the MUD.

### Rendering conventions

Launcher pages render through `render_frame` in `bridge/menu_render.sh`.
Rules are strict — deviations reintroduce flicker or scroll artifacts:

**Semantic colour palette (`bridge/menu_render.sh`).** All escape codes are
referenced by role, not raw colour, so visual adjustments stay localised:

| Name            | Role                                               |
|-----------------|----------------------------------------------------|
| `_MR_TITLE`     | Page banners, ASCII logo, section titles           |
| `_MR_ACTIVE`    | Focused/selected row, emphasis in prompts          |
| `_MR_ITEM`      | Inactive selectable menu rows                      |
| `_MR_SECTION`   | Section headings inside pages (quieter than items) |
| `_MR_BODY`      | Body text — About prose, script summaries          |
| `_MR_HINT`      | Footer nav hints, secondary prompt labels          |
| `_MR_QUOTE`     | Italic quote text on the main menu                 |
| `_MR_QUOTE_ATTR`| Quote attribution line (sage green)                |
| `_MR_ACCENT`    | Call-to-action rows, script alias headings         |
| `_MR_DESC`      | Pane-description text in layout mockup             |
| `_MR_YELLOW`    | Warnings (non-fatal errors, can't-delete notices)  |
| `_MR_ERR`       | Hard errors                                        |

**Alignment convention (Profile / Options pages).** Menu rows are
left-aligned on a shared column inside a centred block. The widest label
is found on every render so the block re-centres correctly after terminal
resize. `draw_menu_item` accepts an optional `pad_override` (third arg) to
override its default per-row centering, and an optional `inactive_color`
(fourth arg) to colour a row differently in its inactive state (used for
the amber "[+] Create new profile" row).

**About page three-colour scheme.** `_render_about` classifies each wrapped
line before printing: all-uppercase lines → `_MR_TITLE` (headings); lines
starting with whitespace → `_MR_ACCENT` (key/command lines such as
`  cp -r`); all other non-empty lines → `_MR_BODY` (prose). Indented lines
pass through `wrap_text` unchanged — a leading-whitespace guard flushes the
current word-wrap buffer and emits the line verbatim, preserving command
column alignment.

- **Alt screen buffer.** Enter on launch (`\e[?1049h`), leave on exit. Cleared
  automatically when tmux attaches.
- **Cursor hidden** (`\e[?25l`) except during profile name entry.
- **Mouse + alt-scroll disabled** (`\e[?1000l \e[?1002l \e[?1003l \e[?1006l
  \e[?1007l`) while launcher is active. Restored on exit.
- **No full clear between frames.** `render_frame` overwrites cell-by-cell:
  `\e[H` home, each line followed by `\e[K`, `\e[J` at end. Never `\e[2J`.
- **No trailing newline** after the last line of any frame — it scrolls the
  terminal and jitters the title/footer row.
- **Dirty-flag redraw.** Main loop uses `_DIRTY=1` set by a `WINCH` trap or
  state-changing key handler; `read -rsn1 -t 0.2` yields fast enough resize
  response without a busy loop.
- **Handoff via `exec`.** Launcher → tmux_start.sh uses `exec bash …`; the
  tmux session is created and then attached with a plain `tmux attach` (not
  exec, so the return-to-menu sentinel check can run after attach exits).
  The launcher → tmux_start handoff itself is exec'd, so there is no
  intermediate bash flash between menu and cockpit.

**Pane-setup barrier.** `bridge/tmux_start.sh` prefixes the tt++ launch command with `sleep 0.3 &&` so that `tmux split-window` and `tmux resize-pane` complete before tt++/Lua begin writing to `ui.log` / `debug.log`. Without the barrier, `tail -f` in the UI/DEV panes reflows mid-output and the first emitted lines are swallowed into scrollback.

**Ctrl+C hardening (ui/dev panes).** Focusing a UI or DEV pane and pressing Ctrl+C would send SIGINT to the `tail -f` foreground process, kill it, and close the pane — breaking the layout for inexperienced users. Both panes are now launched with a hardened wrapper:

```
bash -c 'stty -isig 2>/dev/null; trap "" INT; while true; do tail -f <PATH>; printf "\n[pane kept alive — use cp-u/cp-d to close]\n"; sleep 0.2; done'
```

`stty -isig` disables signal generation (INTR/QUIT/SUSP) for the pane's tty, so Ctrl+C never produces SIGINT in the first place. `trap "" INT` is a belt-and-braces fallback in case stty is unavailable. The `while true` loop restarts `tail -f` if it exits for any other reason (log rotation, truncation). The input pane (`python3 bridge/input_pane.py`) is deliberately unwrapped — it needs signals to function correctly.

### scripts.cache (`bridge/scripts.cache`, gitignored)
Written by `brain.lua` at every client startup (inside `load_scripts()` after
`_register_cockpit_help()`). Parsed by the Scripts page in `launcher.sh`.

Format (line-prefixed, one block per script, alphabetical by alias):
```
SCRIPT:autostab
SUMMARY:backstab/escape loop
HELP:Usage: as<dir>
HELP:...
SCRIPT:autobow
...
```

### startup.conf keys (`bridge/startup.conf`, gitignored)
| Key               | Default    | Description                              |
|-------------------|------------|------------------------------------------|
| `connection_mode` | `mmapper`  | `mmapper` (localhost:4242) or `direct` (mume.org:4242) |
| `show_ui`         | `1`        | Whether to open the UI pane              |
| `show_dev`        | `0`        | Whether to open the dev pane             |
| `show_input`      | `1`        | Whether to open the input pane           |
| `show_pane_dividers` | `1`     | Whether tmux pane borders and the pane-border-status bar are visible at startup. `cp -h` toggles this at runtime without writing back to conf. `bridge/toggle_pane.sh headers --persist` is the mechanism for persistent toggles from the in-game popup. |
| `profile`         | `default`  | Which file in `ttpp/sessions/` to load; also the tt++ session name |

Toggle panes at runtime with `cp -u`, `cp -d`, `cp -i`, `cp -h`.

`profile` and `connection_mode` are read by `ttpp/core/config.tin` at tt++
startup via `bridge/read_config.sh`, which materialises the `_profile`,
`_host`, `_port`, and `_ses_cmd` tt++ variables used by the `connect` alias.
`_ses_cmd` is `ses` for mmapper mode and `ssl` for direct mode (TLS).

## Version Control

The project uses Git with a remote repository on GitHub.

To save and push all current changes:
```bash
git add . && git commit -m "update" && git push
```

Commit often — treat commits as save points. Good times to commit:
- When a new feature works
- Before starting something new
- Before a cockpit -reload test session

### Note for AI assistants
Remind the user to commit when:
- A feature has just been completed and verified working
- Significant changes have been made across multiple files
- Before suggesting large refactors or restructuring

Suggested reminder phrasing:
"This looks like a good point to commit — 
git add . && git commit -m 'update' && git push"

## TT++ Command Reference

Common commands with exact syntax. Refer to `ttpp_manual.txt` for full docs.

```
#alias  {name} {commands} {priority}
#action {message} {commands} {priority}      -- fires on output in its own session only
#unaction {exact-message-pattern}            -- pattern must match #action exactly
#delay  {seconds} {command}                  -- unnamed one-shot delay
#delay  {name} {command} {seconds}           -- named delay, can be cancelled
#undelay {name}
#macro  {key sequence} {commands}
#highlight {color} {pattern}
#substitute {pattern} {replacement}
#variable {name} {value}
#if     {expression} {commands} {else}
#{session} {command}                         -- dispatch command to another session
#kill   {type}                               -- kills all of type in current session
#zap    {session}                            -- terminates a session
#run    {session} {shell-command}            -- starts subprocess as a session
#lua    {text}                               -- sends text to the lua #run session stdin
```

**Brace handling:** braces `{}` captured in action wildcards (`%1`, `%2`) are
hex-encoded by TT++ (`{` → `\x7B`). Any TT++ command containing braces must be
sent via `tintin_cmd()` (file-based), not the `tintin()` relay.

## Coding Conventions

### General
- All code comments must be in English, clear and descriptive
- Each file must have a header comment explaining its purpose

### TinTin++ (.tin files)
- Use `#nop` for all comments
- Use `#nop` section headers to group related items
- New files placed in `ttpp/core/` are picked up automatically — no
  changes to `main.tin` needed

### Lua scripts (`lua/scripts/`)
- One feature per file — all aliases, triggers, state, and logic in one place
- Register aliases and triggers at the bottom of the file (runs at load time)
- Public functions callable from tt++ via `#lua` must be global (no `local`)
- Use `game_cmd(...)` for load-time aliases, `session_cmd(...)` for triggers and delays
- New files placed in `lua/scripts/` are picked up automatically — no
  changes to `brain.lua` needed

### State Change Echoes
All aliases that change player state (target, spamdoors, spell selection, etc.)
must echo the new state using this format:

```
#showme {<F9AA8B7>## Label: <FFFFFFF>$value<099>}
```

| Code        | Role                                        |
|-------------|---------------------------------------------|
| `<F9AA8B7>` | Steel-blue — labels and the `##` prefix     |
| `<FFFFFFF>` | White — values                              |
| `<099>`     | Reset — always close the colored block      |

The `##` prefix makes state-change lines visually distinct from game output.
These are the TinTin++ 24-bit truecolor equivalents of Mudlet's
`<154,168,183>` (label) and `<255,255,255>` (value).

### Script Status Messages
Lua scripts report key lifecycle events to the UI pane via `script_ui()` in
`brain.lua`:

```lua
script_ui("AUTOSTAB", "Running.")
script_ui("AUTOSTAB", "Stopped — target dead.")
script_ui("AUTOSTAB", "Stopped — timed out.")
```

Renders in the UI pane as:

```
▶ AUTOSTAB: Running.
▶ AUTOSTAB: Stopped — target dead.
```

`▶ SCRIPTNAME` is teal (`#26C6DA`), the message is bold bright white, and
dynamic values are bold yellow via `ui_var()`. Colors use ANSI escape
codes (not TT++ format) since the UI pane is a plain terminal (`tail -f`).

**Rules:**
- Use `script_ui` for key state changes only: started, stopped, errors.
- **Max 33 characters total** — `▶ AUTOSTAB: Stopped — timed out.` is the
  limit.
- Use "Stopped" when a script ends for any reason (not "aborted",
  "cancelled", etc.).
- One `script_ui` call per event — never call both `script_ui` and `ui()`
  for the same event.
- The mume main window (`as_show` / `tintin_show`) is separate — use it for
  in-game context (e.g. `## AUTOSTAB: target: orc dir: west`), not for status.

See "UI Message Style Rules" below for cross-cutting conventions (trailing
period, event phrasing, dynamic value highlighting, no timestamps).

### UI System Events
Infrastructure lifecycle events (brain start, game session connect/disconnect,
cockpit reload, future framework-level events) use `system_ui()` in
`brain.lua`:

```lua
system_ui("Game session " .. ui_var(ses) .. " connected.")
system_ui("Game session " .. ui_var(ses) .. " closed.")
```

Renders in the UI pane as:

```
● SYSTEM: Game session mume connected.
● SYSTEM: Game session mume closed.
```

`● SYSTEM` is blue (`#42A5F5`), the message is bold bright white, and
dynamic values are bold yellow via `ui_var()`.

Infrastructure lifecycle events that the user needs to see (game session
connect/disconnect, cockpit reload, future framework-level events) use
`system_ui()`. Events that are internal brain plumbing (brain process start,
script-load diagnostics) go to `dbg()` and appear in the dev pane only.

Use `system_ui` for user-relevant state transitions only — not for game events,
script lifecycle (use `script_ui`), warnings (`ui_warn`), or errors (`ui_err`).

### UI Warnings and Errors
When the player needs to see a warning or error, use the severity helpers in
`brain.lua`:

```lua
ui_warn("Config file missing, using defaults.")
ui_err("Failed to load script " .. ui_var("foo.lua") .. ".")
```

Renders as:

```
⚠ WARN: Config file missing, using defaults.
✖ ERROR: Failed to load script foo.lua.
```

`⚠ WARN` is amber (`#FFB300`), `✖ ERROR` is red (`#E53935`). Messages are
bold bright white, and dynamic values are bold yellow via `ui_var()`.

**UI vs debug log:**
- Routine / recoverable issues with no player impact → `dbg()` only.
- Issues the player should know about (misconfig, missing feature, script
  failure) → `ui_warn()` or `ui_err()`. These mirror to `debug.log`
  automatically via `ui()` — don't follow them with a redundant `dbg()`.

### UI Dynamic Values
Any message written to `ui.log` that contains dynamic content (session names,
player names, counts, etc.) must highlight the dynamic parts via `ui_var()`
in `brain.lua`:

```lua
local _C_VAR = "\027[1;38;2;255;238;88m"   -- bold yellow #FFEE58 — dynamic values

function ui_var(v)
    return _C_VAR .. tostring(v) .. _C_RESET .. _C_TEXT
end
```

Dynamic values render in bold yellow, the rest of the message in bold
bright white (the `_C_TEXT` base). The trailing `_C_TEXT` inside
`ui_var` restores the base colour after the variable so subsequent text
continues in bold white rather than falling back to the terminal
default.

Usage:

```lua
system_ui("Game session " .. ui_var(ses) .. " connected.")
script_ui("AUTOSTAB", "Stopped — " .. ui_var(reason) .. ".")
ui_err("Failed to load script " .. ui_var("foo.lua") .. ".")
```

The convention is semantic — `ui_var` marks "this is a dynamic value", not
a specific style. If the style changes later, only one place needs updating.

See "UI Message Style Rules" below for when to apply `ui_var()` and other
cross-cutting rules.

### UI Message Style Rules
These rules apply to every message written to `ui.log` through any helper
(`ui`, `script_ui`, `system_ui`, `ui_warn`, `ui_err`):

- **Trailing period — UI vs dev.** User-facing helpers (`ui`, `system_ui`, `script_ui`, `ui_warn`, `ui_err`) write full sentences and always end with a period. `dbg()` is developer-facing log output — terse, `key: value` or status-style — and never ends with a period. Quick test: if the line reads like console output from a tool (`server connected`, `cache miss for foo`, `3 scripts loaded`), it's `dbg()` and takes no period. If it reads like a status report to the player (`Game session mume connected.`), it's one of the UI helpers and does.
- **Event-style phrasing.** Describe what happened, not what the state is
  now. `Game session mume connected.`, not `Game session: mume`.
- **Dynamic values highlighted.** Any variable part of a message (session
  name, target, reason, count, filename) is wrapped in `ui_var()` and
  renders in bold yellow against the bold white base text.
- **No timestamps.** `ui.log` is meant to be scannable at a glance.
  `debug.log` already carries timestamps for diagnostic purposes.

## Windows Installer (Planned)

One-click install for Windows users with no Linux/WSL experience.
Not yet implemented — documented here for future development.

### Goal

A single `.bat` file that sets up the complete environment on a stock Windows machine.
Target user: MUME player on Windows, no Linux/WSL knowledge required.

### What it does

1. **mmapper** — checks if mmapper is already installed; if not, downloads and installs it via winget or the official installer
2. **WSL2** — enables required Windows features (`VirtualMachinePlatform`, `Microsoft-Windows-Subsystem-Linux`) and installs Ubuntu via `wsl --install -d Ubuntu --no-launch`
3. **Reboot handling** — if a reboot is needed, the script registers itself under `HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce` and resumes automatically after login
4. **Ubuntu user** — created non-interactively, no prompt for the end user:
   ```bat
   ubuntu.exe install --root
   wsl -u root -- useradd -m -s /bin/bash mume
   wsl -u root -- bash -c "echo 'mume:mume' | chpasswd"
   wsl -u root -- bash -c "printf '[user]\ndefault=mume\n' >> /etc/wsl.conf"
   ```
5. **Packages** — `apt install -y tintin++ lua5.4 tmux` inside Ubuntu
6. **WSL network** — writes `C:\Users\<you>\.wslconfig` with `networkingMode=mirrored` (required for mmapper on localhost:4242 to be reachable from WSL)
7. **MUME files** — copies project into `~/MUME/` inside Ubuntu (or clones from GitHub if hosted there)
8. **Alacritty** — installs via `winget install Alacritty.Alacritty`, then writes the config file to `%APPDATA%\alacritty\alacritty.toml` (colors, font, cursor, scrollback — see `misc/WSL and Terminal settings`)
9. **Shell entrypoint** — sets Alacritty's shell to `wsl.exe -- bash -c "cd ~/MUME && ./start.sh"` in the config
10. **Desktop shortcut** — creates a `.lnk` pointing to Alacritty on the user's desktop

### User experience

1. Right-click `.bat` → Run as administrator (UAC prompt — unavoidable)
2. If WSL2 was not already enabled: one automatic reboot, installer resumes on login
3. Alacritty opens with the client running — no further steps

### Licensing

The script only automates installation from official sources (Microsoft/Canonical/apt/winget).
No third-party binaries are bundled. Safe to distribute on GitHub or directly to friends.

---

## For AI Assistants
- This file is the source of truth for the project
- `ttpp_manual.txt` is the TinTin++ reference manual — consult it for tt++ syntax, commands, and settings
- Do not redesign core architecture unless explicitly asked
- New events must follow the protocol: `TYPE:arg1:arg2:...`
- Latency-critical logic belongs in tt++ (triggers/aliases), not Lua
- Lua is for state, timers, comms and non-latency-critical logic
- New automation features go in `lua/scripts/` as self-contained `.lua` files
- No paired .tin files for Lua-based features — one file per script
- All code and comments should be in English
- Follow the conventions defined in the Coding Conventions section
- Never hardcode session names (`"mume"`) in scripts or tt++ files
- Use `game_cmd()` for `#alias` registration
- Use `session_cmd()` for `#action`, `#unaction`, `#delay`, `#undelay`
- Use `send()` for MUD commands
- `GAME_SESSION` may be nil if no game session is connected — all functions guard against this safely

### Logging Guidelines

**UI LOG (`logs/ui.log`)** — game-relevant information the player cares about:
- Game-relevant state changes (target acquired/changed, spell changes, buffs added or about to drop, etc.)
- Communication (tells, says, narrates etc.)
- Not combat events — not damage hits, not HP threshold crossings, not reflexes like stunned

**DEV LOG (`logs/debug.log`)** — technical/diagnostic information:
- Errors and unexpected input
- Technical state transitions
- Function entry points for debugging (`get_state called`, `get_tells called`)
- Unknown or unhandled events

**Script load messages.** On load, a script emits a single `dbg()` line of the form `[SCRIPTNAME] loaded` — nothing more. Alias/trigger registration details belong in the script's `cp -<name>` help box (via `register_script`), not in the startup log. The load line is a liveness signal, not a manifest.

**Rules:**
- Never log the same event to both panes redundantly — `ui()` already mirrors to dev with a `UI:` prefix, so never follow a `ui()` call with a `dbg()` for the same message
- Log to UI only when something meaningful changes, not on every trigger fire, you need to ask what is appropriate to log when new content is added
- Unknown events go to dev only, not UI

## Installed Scripts

### autostab (`lua/scripts/autostab.lua`)
Alias: `as<dir>` (e.g. `ase`, `asw`)

Backstab/escape loop. Moves in a direction, backstabs `$target`, then escapes
back. On success repeats the cycle; on escape failure retries up to 2 times then
flees and stops. Stops automatically if the target dies, disappears, or no
trigger fires within 10 seconds. Uses `game_cmd` for alias registration and
`session_cmd` for trigger and delay lifecycle. Public API exposed under
`scripts.autostab`.

### autobow (`lua/scripts/autobow.lua`)
Alias: `ash<dir>` (e.g. `ashe`, `ashw`)

Shoot/escape loop for bow and crossbow. Moves in a direction, shoots `$target`,
then escapes back. Auto-detects weapon type from server response on first shot —
crossbow reloads between shots, bow skips reload. On escape failure retries up
to 2 times then flees and stops. Stops automatically if the target dies,
disappears, or no trigger fires within 15 seconds. Uses `game_cmd` and
`session_cmd`. Public API exposed under `scripts.autobow`.

### char_state (`lua/scripts/char_state.lua`)
Passive GMCP collector — no alias, no public API.

Subscribes to Char.Name, Char.StatusVars, and Char.Vitals. Each body is
merged flat into `state.char.*` with kebab-case keys converted to
snake_case. On every XP increase, emits `[CHAR] xp gained: +N (total M)`
to debug.log. Otherwise silent.

### comm_log (`lua/scripts/comm_log.lua`)
Passive GMCP collector — no alias, no public API.

Handles Comm.Channel.Text (message history, ring-buffered at 500),
Comm.Channel.List (available channels stored in `state.comm.channels`), and
drives channel enabling dynamically from the received list via the tt++ alias
`gmcp_enable_channel`. No hardcoded channel list.

### core_state (`lua/scripts/core_state.lua`)
Passive GMCP collector — no alias, no public API.

Logs arrival of Core.Goodbye (for future disconnect-flow work) and records
the timestamp of the most recent Core.Ping in `state.core.last_ping`.

### world_state (`lua/scripts/world_state.lua`)
Passive GMCP collector — no alias, no public API.

Handles Event.Darkness, Event.Moon, Event.Moved, and Event.Sun. Stores
each decoded body into the corresponding `state.world.<event>` field.

## Current Status
- [x] GMCP data collection — iteration 2a
      (trace flag + generic collectors for Char.*, Comm.Channel, Event.Darkness, Event.Sun)
- [x] GMCP data collection — iteration 2b-i
      (comm.channel correction, dynamic channel enabling,
      full event coverage, Core.Goodbye scaffold,
      MUME GMCP documented)
- [ ] GMCP disconnect flow — iteration 2b-ii
      (Core.Goodbye + SESSION DISCONNECTED drive popup with
      mode-aware reconnect)
- [x] GMCP infrastructure (telnet negotiation, dkjson, gmcp.dispatch)
- [x] tt++ + Lua integration via #run
- [x] Event protocol (DMG, TELL, EVENT, TARGET, HP)
- [x] cp command system with dynamic help box
- [x] Persistent UI and debug logs
- [x] Hot-reload via cp -r
- [x] Auto-loading of tt++ modules and Lua scripts
- [x] Self-contained Lua script pattern (autostab as reference implementation)
- [x] autobow script (bow/crossbow shoot-escape loop with weapon auto-detection)
- [x] Dynamic game session tracking (GAME_SESSION / $game_session)
- [x] Single game session enforcement (intruder zap)
- [x] game_cmd() / session_cmd() — no hardcoded session names in scripts
- [x] cp -r fully dynamic — no hardcoded session names
- [x] Input pane (prompt_toolkit, highlight, repeat, scroll, focus return)
- [ ] Live server connection
- [ ] Real server trigger mapping
- [ ] Spell timer system
- [ ] Affect tracker
- [ ] Tells history UI
- [ ] PvP keybinds finalized
- [x] Session settings persistence (#class-based, auto-save on deactivate)
- [x] Pre-tmux startup menu (retro DOS-style, bash+ANSI, launcher.sh / menu_render.sh)
- [x] Profile and connection wiring (startup.conf → _profile/_host/_port/_ses_cmd → connect alias)
- [x] TLS for direct connections (_ses_cmd=ssl uses #ssl instead of #ses)
- [x] Clean client startup (MOTD suppression, welcome banner,
  auto-connect, game_session-guarded cp -r)
- [x] In-game popup menu (status header, Options, Scripts,
      Save profile, context-aware Continue/Reconnect)
- [x] GitHub version check with cached update indicator
- [x] Self-update ("Update" in launcher menu, guarded for developer checkouts)
- [x] Constant ping monitor with link quality indicator

## Roadmap

### Phase 5 — GMCP infrastructure ✓
- `lua/lib/dkjson.lua` bundled; `package.path` extended in `brain.lua`
- `gmcp` namespace in Lua: `handlers`, `modules`, `dispatch`
- `ttpp/core/gmcp.tin`: telnet negotiation, Core.Hello, Core.Supports.Set, SB dispatch
- Subscribed modules: Char 1, Comm.Channel 1, Event 1

### Phase 2 — Profile and connection wiring ✓
- `ttpp/core/config.tin` reads `bridge/startup.conf` via `bridge/read_config.sh`
  at startup and materialises `_profile`, `_host`, `_port`, `_ses_cmd` tt++ variables
- `#alias {connect}` opens `#$_ses_cmd {$_profile} {$_host} {$_port}` — `_ses_cmd`
  is `ses` (mmapper, plain telnet) or `ssl` (direct, TLS); session is named after
  the profile, so SESSION CONNECTED naturally loads the right `ttpp/sessions/<profile>.tin`
- `default` and `mume` are retained as legacy aliases that call `connect`
  (not advertised in the cockpit help box)
- cockpit help shows a single `connect` entry under Connection

### Phase 3 — In-game popup menu ✓
- ESC from any pane opens a tmux display-popup overlay (tmux root
  keybinding in `tmux_start.sh`, works regardless of pane focus). [3a]
- Popup renders via `bridge/ingame_menu.sh`, sharing `bridge/menu_render.sh`
  helpers with the launcher. [3a]
- `bridge/toggle_pane.sh` extracted from the `cp -u/-d/-i/-h` aliases;
  accepts an optional `--persist` flag used by the popup to write
  `startup.conf`. [3b.1]
- Status header at the top of the popup shows Profile · Mode · Link.
  Backed by `bridge/session.state` (connection status) and
  `bridge/ping.cache` (link quality). [3b.2]
- Options submenu: UI / Dev / Input / Pane headers toggles. State
  re-probed from tmux on every render — never cached. Toggles call
  `toggle_pane.sh --persist` directly, so no `cp -X` echo appears in the
  game pane. [3b.3]
- Scripts submenu: ports launcher's Scripts page. Reads `scripts.cache`
  on each render. Scrollable. Rendering duplicated (not shared via
  `menu_render.sh`) to keep the shared helper stable. [3b.4]
- Save profile row (always visible — save works even after link loss, since
  tt++ keeps the disconnected session alive) triggers `cp -s` via
  `tmux send-keys`; inline "Saved ✓" flashes in `_MR_ACCENT` for ~1 s. [3b.5]
- Context-aware top menu item: "Continue" when connected (dismisses
  popup) or "Reconnect" when disconnected (fires `connect` alias then
  dismisses). Rebuilt from `bridge/session.state` on every render. [3b.5]

Explicitly NOT in the popup (deliberate scope trims):
- About page — not enough value to justify the code.
- Reload — `cp -r` from the input pane is the intended path.
- Profile switch / connection mode — launcher-only; requires restart.
- Layout mockup — saves vertical space in the popup.

### Phase 4a — Popup ping monitor  ✗ SUPERSEDED
Sparkline in popup, popup-local lifecycle. Replaced by 4b.

### Phase 4b — Constant ping monitor with link quality  ✓
Always-running monitor tied to tmux session lifecycle.
Quality summarised as a single word (stable / ok / jittery /
spiking / poor / dead) via p95−p50 spread analysis over
60-sample ring buffer. Shown inline in popup status header.
Uptime removed from header. [4b]

### Phase 3c — Polish ✓
- Version check footer on the launcher About page (top-right, always
  visible). Background refresh on launcher start, 6h cache, graceful
  offline handling. [3c]
- Conditional "Update" row in launcher main menu (appears only when
  version.cache indicates a newer tag). Safe self-update with
  triple-guard protection for developer checkouts. Version comparison
  normalised for "v" prefix. [3c]

Parked for later (post-3c):
- Version check footer
- Reset layout to defaults
- Live script dashboard (IDLE/RUNNING/FIRING tags)
- Stop-all-scripts emergency button
- Pane dimming
