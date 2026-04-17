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
├── architecture.md       # This file
├── ttpp_manual.txt       # TinTin++ reference manual
│
├── ttpp/
│   ├── main.tin          # tt++ entry point — auto-loads all of core/
│   └── core/             # All tt++ modules (.tin files), auto-loaded
│
├── lua/
│   ├── brain.lua         # Lua brain — infrastructure, event loop, auto-loads scripts/
│   └── scripts/          # Self-contained Lua automation scripts (.lua files)
│
├── bridge/
│   ├── open_pane.sh      # Opens/manages tmux panes dynamically
│   └── input_pane.py     # Input pane — prompt_toolkit CLI, forwards to TT++
│
└── logs/
    ├── ui.log            # Persistent UI output (shown in ui pane)
    └── debug.log         # Lua debug output (shown in dev pane)

## Architecture Overview
┌──────────────────────────────────────────┐
│               MUD SERVER                 │
└─────────────────┬────────────────────────┘
                  │ telnet
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
    script_ui(name, msg)      — structured status line in UI pane
    tintin(ses, cmd)          — send simple command to tt++ session
    tintin_cmd(ses, cmd)      — send brace-containing command via temp file
    tintin_show(ses, msg)     — #showme in a specific session
    send(cmd)                 — send MUD command to game session
    game_cmd(cmd)             — register in gts + GAME_SESSION
    session_cmd(cmd)          — register in GAME_SESSION only
    set_game_session(ses)     — called by SESSION CONNECTED event
    clear_game_session(ses)   — called by SESSION DISCONNECTED event
    register_script(meta)     — register script in cockpit help system

### Startup order in `main.tin`
Relay actions that catch Lua stdout **must be registered before `#run {lua}`**.
Lua begins executing scripts immediately on startup and emits output before
`main.tin` finishes — if the actions aren't in place, that output is lost.

```tintin
#action {tintin (%1) %2}      {#%1 %2}      -- registered first
#action {tintin_read %1}      {#read %1}    -- registered first
#run {lua} {lua lua/brain.lua}              -- Lua starts after
```

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
| game    | Active game connection — name is dynamic, default `mume` |

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

### Registration functions

Scripts must never hardcode a session name. Use these functions:

| Function | Registers in | Use for |
|----------|-------------|---------|
| `game_cmd(cmd)` | gts + GAME_SESSION | `#alias`, `#substitute`, `#highlight` |
| `session_cmd(cmd)` | GAME_SESSION only | `#action`, `#unaction`, `#delay`, `#undelay` |
| `send(cmd)` | GAME_SESSION | MUD commands |
| `tintin_cmd(ses, cmd)` | specific session | internal use only |
| `tintin(ses, cmd)` | specific session | internal use only, no braces |

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
  any other pane returns focus to the input pane automatically

**Dependencies:**
- Python 3 (system)
- `prompt_toolkit` — install with:
  `pip install prompt_toolkit --break-system-packages`

**Known limitation:** drag-select in the TT++ pane does not auto-return
focus to the input pane. Click once in the input pane to return.

## Cockpit System
Unified window and system management via `cp` commands:

| Command       | Action                          |
|---------------|---------------------------------|
| `cp`          | Show help                       |
| `cp -i`       | Toggle input pane               |
| `cp -u`       | Toggle UI pane                  |
| `cp -d`       | Toggle dev pane                 |
| `cp -h`       | Toggle pane title headers       |
| `cp -s`       | Show pane layout + Lua state    |
| `cp -r`       | Full reload (tt++ + Lua)        |
| `cp -e`       | Kill tmux session               |
| `cp -<alias>` | Show help for installed script  |

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
./start.sh          # tt++ + UI pane + input pane (default)
./start.sh -d       # tt++ + UI pane + dev pane + input pane
./start.sh -u -d    # explicit — same as -d
```
UI and input panes are on by default.
Toggle panes at runtime with `cp -u`, `cp -d`, `cp -i`.

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
Lua scripts report key lifecycle events to the UI pane via `script_ui()` in `brain.lua`:

```lua
script_ui("AUTOSTAB", "Running")
script_ui("AUTOSTAB", "Stopped — target dead.")
script_ui("AUTOSTAB", "Stopped — timed out.")
```

Renders in the UI pane as:
```
▪ AUTOSTAB - Running
▪ AUTOSTAB - Stopped — target dead.
```

`▪ SCRIPTNAME` is teal (`#26C6DA`), the message is bright white. Colors use ANSI
escape codes (not TT++ format) since the UI pane is a plain terminal (`tail -f`).

**Rules:**
- Use `script_ui` for key state changes only: started, stopped, errors
- **Max 33 characters total** — `▪ AUTOSTAB - Stopped — timed out` is the limit
- Use "Stopped" when a script ends for any reason (not "aborted", "cancelled", etc.)
- No trailing periods — messages end with the last word, no punctuation
- One `script_ui` call per event — never call both `script_ui` and `ui()` for the same event
- The mume main window (`as_show` / `tintin_show`) is separate — use it for
  in-game context (e.g. `## AUTOSTAB: target: orc dir: west`), not for status

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
`session_cmd` for trigger and delay lifecycle.

### autobow (`lua/scripts/autobow.lua`)
Alias: `ash<dir>` (e.g. `ashe`, `ashw`)

Shoot/escape loop for bow and crossbow. Moves in a direction, shoots `$target`,
then escapes back. Auto-detects weapon type from server response on first shot —
crossbow reloads between shots, bow skips reload. On escape failure retries up
to 2 times then flees and stops. Stops automatically if the target dies,
disappears, or no trigger fires within 15 seconds. Uses `game_cmd` and
`session_cmd`.

## Current Status
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
- [ ] Session settings persistence (see Roadmap)

## Roadmap
1. Connect to live server and map real output to event protocol
2. Build prompt parser (HP, mana, moves from prompt line)
3. Spell timer system in Lua
4. Affect tracker (buffs/debuffs with countdowns)
5. Tells and comms UI section
6. PvP keybinds and combat aliases
7. Port existing scripts from previous client
8. **Player settings persistence** — player-created `#alias`, `#action`,
   `#variable` etc. are in-memory only and lost on restart/reload.
   `#write` dumps everything including core, so it can't be used directly.
   A `#class`-based approach was tried and abandoned — the open class
   captures script-registered triggers alongside user settings, making
   the save file unreliable. The challenge is saving only user additions
   separately from core. Needs a different solution before the client is
   used seriously.
