# MUME Project — Full Context
# Generated for use as AI prompt context.
# Contains all source files in the project.

---

# FILE: architecture.md
# (Source of truth — read this first)

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
│   └── open_pane.sh      # Opens/manages tmux panes dynamically
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
│  pane 0 (75%):  TinTin++ — game I/O     │
│  pane 1 (top):  ui    — tail ui.log     │
│  pane 2 (bot):  dev   — tail debug.log  │
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
`io.popen("ls ...")` + `dofile()` at startup. Each script runs in the global
environment and has access to all infrastructure functions from `brain.lua`
(`tintin`, `tintin_cmd`, `tintin_show`, `send`, `dbg`, `ui`, `script_ui`).

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
-- Alias in gts — available immediately at startup, inherited by mume on connect
tintin_cmd("gts", '#alias {as%1} {#lua {autostab_start("%1", "$target")}}')
-- Actions registered dynamically in mume when autostab activates
-- #unaction uses the exact pattern string — no labels
tintin_cmd("mume", "#action {You successfully escaped the fight!} {#lua {autostab_on_success()}}")
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
tintin_cmd("mume", "#action {pat} {body}")  -- registers trigger in mume
tintin_cmd("gts",  "#alias {name} {body}")  -- registers alias in gts
tintin_cmd("mume", "#delay {name} {cmd} {seconds}")
```
```tintin
#action {tintin_read %1} {#read %1}
```

**Which session to use:**
- `"gts"` — persistent aliases and named delays. gts always exists; aliases
  registered here are inherited by mume when it is created.
- `"mume"` — triggers (`#action`), delays that belong to an active MUD session.
  `#action` only fires on output in the session it is registered in — MUD output
  arrives in mume, so triggers must be in mume.

**`tintin_show(ses, msg)`** — for `#showme` display (messages rarely contain braces):
```lua
tintin_show("mume", "some message")
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

## TT++ Session Scoping

TT++ aliases and actions are **session-specific**, not global. New sessions
inherit the alias/action pool of the session that created them — but only at
creation time. Changes to the parent session afterwards do not propagate to
existing child sessions.

**Consequence for `cp -r` (reload):** the reload must run in the `gts` session
so that `#kill alias` clears the gts pool. When brain re-registers aliases in
gts after reload, the existing mume session picks them up through the shared
pool. If the reload runs in mume instead, aliases re-registered in gts are not
visible in mume. This is why `cp -r` begins with `#gts`.

**Alias session rules:**
- Register persistent aliases in `gts` — always exists, mume inherits on connect
- Register `#action` triggers in `mume` — triggers only fire on output in their
  own session; MUD output arrives in mume

## Cockpit System
Unified window and system management via `cp` commands:

| Command       | Action                          |
|---------------|---------------------------------|
| `cp`          | Show help                       |
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
   own aliases, triggers, and timers at load time via `tintin_cmd()`.
   This is the approved pattern for all automation features.

## Startup
```bash
./start.sh          # tt++ + UI pane (default)
./start.sh -d       # tt++ + UI pane + dev pane
./start.sh -u -d    # explicit — same as -d
```
UI pane is on by default. Toggle panes at runtime with `cp -u` and `cp -d`.

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
- Use `tintin_cmd("gts", ...)` for load-time aliases, `tintin_cmd("mume", ...)` for triggers
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

## Current Status
- [x] tt++ + Lua integration via #run
- [x] Event protocol (DMG, TELL, EVENT, TARGET, HP)
- [x] cp command system with dynamic help box
- [x] Persistent UI and debug logs
- [x] Hot-reload via cp -r
- [x] Auto-loading of tt++ modules and Lua scripts
- [x] Self-contained Lua script pattern (autostab as reference implementation)
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
8. **Player settings persistence** — player-created `#alias`, `#action`, `#variable`
   etc. are in-memory only and lost on restart/reload. `#write` dumps everything
   including core, so it can't be used directly. The challenge is saving only
   player additions separately from core. Needs a solution before the client is
   used seriously.

---

# FILE: start.sh

```bash
#!/bin/bash
cd "$(dirname "$0")"

# -----------------------------
# ARGUMENT PARSING
# -----------------------------
SHOW_DEV=0
SHOW_UI=1

for arg in "$@"; do
    case $arg in
        -d) SHOW_DEV=1 ;;
        -u) SHOW_UI=1 ;;
        -du|-ud) SHOW_DEV=1; SHOW_UI=1 ;;
    esac
done

echo "Starting MUME cockpit..."
[ $SHOW_UI  -eq 1 ] && echo "   UI pane:  ON"
[ $SHOW_DEV -eq 1 ] && echo "   Dev pane: ON"

# -----------------------------
# 1. INSTALL DEPENDENCIES
# -----------------------------
if ! command -v tmux >/dev/null 2>&1; then
    echo "Installing tmux..."
    sudo apt update && sudo apt install -y tmux
fi

if ! command -v lua >/dev/null 2>&1; then
    echo "Installing lua..."
    sudo apt update && sudo apt install -y lua5.4
fi

# -----------------------------
# 2. CREATE DIRS AND LOGS
# -----------------------------
mkdir -p bridge logs

chmod +x bridge/open_pane.sh

# Reset log files on each startup
touch logs/debug.log logs/ui.log
> logs/debug.log
> logs/ui.log

# -----------------------------
# 3. KILL OLD SESSION
# -----------------------------
tmux kill-session -t mume 2>/dev/null || true

# -----------------------------
# 4. CREATE SESSION
# -----------------------------
TERM_COLS=$(tput cols)
TERM_LINES=$(tput lines)

tmux new-session -d -s mume -x "$TERM_COLS" -y "$TERM_LINES" -n cockpit
tmux set-option -t mume status off
tmux set-option -t mume mouse on

# Pane borders — discrete dark grey
tmux set-option -t mume pane-border-status top
tmux set-option -t mume pane-border-format "#{?pane_title,#{pane_title},}"
tmux set-option -t mume pane-border-style "fg=colour238"
tmux set-option -t mume pane-active-border-style "fg=colour238"

# -----------------------------
# 5. BUILD LAYOUT BASED ON ARGUMENTS
# -----------------------------
RIGHT_WIDTH=33
LEFT_WIDTH=$(( TERM_COLS - RIGHT_WIDTH - 1 ))

if [ $SHOW_UI -eq 1 ] && [ $SHOW_DEV -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "tail -f $HOME/MUME/logs/ui.log"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux split-window -v -t mume:cockpit.1 "tail -f $HOME/MUME/logs/debug.log"
    tmux select-pane -t mume:cockpit.2 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ $SHOW_UI -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "tail -f $HOME/MUME/logs/ui.log"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ $SHOW_DEV -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "tail -f $HOME/MUME/logs/debug.log"
    tmux select-pane -t mume:cockpit.1 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

# -----------------------------
# 6. START TT++
# -----------------------------
tmux send-keys -t mume:cockpit.0 \
    "cd $HOME/MUME && tt++ ttpp/main.tin" C-m
tmux select-pane -t mume:cockpit.0 -T "MUME"

# -----------------------------
# 7. FOCUS TT++
# -----------------------------
tmux select-pane -t mume:cockpit.0
tmux attach -t mume
```

---

# FILE: ttpp/main.tin

```tintin
#nop ===== MAIN ENTRY POINT =====

#nop ===== TT++ DEFAULT SETTINGS =====
#nop Repeat last command with enter on empty line
#CONFIG {REPEAT ENTER} {ON}

#nop ===== CORE — auto-loaded from ttpp/core/ =====
#script {ls ttpp/core/*.tin 2>/dev/null | sed 's/^/#read /'}

#nop Catch commands from Lua — must be registered before #run {lua} so they exist
#nop when Lua starts and immediately emits output during script load.
#nop tintin(ses, cmd)  — relay for simple brace-free commands (MUD sends, etc.)
#action {tintin (%1) %2}      {#%1 %2}
#nop tintin_cmd — file-based relay for commands with braces (actions, delays, etc.)
#nop brain.lua writes the command to a unique file then signals via tintin_read.
#nop #read executes file content directly — braces are preserved, no session required.
#action {tintin_read %1}      {#read %1}
#action {tintin_show (%1) %2} {#%1 #showme %2}

#nop Start Lua as a sub-session
#run {lua} {lua lua/brain.lua}

#nop Return to startup session
#gts

#showme {[SYSTEM] Framework loaded.}

#nop Show cockpit info on startup — delay allows Lua to register _cockpit_help
#delay {0.5} {cp}
```

---

# FILE: ttpp/core/aliases.tin

```tintin
#nop ===== SEND HELPER =====
#nop _send <command>  — echo expanded command locally, then send to MUD.
#nop All MUD-sending aliases should route through this.
#nop Set _echo_sends to 0 to suppress echo (e.g. during scripted sequences).

#var {_echo_sends} {1}

#alias {_send %0} {
    #if {$_echo_sends == 1} {#showme {%0}};
    %0
}

#nop ===== CONNECTION ALIASES =====

#alias {mume} {
    #ses {mume} {localhost} {4242}
}

#nop ===== COCKPIT SYSTEM =====
#nop Direct cp aliases. {cp} has priority 6 so specific {cp -X} aliases (priority 5) win.
#nop Script aliases like {cp -autostab} are registered by Lua at startup.

#alias {cp -u} {
    #system {
        EXISTS=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^ui$');
        if [ -n "$EXISTS" ]; then
            tmux kill-pane -t $(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' | awk '/ui/{print "mume:cockpit." $1}');
        else
            bash $HOME/MUME/bridge/open_pane.sh ui;
        fi
    }
}

#alias {cp -d} {
    #system {
        EXISTS=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep '^dev$');
        if [ -n "$EXISTS" ]; then
            tmux kill-pane -t $(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' | awk '/dev/{print "mume:cockpit." $1}');
        else
            bash $HOME/MUME/bridge/open_pane.sh dev;
        fi
    }
}

#alias {cp -h} {
    #system {
        STATUS=$(tmux show-option -t mume pane-border-status | awk '{print $2}');
        if [ "$STATUS" = "off" ]; then
            tmux set-option -t mume pane-border-status top;
        else
            tmux set-option -t mume pane-border-status off;
        fi
    }
}

#alias {cp -s} {
    #showme {[COCKPIT] Active panes:};
    #system {
        tmux list-panes -t mume:cockpit -F '  #{pane_index}: #{pane_title} (#{pane_width}x#{pane_height})'
    }
}

#alias {cp -r} {
    #nop Switch to gts so all #kill and #read commands run in the gts context.;
    #nop This ensures re-registered aliases are in the gts pool inherited by all sessions.;
    #gts;
    #system {echo "[$(date '+%H:%M:%S')] COCKPIT RELOAD — wiping state" >> $HOME/MUME/logs/debug.log};
    #zap lua;
    #kill alias;
    #kill action;
    #kill substitute;
    #kill highlight;
    #kill variable;
    #kill macro;
    #kill delay;
    #mume #kill delay;
    #kill event;
    #read ttpp/main.tin;
    #showme {[COCKPIT] Full reload complete};
    #ses {mume}
}

#alias {cp -e} {
    #showme {[COCKPIT] Goodbye. Shutting down client...};
    #zap lua;
    #system {tmux kill-session -t mume}
}

#nop Priority 6 — fires only when no specific {cp -X} alias (priority 5) matches
#alias {cp} {_cockpit_help} {6}
```

---

# FILE: ttpp/core/triggers.tin

```tintin
#nop ===== EVENTS / TRIGGERS =====

#nop ===== SESSION EVENTS =====

#nop Return to gts when a game session disconnects (prevents falling through to lua session)
#event {SESSION DISCONNECTED} {
    #showme {[SYSTEM] Session %0 disconnected -- returning to gts};
    #session {gts}
}

#action {%1 hits you for %2 damage} {
    #lua handle_event("gts", "DMG:%2")
}

#action {%1 tells you '%2'} {
    #lua handle_event("gts", "TELL:%1:%2")
}

#action {You are stunned} {
    #lua handle_event("gts", "EVENT:stunned")
}

#alias {testevent} {
    #lua handle_event("gts", "DMG:15")
}
```

---

# FILE: ttpp/core/targeting.tin

```tintin
#nop ===== TARGETING =====
#nop
#nop   z              — display current target
#nop   z <target>     — set target and display
#nop
#nop Race shortcuts:
#nop   helf orc man hobbit elf dwarf bear troll
#nop
#nop Track aliases:
#nop   lm trt tw trd tm tp td tt

#nop ===== DISPLAY / SETTER =====

#alias {z} {
    #if {"%1" != ""} {
        #var {target} {%1}
    };
    #if {"$target" != ""} {
        #showme {<F9AA8B7>## TARGET: <FFFFFFF>$target<099>}
    } {
        #showme {<F9AA8B7>## TARGET: <099>(none)}
    }
}

#nop ===== RACE SHORTCUTS =====

#alias {helf}   {z *half-elf*}
#alias {bear}   {z *bear*}
#alias {troll}  {z *troll*}
#alias {orc}    {z *orc*}
#alias {man}    {z *man*}
#alias {hobbit} {z *hobbit*}
#alias {elf}    {z *elf*}
#alias {dwarf}  {z *dwarf*}

#nop ===== TRACK ALIASES =====

#alias {lm}  {_send label m}
#alias {trt} {_send track $target}

#alias {tw} {
    #if {"$target" == "*orc*"} {
        _send track warg
    } {
        _send track warhorse
    }
}

#alias {trd} {_send track dales}
#alias {tm}  {_send track mule}

#alias {tp} {
    #if {"$target" == "*hobbit*" || "$target" == "*dwarf*"} {
        _send track pony
    } {
        _send track pack
    }
}

#alias {td} {_send track donkey}
#alias {tt} {_send track trained}
```

---

# FILE: ttpp/core/spells.tin

```tintin
#nop ===== SPELLS =====
#nop Variables: spell (current spell, with quotes), ss (cast speed)
#nop
#nop   Speed setters:
#nop     quick fast normal norm car thor
#nop
#nop   Spell setters:
#nop     mm arm chill ct bh burn grasp bolt spray
#nop     smother smoth smo blind clight charm
#nop     sleep fball fireball silence disp edrain harm hold
#nop
#nop   _show_spell       — display current spell
#nop   _show_spell_speed — display current spell speed
#nop
#nop Usage: cast $ss $spell          (no target)
#nop         cast $ss $spell $target  (with target)
#nop
#nop Spell names are stored WITH surrounding single quotes so they
#nop expand correctly in cast commands, e.g. cast quick 'fireball' orc

#var {spell} {}
#var {ss}    {normal}

#nop ===== STATE DISPLAY =====

#alias {_show_spell} {
    #if {"$spell" != ""} {
        #showme {<F9AA8B7>## SPELL: <FFFFFFF>$spell<099>}
    } {
        #showme {<F9AA8B7>## SPELL: <099>(none)}
    }
}

#alias {_show_spell_speed} {
    #showme {<F9AA8B7>## SPELL-SPEED: <FFFFFFF>$ss<099>}
}

#nop ===== SPELL SPEED =====

#alias {quick}  {#var {ss} {quick};       _show_spell_speed}
#alias {fast}   {#var {ss} {fast};        _show_spell_speed}
#alias {normal} {#var {ss} {normal};      _show_spell_speed}
#alias {norm}   {#var {ss} {normal};      _show_spell_speed}
#alias {car}    {#var {ss} {careful};     _show_spell_speed}
#alias {thor}   {#var {ss} {thoroughly};  _show_spell_speed}

#nop ===== SPELL SETTERS =====

#alias {mm}       {#var {spell} {'magic missile'};   _show_spell}
#alias {chill}    {#var {spell} {'chill touch'};     _show_spell}
#alias {ct}       {#var {spell} {'chill touch'};     _show_spell}
#alias {bh}       {#var {spell} {'burning hands'};   _show_spell}
#alias {burn}     {#var {spell} {'burning hands'};   _show_spell}
#alias {grasp}    {#var {spell} {'shocking grasp'};  _show_spell}
#alias {bolt}     {#var {spell} {'lightning bolt'};  _show_spell}
#alias {spray}    {#var {spell} {'colour spray'};    _show_spell}
#alias {smother}  {#var {spell} {'smother'};         _show_spell}
#alias {smoth}    {#var {spell} {'smother'};         _show_spell}
#alias {smo}      {#var {spell} {'smother'};         _show_spell}
#alias {blind}    {#var {spell} {'blindness'};       _show_spell}
#alias {clight}   {#var {spell} {'call lightning'};  _show_spell}
#alias {charm}    {#var {spell} {'charm'};           _show_spell}
#alias {sleep}    {#var {spell} {'sleep'};           _show_spell}
#alias {fball}    {#var {spell} {'fireball'};        _show_spell}
#alias {fireball} {#var {spell} {'fireball'};        _show_spell}
#alias {silence}  {#var {spell} {'silence'};         _show_spell}
#alias {disp}     {#var {spell} {'dispel evil'};     _show_spell}
#alias {edrain}   {#var {spell} {'energy drain'};    _show_spell}
#alias {harm}     {#var {spell} {'harm'};            _show_spell}
#alias {hold}     {#var {spell} {'hold'};            _show_spell}
```

---

# FILE: ttpp/core/spamdoors.tin

```tintin
#nop ===== SPAMDOORS =====
#nop Door targets: sd1 (primary), sd2, sd3
#nop
#nop   sd                    — display current targets
#nop   sd <d1>               — set sd1, display
#nop   sd <d1> <d2>          — set sd1+sd2, display
#nop   sd <d1> <d2> <d3>     — set all three, display
#nop   dx                    — reset sd1 to "exit", display
#nop   dx <exit>             — set sd1, display
#nop   dx <exit> <d2> <d3>   — set all three via dx, display
#nop
#nop All sends go through _send (defined in aliases.tin) for local echo.

#nop sd1 defaults to "exit" — covers the most common case out of the box
#var {sd1} {exit}
#var {sd2} {}
#var {sd3} {}

#nop ===== DISPLAY / SETTER =====

#alias {sd} {
    #if {"%1" != ""} {
        #var {sd1} {%1};
        #if {"%2" != ""} {#var {sd2} {%2}};
        #if {"%3" != ""} {#var {sd3} {%3}}
    };
    #var {_sd_line} {};
    #if {"$sd1" != ""} {#var {_sd_line} {$_sd_line<F9AA8B7> SD1: <FFFFFFF>$sd1}};
    #if {"$sd2" != ""} {#var {_sd_line} {$_sd_line<F9AA8B7>  SD2: <FFFFFFF>$sd2}};
    #if {"$sd3" != ""} {#var {_sd_line} {$_sd_line<F9AA8B7>  SD3: <FFFFFFF>$sd3}};
    #if {"$_sd_line" != ""} {
        #showme {<F9AA8B7>##$_sd_line<099>}
    } {
        #showme {<F9AA8B7>## (no spam doors set)<099>}
    }
}

#nop ===== SETTER =====

#alias {dx} {
    #if {"%1" == ""} {
        #var {sd1} {exit};
        sd
    } {
        #var {sd1} {%1};
        #if {"%2" != ""} {#var {sd2} {%2}};
        #if {"%3" != ""} {#var {sd3} {%3}};
        sd
    }
}

#nop ===== BLOCK DOOR =====

#alias {bd}  {_send cast n 'block door' $sd1}
#alias {be}  {_send cast n 'block door' $sd1 e}
#alias {bs}  {_send cast n 'block door' $sd1 s}
#alias {bw}  {_send cast n 'block door' $sd1 w}
#alias {bu}  {_send cast n 'block door' $sd1 u}
#alias {bed} {_send cast n 'block door' $sd1 d}
#alias {bdd} {_send cast q 'block door' $sd1}

#nop ===== CLOSE =====

#alias {c}  {_send close $sd1}
#alias {ce} {_send close $sd1 e}
#alias {cs} {_send close $sd1 s}
#alias {cw} {_send close $sd1 w}
#alias {cu} {_send close $sd1 u}
#alias {cd} {_send close $sd1 d}

#nop ===== LOCK =====

#alias {cc} {_send close $sd1;_send lock $sd1}
#alias {le} {_send lock $sd1 e}
#alias {ls} {_send lock $sd1 s}
#alias {lw} {_send lock $sd1 w}
#alias {lu} {_send lock $sd1 u}
#alias {ld} {_send lock $sd1 d}

#nop ===== UNLOCK =====

#alias {ue} {_send unlock $sd1 e}
#alias {us} {_send unlock $sd1 s}
#alias {uw} {_send unlock $sd1 w}
#alias {uu} {_send unlock $sd1 u}
#alias {ud} {_send unlock $sd1 d}

#nop ===== OPEN =====

#alias {oo} {_send unlock $sd1;_send open $sd1}
#alias {o}  {_send open $sd1}
#alias {oe} {_send open $sd1 e}
#alias {os} {_send open $sd1 s}
#alias {ow} {_send open $sd1 w}
#alias {ou} {_send open $sd1 u}
#alias {od} {_send open $sd1 d}

#nop ===== PICK =====

#alias {pd}  {_send pick $sd1}
#alias {pe}  {_send pick $sd1 e}
#alias {ps}  {_send pick $sd1 s}
#alias {pw}  {_send pick $sd1 w}
#alias {pu}  {_send pick $sd1 u}
#alias {ped} {_send pick $sd1 d}

#nop ===== SD2 SHORTCUTS =====

#alias {3} {_send open $sd2}
#alias {2} {_send close $sd2}
```

---

# FILE: ttpp/core/hotkeys.tin

```tintin
#nop ===== KEYBINDS =====

#macro {\eOP} {kill $target}
#macro {\eOQ} {defend}
#macro {\eOR} {flee}
```

---

# FILE: ttpp/core/highlights.tin

```tintin
#nop ===== HIGHLIGHTS =====

#nop --- Spell buffs (beneficial magic) ---

#substitute {^- shield} {<F55ffff>%0<900>}
#substitute {^- armour} {<F55ffff>%0<900>}
#substitute {^- strength} {<F55ffff>%0<900>}
#substitute {^- bless} {<F55ffff>%0<900>}
#substitute {^- protection from evil} {<F55ffff>%0<900>}
#substitute {^- detect magic} {<F55ffff>%0<900>}
#substitute {^- sense life} {<F55ffff>%0<900>}
#substitute {^- night vision} {<F55ffff>%0<900>}
#substitute {^- breath of briskness} {<F55ffff>%0<900>}
#substitute {^- shroud} {<F55ffff>%0<900>}
#substitute {^- detect evil} {<F55ffff>%0<900>}

#nop --- Stored spells ---

#substitute {- stored spell%1} {<F8c1ebb>%0<900>}

#nop --- Comfort and consumables ---

#substitute {^- comfortable} {<F00aa00>%0<900>}
#substitute {^- potion} {<F00aa00>%0<900>}
#substitute {^- very comfortable} {<F00aa00>%0<900>}
#substitute {^-%1draught%2} {<F00aa00>%0<900>}
#substitute {^-%1miruvor%2} {<F00aa00>%0<900>}

#nop --- Minor negative effects ---

#substitute {^- lethargy} {<Fffaa00>%0<900>}
#substitute {^- tiredness} {<Fffaa00>%0<900>}
#substitute {^- depressed} {<Fffaa00>%0<900>}
#substitute {^- haggardness} {<Fffaa00>%0<900>}

#nop --- Serious negative effects ---

#substitute {^-%1wound%2} {<Fff0000>%0<900>}
#substitute {^-%1disease%2} {<Fff0000>%0<900>}

#nop --- Sanctuary ---

#substitute {^- sanctuary} {<Ff700ff>%0<900>}

#nop --- Mob indicators ---

#substitute {^A pair of tiny eyes gleam at you from the shadows.} {<F00ffff>%0<900>}
#substitute {^%1(MIN)%2} {<F00ffff>%0<900>}

#nop --- Charmies and pets ---

#substitute {^%1(B)%2} {<F2ab464>%0<900>}
#substitute {^%1(AA)%2} {<F2ab464>%0<900>}
#substitute {^%1(BB)%2} {<F2ab464>%0<900>}
#substitute {^%1(CC)%2} {<F2ab464>%0<900>}
#substitute {^%1(DD)%2} {<F2ab464>%0<900>}

#nop --- Blinded mobs ---

#substitute {^%1 seems to be blinded!} {<F23aaee>%0<900>}
```

---

# FILE: ttpp/core/charmies.tin

```tintin
#nop ===== CHARMIES =====
#nop Follower/charmie commands. Named followers: aa, bb.
#nop Variables: character (group member to protect/rescue), mees (secondary follower target)

#var {character} {}
#var {mees} {}

#nop ===== VARIABLE SETTERS =====

#alias {char} {
    #if {"%1" != ""} {
        #var {character} {%1}
    };
    #if {"$character" != ""} {
        #showme {<F9AA8B7>## CHAR: <FFFFFFF>$character<099>}
    } {
        #showme {<F9AA8B7>## CHAR: <099>(none)}
    }
}

#alias {sm} {
    #if {"%1" != ""} {
        #var {mees} {%1}
    };
    #if {"$mees" != ""} {
        #showme {<F9AA8B7>## MEES: <FFFFFFF>$mees<099>}
    } {
        #showme {<F9AA8B7>## MEES: <099>(none)}
    }
}

#nop ===== GENERAL FOLLOWER ORDERS =====

#alias {aa}  {_send order followers assist}
#alias {ab}  {_send order bb bash}
#alias {bt}  {_send order bb bash $target}
#alias {of}  {_send order followers %0}
#alias {oft} {_send order followers flush t}
#alias {ok}  {_send order followers hit $target}
#alias {op}  {_send order followers protect $character}
#alias {or}  {_send order followers rescue $character}
#alias {bb}  {_send bash $target}

#nop ===== SPELL ORDERS =====

#alias {oht}  {_send order aa cast 'harm' $target}
#alias {obk}  {_send order bb hit $mees}
#alias {olb}  {_send order followers cast 'lightning bolt'}
#alias {olbt} {_send order followers cast 'lightning bolt' $target}
#alias {obh}  {_send order followers cast 'burning hands'}
#alias {obt}  {_send order followers cast 'burning hands' $target}
```

---

# FILE: ttpp/core/thief.tin

```tintin
#nop ===== THIEF =====
#nop Escape, arrow/bolt management, hide.

#var {acontainer} {quiver}
#var {arrow}      {arrow}

#nop ===== DISPLAY =====

#alias {_show_acontainer} {
    #showme {<F9AA8B7>## ARROW CONTAINER: <FFFFFFF>$acontainer  <F9AA8B7>(ammo: <FFFFFFF>$arrow<F9AA8B7>)<099>}
}

#nop ===== ARROW CONTAINER =====

#alias {acontainer} {
    #if {"%1" == "quiver" || "%1" == "case"} {
        #var {acontainer} {%1};
        #if {"$acontainer" == "quiver"} {
            #var {arrow} {arrow}
        } {
            #var {arrow} {bolt}
        };
        _show_acontainer
    } {
        #if {"%1" != ""} {
            #showme {<F9AA8B7>## ERROR: acontainer must be 'quiver' or 'case'<099>}
        } {
            _show_acontainer
        }
    }
}

#alias {quiver} {acontainer quiver}
#alias {case}   {acontainer case}

#nop ===== ARROWS =====

#alias {ga} {_send get all.$arrow;_send put all.$arrow $acontainer}

#nop ===== ESCAPE =====

#alias {en} {_send escape north}
#alias {ee} {_send escape east}
#alias {es} {_send escape south}
#alias {ew} {_send escape west}
#alias {eu} {_send escape up}
#alias {ed} {_send escape down}

#nop ===== HIDE =====

#alias {hn} {_send hide normal}
#alias {hq} {_send hide quick}
#alias {hf} {_send hide fast}
#alias {ht} {_send hide thorough}
```

---

# FILE: ttpp/core/eq.tin

```tintin
#nop ===== EQ MANAGEMENT =====
#nop Quick-swap aliases for tracked equipment slots.

#var {abody} {}
#var {ring}  {}

#nop ===== SWAP HELPERS =====

#alias {_eq_body} {
    #if {"%1" != "$abody"} {
        #if {"$abody" != ""} {_send rem $abody};
        _send get %1 pack;
        _send wear %1;
        #if {"$abody" != ""} {_send put $abody pack};
        #var {abody} {%1}
    }
}

#alias {_eq_ring} {
    #if {"%1" != "$ring"} {
        #if {"$ring" != ""} {_send rem $ring};
        _send get %1 sable;
        _send wear %1;
        #if {"$ring" != ""} {_send put $ring sable};
        #var {ring} {%1}
    }
}

#nop ===== BODY ALIASES =====

#alias {silvery} {_eq_body fur-cloak}
#alias {fgc}     {_eq_body forest}
#alias {forest}  {_eq_body forest}
#alias {ragged}  {_eq_body ragged}
#alias {bhc}     {_eq_body hooded}
#alias {fur}     {_eq_body fur}
#alias {grey}    {_eq_body fine-grey-cloak}
#alias {tainted} {_eq_body tainted-grey-cloak}
#alias {soot}    {_eq_body soot}
#alias {woven}   {_eq_body woven}
#alias {sacred}  {_eq_body sacred}
#alias {mantle}  {_eq_body mantle}

#nop ===== RING ALIASES =====

#alias {ccr}   {_eq_ring garnet-ring}
#alias {ob}    {_eq_ring rubyring}
#alias {db}    {_eq_ring sapphire}
#alias {rempr} {_eq_ring emerald-ring}
#alias {strr}  {_eq_ring topaz-ring}
#alias {iron}  {_eq_ring ironring}
#alias {opal}  {_eq_ring opal-ring}
#alias {wooden}{_eq_ring wooden}
#alias {mana}  {_eq_ring golden-ruby-ring}
#alias {sp}    {_eq_ring copperring}

#nop ===== MISC ALIASES =====

#alias {boots} {
    _send rem boots;
    _send wear 2.boots
}

#alias {gloves} {
    _send rem gloves;
    _send wear 2.gloves
}
```

---

# FILE: ttpp/core/consumables.tin

```tintin
#nop ===== CONSUMABLES =====
#nop Aliases for usable items (potions, powders, etc.)

#alias {powd} {_send use powder}
```

---

# FILE: lua/brain.lua

```lua
-- ===== LUA BRAIN =====
-- Communicates with tt++ via stdout/stdin (#run session)
-- UI output to logs/ui.log (persistent), debug to logs/debug.log

local UI_LOG    = "logs/ui.log"
local DEBUG_LOG = "logs/debug.log"

local TT_SESSION = "gts"

-- -----------------------------
-- LOGGERS
-- -----------------------------
local debug_fh  = io.open(DEBUG_LOG, "a")
local ui_log_fh = io.open(UI_LOG, "a")

function dbg(msg)
    if debug_fh then
        debug_fh:write(os.date("[%H:%M:%S] ") .. msg .. "\n")
        debug_fh:flush()
    end
end

function ui(msg)
    if ui_log_fh then
        ui_log_fh:write(msg .. "\n")
        ui_log_fh:flush()
    end
    dbg("UI: " .. msg)
end

-- script_ui(name, msg) — structured status line for the UI pane.
-- Format:  ▪ NAME - message
-- Use for key state changes only: started, stopped, errors.
-- Not for per-cycle noise or debug detail.
local _C_SCRIPT = "\027[38;2;38;198;218m"  -- teal  #26C6DA
local _C_TEXT   = "\027[97m"               -- bright white
local _C_RESET  = "\027[0m"

function script_ui(name, msg)
    ui(string.format("%s▪ %s%s - %s%s%s", _C_SCRIPT, name, _C_RESET, _C_TEXT, msg, _C_RESET))
end

-- -----------------------------
-- TT++ COMMUNICATION
-- tintin(ses, cmd)   — relay-based: run a simple TT++ command with no braces
-- tintin_cmd(ses, cmd) — file-based: run a TT++ command that contains braces
-- tintin_show(ses, msg) — #showme msg in session 'ses'
-- send(cmd)          — send a MUD command to the mume session
-- -----------------------------
local _tintin_cmd_seq = 0

function tintin(ses, cmd)
    print(string.format("tintin (%s) %s", ses, cmd))
    io.flush()
end

function tintin_cmd(ses, cmd)
    _tintin_cmd_seq = _tintin_cmd_seq + 1
    local path = string.format("logs/cmd_%d.tin", _tintin_cmd_seq)
    local f, err = io.open(path, "w")
    if not f then
        dbg("tintin_cmd ERROR: cannot open " .. path .. " — " .. tostring(err))
        return
    end
    -- The file contains "#ses cmd" so TT++ dispatches to the right session when read.
    f:write(string.format("#%s %s\n", ses, cmd))
    f:write(string.format("#system {rm -f %s}\n", path))
    f:close()
    print("tintin_read " .. path)
    io.flush()
end

function tintin_show(ses, msg)
    print(string.format("tintin_show (%s) %s", ses, msg))
    io.flush()
end

function send(cmd)
    dbg("SEND: " .. cmd)
    tintin("mume", cmd)
end

-- -----------------------------
-- SCRIPT REGISTRY
-- Scripts call register_script(meta) at load time; _register_cockpit_help()
-- builds _cockpit_help after all scripts load.
-- -----------------------------
local _scripts = {}
local _BOX_W   = 50

local function _pad(s, width)
    if #s > width then s = s:sub(1, width) end
    return s .. string.rep(" ", width - #s)
end

local function _box_row(content)
    return "#showme {║ " .. _pad(content, _BOX_W - 2) .. " ║}"
end

local function _build_box(title, body_lines)
    local hr    = string.rep("═", _BOX_W)
    local blank = "║" .. string.rep(" ", _BOX_W) .. "║"
    local parts = {}
    parts[#parts+1] = "#showme { }"
    parts[#parts+1] = "#showme {╔" .. hr .. "╗}"
    parts[#parts+1] = _box_row(title)
    parts[#parts+1] = "#showme {╠" .. hr .. "╣}"
    for _, l in ipairs(body_lines) do
        if l == "" then
            parts[#parts+1] = "#showme {" .. blank .. "}"
        else
            parts[#parts+1] = _box_row(l:gsub("[{}]", ""))
        end
    end
    parts[#parts+1] = "#showme {╚" .. hr .. "╝}"
    parts[#parts+1] = "#showme { }"
    return parts
end

function register_script(meta)
    _scripts[meta.alias] = meta
    local body = {}
    if meta.summary then
        body[#body+1] = "  " .. meta.summary
        body[#body+1] = ""
    end
    for _, l in ipairs(meta.help or {}) do
        body[#body+1] = "  " .. l
    end
    local parts = _build_box("  " .. meta.alias:upper(), body)
    tintin_cmd("gts", "#alias {cp -" .. meta.alias .. "} {" .. table.concat(parts, ";") .. "}")
    dbg("register_script: " .. meta.alias)
end

local function _register_cockpit_help()
    local body = {
        "  Connection:",
        "   mume              connect via MMapper",
        "",
        "  Window management:",
        "   cp -u       toggle UI pane",
        "   cp -d       toggle dev pane",
        "   cp -h       toggle headers",
        "   cp -s       show system status",
        "   cp -r       full system reload",
        "   cp -e       kill session",
        "",
    }
    if next(_scripts) then
        body[#body+1] = "  Scripts  (type cp -<name> for details):"
        local aliases = {}
        for a in pairs(_scripts) do aliases[#aliases+1] = a end
        table.sort(aliases)
        for _, a in ipairs(aliases) do
            local m = _scripts[a]
            body[#body+1] = string.format("   %-18s %s", "cp -" .. a, m.summary or "")
        end
        body[#body+1] = ""
    end
    local parts = _build_box("  COCKPIT SYSTEM", body)
    local body_str = table.concat(parts, ";")
    tintin_cmd("gts", "#alias {_cockpit_help} {" .. body_str .. "}")
    dbg("_register_cockpit_help: done")
end

-- -----------------------------
-- EVENT HANDLERS
-- Scripts register: handlers["TYPE"] = function(parts) ... end
-- -----------------------------
local handlers = {}

-- -----------------------------
-- EXPOSED FUNCTIONS (called via #lua from tt++)
-- -----------------------------
function handle_event(ses, line)
    dbg("EVENT IN: " .. line)

    -- Direct Lua call: functionname(args)
    if line:match("^[%w_]+%(") then
        local fn, err = load(line)
        if fn then
            local ok, err2 = pcall(fn)
            if not ok then dbg("LUA ERROR: " .. tostring(err2)) end
        else
            dbg("LUA SYNTAX ERROR: " .. tostring(err))
        end
        return
    end

    -- Structured event: TYPE:arg1:arg2:...
    local parts = {}
    for p in line:gmatch("[^:]+") do
        parts[#parts+1] = p
    end
    local typ = table.remove(parts, 1)
    local handler = handlers[typ]
    if handler then
        handler(parts)
    else
        dbg("UNKNOWN EVENT: " .. line)
    end
end

-- -----------------------------
-- MODULES — auto-loaded from lua/scripts/
-- -----------------------------
local function load_scripts()
    local p = io.popen("ls lua/scripts/*.lua 2>/dev/null")
    if p then
        for f in p:lines() do
            dofile(f)
        end
        p:close()
    end
    _register_cockpit_help()
end
load_scripts()

-- -----------------------------
-- STARTUP
-- -----------------------------
ui("=== LUA BRAIN STARTED ===")
dbg(string.format("session=%s, lua=%s", TT_SESSION, _VERSION))
tintin_show("gts", "Lua brain ready.")

-- Main loop
for line in io.lines() do
    handle_event(TT_SESSION, line)
end
```

---

# FILE: lua/scripts/autostab.lua
# (Reference implementation of the self-contained Lua script pattern)

```lua
-- ===== AUTOSTAB =====
-- Self-contained script. Registers alias on load — no paired .tin file needed.
--
-- Alias:  as<dir>  (e.g. ase = autostab east)
-- Flow:   go dir -> backstab $target -> escape retDir
--   on escape success: repeat cycle, reset watchdog
--   on escape fail:    retry escape up to 2 times per cycle, reset watchdog
--                      if both retries fail: flee + abort
--   on target dead/gone: abort
--
-- MUD triggers (success/fail/dead/gone) and watchdog (as_watch)
-- are registered dynamically by autostab_start() and cleaned up on abort.
-- Watchdog fires if no escape result is seen within WATCH_TIMEOUT seconds.

local RET           = { n="s", s="n", e="w", w="e", u="d", d="u" }
local WATCH_TIMEOUT = 10  -- seconds with no activity before auto-cancel

local as = {
    active      = false,
    dir         = nil,
    ret         = nil,
    target      = nil,
    retry_count = 0,
}

local function as_dbg(msg)
    dbg("[AUTOSTAB] " .. msg)
end

local function as_show(msg)
    tintin_show("mume", "<F9AA8B7>## AUTOSTAB: <FFFFFFF>" .. msg .. "<099>")
end

-- -----------------------------
-- TRIGGER LIFECYCLE
-- -----------------------------

local function register_triggers()
    tintin_cmd("mume", "#action {You successfully escaped the fight!} {#lua {autostab_on_success()}}")
    tintin_cmd("mume", "#action {You failed to escape the fight!} {#lua {autostab_on_fail()}}")
    tintin_cmd("mume", "#action {%1 is dead! R.I.P.} {#lua {autostab_on_dead()}}")
    tintin_cmd("mume", "#action {%1 disappears into nothing.} {#lua {autostab_on_gone()}}")
end

local function unregister_triggers()
    tintin_cmd("mume", "#unaction {You successfully escaped the fight!}")
    tintin_cmd("mume", "#unaction {You failed to escape the fight!}")
    tintin_cmd("mume", "#unaction {%1 is dead! R.I.P.}")
    tintin_cmd("mume", "#unaction {%1 disappears into nothing.}")
end

-- -----------------------------
-- WATCHDOG
-- -----------------------------

local function reset_watchdog()
    tintin_cmd("mume", string.format("#delay {as_watch} {#lua {autostab_watchdog()}} {%d}", WATCH_TIMEOUT))
end

-- -----------------------------
-- INTERNAL
-- -----------------------------

local function do_cycle()
    send(as.dir)
    send("backstab " .. as.target)
    send("escape "   .. as.ret)
end

local function abort(reason)
    as.active = false
    unregister_triggers()
    tintin_cmd("mume", "#undelay {as_watch}")
    as_dbg("stopped: " .. reason)
    script_ui("AUTOSTAB", "Stopped — " .. reason)
end

-- -----------------------------
-- PUBLIC API (called via #lua from tt++ triggers/aliases/delays)
-- -----------------------------

function autostab_start(dir, target)
    if not RET[dir] then
        as_show("bad direction: " .. tostring(dir))
        return
    end
    if not target or target == "" then
        as_show("no target set — use 'z <name>' first")
        return
    end

    if as.active then
        unregister_triggers()
        tintin_cmd("mume", "#undelay {as_watch}")
    end

    as.active      = true
    as.dir         = dir
    as.ret         = RET[dir]
    as.target      = target
    as.retry_count = 0

    register_triggers()
    reset_watchdog()

    as_dbg(string.format("start dir=%s ret=%s target=%s", dir, as.ret, target))
    as_show(string.format("target: %s dir: %s", as.target, as.dir))
    script_ui("AUTOSTAB", "Running")
    do_cycle()
end

function autostab_on_success()
    if not as.active then return end
    as.retry_count = 0
    reset_watchdog()
    as_dbg("escaped — repeating")
    do_cycle()
end

function autostab_on_fail()
    if not as.active then return end
    as.retry_count = as.retry_count + 1
    reset_watchdog()
    if as.retry_count <= 2 then
        as_dbg(string.format("escape failed (attempt %d/2) — retrying", as.retry_count))
        send("escape " .. as.ret)
    else
        as_dbg("escape failed 3 times — fleeing and aborting")
        send("flee")
        abort("fled")
    end
end

function autostab_on_dead()
    if not as.active then return end
    abort("dead")
end

function autostab_on_gone()
    if not as.active then return end
    abort("gone")
end

function autostab_watchdog()
    if not as.active then return end
    as.active = false
    unregister_triggers()
    as_dbg(string.format("watchdog: no activity for %ds — stopped", WATCH_TIMEOUT))
    script_ui("AUTOSTAB", "Stopped — timed out")
end

-- -----------------------------
-- SETUP — register alias on load, declare metadata
-- -----------------------------
tintin_cmd("gts", '#alias {as%1} {#lua {autostab_start("%1", "$target")}}')
register_script({
    alias   = "autostab",
    summary = "backstab/escape loop",
    help    = {
        "Usage:  as<dir>   e.g. ase, asw, asn, asu",
        "        Set target first: z <name>",
        "",
        "Cycle:",
        "  go dir -> backstab -> escape back",
        "",
        "On success: repeat the cycle",
        "On fail:    retry escape (up to 2x)",
        "            then flee and stop",
        "Target dead or gone: stop",
        "After 10s with no activity: stop",
    }
})
as_dbg("loaded — alias as<dir> registered")
```

---

# FILE: bridge/open_pane.sh

```bash
#!/bin/bash
TYPE=$1
MUME="$HOME/MUME"

# Exit if pane already exists
EXISTING=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep "^$TYPE$")
if [ -n "$EXISTING" ]; then
    exit 0
fi

COLS=$(tmux display-message -p '#{window_width}')
RIGHT_WIDTH=33
LEFT=$(( COLS - RIGHT_WIDTH - 1 ))

# Check if any right pane already exists
HAS_RIGHT=$(tmux list-panes -t mume:cockpit -F '#{pane_title}' | grep -E '^(ui|dev)$')

if [ -n "$HAS_RIGHT" ]; then
    RIGHT_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index} #{pane_title}' \
        | grep -E ' (ui|dev)$' | cut -d' ' -f1 | head -1)

    case $TYPE in
        ui)
            tmux split-window -v -t mume:cockpit.$RIGHT_INDEX \
                "tail -f $MUME/logs/ui.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            tmux swap-pane -s mume:cockpit.$NEW_INDEX -t mume:cockpit.$RIGHT_INDEX
            ;;
        dev)
            tmux split-window -v -t mume:cockpit.$RIGHT_INDEX \
                "tail -f $MUME/logs/debug.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            ;;
    esac
else
    case $TYPE in
        ui)
            tmux split-window -h -t mume:cockpit.0 \
                "tail -f $MUME/logs/ui.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "ui"
            ;;
        dev)
            tmux split-window -h -t mume:cockpit.0 \
                "tail -f $MUME/logs/debug.log"
            NEW_INDEX=$(tmux list-panes -t mume:cockpit -F '#{pane_index}' | tail -1)
            tmux select-pane -t mume:cockpit.$NEW_INDEX -T "dev"
            ;;
    esac
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT"
fi

tmux select-pane -t mume:cockpit.0
```

---

# FILE: misc/WSL and Terminal settings

```
# OS / ENVIRONMENT
#   - Windows with WSL2 + Ubuntu
#   - Project files live at ~/MUME/ inside Ubuntu
#
# WSL NETWORK SETTING (required for mmapper)
#   mmapper runs on Windows and listens on localhost:4242.
#   TinTin++ in Ubuntu connects to localhost:4242.
#   WSL2 must run in mirrored networking mode.
#
#   File: C:\Users\<you>\.wslconfig
#   Content:
#     [wsl2]
#     networkingMode=mirrored
#
# TERMINAL: Alacritty
# Config: %APPDATA%\alacritty\alacritty.toml

[colors.primary]
foreground = "#C0C0C0"
background = "#000000"

[colors.normal]
black   = "#000000"  red     = "#800000"  green   = "#008000"
yellow  = "#808000"  blue    = "#000080"  magenta = "#800080"
cyan    = "#008080"  white   = "#C0C0C0"

[colors.bright]
black   = "#808080"  red     = "#FF0000"  green   = "#00FF00"
yellow  = "#FFFF00"  blue    = "#0000FF"  magenta = "#FF00FF"
cyan    = "#00FFFF"  white   = "#FFFFFF"

[cursor]
style = { shape = "Beam", blinking = "On" }
blink_interval = 500
thickness = 0.15

[font]
size = 15
[font.normal]
family = "Lucida Console"

[scrolling]
history = 10000

[terminal.shell]
program = "wsl.exe"
```
