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
│   │                     #   welcome.tin — clean boot banner + auto-connect
│   │                     #   system.tin  — connection aliases, cp commands, session events
│   └── sessions/         # Per-profile personal settings (.tin files)
│
├── lua/
│   ├── brain.lua         # Lua brain — infrastructure, event loop, auto-loads scripts/
│   └── scripts/          # Self-contained Lua automation scripts (.lua files)
│
├── bridge/
│   ├── launcher.sh           # Pre-tmux startup menu (DOS-style, pure bash)
│   ├── menu_render.sh        # Render/input helpers sourced by launcher.sh
│   ├── tmux_start.sh         # tmux session creation (extracted from start.sh)
│   ├── read_config.sh        # Emits tt++ #var assignments from startup.conf
│   ├── quotes.txt            # Tolkien quotes shown on main menu (pipe-sep format)
│   ├── about.txt             # About page body text
│   └── scripts.cache         # Script registry written by brain.lua (gitignored)
│   ├── open_pane.sh          # Opens/manages tmux panes dynamically
│   ├── input_pane.py         # Input pane — prompt_toolkit CLI, forwards to TT++
│   ├── focus_input.sh        # Resolves input pane index at click time (MouseUp1Pane target)
│   ├── on_window_resize.sh   # Fired on terminal resize — re-applies stored layout
│   ├── on_pane_resize.sh     # Fired on border drag — saves new layout values
│   ├── layout.conf           # Persisted layout state (gitignored)
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
bridge/.layout_lock
bridge/.pane_resize_pid
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
| `cp -r`       | Full reload                     |
| `cp -e`       | Full shutdown                   |
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
| Profile page | Lists `ttpp/sessions/*.tin`; select, create (blank / copy from existing), delete. `default` cannot be deleted. Profile selection is cosmetic in Phase 1 (written to `startup.conf`; not yet read by tt++) |
| Options page | Toggle UI / Dev / Input panes; pane dividers; connection mode; live layout mockup (updates on divider toggle). Content hides progressively at small heights: descriptions → mockup → section headings; menu items always render |
| Scripts page | Reads `bridge/scripts.cache`; scrollable |
| About page | Reads `bridge/about.txt`; word-wrapped, cached per resize, scrollable |
| Quit | Confirmation prompt; ESC cancels |
| Persistence | Options saved to `bridge/startup.conf` on Back / ESC |

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
  `Type 'cp' for available commands.` hint, and `Connecting to MUME...`.
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
| `show_pane_dividers` | `1`     | Whether tmux pane borders and the pane-border-status bar are visible at startup. `cp -h` toggles this at runtime without writing back to conf. |
| `profile`         | `default`  | Which file in `ttpp/sessions/` to load; also the tt++ session name |

Toggle panes at runtime with `cp -u`, `cp -d`, `cp -i`.

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
- [x] Session settings persistence (#class-based, auto-save on deactivate)
- [x] Pre-tmux startup menu (retro DOS-style, bash+ANSI, launcher.sh / menu_render.sh)
- [x] Profile and connection wiring (startup.conf → _profile/_host/_port/_ses_cmd → connect alias)
- [x] TLS for direct connections (_ses_cmd=ssl uses #ssl instead of #ses)
- [x] Clean client startup (MOTD suppression, welcome banner,
  auto-connect, game_session-guarded cp -r)

## Roadmap

### Phase 2 — Profile and connection wiring ✓
- `ttpp/core/config.tin` reads `bridge/startup.conf` via `bridge/read_config.sh`
  at startup and materialises `_profile`, `_host`, `_port`, `_ses_cmd` tt++ variables
- `#alias {connect}` opens `#$_ses_cmd {$_profile} {$_host} {$_port}` — `_ses_cmd`
  is `ses` (mmapper, plain telnet) or `ssl` (direct, TLS); session is named after
  the profile, so SESSION CONNECTED naturally loads the right `ttpp/sessions/<profile>.tin`
- `default` and `mume` are retained as legacy aliases that call `connect`
  (not advertised in the cockpit help box)
- cockpit help shows a single `connect` entry under Connection

### Phase 3 — In-game popup menu (planned)
- ESC from any pane opens a `tmux display-popup` overlay (tmux root
  keybinding in `tmux_start.sh`, not prompt_toolkit — works regardless of
  which pane has focus or whether the input pane exists)
- Popup renders via a new `bridge/ingame_menu.sh` that sources
  `bridge/menu_render.sh` — same colours, layout, and input handling
  as the launcher
- Menu items: Continue (dismiss), Options (shared sub-menu with the
  launcher), Scripts, About, Quit (confirmed)
- Quit triggers the existing `cp -e` path via `tmux send-keys` — no
  architectural changes to PROGRAM TERMINATION
- ESC inside the popup closes it; ESC in-game re-opens it
- Background game continues running while the popup is open
