# Cockpit — Notes for Claude

A terminal-based MUD client for MUME. Fast. Designed for low-latency I/O
with a scripting brain on top.

## Stack

- **TinTin++** — I/O, triggers, keybinds, latency-critical logic.
- **Lua** — state, timers, comms, non-latency-critical logic.
- **tmux** — window orchestration (game + input + ui + dev panes).
- **bash + ANSI** — pre-tmux startup menu and in-game popup.

## Authoritative documentation

- `architecture.md` — structure, stack, infra API, conventions. Start here.
- `ttpp_manual.txt` — TinTin++ reference. Consult whenever tt++ syntax is
  involved; do not rely on memory for tt++ behaviour.
- `docs/ui-messaging.md` — UI helpers and style rules.
- `docs/gmcp.md` — GMCP modules, schemas, negotiation.
- `docs/events.md` — event bus API and catalogue.
- `docs/ipc.md` — tt++ ↔ Lua IPC patterns.
- `docs/session-lifecycle.md` — SESSION events, game session tracking.
- `docs/input-pane.md` — Enter semantics, recall, history, key forwarding.
- `docs/status-pane.md` — character status pane: renderer, schema, field layout.
- `docs/buffs-pane.md` — buffs pane: renderer, grouping, palette, blink, scroll.
- `docs/comm-pane.md` — comm pane: renderer, comm.state schema, filter persistence.
- `docs/ui-pane.md` — UI pane: renderer, scroll, log-tail mechanics.
- `docs/clock.md` — game clock: sync sources, state schema, degradation rules.
- `docs/affects.md` — affect tracker: data flow, schemas, persistence, tick lifecycle.
- `docs/launcher.md` — pre-tmux menu rendering and flow.
- `docs/popup-menu.md` — in-game ESC popup (ingame_menu.sh).
- `docs/bridge-services.md` — ping monitor, version check, self-update.
- `docs/tmux-bindings.md` — tmux root-table bindings, mouse model, clipboard.
- `docs/release-process.md` — release runbook: version bump, tagging, GitHub release.
- `docs/install-bootstrap.md` — cross-platform install and bootstrap plan.
- `docs/decisions/` — Architecture Decision Records (append-only).

## Rules of thumb

- **tt++ for reflexes, Lua for cognition.** Latency-critical paths stay in tt++.
- **Two-tier Lua loading.** Always-on GMCP collectors (no alias, no
  `register_script`) go in `lua/core/*.lua`. Opt-in automation modules
  (must call `register_script(meta)`) go in `lua/scripts/*.lua`. Both
  are auto-loaded at startup — core first, then scripts. No edits to
  `brain.lua` or `main.tin` needed.
- **Self-contained tt++ modules.** New modules go in `ttpp/core/*.tin`.
  Auto-loaded by `main.tin`.
- **`#nop` is not opaque to `;`** — text after a semicolon inside an
  unbraced `#nop` is parsed and executed as a separate command. Use
  `,` or `—` for pauses, or `#nop {…}` if `;` is unavoidable. See
  ADR 0057.
- **Never hardcode session names.** From inside a Lua script use
  `game_cmd()` / `session_cmd()` / `send()`. `tintin_cmd()` / `tintin()` are
  for brain infrastructure, not scripts.
- **UI output goes through helpers.** `ui()`, `script_ui(name, msg)`,
  `system_ui(msg)`, `ui_warn(msg)`, `ui_err(msg)`. Never write to `ui.log`
  directly. Follow rules in `docs/ui-messaging.md`.
- **Dev log is developer-facing.** `dbg()` is terse `key: value`, no
  trailing period. UI helpers write full sentences with a trailing period.
- **Scripts self-describe.** Aliases, summaries, and per-script help live
  in the script itself via `register_script(meta)`, surfaced through
  `cp -<alias>`. Do not maintain duplicate lists elsewhere.
- **Shared state lives in `state`.** `state.char`, `state.room`,
  `state.comm`, `state.core`, `state.world`. No other cross-script storage.
- **One primary writer per GMCP module.** The file in `lua/core/` that owns
  `state.*` for a module sets `gmcp.handlers["Module.Name"]` (pcall'd).
  Everything else subscribes: `events.subscribe("gmcp_module_name", fn)`.
  `gmcp.dispatch` always emits the event after the primary writer, so
  `state.*` is already updated when any subscriber runs. To add a new
  subscribed module, add it to `gmcp.modules` AND `Core.Supports.Set` in
  `ttpp/core/gmcp.tin` (two-place sync — flagged in `docs/gmcp.md`).

## Language

- Code, comments, commit messages, variable names — English.
- Commit messages follow conventional-commit style: `feat:`, `fix:`,
  `docs:`, `refactor:`, `chore:`.

## When in doubt

- New active script pattern: read `lua/scripts/autostab.lua` or `autobow.lua`.
- New GMCP collector pattern: read `lua/core/char_state.lua` or
  `lua/core/comm_log.lua`.
- tt++ syntax: open `ttpp_manual.txt`, do not guess.
- Style questions: the relevant `docs/*.md` is authoritative over memory.
