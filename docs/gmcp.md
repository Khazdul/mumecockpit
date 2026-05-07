# GMCP

Complete reference for GMCP (Generic MUD Communication Protocol) in Cockpit:
module subscriptions, message schemas, telnet negotiation, Lua dispatch, and
scripting patterns. Touch this file when adding a GMCP collector, subscribing
to a new module, or debugging GMCP message flow.

> **Two-place sync required.** The subscription list must be kept in sync in
> two places:
> - `gmcp.modules` in `lua/brain.lua` — Lua source of truth
> - `Core.Supports.Set` payload in `ttpp/core/gmcp.tin` — sent to the server at handshake
>
> Adding a module to only one place will either silently skip dispatch or send
> a subscription the brain ignores.

## Overview

GMCP delivers structured data from MUME out-of-band over telnet subnegotiation.
The client negotiates via `Core.Hello` + `Core.Supports.Set` at connect; the
server then pushes the modules we subscribed to as `IAC SB GMCP` events.
Payloads are JSON.

## GMCP module reference

MUME supports the following GMCP modules. Cockpit currently subscribes to Char,
Comm.Channel, Event, and Core. Others are documented here so future work can
pick from a known map without re-reading help files.

### Module overview

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

### Subscribed modules — message reference

**Core**

| Message           | Direction | Body                            | Handler               |
|-------------------|-----------|---------------------------------|-----------------------|
| Core.Hello        | → server  | `{client, version}`             | ttpp/core/gmcp.tin    |
| Core.Supports.Set | → server  | array of `"Module N"` strings   | ttpp/core/gmcp.tin    |
| Core.KeepAlive    | → server  | (none)                          | not sent              |
| Core.Ping         | → server  | optional avg ping ms            | not sent              |
| Core.Ping         | ← server  | (none)                          | lua/core/core_state.lua        |
| Core.Goodbye      | ← server  | optional reason string          | lua/core/core_state.lua (also drives connection.state) |

**Char**

| Message         | Direction | Body                           | Handler        |
|-----------------|-----------|--------------------------------|----------------|
| Char.Login      | → server  | `{name, password}`             | not sent       |
| Char.Name       | ← server  | `{name, fullname}`             | lua/core/char_state.lua (also drives connection.state); wrapped by lua/core/status_state.lua (serialises to bridge) and lua/core/server_prefs.lua (locks server wrap width) |
| Char.StatusVars | ← server  | name/caption pairs (see below) | lua/core/char_state.lua |
| Char.Vitals     | ← server  | flat object (see below)        | lua/core/char_state.lua |

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
| Comm.Channel.Enable  | → server  | channel name string                 | lua/core/comm_log.lua → alias `gmcp_enable_channel` in gmcp.tin     |
| Comm.Channel.List    | ← server  | array of `{name, caption, command}` | lua/core/comm_log.lua                                               |
| Comm.Channel.Text    | ← server  | see below                           | lua/core/comm_log.lua                                               |

Comm.Channel.Text body:

    channel      — channel name
    destination  — recipient name (only for sent messages)
    talker       — sender name ("you" for sent messages)
    talker-type  — optional: npc | ally | neutral | enemy
    text         — text heard, may contain ANSI codes (preserved)

Channel-enable flow:
1. tt++ sends `Core.Supports.Set` including `"Comm.Channel 1"` at handshake.
2. Server auto-sends `Comm.Channel.List` with available channels.
3. `lua/core/comm_log.lua` receives the list, stores it in `state.comm.channels`, and issues `Comm.Channel.Enable` for each channel by calling the `gmcp_enable_channel` alias.
4. Server begins streaming `Comm.Channel.Text` for those channels.

No channel list is hardcoded client-side — whatever the server advertises gets enabled.

**Event**

| Message        | Body                                                        | Handler         |
|----------------|-------------------------------------------------------------|-----------------|
| Event.Darkness | `{what: "start"\|"grow"\|"shrink"\|"end-soon"\|"end"}`      | lua/core/world_state.lua |
| Event.Moon     | `{what: "rise"\|"set"}`                                     | lua/core/world_state.lua |
| Event.Moved    | `{dir: "north"\|"east"\|...}` (dir optional)                | lua/core/world_state.lua |
| Event.Sun      | `{what: "light"\|"rise"\|"set"\|"dark"}`                    | lua/core/world_state.lua |

All Event handlers store the decoded body as-is under the corresponding `state.world.<event>` field.

### Unsubscribed modules — one-liner per module

- **Client** — Mudlet-specific client package and map data; used by Mudlet's MUME plugin for room mapping.
- **External.Discord** — integrates with the MUME Discord channel; bridges in-game communication to Discord.
- **Group** — group/party state; tracks members, their positions and vitals for group displays.
- **MUME.Client** — remote text editing; allows the server to open an editor on the client for composing notes and mail.
- **Room** — current room data including vnum, name, description, and exits; the basis for any mapper.
- **Room.Chars** — characters present in the current room; used for room-level displays and targeting aids.
- **Room.Known** — previously visited rooms; used to sync a visited-room database with the client.

Subscription requires adding to both the `Core.Supports.Set` payload and `gmcp.modules`.

## Negotiation registration

IAC events are session-scoped — they fire in the session that received the bytes, and only if registered inside that session. We register via a `SESSION CREATED` handler that uses `#%0 #event` to install `IAC WILL GMCP` and `IAC SB GMCP` inside the connecting session.

`SESSION CONNECTED` is too late: it fires after the first telnet data swap, by which point tt++'s default `IAC DONT GMCP` has already shipped. `SESSION CREATED` fires when `#session` is executed, before TCP handshake, so our handler is in place when the server's first bytes arrive.

## Sending sub-negotiations

Syntax: `#send {$IAC$SB${GMCP}Package.Name JSON $IAC$SE\}`

- `${GMCP}` uses brace delimiters so no space leaks between the GMCP option byte and the package name. `$GMCP Package` (no braces) would include a literal space that servers parse as part of the package name and reject.
- Package name and JSON body separated by exactly one space.
- No whitespace before `$IAC$SE`.
- Trailing `\` before the closing `}` suppresses tt++'s automatic `\r\n` — required, otherwise every send injects a blank command into the MUD input stream.
- IAC byte values live in tt++ variables (`#var {IAC} {\xFF}` etc.) declared at file load time. `\x` escapes are evaluated on assignment; using them inline inside an `#event` body produces literal `\xFF` text, not byte 0xFF.

## Reception

`#event {IAC SB GMCP}` fires with `%0` = module name, `%1` = list-flattened body, `%2` = raw JSON string. Use `%2` — `%1` is tt++'s nested-brace representation and loses type information.

`%2`'s payload includes the leading package name (e.g. `Char.Vitals {...}`), so `gmcp.dispatch` strips the first whitespace-delimited token before JSON decode.

## Lua dispatch

`gmcp.dispatch(module, payload)` in `brain.lua` strips the leading package-name token, parses the remainder as JSON via dkjson, and calls `gmcp.handlers[module]` with the decoded Lua value (or `nil` for empty bodies such as `Core.Goodbye`). Handlers run under `pcall` — a crashing handler logs to dev via `dbg()` but doesn't take down the brain.

## Script integration pattern

Scripts subscribe at load time:

```lua
gmcp.handlers["Char.Vitals"] = function(body)
    state.char.hp = body.hp
    -- ...
end
```

Unknown modules log `GMCP no handler: <Module>` to dev and drop. Modules not listed in `gmcp.modules` will never fire regardless of handlers registered — the subscription list is the gate.

## Data collection (iteration 2a)

**Generic flat-copy pattern.** `lua/core/char_state.lua` merges Char.Name /
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

## Null handling

MUME sends JSON `null` for fields that are off or absent (e.g. `{"climb": null}`
when the character is not climbing). Without special treatment, dkjson decodes
`null` as Lua `nil`, which is indistinguishable from a missing key — the field
simply disappears from the decoded table.

To preserve the distinction, `brain.lua` passes `json.null` as the third argument
to `json.decode`:

```lua
local parsed, _, err = json.decode(json_body, 1, json.null)
```

dkjson maps every JSON `null` to this sentinel object instead of `nil`. The
sentinel is exposed on the `gmcp` namespace as `gmcp.null` so handlers can
reference it without requiring dkjson themselves.

Handlers that store into `state.*` should convert the sentinel to `nil` before
writing, since Lua tables cannot hold `nil` values. The canonical consumer is
`merge_flat` in `lua/core/char_state.lua`:

```lua
if v == gmcp.null then
    state.char[key] = nil
else
    state.char[key] = v
end
```

Handlers that test a body field directly (e.g. `if body.foo then`) must be
aware that `json.null` is truthy — check `body.foo ~= gmcp.null` when the
field can legitimately arrive as JSON `null`.

## JSON library

`lua/lib/dkjson.lua` — pure-Lua MIT-licensed JSON library (David Kolf, v2.8), bundled verbatim. `package.path` is extended in `brain.lua` at startup to include `lua/lib/` so no path juggling is needed. GMCP message bodies may be empty, a JSON string, a JSON number, an array, or an object depending on the module. Handlers receive whatever dkjson decodes — or `nil` for empty bodies.

## Debugging

Turn on telnet trace with `#config {debug telnet} {on}` in gts (NOT `#config {telnet} {info} {on}` — that is invalid syntax that puts TELNET in DEBUG mode and disables the telnet stack). Turn off with `#config {debug telnet} {off}`.

`GMCP no handler: <Module>` entries in `debug.log` are the health signal — if they appear, negotiation completed and the server is streaming the modules we subscribed to.

With `gmcp.trace = true`, the best way to discover a module's real body shape is to subscribe, reload, and grep debug.log for `[GMCP] <Module>`.

---
Back to [architecture.md](../architecture.md).
