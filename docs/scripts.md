# Scripts — authoring guide

How to write an opt-in automation module under `lua/scripts/`: where it
sits in the brain's two-tier loader, the metadata header that
documents it to the user, how it is enabled or disabled, and what
infrastructure it may call. Touch this file when changing the script
contract, the header format, the loader, or the `scripts.cache` format.

## Two-tier split (lua/core vs lua/scripts)

The Lua brain loads modules in two tiers at startup ([ADR 0002](decisions/0002-lua-core-vs-scripts-split.md)):

- **`lua/core/*.lua`** — always-on infrastructure. GMCP collectors and
  state serializers. No alias, no header, no opt-in machinery. Every
  file is `dofile()`'d at brain startup, alphabetical order. A file
  belongs here if and only if it has no alias and only listens to
  GMCP to write `state.*`.
- **`lua/scripts/*.lua`** — opt-in automation modules. Each file
  carries a metadata header (see below) and is loaded only when
  enabled in `scripts.conf`. A file belongs here if it provides a
  player-facing alias or behaviour the user might want to toggle.

Core loads first, scripts second, so a script's load-time code may
read `state.*` fields populated by core collectors.

## Metadata header

A script declares itself in a comment block at the top of its file.
The header is the contiguous run of `--` comment lines before the
first line that is not a `--` comment (a blank line ends the block).

Inside the block, `-- @key value` lines are metadata. Other comment
lines (decorative rules, prose, dividers) are ignored.

Recognised keys:

| Key | Repeatable | Purpose                                                          |
|-----|------------|------------------------------------------------------------------|
| `@summary` | no  | One-line description shown in `cp` Scripts list and launcher.    |
| `@alias`   | yes | An in-game alias the script provides. First token = alias name; remainder = description. |
| `@help`    | yes | Detailed help line. Shown in `cp -<name>` and the Scripts view.  |

Unknown `@key` lines are silently ignored — the parser is
forward-compatible. The script's name is its filename without `.lua`;
there is no `@script` / `@name` key.

### Annotated example

```lua
-- ============================================================
--  coinlooter
-- ============================================================
-- @summary  Auto-loots coins after mob kills
-- @alias    cl    Pick up coin piles in the current room
-- @help     Subscribes to mob_death and sends the appropriate
-- @help     get-coins command on each kill:
-- @help
-- @help       Living mob killed  →  get coins all.corpse
-- @help       Undead mob killed  →  get all.coins
-- @help
-- @help     1-second debounce: at most one auto-loot per second
-- @help     so rapid kills do not double-send.

local M = {}
scripts.coinlooter = M

-- ... script body ...
```

The decorative `-- =====...` rules around the title are ordinary
comments inside the header block — the parser sees them, finds no
`@key`, and ignores them.

## Enabling and disabling

A flat key=value config file controls which scripts load:

- **`bridge/runtime/scripts.conf`** — written by the launcher's
  Scripts view, shadows the template. User-owned.
- **`bridge/launcher/templates/scripts.conf`** — shipped default,
  lists every script in `lua/scripts/` as `=0` (disabled). Mirrors the
  ADR 0042 blank-profile pattern.

At brain startup the loader reads runtime first, falling back to
template. A script absent from both files defaults to enabled —
useful when dropping a new script in for ad-hoc work.

Format:

```
# Comments and blank lines are ignored.
autobow=0
autostab=0
coinlooter=1
```

Toggling state takes effect at the **next brain startup** ([ADR 0093](decisions/0093-script-metadata-headers-and-opt-in-loading.md)).
The in-game popup's Scripts view is read-only by design: an enabled
script's aliases, triggers, and event subscriptions have no
universal teardown contract, so toggling mid-session would leave
phantom registrations. The Exit-to-main-menu path is the intended
toggle workflow.

## scripts.cache

`bridge/runtime/scripts.cache` is written on every brain startup with
**every** script in `lua/scripts/` — enabled and disabled — so the
launcher and in-game popup can render the full installed set.

Format (one record per script, alphabetical by name):

```
SCRIPT:<name>
ENABLED:<0|1>
SUMMARY:<text>
ALIAS:<name>|<description>
HELP:<line>
```

A new `SCRIPT:` line starts a new record. `SUMMARY:` and `HELP:` /
`ALIAS:` lines may appear zero-to-many times per record. See
[docs/bridge-services.md](bridge-services.md) for the full runtime
file inventory.

## What a script may use

A script runs in the global environment after core loads. The
infrastructure surface available to it:

### Sending commands

- `send(cmd)` — send a MUD command to the current game session.
- `game_cmd(cmd)` — register an alias / highlight / substitute /
  permanent trigger in the shared `core` class so it survives
  reconnects.
- `session_cmd(cmd)` — register a session-only action / delay
  (`#action`, `#unaction`, `#delay`, `#undelay`); cleaned up when
  the session ends.

Never hardcode session names. The wrappers resolve the current
session automatically. See [docs/ipc.md](ipc.md) for the IPC contract.

### Subscribing to events

```lua
events.subscribe("mob_death", function(name, kind) ... end)
events.subscribe("gmcp_char_vitals", function(payload) ... end)
events.unsubscribe("mob_death", M.handler)   -- on stop
```

See [docs/events.md](events.md) for the event catalogue and
[docs/gmcp.md](gmcp.md) for the GMCP collector pattern (always-on
collectors live in `lua/core/`; scripts subscribe to the events they
emit).

### UI messaging

- `script_ui(name, msg)` — script lifecycle status line (`▶ NAME: msg.`).
- `system_ui(msg)`, `ui_warn(msg)`, `ui_err(msg)` — infrastructure /
  warning / error lines.
- `ui(msg)` — generic UI pane line.
- `dbg(msg)` — terse `key: value` to dev pane.

Style rules: full sentences with a trailing period for UI helpers;
terse `key: value` (no trailing period) for `dbg()`. See
[docs/ui-messaging.md](ui-messaging.md) for the full conventions.

### Shared state

`state.char`, `state.room`, `state.comm`, `state.world`, `state.core`,
`state.run` — populated by `lua/core/` collectors. Read freely from a
script; writing is the collector's job.

### Public API

Anything tt++ calls back via `#lua` must live under `scripts.<name>`.
Private helpers stay file-local `local`. See `autostab.lua` or
`autobow.lua` for the canonical pattern.

## Adding a new script

1. Drop a file in `lua/scripts/<name>.lua`.
2. Write its header (`@summary`, optional `@alias` / `@help`).
3. Implement the module — local table, `scripts.<name> = M`, register
   aliases via `game_cmd()` and triggers via `session_cmd()`,
   subscribe to events via `events.subscribe`.
4. Decide the default for the shipped install: edit
   `bridge/launcher/templates/scripts.conf` and add `<name>=0` (the
   default convention) or `<name>=1` if it should be on for everyone.
5. End the file with `dbg("[<NAME>] loaded")` — the brain prints this
   in the dev pane on startup so you can see it picked up. See
   [docs/ui-messaging.md](ui-messaging.md) — load lines are a
   liveness signal, not a manifest.

Next start of the brain, the script appears in `scripts.cache`, in
the launcher's Scripts view, and (if enabled) in the in-game `cp`
help with a `cp -<name>` detail box.
