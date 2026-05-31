# Stored Spells Tracker

Tracks active stored spells per character, learns observed decay durations from
the last 3 samples, and persists per character to disk. This document covers the
data layer and event bus; rendering is deferred to a future timers-pane
integration PR.

## Data flow

Three detection paths feed into `lua/core/stored_spells.lua`. All paths converge
on `state.char.stored_spells` and emit `stored_spells_changed` downstream.

**Path 1 — SENT OUTPUT snooper** (store-attempt tracking and non-alias intent):

```
User types: cast 'store' fireball   (or: sto fireball, stor fireball, etc.)
  │
  ▼
GAME_SESSION #event {SENT OUTPUT} — owned by _register_run_log_capture in
  ttpp/core/run_log.tin (canonical handler — see ADR 0059).
  Session-scoped to avoid recursion (see docs/ipc.md).
  USER_INPUT branch gated on non-empty payload: #if {"%0" != ""}
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
  — registered by _register_input_ipc_actions in ttpp/core/input_ipc.tin
    (cross-cutting input-IPC infrastructure, not owned by stored_spells)
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
                            ──►  data/characters/<char>/stored_spells_active.json   (disk)
                            ──►  data/characters/<char>/stored_spells_learned.json  (disk)
  │
  ▼ events.emit("stored_spells_changed")
  ▼
lua/core/timers_state.lua    ──►  bridge/runtime/timers.state   (JSON, atomic write)
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
They reset on each fresh brain launch and do not survive a reconnect.

**`_pending_attempts`** — FIFO queue (Lua array) of spell full names. One entry
is pushed per `store_attempt_started`; the front entry is consumed by
`store_succeeded`, by the store-specific `store_attempt_failed`, or by the
**shared** `spell_cast_failed` (owned by `lua/core/spellcast.lua`) — both
failure events route through the same `_drain_pending_attempt` handler. Path 2
(empty Enter) funnels into `store_attempt_failed` to pop the front. This FIFO is
stored-spells' own; it is **separate** from spellcast's `_cast_queue` (the
blind/charm queue), but a single `spell_cast_failed` pops the front of **both**
— see [Failure queue drain](#failure-queue-drain) and
[docs/spellcast.md](spellcast.md).

**`_last_cast_intent`** — single slot holding the most recent non-store spell
full name. Updated by path 1 on direct `cast 'X'` commands and by path 3 on any
cast including alias-expanded forms. Read by the `spell_cast_recalled` handler
to identify which stored entry to consume. Intentionally not cleared after a
recall so successive recalls of the same spell work correctly.

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

The `USER_INPUT:%0` dispatch lives inside the canonical
`#event {SENT OUTPUT}` handler registered by `_register_run_log_capture`
in `ttpp/core/run_log.tin` (see [ADR 0059](decisions/0059-canonical-sent-output-handler.md)
and `docs/ipc.md` for why the registration is session-scoped). The
USER_INPUT branch is gated on `#if {"%0" != ""}`, which filters
IAC/GMCP flushes that also fire `SENT OUTPUT` with empty payload.

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
{EMPTY_INPUT}}}` is registered in GAME_SESSION by
`_register_input_ipc_actions` in `ttpp/core/input_ipc.tin` — cross-cutting
input-IPC infrastructure, not a stored-spells concern. Unlike `SENT OUTPUT`,
`RECEIVED INPUT` fires only on actual user keystrokes, so an empty `%0` here
is unambiguous. The `user_input_empty` subscriber in `stored_spells.lua`
funnels into `store_attempt_failed`, popping the front of `_pending_attempts`.

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

## Stat / info reconcile

When the player types `stat` or `info`, MUME's "Affected by:" (or "You are
subjected to the following temporary effects:") block lists stored spells
interleaved with affects, one per line as `- stored spell <name>`.
Duplicates appear literally — two stored earthquakes produce two
`- stored spell earthquake` lines. Classification is by the literal
`stored spell ` prefix, never by name: a block containing both
`- armour` and `- stored spell armour` produces an affect entry and a
stored-spell entry, reconciled on independent paths.

[`lua/core/stat_reconcile.lua`](../lua/core/stat_reconcile.lua) splits each
captured `- <text>` line on the prefix and emits two events at block
terminate: `affects_observed` (for the rest) and `stored_spells_observed`
(for prefix-matching lines, prefix stripped). Either list may be empty.
See [docs/events.md](events.md#stored_spells_observed) for the event
contract.

The `stored_spells_observed` subscriber in `stored_spells.lua` runs a
per-name multiset diff:

- **Build `want`** — count occurrences per name in the observed payload,
  skipping any name not in `spells_data.spells` (silent `dbg` line
  `[STORED_SPELLS] reconcile: unknown spell <name>`).
- **Build `have`** — count occurrences per name in `state.char.stored_spells`.
- **For each name in the union**:
  - `want > have` → ADD `(want - have)` untracked entries — same shape as
    magic-blast-produced entries (`tracked = false`, no `started_at`, no
    `expected_duration`, no `expires_at`).
  - `have > want` → REMOVE `(have - want)` entries of that name. Removal
    priority: untracked entries first; then tracked entries by oldest
    `started_at` first. This preserves the running timers of tracked
    entries that the block confirms.
  - `want == have` → leave untouched.

Removals are silent: no `char_ui` "decayed" line and no duration sample is
recorded in `stored_spells_learned.json` (a reconcile removal is not a
natural decay). If anything changed, `stored_spells_changed` is emitted and
`stored_spells_active.json` is rewritten via the same `_save_active()`
helper used by the store handlers.

Tracked entries the block confirms keep their existing `expires_at`, so
the timers-pane countdown is uninterrupted. Newly-added entries render with
the existing full-grey-bar untracked styling — no renderer change.

## Persistence

### Times file

**Path:** `data/characters/<character>/stored_spells_learned.json`

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

**Path:** `data/characters/<character>/stored_spells_active.json`

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

Written atomically at the end of `store_succeeded`, the `spell_cast_recalled`
handler, `store_decayed`, and `stored_spells_untracked`. All entries are written
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
alias in `ttpp/core/stored_spells.tin`, which is invoked from `SESSION
CONNECTED` in `ttpp/core/system.tin` (immediately after
`_register_affect_actions`).

On each invocation the function registers via `session_cmd()`:

- **Four store-specific failure-pattern `#action` triggers** (priority 3) — each
  emits `store_attempt_failed` (`^Your mind is too full to store it.$`,
  `^You failed.$`, `^You do not know any such a spell.$`,
  `^You can cast quickly, fast, normally, carefully, or thoroughly.$`). The
  eight *shared* cast-failure lines are no longer registered here — they are
  owned by `lua/core/spellcast.lua` (`spell_cast_failed`), which this module
  subscribes to via `_drain_pending_attempt`. See [docs/spellcast.md](spellcast.md).
- **`store_succeeded` and `store_decayed` `#action` triggers** — one each,
  priority 3. The recall line `^You quickly recall your stored spell...$` is no
  longer registered here either — it is owned by spellcast (`spell_cast_recalled`),
  which this module subscribes to (the recall handler is unchanged).
- **`stored_spells_untracked` `#action` triggers** — two patterns (self-cast and
  third-party magic blast).
- **Two MUME-echo `#action` triggers** — path 3; emit `user_cast`.

The path 2 `RECEIVED INPUT` event is **not** registered here. It is owned
by `_register_input_ipc_actions` in `ttpp/core/input_ipc.tin` (cross-cutting
input-IPC infrastructure), and `stored_spells.lua` only subscribes to the
resulting `user_input_empty` event bus topic.

The `SENT OUTPUT` snooper that drives path 1 is **not** registered here.
It lives in the canonical `#event {SENT OUTPUT}` handler owned by
`_register_run_log_capture` in `ttpp/core/run_log.tin` (see
[ADR 0059](decisions/0059-canonical-sent-output-handler.md)); the Lua
`user_input` event-bus subscription further up in `stored_spells.lua`
is what binds this module to that dispatch. Store-attempt detection
therefore depends on both pieces being in place.

On its first invocation per load cycle the function also calls `_install_hooks()`,
which wraps `gmcp.handlers["Char.Name"]` to reload persisted data on login. The
`_installed` flag is module-local and resets to `false` on each fresh brain launch.

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
    → char_ui("store", name, "stored")                             -- ◆ STORE: fireball stored.

MUME: "Your mind feels empty for a while."
  → store_decayed
    → find oldest entry by started_at
    → if tracked: record observed duration, persist times
    → remove entry; refresh expected_duration / expires_at on remaining active
      tracked entries of the same spell so countdowns reflect the freshly
      recorded sample; persist active list
    → char_ui("store", name, "decayed", "89:58 — sample recorded") -- ◆ STORE: fireball decayed (89:58 — sample recorded).

user sends: cast 'fireball' orc
  → user_input event
    → _last_cast_intent = "fireball"

MUME: "You quickly recall your stored spell..."
  → spell_cast_recalled   (owned by spellcast.lua; stored-spells subscribes)
    → find entry with highest started_at where name == "fireball"
    → remove entry, persist active list
    → char_ui("store", name, "recalled")                           -- ◆ STORE: fireball recalled.

MUME: "You blast the area with magical energies."  (or "%1 blasts...")
  → stored_spells_untracked
    → all entries: tracked = false, expires_at = nil
    → persist active list
    → ui_warn("STORE: lost track of stored spells.")
```

## Failure queue drain

Two events drain `_pending_attempts`, both through the same
`_drain_pending_attempt` handler:

- **`store_attempt_failed`** — the four store-specific failure lines owned by
  this module (mind too full, you failed, no such spell, bad speed argument),
  plus the empty-line abort.
- **`spell_cast_failed`** — the eight shared cast-failure lines (out of mana,
  backfire, nothing happens, fear, relaxed, concentration lost, flee, too
  afraid), owned by `lua/core/spellcast.lua`.

Either pops the front of `_pending_attempts`. The queue drains FIFO — if two
store attempts were pending, the first failure consumes the first queued spell.

An empty line sent to MUME (just Enter) aborts the oldest pending cast attempt.
Detected via RECEIVED INPUT in GAME_SESSION; reuses the `store_attempt_failed`
path.

**Cross-pop.** `spell_cast_failed` is subscribed by **both** stored-spells
(this `_pending_attempts` FIFO) and spellcast (its own `_cast_queue` of
blind/charm attempts). A single shared failure therefore pops the front of both
FIFOs. With a store and a blind/charm in flight at once, one failure desyncs
both — the accepted trade-off; both modules guard the empty case and spellcast's
10 s idle flush bounds the staleness. See
[ADR 0123](decisions/0123-shared-cast-feedback-ownership.md) and
[docs/spellcast.md](spellcast.md).

## Default duration

When no observed samples exist for a spell, `expected_duration` defaults to
`5400` seconds (90 minutes). Once at least one natural decay has been observed,
the mean of up to 3 samples is used.

## Known limitations

### Untracked entries after magic blast

Once `stored_spells_untracked` fires, all entries are marked `tracked = false`
and their `expires_at` is cleared. They survive disk-restore across restarts but
no decay samples are recorded for them. The renderer (future PR) will display
them in a degraded style.

---
Back to [architecture.md](../architecture.md).
