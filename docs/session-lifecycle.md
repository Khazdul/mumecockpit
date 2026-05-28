# Session Lifecycle

Everything about tt++ session creation, game session tracking, state
persistence, and clean startup flow. Touch this file when changing how
sessions are connected, disconnected, or reloaded, or when modifying
`bridge/runtime/connection.state` consumers.

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

## Runtime connection state (`bridge/runtime/connection.state`)

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
  of `CONNECTION_STATE_PATH` and only act — and only emit `system_ui` — on
  an actual disconnected→connected or connected→disconnected transition.
- `mark_mume_connected()` calls `_write_connection_state()` (atomic temp+rename
  of a single `connected_at` line), then `system_ui(ui_var(name) .. " logged in.")`.
- `mark_mume_disconnected()` calls `_clear_connection_state()`, emits
  `system_ui(ui_var(name) .. " logged out.")`, then auto-opens the popup if
  `bridge/runtime/.popup_open` is absent (see `docs/popup-menu.md` — Auto-open on disconnect).

`set_game_session()` no longer writes `connection.state` — it only tracks tt++
session liveness. `clear_game_session()` delegates to `mark_mume_disconnected()`
(rather than calling `_clear_connection_state()` directly) so the direct-mode
abrupt-drop path joins the single dispatch point. The belt-and-braces role
is unchanged; the transition guard in `mark_mume_disconnected()` keeps it
idempotent.

### Format

    connected_at=<epoch seconds>

Written atomically via temp-file + rename; readers must treat the file
as a sentinel — present when connected, absent when disconnected — and
must never block on parse errors. Readers may silently ignore unknown
keys for forward compatibility.

Consumer: `bridge/launcher/ingame_menu.sh` and the four right-column data
panes (status, buffs, group, comm) test for file existence to gate
rendering. The connection-mode label in the popup status header is
sourced from `bridge/runtime/startup.conf`, not from this file.

### User-reconnect sentinel (`bridge/runtime/.user_reconnecting`)

A single-shot sentinel that suppresses the disconnect-popup auto-open
during a user-initiated `reconnect`. Without it, the transient disconnect
signal that the reconnect alias deliberately produces (MMapper `_disconnect`
or direct-mode `#zap`) would race ahead of the follow-up `_connect`/`connect`
and pop the menu mid-reconnect.

- **Writer:** `ttpp/core/system.tin` — the `reconnect` alias calls
  `#lua {mark_user_reconnecting()}` before the disconnect step, and
  `#lua {clear_user_reconnecting()}` from the post-`#delay` body as
  belt-and-braces (in case the disconnect signal never arrives).
- **Reader:** `lua/brain/connection.lua` — `mark_mume_disconnected()`
  checks the sentinel. When present it is removed and the popup
  auto-open is skipped (single-shot eat). All other disconnect-side
  work (state clear, `system_ui` logout line, `run_ending` emit, resets)
  still runs unchanged.
- **Semantics:** single-shot. A second disconnect after the sentinel is
  eaten opens the popup normally — a real disconnect following a
  user-initiated reconnect is not suppressed.
- **Stale cleanup:** `bridge/launcher/tmux_start.sh` removes the file at
  the top of each run alongside the other startup sentinels.

See ADR 0058 for the design rationale and rejected alternatives.

### Known limitations

- **Silent disconnect (half-open TCP)** — not detected automatically.
  Neither GMCP nor the MMapper text trigger fires. The player has a clean
  UX path: ESC opens the popup (Reconnect appears beneath Continue
  whenever `connection.state` exists), and selecting Reconnect routes
  through the sentinel-protected alias so a successful reconnect does
  not produce a spurious popup. See ADR 0058.
- **Bootstrap window** — the tt++ session opens before `Char.Name` arrives
  (~0.5–2 s). During this window `connection.state` is absent and the popup
  shows "Disconnected". The reconnect alias handles this correctly; a
  pending-state is not worth the complexity.

## Session Settings Persistence

Personal game settings live in `ttpp/profiles/<name>.tin`, named after
the session (default: `default.tin`). The file is loaded into a tt++ class
of the same name on SESSION CONNECTED, and the class is kept open for
the duration of the session so that any aliases, variables, or other
settings added at runtime are captured automatically.

**New-profile origin.** `bridge/launcher/templates/blank_profile.tin` is the single
source of truth for the content of any new profile. `start.sh` seeds
`ttpp/profiles/default.tin` from this template on fresh installs (idempotent
— a no-op when the file already exists). The launcher's "Create blank profile"
flow `cp`s from the same template. The shipped template includes default numpad
`#macro` registrations so that `#class {<profile>} {write}` on session
deactivation never produces an empty file (which tt++ would reject on the next
`#read`). See ADR 0042.

**Profile file format:** Profile files are stored bare — no
`#class {name} {open}` / `{close}` wrapping is required or expected. The
cockpit handles class assignment externally. Legacy MUME settings files can
be dropped into `ttpp/profiles/` and renamed to match the session without
modification.

**Sanitizer:** `bridge/release/sanitize_profile.sh <path>` is the boundary between
user-editable profile files and tt++'s strict `#read` parser. It normalizes
common file-header artifacts in place using an atomic temp-file + rename:

- **UTF-8 BOM** — stripped if present in the first three bytes (VS Code on
  Windows writes a BOM by default).
- **CRLF / bare `\r`** — normalized to LF (same source).
- **`#class {…} {open|close}` wrapping** — stripped (any class name, so
  legacy files dragged in under a different class name are cleaned).
- **Leading blank lines** — whitespace-only lines before the first non-blank
  line are removed (tt++ rejects files that do not start with a `#` command).

Non-existent path: exits 0 silently (handles first connect on a new profile).
The script is idempotent — a second run on an already-clean file is a no-op.
Trailing blank lines are untouched.

**Core-collision strip:** `bridge/release/strip_core_collisions.sh <path>` runs
immediately after `sanitize_profile.sh` from inside `_save_profile`. It scans
the just-written profile file for `#alias {name} {...}` entries whose name
matches any pattern in `bridge/runtime/core_aliases.list` (the runtime
allowlist of core-registered alias names produced at launcher startup by
`bridge/launcher/core_aliases.py`) and rewrites the file with those lines
removed via the same atomic temp + rename pattern as the sanitizer. The
strip is silent — no stdout, no log, no UI surface — because the only path
that produces a shadowing alias is direct prompt typing (`#alias {cp} {...}`
at the tt++ prompt), an intentional action that already self-explains;
verification is via direct inspection of the profile file after save.
`_save_profile` invokes it as a fire-and-forget `#system` call. Closes the
live-typed prompt vector where a user types `#alias {cp} {...}` directly
into tt++ and `#class write` would otherwise persist it on the next save;
the override survives only within the current session, preserving the
ADR 0115 escape hatch without granting it permanence. Fail-open: a missing
or empty allowlist exits silently with no stripping. Lua-registered script
aliases (`cp -autostab` etc.) are not in the allowlist and are therefore
not caught — flagged as a known gap in ADR 0115. The two scripts are
orthogonal and compose: sanitize handles file-shape hygiene, strip handles
content-shape hygiene.

The `mume` alias is retained as a legacy shortcut that connects as `default`
— the game session name is always `default` unless a profile is explicitly
selected (Phase 2).

**Save mechanism:** Profile auto-save runs synchronously in tt++,
hooked at every path where the game session is still alive at the
moment of disconnect or exit. `mark_mume_disconnected()` no longer
carries a save responsibility — it owns popup auto-open, `run_ending`,
and state teardown only. All save points call the shared
`_save_profile` helper:

1. **User-triggered — `cp -s`** — the popup Save button. Delegates to
   `_save_profile` and emits the `system_ui` "Profile saved to ..."
   confirmation. Works after link loss as well as during a live
   connection (tt++ keeps the disconnected session alive).

2. **Explicit exit — `cp -e`** — runs `_save_profile` *before* the
   `#gts;` step, so the save executes in the game session's context
   where the class and `_profile_loaded` are visible.

3. **SESSION DEACTIVATED handler** (registered in `system.tin`) —
   fires `_save_profile` whenever a game session deactivates. The
   event body runs in the deactivating session's context, so
   `_save_profile` sees the session-scoped `_profile_loaded` flag.
   Covers `#zap` from gts, `cp -e`'s zap step, and the direct-mode
   SESSION DISCONNECTED → `#session {gts}` chain (which deactivates
   the game session on its way out).

4. **MMapper text action — `Status: MUME closed the connection.`** —
   registered against the game session by SESSION CONNECTED. Fires
   `_save_profile` (then calls `mark_mume_disconnected()`) when MMapper
   detects an abrupt MUME-side drop while keeping its own socket alive.
   The action is registered in session scope; its body runs in the
   session. Covers the MMapper-mode case where SESSION DEACTIVATED
   never fires on a game-side `quit` or MMapper-absorbed drop.

All four paths run synchronously against a live game session, so the
class content is captured before any teardown.

### Save call-site invariant

`_save_profile` is **session-context-only**. The profile class lives
in the session; `#class write` operates on the invoking session's
classes; and the `_profile_loaded` guard flag is session-scoped.
Calling `_save_profile` from gts will silently no-op because gts
sees neither the class nor the flag. Every save call site must
therefore execute in the session whose class is being written.

In practice this means: invoke from the input pane / popup `tmux
send-keys` to the cockpit pane (which is focused on the game
session), from a session-scoped action (the MMapper text trigger),
from the SESSION DEACTIVATED event body (runs in the deactivating
session), or from `cp -e` *before* its `#gts;` step. Do not invoke
from gts directly. Future per-session-state operations that follow
the same pattern (affects history, run state, etc.) inherit this
constraint; see ADR 0064.

Residual edge case (documented, not defended): explicit
`#gts; cp -s` from the input pane skips the actual save (the
`_profile_loaded` guard fails in gts) while still emitting the
"Profile saved" `system_ui` line. The normal popup and bare
`cp -s` paths are unaffected.

**Load-state guard (`_profile_loaded`).** `_save_profile` checks a
session-scoped `_profile_loaded` flag in addition to `$_profile`
before writing. The flag is set to `1` at the end of the SESSION
CONNECTED load sequence, wrapped in `#%0 #class {core} {open}` /
`#%0 #class {core} {close}` so the variable lands in the `{core}`
class rather than the re-opened profile class — `#class
{<profile>} {write}` therefore never serializes `_profile_loaded`
into the on-disk profile file. Variable reads are not class-scoped,
so `_save_profile`'s `$_profile_loaded` check is unaffected by the
wrapping. The flag is cleared back to `0` in the SESSION
DISCONNECTED and SESSION TIMED OUT handlers — after `#session
{gts}` (so the SESSION DEACTIVATED handler that fires during the
gts switch still sees the flag set and saves correctly) and before
the `clear_game_session` Lua call. This prevents a failed connect
— where the session deactivates without ever loading its class —
from wiping the on-disk profile with an empty `#class write`. The
flag also no-ops the redundant `_save_profile` call in the MMapper
text action once a previous disconnect has already cleared it.

**Single definition of the save sequence.** `_save_profile` in
`ttpp/core/system.tin` is the only place `#class write` +
`sanitize_profile.sh` appears. Its body is a direct `#if` block —
no `#gts {...}` wrapper, no `#$_profile {...}` dispatch — and it
no-ops when no profile is loaded.

After `#class write`, `sanitize_profile.sh` strips the wrapping lines that
`#class write` always emits, keeping the at-rest file bare.

`#class write` serializes only the named profile class (`{<profile>}`), by design.
The `{core}` class — which holds all registrations made via `game_cmd()` and
`session_cmd()` — is runtime-only infrastructure and is never written to disk.

**SESSION DEACTIVATED is reserved as a system event.** User profiles must not
register their own SESSION DEACTIVATED handler. A handler in the profile file
would be loaded into the session class and would shadow the system handler,
silently breaking auto-save. This is a known footgun; sanitizer enforcement
of the reserved-event rule is out of scope for this PR.

PROGRAM TERMINATION does not save — by the time the event fires, the
game session has already been torn down by tt++ and `#class write` against
it is a no-op. The event is only used for tmux teardown (see Shutdown
Teardown below). Periodic save for terminal close / SIGKILL / crash is a
separate future phase.

**Known limitation — settings modified from gts after disconnect are not
saved.** Changes made to the session class from gts *while connected* ARE
saved on the next disconnect, because the SESSION DEACTIVATED handler (and,
in MMapper mode, the text action) fires while the session class still exists.
The remaining gap is changes made from gts *after* disconnect, when no game
session is running — there is no session class to write at that point. To
persist late edits, reconnect (which writes a fresh class on SESSION
CONNECTED) or run
`#default #class {default} {write} {ttpp/profiles/default.tin}` manually.

**Known limitation — crash / SIGKILL / terminal close.** Save points 1–4
above all require a live game session. A killed process, closed terminal
window, or `tmux kill-server` bypasses every path. Mitigations today are
the popup Save button and the user habit of `cp -s` before risky operations.
Periodic auto-save remains parked as a separate Phase 2 axis (see "Possible
future: periodic auto-save" below).

**Shutdown Teardown:** PROGRAM TERMINATION runs
`tmux kill-session -t mume 2>/dev/null`. Any graceful tt++ exit — `cp -e`,
`#zap` from gts, or `#end` — closes the entire cockpit tmux session
including the ui, dev, and input panes. `cp -e` no longer kills tmux
directly; it goes through PROGRAM TERMINATION like any other exit path.
Standalone tt++ runs outside the cockpit are unaffected by the missing
tmux session (error is suppressed).

**Load sequence on SESSION CONNECTED:**
1. `sanitize_profile.sh ttpp/profiles/%0.tin` — normalizes BOM, CRLF, class wrapping, leading blanks, and strips stray `#var {_profile_loaded} {…}` lines (infrastructure flag that must not appear in a profile file)
2. `#class {%0} {open}` — opens the session class
3. `#read ttpp/profiles/%0.tin` — loads profile content into the open class
4. `#class {%0} {close}` — closes the class; subsequent registrations land in no class
5. Register infrastructure: reconnect alias, disconnect action, `_register_mud_events`,
   `_register_clock_actions`, `_register_affect_actions` — these are not user data
6. `#class {%0} {open}` — re-opens the class so runtime additions during play are captured

Core/script registrations after step 4 take priority over the profile on name collisions:
stale aliases in saved profiles do not block updates to core.

The order-based class hygiene above (close before step 5, re-open at step 6) governs
synchronous tt++ registrations and runtime-typed user input. Registrations that go through
the Lua relay (`game_cmd()` / `session_cmd()`) execute asynchronously — after the
synchronous handler completes, including after the class is re-opened at step 6. These
functions wrap each command in `#class {core} {open}` / `#class {core} {close}` written
as a single `;`-separated, `#<ses>`-prefixed input line in one relay file, so the triple
runs atomically against any `#class`-manipulating trigger in another session and the
registration always lands in `{core}` regardless of session class state when the relay
drains. (Earlier the triple was three separate relay files and could be interleaved by
foreign-session triggers — see ADR 0097.) Two-class model: `{<profile>}` holds user data,
`{core}` holds all script and infrastructure registrations.

**Save sequence** (single body, defined once in `_save_profile`):
1. `#class {$_profile} {write} {ttpp/profiles/$_profile.tin}` — writes file with wrapping
2. `sanitize_profile.sh ttpp/profiles/$_profile.tin` — normalizes the file (strips wrapping and header artifacts)
3. `strip_core_collisions.sh ttpp/profiles/$_profile.tin` — drops any `#alias` line whose pattern shadows a core registration. Silent in every path — no stdout, no log, no UI surface. See "Core-collision strip" under Sanitizer above.

Call sites of `_save_profile`: `cp -s` (user-triggered), `cp -e` (explicit
save before the gts switch), the SESSION DEACTIVATED handler (covers `#zap`
and the direct-mode SESSION DISCONNECTED → `#session {gts}` chain), and the
MMapper `Status: MUME closed the connection.` text action (covers
MMapper-stay-alive disconnects). All four fire synchronously against a live
game session, and all four run in session context (see "Save call-site
invariant" above).

**Conventions:**
- Never hardcode `mume` as the class name in system code — always use
  the session name variable (`%0` or `$game_session`)
- Scripts must not register permanent aliases via `session_cmd()` —
  use `game_cmd()` instead, or they will be written into the session file

## Possible future: periodic auto-save

**Motivation.** Phase 1 covers all graceful exit paths (SESSION DEACTIVATED,
`cp -e`). Remaining gap: ungraceful termination — terminal window closed,
tmux kill-server, SIGKILL, system crash. PROGRAM TERMINATION cannot save
(sessions already torn down — see Shutdown Teardown above). Current
mitigations are the popup Save button and the user habit of `cp -s` before
risky operations.

**Approach (sketch).** Lua-driven periodic save. `brain.lua` starts a
recurring timer at startup that, every N seconds, calls `tintin_cmd()` to
fire the same two-step save against the active GAME_SESSION: `#class write`
followed by `sanitize_profile.sh`. Falls through silently when GAME_SESSION
is nil. Re-armed each tick.

**Configuration.** Interval lives in `bridge/runtime/startup.conf`, e.g.
`save_interval_seconds=300` (default 300, 0 disables). Read by
`bridge/launcher/read_config.sh` (and surfaced as a tt++ var) or directly by
`brain.lua` at startup. Decision deferred until implementation.

**Tradeoffs.** Worst-case data loss bounded to one interval rather than the
full session. Cost: one file write to `ttpp/profiles/<profile>.tin` every N
seconds while connected — negligible. No tt++ event-loop impact; the work
happens in Lua and reaches tt++ via the existing IPC.

**Why parked.** Phase 1 covers all documented exit paths (`cp -e`, popup
Exit). Remaining failure modes are infrequent enough that the explicit-save
habit suffices for now. Pick up when there is a concrete trigger — recurring
data-loss reports from users, unattended long-session use cases, or a
planned move toward less graceful shutdown paths.

## Clean client startup

tt++ is launched with a CLI flag that suppresses its built-in greeting
banner (set in `bridge/launcher/tmux_start.sh`). The small residual flash is
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
   on initial boot.

3. **Silent Lua launch.** `#line quiet {#run {lua} {lua lua/brain.lua}}`
   suppresses the `#TRYING TO LAUNCH 'lua'` notice.

`welcome.tin` then owns the welcome screen and auto-connect:

- `_do_startup` runs 0.5 s after boot (time for tt++ and Lua to finish
  their own boot output). Skipped if a game session is already active.
- Clears scrollback (tt++'s `#buffer clear`, terminal's `\e[3J`, and
  `tmux clear-history`).
- Prints the MUME + COCKPIT wordmark in plain white (no starfield, no
  animation) via hand-rolled `#showme` lines — a deliberate static,
  starless subset of the launcher / popup banner. The shared
  `bridge/launcher/launcher_banner.py` is **not** used here: the
  welcome screen is a tt++ startup surface, not a `prompt_toolkit`
  one, and the wordmark art is frozen so a small amount of duplication
  is the accepted cost (ADR 0100). Followed by a welcome line, a
  `Press <Esc> for menu.` hint, and `Connecting to MUME...`.
- Calls `connect`, which resolves to `#$_ses_cmd {$_profile} {$_host} {$_port}`
  via `config.tin` — `$_ses_cmd` is `ses` (mmapper/plain) or `ssl` (direct/TLS).
  User lands directly in the MUD.

---
Back to [architecture.md](../architecture.md).
