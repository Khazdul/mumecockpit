# UI Messaging

Rules and helpers for writing to the UI pane (`logs/ui.log`) and dev log
(`logs/debug.log`). Touch this file when writing any script that produces
player-visible output, or when adjusting colour constants or style rules.

## State Change Echoes

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

## Script Status Messages

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
codes (not TT++ format) since the UI pane renders `logs/ui.log` directly via
`bridge/panes/ui_pane.py` (`prompt_toolkit` ANSI fragment conversion).

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

## UI System Events

Infrastructure lifecycle events (brain start, game session connect/disconnect,
cockpit reload, future framework-level events) use `system_ui()` in
`brain.lua`:

```lua
system_ui("Connecting to MUME...")
system_ui(ui_var(name) .. " logged in.")
system_ui(ui_var(name) .. " logged out.")
system_ui("Connection to MUME closed.")
```

Renders in the UI pane as:

```
● SYSTEM: Connecting to MUME...
● SYSTEM: Khazdul logged in.
● SYSTEM: Khazdul logged out.
● SYSTEM: Connection to MUME closed.
```

`● SYSTEM` is blue (`#42A5F5`), the message is bold bright white, and
dynamic values are bold yellow via `ui_var()`.

Infrastructure lifecycle events that the user needs to see (game session
connect/disconnect, cockpit reload, future framework-level events) use
`system_ui()`. Events that are internal brain plumbing (brain process start,
script-load diagnostics) go to `dbg()` and appear in the dev pane only.

Use `system_ui` for user-relevant state transitions only — not for game events,
script lifecycle (use `script_ui`), warnings (`ui_warn`), or errors (`ui_err`).

## Helper Selection Guide

Pick the helper by what the event represents:

| Event type                                                         | Helper               | Marker    |
|--------------------------------------------------------------------|----------------------|-----------|
| Character-state lifecycle (affect up/down, spell stored/recalled)  | `char_ui`            | `◆`       |
| Script lifecycle (started, stopped, error)                         | `script_ui`          | `▶`       |
| Infrastructure event (connect, disconnect, reload)                 | `system_ui`          | `●`       |
| Degraded path the player should see                                | `ui_warn` / `ui_err` | `⚠` / `✖` |

Rule of thumb: character-state lifecycle event → `◆`; script started/stopped/error → `▶`; cockpit infrastructure → `●`; degraded path the player must act on → `⚠` / `✖`.

## Character Events

Character-state lifecycle events use `char_ui()` in `brain.lua`:

```lua
char_ui("spell",  "armour",      "up")
char_ui("buff",   "Orkish draught", "refreshed")
char_ui("debuff", "lethargy",    "down")
char_ui("store",  "fireball",    "stored")
char_ui("store",  "fireball",    "recalled")
char_ui("store",  "earthquake",  "decayed", "89:58 — sample recorded")
char_ui("store",  "fireball",    "decayed", "untracked")
char_ui("blind",  "2.orc",       "up")
char_ui("blind",  "2.orc",       "down")
```

Renders in the UI pane as:

```
◆ SPELL: armour up.
◆ BUFF: Orkish draught refreshed.
◆ DEBUFF: lethargy down.
◆ STORE: fireball stored.
◆ STORE: fireball recalled.
◆ STORE: earthquake decayed (89:58 — sample recorded).
◆ STORE: fireball decayed (untracked).
◆ BLIND: 2.orc up.
◆ BLIND: 2.orc down.
```

### Signature

```
char_ui(category, name, verb, detail?)
```

- **`category`** — selects the tag label and colour. Controlled vocabulary: see table below.
- **`name`** — the character-state entity name; rendered via `ui_var()` (bold yellow).
- **`verb`** — what happened. Canonical verbs: `up`, `refreshed`, `expiring` (reserved — no emitters yet), `down`. Domain-specific verbs (`stored`, `recalled`, `decayed`, …) are allowed when they read more naturally.
- **`detail`** (optional) — extra context appended in parentheses. Plain string; not highlighted.

Prose form: `◆ TAG: name verb.` or `◆ TAG: name verb (detail).` Trailing period is always present.

### Category table

| Category    | Tag      | Colour           | Hex       | Notes                                    |
|-------------|----------|------------------|-----------|------------------------------------------|
| `spell`     | `SPELL`  | Light steel-blue | `#7AA9D6` |                                          |
| `buff`      | `BUFF`   | Soft sage green  | `#8FBC8F` |                                          |
| `debuff`    | `DEBUFF` | Muted brick red  | `#C97070` |                                          |
| `store`     | `STORE`  | Muted lavender   | `#B39DDB` |                                          |
| `blind`     | `BLIND`  | Cyan             | `#00CCCC` | Matches the buffs-pane Blinds group      |
| `herb`      | —        | TBD              | —         | Reserved; colour set when tracker lands  |
| `charm`     | —        | TBD              | —         | Reserved; colour set when tracker lands  |
| *(unknown)* | `AFFECT` | Teal             | `#26C6DA` | Defensive fallback                       |

### Canonical verbs

| Verb        | Meaning                                  | Emitters                  |
|-------------|------------------------------------------|---------------------------|
| `up`        | Effect became active                     | affects (init), blinds (landing) |
| `refreshed` | Effect re-applied while already active   | affects (refresh)         |
| `expiring`  | Effect about to drop (**reserved**)      | *(none yet)*              |
| `down`      | Effect dropped                           | affects (drop), blinds (tick prune at 90 s) |
| `stored`    | Spell stored to memory                   | stored\_spells            |
| `recalled`  | Stored spell recalled                    | stored\_spells            |
| `decayed`   | Stored spell decayed naturally           | stored\_spells            |

One `char_ui` call per event — no other helper is invoked for the same event.

## UI Warnings and Errors

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

## UI Dynamic Values

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
system_ui(ui_var(name) .. " logged in.")
script_ui("AUTOSTAB", "Stopped — " .. ui_var(reason) .. ".")
ui_err("Failed to load script " .. ui_var("foo.lua") .. ".")
```

The convention is semantic — `ui_var` marks "this is a dynamic value", not
a specific style. If the style changes later, only one place needs updating.

Spell names in script UI output follow the same convention: pass the spell name
to `ui_var()` and omit surrounding quotes. Example:
`script_ui("STORE", "stored " .. ui_var(name) .. ".")` renders as
`▶ STORE: stored fireball.` with `fireball` in bold yellow.

See "UI Message Style Rules" below for when to apply `ui_var()` and other
cross-cutting rules.

## UI Message Style Rules

These rules apply to every message written to `ui.log` through any helper
(`ui`, `script_ui`, `system_ui`, `ui_warn`, `ui_err`):

- **Trailing period — UI vs dev.** User-facing helpers (`ui`, `system_ui`, `script_ui`, `ui_warn`, `ui_err`) write full sentences and always end with a period. `dbg()` is developer-facing log output — terse, `key: value` or status-style — and never ends with a period. Quick test: if the line reads like console output from a tool (`server connected`, `cache miss for foo`, `3 scripts loaded`), it's `dbg()` and takes no period. If it reads like a status report to the player (`Khazdul logged in.`), it's one of the UI helpers and does.
- **Event-style phrasing.** Describe what happened, not what the state is
  now. `Khazdul logged in.`, not `Character: Khazdul`.
- **Dynamic values highlighted.** Any variable part of a message (session
  name, target, reason, count, filename) is wrapped in `ui_var()` and
  renders in bold yellow against the bold white base text.
- **No timestamps.** `ui.log` is meant to be scannable at a glance.
  `debug.log` already carries timestamps for diagnostic purposes.

## Logging Guidelines

**UI LOG (`logs/ui.log`)** — game-relevant information the player cares about:
- Game-relevant state changes (target acquired/changed, spell changes, buffs added or about to drop, etc.)
- Communication (tells, says, narrates etc.)
- Not combat events — not damage hits, not HP threshold crossings, not reflexes like stunned

**DEV LOG (`logs/debug.log`)** — technical/diagnostic information:
- Errors and unexpected input
- Technical state transitions
- Function entry points for debugging (`get_state called`, `get_tells called`)
- Unknown or unhandled events

**Script load messages.** On load, a script emits a single `dbg()` line of the form `[SCRIPTNAME] loaded` — nothing more. Alias/trigger registration details belong in the script's `cp -<name>` help box (rendered from the `@`-tagged header at the top of the file — see [docs/scripts.md](scripts.md)), not in the startup log. The load line is a liveness signal, not a manifest.

**Rules:**
- Never log the same event to both panes redundantly — `ui()` already mirrors to dev with a `UI:` prefix, so never follow a `ui()` call with a `dbg()` for the same message
- Log to UI only when something meaningful changes, not on every trigger fire, you need to ask what is appropriate to log when new content is added
- Unknown events go to dev only, not UI

## Colour Constants

All ANSI constants are defined at the top of `lua/brain.lua`. Scripts must
never hard-code escape sequences — use the helper functions (`ui_var()`,
`script_ui()`, etc.) instead. Values are documented here so the exact colours
are known without guessing.

| Constant    | Escape value                        | Colour / role                         |
|-------------|-------------------------------------|---------------------------------------|
| `_C_SCRIPT` | `"\027[38;2;38;198;218m"`           | Teal `#26C6DA` — `▶ SCRIPTNAME` prefix |
| `_C_SYSTEM` | `"\027[38;2;66;165;245m"`           | Blue `#42A5F5` — `● SYSTEM` prefix   |
| `_C_WARN`   | `"\027[38;2;255;179;0m"`            | Amber `#FFB300` — `⚠ WARN` prefix    |
| `_C_ERR`    | `"\027[38;2;229;57;53m"`            | Red `#E53935` — `✖ ERROR` prefix     |
| `_C_SPELL`  | `"\027[38;2;122;169;214m"`          | Light steel-blue `#7AA9D6` — `◆ SPELL` prefix |
| `_C_BUFF`   | `"\027[38;2;143;188;143m"`          | Soft sage green `#8FBC8F` — `◆ BUFF` prefix |
| `_C_DEBUFF` | `"\027[38;2;201;112;112m"`          | Muted brick red `#C97070` — `◆ DEBUFF` prefix |
| `_C_STORE`  | `"\027[38;2;179;157;219m"`          | Muted lavender `#B39DDB` — `◆ STORE` prefix |
| `_C_BLIND`  | `"\027[38;2;0;204;204m"`            | Cyan `#00CCCC` — `◆ BLIND` prefix (matches buffs-pane Blinds group) |
| `_C_VAR`    | `"\027[1;38;2;255;238;88m"`         | Bold yellow `#FFEE58` — dynamic values |
| `_C_TEXT`   | `"\027[1;97m"`                      | Bold bright white — base message text |
| `_C_RESET`  | `"\027[0m"`                         | Reset all attributes                  |

---
Back to [architecture.md](../architecture.md).
