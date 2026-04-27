# Session Lifecycle

Everything about tt++ session creation, game session tracking, state
persistence, and clean startup flow. Touch this file when changing how
sessions are connected, disconnected, or reloaded, or when modifying
`bridge/session.state` consumers.

The client uses three tt++ sessions:

| Session | Role |
|---------|------|
| `gts`   | Global — always exists, entry point, alias pool |
| `lua`   | Lua subprocess — created by `#run`, never interacted with directly |
| game    | Active game connection — name is dynamic, default `default` |

## Dynamic game session tracking

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

## Runtime session state (`bridge/session.state`)

Tracks whether the player is connected to MUME — distinct from whether
the tt++ session is alive. In MMapper mode the tt++ ↔ MMapper socket can
be up while MUME itself has dropped; the two concepts must be tracked
separately.

### Signals

**Primary (both modes):**
- `Char.Name` GMCP → `mark_mume_connected()` — fires when MUME delivers
  the player's name after successful login.
- `Core.Goodbye` GMCP → `mark_mume_disconnected()` — fires on graceful
  MUME disconnect (e.g. `quit`).

**Secondary / fallback:**
- `"Status: MUME closed the connection."` text action (MMapper mode) →
  `mark_mume_disconnected()` — fires when MMapper detects an abrupt
  MUME-side drop while its own process stays alive.
- `SESSION DISCONNECTED` → `clear_game_session()` → `mark_mume_disconnected()`
  — fallback for direct-mode abrupt disconnects and for MMapper-process-death
  (entire MMapper process killed).

`mark_mume_disconnected()` is the **single dispatch point** for all disconnect
signals. Any signal that should trigger popup auto-open and session-state teardown
routes through it. The transition guard (no-op when state is already absent)
handles dedup automatically — the second signal for the same event finds state
already cleared and returns early.

### API

`mark_mume_connected()` and `mark_mume_disconnected()` (globals, `brain.lua`):
- Idempotent and transition-only: they detect current state via the existence
  of `SESSION_STATE_PATH` and only act — and only emit `system_ui` — on
  an actual disconnected→connected or connected→disconnected transition.
- `mark_mume_connected()` calls `_write_session_state()` (atomic temp+rename,
  reads `connection_mode` from `startup.conf`), then `system_ui("Connected to MUME.")`.
- `mark_mume_disconnected()` calls `_clear_session_state()`, emits
  `system_ui("Disconnected from MUME.")`, then auto-opens the popup if
  `bridge/.popup_open` is absent (see `docs/popup-menu.md` — Auto-open on disconnect).

`set_game_session()` no longer writes `session.state` — it only tracks tt++
session liveness. `clear_game_session()` delegates to `mark_mume_disconnected()`
(rather than calling `_clear_session_state()` directly) so the direct-mode
abrupt-drop path joins the single dispatch point. The belt-and-braces role
is unchanged; the transition guard in `mark_mume_disconnected()` keeps it
idempotent.

### Format

    connected_at=<epoch seconds>
    connection_mode=<mmapper|direct>

Written atomically via temp-file + rename; readers must treat missing
or malformed values as "Disconnected" and never block.

Consumer: `bridge/ingame_menu.sh` reads this file on every popup render
to drive the status header (connected vs disconnected). The Link fragment
is served from `bridge/ping.cache`, independent of session state.

### Known limitations

- **Silent disconnect (half-open TCP)** — not detected. Neither GMCP nor
  the MMapper text trigger fires. The player must invoke `Reconnect` manually
  from the popup. ADR link forthcoming.
- **Bootstrap window** — the tt++ session opens before `Char.Name` arrives
  (~0.5–2 s). During this window `session.state` is absent and the popup
  shows "Disconnected". The reconnect alias handles this correctly; a
  pending-state is not worth the complexity.
- **`cp -r` clears uptime** — `_clear_session_state()` runs unconditionally
  at brain startup. MUME does not re-send `Char.Name` while the TCP connection
  is live, so `session.state` stays absent after a reload until the next full
  reconnect. Popup shows "Disconnected" after `cp -r`. Accepted.

## cp -r behaviour

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

## Session Settings Persistence

Personal game settings live in `ttpp/sessions/<name>.tin`, named after
the session (default: `default.tin`). The file is loaded into a tt++ class
of the same name on SESSION CONNECTED, and the class is kept open for
the duration of the session so that any aliases, variables, or other
settings added at runtime are captured automatically.

**Profile file format:** Profile files are stored bare — no
`#class {name} {open}` / `{close}` wrapping is required or expected. The
cockpit handles class assignment externally. Legacy MUME settings files can
be dropped into `ttpp/sessions/` and renamed to match the session without
modification.

**Sanitizer:** `bridge/sanitize_profile.sh <path>` strips any
`#class {…} {open|close}` lines from a profile file in place, using an
atomic temp-file + rename. It matches any class name (not just the session
name) so it cleans legacy files dragged in under a different class name.
Non-existent path: exits 0 silently (handles first connect on a new profile).
The script is idempotent — a second run on an already-clean file is a no-op.

The `mume` alias is retained as a legacy shortcut that connects as `default`
— the game session name is always `default` unless a profile is explicitly
selected (Phase 2).

**Save mechanism:** SESSION DEACTIVATED fires inside the game session
while it is still alive — whenever the session loses focus. This covers:
- `#zap` — user disconnects directly
- `cp -r` — `#gts` at the start of reload deactivates the game session
- `cp -e` — `#gts` at the start of shutdown deactivates the game session

After `#class write`, `sanitize_profile.sh` strips the wrapping lines that
`#class write` always emits, keeping the at-rest file bare.

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
1. `sanitize_profile.sh ttpp/sessions/%0.tin` — strips any class wrapping (defensive)
2. `#class {%0} {open}` — opens the session class
3. `#read ttpp/sessions/%0.tin` — loads profile content into the open class
4. `#class {%0} {close}` — closes the class; subsequent registrations land in no class
5. Register infrastructure: reconnect alias, disconnect action, `_register_mud_events`,
   `_register_clock_actions`, `_register_affect_actions` — these are not user data
6. `#class {%0} {open}` — re-opens the class so runtime additions during play are captured

Core/script registrations after step 4 take priority over the profile on name collisions:
stale aliases in saved profiles do not block updates to core.

**Load sequence on cp -r (already-connected session):**
1. `sanitize_profile.sh ttpp/sessions/$game_session.tin` — strips any class wrapping
2. `#class {$game_session} {open}` — opens the session class
3. `#read ttpp/sessions/$game_session.tin` — loads profile content into the open class
4. `#class {$game_session} {close}` — closes the class; subsequent registrations land in no class
5. Register infrastructure: `_register_mud_events`, `_register_clock_actions`,
   `_register_affect_actions` — these are not user data
6. `#class {$game_session} {open}` — re-opens the class so runtime additions are captured

**Save sequence (cp -s and SESSION DEACTIVATED):**
1. `#class {name} {write} {ttpp/sessions/name.tin}` — writes file with wrapping
2. `sanitize_profile.sh ttpp/sessions/name.tin` — strips the wrapping

**Conventions:**
- Never hardcode `mume` as the class name in system code — always use
  the session name variable (`%0` or `$game_session`)
- Scripts must not register permanent aliases via `session_cmd()` —
  use `game_cmd()` instead, or they will be written into the session file

## Clean client startup

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

---
Back to [architecture.md](../architecture.md).
