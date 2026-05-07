# Stored Spells Tracker

Tracks active stored spells per character, learns observed decay durations from
the last 3 samples, and persists per character to disk. This document covers the
data layer and event bus; rendering is deferred to a future buffs-pane
integration PR.

## Data flow

Three detection paths feed into `lua/core/stored_spells.lua`. All paths converge
on `state.char.stored_spells` and emit `stored_spells_changed` downstream.

**Path 1 — SENT OUTPUT snooper** (store-attempt tracking and non-alias intent):

```
User types: cast 'store' fireball   (or: sto fireball, stor fireball, etc.)
  │
  ▼
GAME_SESSION #event {SENT OUTPUT} — session-scoped to avoid recursion (see docs/ipc.md)
  — non-empty payload only: #if {"%0" != ""}
  │
  ▼ #lua {USER_INPUT:%0}
  │
  ▼
brain.lua handlers["USER_INPUT"]
  — rejoins parts with ":" (raw input may contain ":")
  — events.emit("user_input", raw)
  │
  ▼
stored_spells.lua — user_input subscriber
  — matches sto/stor/store X shortcuts and cast '...' / cast speed '...' syntax
  — resolves spell names via _resolve_spell()
  — if "store": events.emit("store_attempt_started", target)
  — else: _last_cast_intent = resolved (for recall detection)
  │
  ▼ events.emit("store_attempt_started", "fireball")
  ▼
stored_spells.lua — store_attempt_started subscriber
  — appends to _pending_attempts FIFO
```

**Path 2 — RECEIVED INPUT** (empty-input abort):

```
User presses Enter on empty line
  │
  ▼
GAME_SESSION #event {RECEIVED INPUT} — fires only on actual user keystrokes
  — empty payload only: #if {"%0" == ""}
  │
  ▼ #lua {EMPTY_INPUT}
  │
  ▼
brain.lua handlers["EMPTY_INPUT"]
  — events.emit("user_input_empty")
  │
  ▼
stored_spells.lua — user_input_empty subscriber
  — if _pending_attempts non-empty: events.emit("store_attempt_failed")
  — else: silent no-op
```

**Path 3 — MUME server echo** (`_last_cast_intent` alias coverage):

```
MUME echoes every cast:  [cast 'armour']   or   [cast n 'armour']
  │
  ▼
GAME_SESSION #action — ^[c%1 '%2'  and  ^[c%1 %2 '%3'  (priority 3)
  — registered by _register_stored_spells_actions()
  │
  ▼ events.emit("user_cast", captured_spell_text)
  │
  ▼
stored_spells.lua — user_cast subscriber
  — resolves captured text via _resolve_spell()
  — if resolved != "store": _last_cast_intent = resolved
```

**State and persistence** (all paths converge):

```
tt++ #action (GAME_SESSION, priority 3) → events.emit("store_succeeded" | "store_decayed" | ...)
  │
  ▼
lua/core/stored_spells.lua  ──►  state.char.stored_spells       (active list)
                            ──►  state.char.stored_spell_times   (ring-buffer history)
                            ──►  logs/stored_spells_active/<char>.json   (disk)
                            ──►  logs/stored_spells_times/<char>.json    (disk)
  │
  ▼ events.emit("stored_spells_changed")
  ▼
lua/core/buffs_state.lua    ──►  bridge/buffs.state   (JSON, atomic write)
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

### Runtime-only structures

Two module-local variables hold transient state that is never written to disk.
They reset on each `cp -r` (fresh module load) and do not survive a reconnect
without reload.

**`_pending_attempts`** — FIFO queue (Lua array) of spell full names. One entry
is pushed per `store_attempt_started`; the front entry is consumed by
`store_succeeded` or `store_attempt_failed`. Path 2 (empty Enter) funnels into
`store_attempt_failed` to pop the front.

**`_last_cast_intent`** — single slot holding the most recent non-store spell
full name. Updated by path 1 on direct `cast 'X'` commands and by path 3 on any
cast including alias-expanded forms. Read by `store_recalled` to identify which
stored entry to consume. Intentionally not cleared after a recall so successive
recalls of the same spell work correctly.

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

## Cast detection

### Path 1 — SENT OUTPUT snooper

The only path that sees the target spell for store attempts. This path drives
`_pending_attempts` exclusively.

The event `#event {SENT OUTPUT} {#if {"%0" != ""} {#lua {USER_INPUT:%0}}}` is
registered in GAME_SESSION by `_register_stored_spells_actions()` (see
`docs/ipc.md` for why top-level registration causes self-amplifying recursion
and must be session-scoped). The `%0 != ""` guard filters IAC/GMCP flushes that
also fire `SENT OUTPUT` with empty payload.

The `user_input` subscriber matches in two stages, first match wins:

**Top-level store shortcuts** — MUME accepts `sto X`, `stor X`, and `store X`
as server-side shortcuts that expand to `cast 'store' X`. Prefixes are tested
longest-first (`store` before `stor` before `sto`) to avoid ambiguous matches.
If the target resolves, `store_attempt_started` is emitted.

**`cast '...'` syntax** — if no shortcut matched, two Lua patterns are tried:

- `^c%w+%s+%w+%s+'([^']+)'%s*(.*)$` — cast with speed modifier
- `^c%w+%s+'([^']+)'%s*(.*)$` — cast without speed modifier

If the resolved spell is `"store"`, the tail is parsed as the target and
`store_attempt_started` is emitted. Otherwise `_last_cast_intent` is set.

### Path 2 — RECEIVED INPUT (empty-input abort)

An empty line sent to MUME (just Enter) tells MUME to abort the current
cast-in-progress. The event `#event {RECEIVED INPUT} {#if {"%0" == ""} {#lua
{EMPTY_INPUT}}}` is registered in GAME_SESSION by `_register_stored_spells_actions()`.
Unlike `SENT OUTPUT`, `RECEIVED INPUT` fires only on actual user keystrokes, so
an empty `%0` here is unambiguous. The `user_input_empty` subscriber funnels
into `store_attempt_failed`, popping the front of `_pending_attempts`.

### Path 3 — MUME server echo

MUME echoes every cast attempt as a bracketed line regardless of whether the
player typed full `cast '...'` syntax or a server-side alias (e.g. `arm`,
`fireb`). Two `#action` patterns are registered in GAME_SESSION by
`_register_stored_spells_actions()`:

```
^[c%1 '%2'     — [cast 'armour']       (no speed prefix)
^[c%1 %2 '%3'  — [cast n 'armour']     (with speed prefix)
```

The `^[c` start-anchor prevents false matches against mid-line bracket content.
No closing `]` anchor — targeted casts (`[cast n 'fireball' orc]`) match
identically to untargeted ones. The captured spell text is emitted as
`user_cast` and resolved to update `_last_cast_intent`. The `"store"` spell is
filtered on this path because path 1 already handles it and also knows the
target spell.

### Why two paths for non-store casts

Path 1 (SENT OUTPUT) misses alias-expanded casts — if a player types `arm`,
no `cast '...'` syntax appears in the outgoing bytes, so `_last_cast_intent`
would not be set. Path 3 (MUME echo) covers these because MUME always echoes
the expanded bracketed form. Conversely, path 3 does not include the cast
target, so store-attempt tracking (which needs the target spell) must come from
path 1 exclusively.

Direct `cast 'X'` commands hit both paths in quick succession (SENT OUTPUT
fires first, then the game echoes). The second write is idempotent — both
resolve to the same full name.

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

On each invocation the function registers via `session_cmd()`:

- **`SENT OUTPUT` event** — path 1 snooper; non-empty payload only.
- **`RECEIVED INPUT` event** — path 2 abort detector; empty payload only.
- **Twelve failure-pattern `#action` triggers** (priority 3) — each emits
  `store_attempt_failed`.
- **`store_succeeded`, `store_decayed`, `store_recalled` `#action` triggers** —
  one each, priority 3.
- **`stored_spells_untracked` `#action` triggers** — two patterns (self-cast and
  third-party magic blast).
- **Two MUME-echo `#action` triggers** — path 3; emit `user_cast`.

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
    → script_ui("STORE", "stored " .. ui_var(name) .. ".")        -- ▶ STORE: stored fireball.

MUME: "Your mind feels empty for a while."
  → store_decayed
    → find oldest entry by started_at
    → if tracked: record observed duration, persist times
    → remove entry; refresh expected_duration / expires_at on remaining active
      tracked entries of the same spell so countdowns reflect the freshly
      recorded sample; persist active list
    → script_ui("STORE", ui_var(name) .. " decayed (89:58 — sample recorded).")

user sends: cast 'fireball' orc
  → user_input event
    → _last_cast_intent = "fireball"

MUME: "You quickly recall your stored spell..."
  → store_recalled
    → find entry with highest started_at where name == "fireball"
    → remove entry, persist active list
    → script_ui("STORE", ui_var(name) .. " recalled.")

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
