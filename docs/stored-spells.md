# Stored Spells Tracker

Tracks active stored spells per character, learns observed decay durations from
the last 3 samples, and persists per character to disk. This document covers the
data layer and event bus; rendering is deferred to a future buffs-pane
integration PR.

## Data flow

```
User types: cast 'store' fireball
      │
      ▼
tt++ #event {SENT OUTPUT} (ttpp/core/system.tin)
  — fires on every line the user sends to the MUD
      │
      ▼ #lua {USER_INPUT:<sent text>}
      │
      ▼
brain.lua handlers["USER_INPUT"]
  — rejoins parts with ":" (raw input may contain ":")
  — events.emit("user_input", raw)
      │
      ▼
lua/core/stored_spells.lua — user_input subscriber
  — Lua patterns detect cast/store commands
  — resolves spell names via _resolve_spell()
  — if resolved == "store": events.emit("store_attempt_started", target)
  — else: _last_cast_intent = resolved (for recall detection)
      │
      ▼ events.emit("store_attempt_started", "fireball")
      │
      ▼
stored_spells.lua — store_attempt_started subscriber
  — appends to _pending_attempts FIFO

MUME game output
      │
      ▼
tt++ #action (GAME_SESSION, priority 3)
  — registered by _register_stored_spells_actions() at SESSION CONNECTED / cp -r
      │
      ▼ events.emit("store_succeeded" | "store_attempt_failed" | ...)
      │
      ▼
lua/core/stored_spells.lua  ──►  state.char.stored_spells       (active list)
                            ──►  state.char.stored_spell_times   (ring-buffer history)
                            ──►  logs/stored_spells_active/<char>.json   (disk)
                            ──►  logs/stored_spells_times/<char>.json    (disk)
```

## State schema

### `state.char.stored_spells`

Array of currently-active stored spell entries:

```lua
{
    name              = "fireball",   -- string, matches key in spells_data.spells
    started_at        = 1714000000,  -- os.time() when store_succeeded fired
    expected_duration = 5400,         -- integer seconds (mean of samples, else 5400)
    expires_at        = 1714005400,  -- started_at + expected_duration, or nil if untracked
    tracked           = true,         -- false after stored_spells_untracked fires
}
```

`tracked` becomes `false` and `expires_at` becomes `nil` when a magic-blast
event fires, because the blast consumes all stored spells in an unknown order.

### `state.char.stored_spell_times`

Table mapping spell name → array of up to 3 observed decay durations (integers,
seconds). FIFO ring-buffer: push to end, drop from front when length exceeds 3.

```lua
{
    fireball  = {5398, 5401, 5399},
    sanctuary = {5395, 5402},
}
```

Both slots are initialised to `{}` at module load and re-initialised to `{}`
on each `Char.Name` (login). `state.char.reset()` (called on disconnect) wipes
them via the standard non-function-key sweep in `char_state.lua`.

## Spell-name resolution

For input `s` (arbitrary case) and a spell with full name `full` and shortest
prefix `shortest` (canonical lowercase in `spells_data.lua`):

`s` matches `full` iff:
- `string.lower(s):sub(1, #shortest) == shortest` (s is at least as long as the
  shortest unambiguous prefix, and its prefix matches), **and**
- `full:sub(1, #string.lower(s)) == string.lower(s)` (full starts with the
  lowercased input — rules out over-long inputs).

Iterate all spells; if exactly one full name matches, return it; otherwise
return `nil` (no match or ambiguous).

Examples:

| Input      | Resolves to     | Reason                          |
|------------|-----------------|---------------------------------|
| `"fireb"`  | `"fireball"`    | prefix match, unique            |
| `"FireB"`  | `"fireball"`    | case-insensitive                |
| `"magic m"`| `"magic missile"` | prefix disambiguates vs blast |
| `"magic b"`| `"magic blast"` | prefix disambiguates vs missile |
| `"magic "` | `nil`           | too short — neither prefix met  |
| `"store"`  | `"store"`       | exact canonical form            |

## SENT OUTPUT snooping

The tt++ event `SENT OUTPUT` fires on every line the user sends. The IPC path
is:

1. `#event {SENT OUTPUT} {#if {"%0" != ""} {#lua {USER_INPUT:%0}}}` registered
   in GAME_SESSION by `_register_stored_spells_actions()` (see `docs/ipc.md`
   for why top-level registration recurses).
2. `brain.lua` `handlers["USER_INPUT"]` rejoins the parts and emits `user_input`.
3. `stored_spells.lua` subscriber matches in two stages (first match wins):

### Top-level command shortcuts

MUME accepts `sto X`, `stor X`, and `store X` as server-side shortcuts that
expand to `cast 'store' X`. The snooper recognises these directly so they
queue an attempt without requiring the full `cast '...'` syntax. Prefixes are
tested longest-first (`store` before `stor` before `sto`) to avoid ambiguity.
If the target resolves, `store_attempt_started` is emitted via the normal path.

### `cast '...'` syntax

If no top-level shortcut matched, two Lua patterns are tried in order:

- `^c%w+%s+%w+%s+'([^']+)'%s*(.*)$` — cast with speed modifier
- `^c%w+%s+'([^']+)'%s*(.*)$` — cast without speed modifier

If neither pattern matches, the line is ignored.

## Cast detection and `_last_cast_intent`

There are two parallel paths that update `_last_cast_intent`:

**SENT OUTPUT snooper** (`user_input` event) catches direct `cast 'X'` syntax
and the `sto`/`stor`/`store X` top-level shortcuts. It is the only path that
sees the _target_ spell for store attempts, so store-attempt tracking
(`_pending_attempts`) is driven exclusively from here.

**MUME server echo** (`user_cast` event) catches every cast — including
alias-expanded ones like `arm` → `[cast n 'armour']` — and updates
`_last_cast_intent` from the bracketed echo line. This gives alias coverage
without needing a per-spell table of top-level abbreviations. The patterns
intentionally omit the closing `]` anchor so targeted casts
(`[cast n 'fireball' orc]`) match identically to untargeted ones
(`[cast n 'armour']`); the `^[c` start-anchor prevents false matches against
mid-line bracket content. The `"store"` spell is filtered out on this path
because the SENT OUTPUT snooper already handles it and also supplies the
target spell.

Both paths converge on the same slot. Direct `cast 'X'` commands hit both
paths in quick succession (SENT OUTPUT fires first, then the game echoes the
bracket line); the second write is idempotent — it resolves to the same full
name and stores the same value.

## Runtime-only state

`_pending_attempts` (FIFO queue of spell names) and `_last_cast_intent` (most
recent non-store spell resolved from outgoing input) are module-local and never
written to disk. They reset on each `cp -r` (fresh module load). This means a
`cp -r` mid-attempt can leave the queue out of sync; both paths are detected and
logged via `dbg`.

## Persistence

### Times file

**Path:** `logs/stored_spells_times/<character>.json`

```json
{
  "fireball": [5398, 5401, 5399],
  "armour":   [5395]
}
```

Written atomically (temp-file + `os.rename`) inside the `store_decayed` handler
when `tracked == true`. Only samples from naturally-decayed tracked entries are
recorded. Entries whose spell name is absent from `spells_data.spells` are
filtered out at load time.

### Active list file

**Path:** `logs/stored_spells_active/<character>.json`

```json
[
  {
    "name": "fireball",
    "started_at": 1714000000,
    "expected_duration": 5400,
    "expires_at": 1714005400,
    "tracked": true
  },
  {
    "name": "armour",
    "started_at": 1714001000,
    "expected_duration": 5400,
    "tracked": false
  }
]
```

Written atomically at the end of `store_succeeded`, `store_recalled`,
`store_decayed`, and `stored_spells_untracked`. All entries are written
(tracked and untracked). Untracked entries omit `expires_at` (nil is not
serialised by dkjson).

**Read** on `Char.Name` (via `_install_hooks()` wrap):

- Entries whose `name` is absent from `spells_data.spells` are dropped (spell
  table changed under us).
- `tracked == true` entries with `expires_at <= os.time()` are dropped (expired
  during downtime).
- `tracked == false` entries are always restored (`expires_at` is nil so they
  never expire).
- `dbg` line: `[STORED_SPELLS] restored N (M expired, K stale)`.

## Registration global

`_register_stored_spells_actions()` is a global Lua function defined in
`lua/core/stored_spells.lua`. It is called by the `_register_stored_spells_actions`
alias in `ttpp/core/stored_spells.tin`, which is invoked from:

- `SESSION CONNECTED` in `ttpp/core/system.tin` (immediately after
  `_register_affect_actions`).
- The `cp -r` reload chain in `ttpp/core/system.tin` (same position).

On its first invocation per load cycle the function also calls `_install_hooks()`,
which wraps `gmcp.handlers["Char.Name"]` to reload persisted data on login. The
`_installed` flag is module-local and resets to `false` on each `cp -r`.

## Event lifecycle

```
user sends: cast 'store' fireball
  → user_input event
    → store_attempt_started("fireball")   _pending_attempts: [fireball]

MUME: "You stored it."
  → store_succeeded
    → pop fireball from queue             _pending_attempts: []
    → append entry to stored_spells
    → persist active list
    → script_ui("STORE", "stored 'fireball' (90:00 remaining).")

MUME: "Your mind feels empty for a while."
  → store_decayed
    → find oldest entry by started_at
    → if tracked: record observed duration, persist times
    → remove entry, persist active list
    → script_ui("STORE", "'fireball' decayed (89:58 — sample recorded).")

user sends: cast 'fireball' orc
  → user_input event
    → _last_cast_intent = "fireball"

MUME: "You quickly recall your stored spell..."
  → store_recalled
    → find entry with highest started_at where name == "fireball"
    → remove entry, persist active list
    → script_ui("STORE", "'fireball' recalled.")

MUME: "You blast the area with magical energies."  (or "%1 blasts...")
  → stored_spells_untracked
    → all entries: tracked = false, expires_at = nil
    → persist active list
    → ui_warn("STORE: lost track of stored spells.")
```

## Failure queue drain

Multiple failure patterns (out of mana, backfire, etc.) each emit
`store_attempt_failed`, which pops the front of `_pending_attempts`. The queue
drains FIFO — if two store attempts were pending, the first failure consumes the
first queued spell.

An empty line sent to MUME (just Enter) aborts the oldest pending cast attempt.
Detected via RECEIVED INPUT in GAME_SESSION; reuses the `store_attempt_failed`
path.

## Default duration

When no observed samples exist for a spell, `expected_duration` defaults to
`5400` seconds (90 minutes). Once at least one natural decay has been observed,
the mean of up to 3 samples is used.

## Known limitations

### `cp -r` mid-session without reconnect

After `cp -r` the Lua brain restarts, clearing `_pending_attempts`,
`_last_cast_intent`, and `state.char.stored_spells`. MUME does not re-send
`Char.Name` while the TCP connection is live, so the persisted active list is
not reloaded until the next full reconnect. Accepted — same root cause as
documented for `docs/affects.md`.

### Untracked entries after magic blast

Once `stored_spells_untracked` fires, all entries are marked `tracked = false`
and their `expires_at` is cleared. They survive disk-restore across restarts but
no decay samples are recorded for them. The renderer (future PR) will display
them in a degraded style.

---
Back to [architecture.md](../architecture.md).
