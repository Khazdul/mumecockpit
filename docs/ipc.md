# tt++ ↔ Lua IPC

Full specification for inter-process communication between TinTin++ and the
Lua brain: the two dispatch patterns, relay action mechanics, brace handling,
and startup ordering. Touch this file when adding a new IPC pattern, debugging
lost events, or changing the startup sequence.

## tt++ → Lua: two patterns

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

> **Caveat — `SENT OUTPUT` must be session-scoped.** A top-level
> `#event {SENT OUTPUT}` fires in every session context, including the `lua`
> `#run` session. Each `#lua {…}` call writes to the lua subprocess stdin,
> which itself counts as a SENT OUTPUT in that session — registering the
> event globally causes immediate self-amplifying recursion that floods tt++
> within seconds of connect. Always register `SENT OUTPUT` via `session_cmd`
> (targeting GAME_SESSION only) so that only MUD-bound bytes are captured.

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

`USER_INPUT` and `EMPTY_INPUT` are the two cross-cutting input-IPC event
types. Both follow Pattern 1 and are owned by core ttpp infrastructure,
not by any one consumer module.

`USER_INPUT` is dispatched from the canonical `#event {SENT OUTPUT}`
handler registered by `_register_run_log_capture` in
`ttpp/core/run_log.tin` — the same handler that writes outbound commands
to the per-run `.log`, with the `USER_INPUT` dispatch sitting in a second
`#if {"%0" != ""} {#lua {USER_INPUT:%0}}` branch alongside the log-write
branch.

`EMPTY_INPUT` is registered by `_register_input_ipc_actions` in
`ttpp/core/input_ipc.tin` as
`#event {RECEIVED INPUT} {#if {"%0" == ""} {#lua {EMPTY_INPUT}}}`,
invoked from `SESSION CONNECTED` in `ttpp/core/system.tin`.

`brain.lua`'s `USER_INPUT` handler rejoins the IPC parts with `":"`
before emitting `user_input`, because raw player input may itself
contain `":"`. `EMPTY_INPUT` carries no payload — the empty-`%0` guard
in the tt++ rule makes the handler unconditional. See the `SENT OUTPUT`
caveat above for why session-scoping is mandatory; both registrations
are scoped via `#%1` precisely for this reason.

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

## Lua → tt++

Two mechanisms, depending on whether the command contains braces:

**`tintin_cmd(ses, cmd)`** — for TT++ commands that contain `{}` (actions, aliases, delays):
Writes `#ses cmd` to a unique `bridge/ipc/cmd_N.tin` file, prints `tintin_read <path>`.
TT++ reads the file via `#read` and the `#ses` prefix dispatches to the target session.
Braces in the file are never passed through wildcard substitution — they survive intact.
Unique filenames prevent race conditions when multiple calls happen in rapid succession.

Each `tintin_cmd` call produces exactly one `#ses cmd` file. A semicolon-chained
`cmd1;cmd2` written as a single `#ses cmd1;cmd2` line would NOT dispatch both
statements to `ses` — only `cmd1` runs in `ses`; `cmd2` falls back to the `lua`
session context. To put multiple statements in one input line and have each one
land in `ses`, every statement must carry its own `#ses` prefix:
`#ses cmd1;#ses cmd2`. tt++ services other sessions' socket input only between
input lines, so all statements on a single `;`-separated line run as one atomic
unit relative to foreign sessions.

`game_cmd` and `session_cmd` rely on this single-line atomicity to bracket each
registration with `#class {core} {open}` / `#class {core} {close}`. The earlier
implementation issued the triple as three separate `tintin_cmd` calls and relied
on Lua-single-threaded FIFO adjacency. That was unsound: FIFO guarantees the
three `#read`s happen in ORDER, not that no foreign trigger runs BETWEEN them.
tt++ tracks "last opened class" with a single global slot; a `#class`-manipulating
trigger firing in another session between the three `#read`s could overwrite that
slot mid-triple, and the `#action` would then register under whatever class the
foreign trigger left open instead of `{core}` — leaking into the saved profile on
`cp -s`. The current implementation consolidates the triple into a single input
line in one relay file, removing the interleaving window. See ADR 0097.

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

**`tintin_show(ses, msg)`** — for `#showme` display (messages rarely contain braces):
```lua
tintin_show(GAME_SESSION, "some message")
```
```tintin
#action {tintin_show (%1) %2} {#%1 #showme %2}
```

## Lua → UI pane

Lua appends to `logs/ui.log` — persists across pane toggles:
```lua
ui_log_fh:write(msg .. "\n")
```

## Lua → Dev pane

Timestamped debug output to `logs/debug.log`:
```lua
debug_fh:write(os.date("[%H:%M:%S] ") .. msg .. "\n")
```

## Startup order in `main.tin`

Relay actions that catch Lua stdout **must be registered before `#run {lua}`**.
Lua begins executing scripts immediately on startup and emits output before
`main.tin` finishes — if the actions aren't in place, that output is lost.

```tintin
#action {tintin (%1) %2}      {#%1 %2}      -- registered first
#action {tintin_read %1}      {#read %1}    -- registered first
#run {lua} {lua lua/brain.lua}              -- Lua starts after
```

## Startup order in `brain.lua`

The brain logs its own start via `dbg()` before calling `load_scripts()`, and
emits an `N scripts loaded.` summary via `dbg()` after. Both are dev-pane-only
— the UI pane stays clean of plumbing events and shows only user-relevant state
transitions (game session connect/disconnect, etc.).

---
Back to [architecture.md](../architecture.md).
