# Affect Tracker

Tracks active affects per character, learns observed durations from the last
3 sessions, and persists per character to disk. This document covers the
data layer and event bus; rendering is handled by the timers pane — see
[`docs/timers-pane.md`](timers-pane.md) for the rendering spec.

## Data flow

```
MUME game output
      │
      ▼
tt++ #action (GAME_SESSION, priority 3)
  — one action per unique pattern string
  — registered by _affects_register_triggers() at SESSION CONNECTED
      │
      ▼ events.emit("affect_init"|"affect_refresh"|"affect_down", name)
      │
      ▼
lua/core/affects.lua  ──►  state.char.affects      (active list)
                      ──►  state.char.affect_times  (ring-buffer history)
                      ──►  data/characters/<character>/affects_learned.json  (disk)
```

## State schema

### `state.char.affects`

Array of currently-active affect entries:

```lua
{
    name              = "armour",    -- string, matches key in affects_data.affects
    type              = "protection",-- string, from data table
    started_at        = 1714000000, -- os.time() when init or refresh fired
    expected_duration = 1800,        -- integer seconds (mean of samples, else static, else nil)
    expires_at        = 1714001800, -- started_at + expected_duration, or nil
}
```

`expected_duration` and `expires_at` are nil for indefinite affects — those
whose data-table entry has no `duration` field (e.g. `hunger`, `thirst`,
`comfortable`, `growth`, `depression`).

### `state.char.affect_times`

Table mapping affect name → array of up to 3 observed durations (integers,
seconds). FIFO ring-buffer: push to end, drop from front when length exceeds 3.

```lua
{
    armour    = {1800, 1795, 1803},
    sanctuary = {268, 271, 267},
}
```

Both slots are initialised to `{}` at module load and re-initialised to `{}`
on each `Char.Name` (login). `state.char.reset()` (called on disconnect) wipes
them via the standard non-function-key sweep in `char_state.lua`.

## Untracked entries (stat / info reconcile)

When the player types `stat` or `info`, MUME prints an "Affected by:" (or
"You are subjected to the following temporary effects:") block — one affect
per line as `- <name>`, terminated by the first line that does not start
with `- ` (in practice the prompt or any other received line).
[`lua/core/stat_reconcile.lua`](../lua/core/stat_reconcile.lua) parses the
block and emits `affects_observed` with the collected name list (stored
spells are split off by the `stored spell ` prefix into a parallel
`stored_spells_observed` event — see [docs/stored-spells.md](stored-spells.md#stat--info-reconcile)).
The `affects.lua` subscriber iterates `affects_data.affects` (the known
universe — unknown names in the payload are skipped) and:

- **observed AND not currently active** → ADD an entry. Timed-capable
  (data has `duration`): `{name, type, tracked = false}` — no `started_at`,
  no `expected_duration`, no `expires_at`; the bar does not drain because
  we have no real timing source yet. Indefinite (no `duration`): a normal
  indefinite entry (`expires_at = nil`, `tracked` not set).
- **currently active AND not observed** → REMOVE the entry silently: no
  `char_ui` "down" line and no sample push. This rule is uniform —
  indefinite affects (`hunger`, `thirst`, `comfortable`, `growth`,
  `depression`) are pruned too. Stat/info is the canonical truth at that
  moment; there is no carve-out for "duration is nil".
- **currently active AND observed** → leave untouched; timed entries keep
  their running timer, untracked entries stay untracked.

`affects_changed` is emitted and the active-list file is written only if
something changed.

**Graduation.** If `affect_init` or `affect_refresh` later fires for an
untracked entry, the refresh path clears the `tracked` field and sets
`started_at` / `expected_duration` / `expires_at` normally — the entry
becomes a tracked timed affect and the bar starts draining. The tick is
armed at this transition (named delay, so re-arming is idempotent).

**affect_down guard.** Untracked entries have no `started_at`, so the
`affect_down` handler short-circuits the observed-duration math and the
sample push when `entry.tracked == false` or `started_at` is nil. The
`char_ui` "down" line and `affects_changed` still fire so the UI and
renderer converge.

## Indefinite affects

Entries in `affects_data.lua` without a `duration` field are indefinite. They
are tracked while active (entry exists in `state.char.affects`, removed when
the drop string fires), but no remaining time is computed, no row suffix is
rendered, and no observed durations are recorded. Examples: `hunger`, `thirst`,
`comfortable`, `growth`, `depression`.

The `duration` field is the single gate: if it is absent, `expected_duration`
and `expires_at` are both nil regardless of any legacy samples on disk. The
tick never prunes indefinite entries. Duration-less affects never appear in
`data/characters/<character>/affects_learned.json`.

Indefinite affects are also excluded from active-list persistence (see
[Persistence — active list](#persistence--active-list) below). Rationale:
their state is unreliable across long absences and we prefer fresh
re-initialisation from in-game refresh strings.

- No `◆ TAG: name refreshed.` UI line is emitted when `initString_2`
  matches for a duration-less affect. The internal refresh path still
  runs (`started_at` is updated, `affects_changed` fires), but the
  player-facing announcement is suppressed because "refreshed" has no
  meaningful semantics without a timer.

## Persistence

**Path:** `data/characters/<character>/affects_learned.json`

`<character>` is `state.char.name` exactly as received from GMCP `Char.Name`
(no case-folding, no sanitising).

**Format:**

```json
{
  "sanctuary": [266, 271, 269],
  "armour":    [1095, 1100, 1102]
}
```

Only affects that have been seen to drop naturally are persisted. Affects
pruned by the tick (past predicted expiry with no game confirmation) are NOT
recorded — that duration sample is suspect. Duration-less affects (no
`duration` field in the data table) never appear in this file; any such
entries written by an older version are filtered out at load time and removed
on the next write.

**Write:** atomic temp-file + `os.rename`, synchronous, inside `affect_down`.

**Read:** on `Char.Name` (via the `gmcp.handlers["Char.Name"]` wrap installed
by `_install_hooks()`). If the file is absent or malformed, `state.char.affect_times`
stays `{}` and a non-fatal `dbg` warning is logged.

## Persistence — active list

**Path:** `data/characters/<character>/affects_active.json`

`<character>` is `state.char.name` verbatim (same convention as
`data/characters/`).

**Schema:** a JSON array of entries with the same shape as
`state.char.affects` items:

```json
[
  {
    "name": "armour",
    "type": "protection",
    "started_at": 1714000000,
    "expected_duration": 1800,
    "expires_at": 1714001800
  }
]
```

Indefinite affects (`expires_at == nil`) are never written. When the last
timed affect drops the file is written as an empty array (`[]`) rather
than deleted, keeping it as a stable presence indicator.

**Write (atomic temp-file + `os.rename`)** at four points:

- End of `affect_init` handler (after entry appended).
- End of `affect_refresh` handler (after `started_at` / `expires_at` updated).
- End of `affect_down` handler (after `table.remove`).
- End of `_affects_tick` after the prune sweep, but only when at least one
  entry was removed (tracked with a `pruned` flag).

**Read** on `Char.Name` as step 4 of the `_install_hooks()` wrap, immediately
after `_load_times()`:

- Missing or malformed file → `dbg` warning, `state.char.affects` stays `{}`.
- Each entry is skipped if: `expires_at == nil` (indefinite / corrupt), the
  affect name is absent from `affects_data.affects`, the data-table entry has
  no `duration` field (table changed under us), or `expires_at <= os.time()`
  (expired during downtime). Expired entries are counted separately in the
  `dbg` log line.
- Surviving entries are appended to `state.char.affects`. If any survive, the
  tick delay is armed and `affects_changed` is emitted.
- No `char_ui` lines are emitted — restore is silent.
- `dbg` line: `[AFFECTS] restored N active affects (M expired)`.

## Pattern storage convention

Pattern strings in `affects_data.lua` (`initString_1`, `initString_2`,
`dropString_1`, `dropString_2`) are stored anchored (`^...$`) in
tt++-compatible form and passed verbatim to `#action` at registration time.
No transformation happens at runtime.

Patterns that share the same string (e.g. `second wind`'s `dropString_1` and
`winded`'s `initString_1`) are collapsed into a single `#action` whose body
emits all relevant events semicolon-separated inside one `#lua {}` block.

### When adding new affects

Pre-convert patterns before committing to the data file:

1. Replace `\.` with `.` (tt++ treats `.` as a literal dot; no escaping needed).
2. Replace `.*` with `%*` (tt++ zero-or-more wildcard).
3. Anchor the pattern with `^` at the start and `$` at the end.
   This guards against false matches from tells, says, narrates, and
   social emotes that quote the same line.

If the pattern contains regex metacharacters not covered by these steps
(`\d`, `\w`, `[...]`, `(...)`, `?`, `+`, `|`), it cannot be used directly —
rewrite the pattern or split it into separate entries.

Examples:

| Game string trigger                    | Pattern to store                  |
|----------------------------------------|-----------------------------------|
| `^You start glowing.`                  | `^You start glowing.$`            |
| `^You feel weaker.$`                   | `^You feel weaker.$`              |
| `^You completely drain.*$`             | `^You completely drain%*$`        |
| `^Your lungs seem to burst as.*$`      | `^Your lungs seem to burst as%*$` |

## Registration global

`_affects_register_triggers()` is a global Lua function defined in
`lua/core/affects.lua`. It is called by the `_register_affect_actions` alias
in `ttpp/core/affects.tin`, which is invoked from `SESSION CONNECTED` in
`ttpp/core/system.tin` (immediately after `_register_clock_actions`).

The stat/info block parser is wired in parallel:
`_register_stat_reconcile_actions()` (in `lua/core/stat_reconcile.lua`) is
invoked from the `_register_stat_reconcile_actions` alias in
`ttpp/core/stat_reconcile.tin`, called from `SESSION CONNECTED` after
`_register_stored_spells_actions`. It registers two header `#action`
triggers (`^Affected by:$`, `^You are subjected to the following temporary
effects:$`) whose tt++ body arms a dynamic catch-all `#action {^%1$}`
inline — synchronously, inside a `#class {core} {open/close}` wrap (per
ADRs 0049 / 0050). Each captured line is forwarded via the structured-event
IPC path (`STAT_LINE:<raw>`), which tolerates quote and parenthesis
characters in a way a Lua `load()` eval would not. On the first non-`- `
line the handler calls `session_cmd("#unaction {^%1$}")` and emits
`affects_observed` with the buffered name list.

The function also calls `_install_hooks()` on its first invocation per load
cycle, which wraps `gmcp.handlers["Char.Name"]` (to reload persisted times on
login) and `state.char.reset` (to cancel the tick on disconnect). The
`_installed` flag is file-local and resets to `false` on each fresh brain
launch.

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing alias and exists only to populate the
game session's action list from the data table.

## Periodic tick

A named `#delay {affects_tick}` runs every 10 seconds in GAME_SESSION while
at least one affect is active. Tick behaviour depends on whether the affect
has a configured drop string (`dropString_1` or `dropString_2`):

**No drop string** — prune at `expires_at` as before. No observed-duration
sample is recorded (game never confirmed the drop). Dbg log:
`[AFFECTS] tick expire: <name>`.

**Has drop string** — the drop message is the sole expiry signal. The tick
keeps the entry in overrun (`expires_at <= now`) and does nothing, so the
renderer can show `!` and `affect_down` can record the actual duration when
the drop arrives. A hard 2.5× safety net applies: if
`now - started_at >= floor(2.5 × expected_duration)` the entry is silently
pruned with no sample and no `char_ui` "down" line. Dbg log:
`[AFFECTS] tick timeout (no drop): <name>`.

**Corrupt entry** (affect name absent from `affects_data.affects`) — pruned
immediately; dbg log `[AFFECTS] tick expire: <name>` (same path as no-drop).

The tick fires every 10 s regardless of overrun — `affects_changed` is emitted
each cycle so the renderer re-evaluates overrun cells.

The tick is self-rescheduling: if `state.char.affects` is non-empty after the
sweep it re-issues `#delay {affects_tick} {#lua {_affects_tick()}} {10}`.
Named non-numeric delays replace an existing delay of the same name (confirmed
by `ttpp_manual.txt`), so re-arming is idempotent.

The tick is armed on the 0→1 transition in `affect_init` and cancelled:
- When the last active affect drops (`affect_down` empties the array).
- When `state.char.reset()` fires (via the reset wrapper — only effective when
  GAME_SESSION is still set, i.e. the Core.Goodbye path; the SESSION DISCONNECTED
  fallback path finds GAME_SESSION nil, but the session dying clears all its
  delays automatically).

## Overrun

An affect with a drop string that remains active past its `expires_at` is in
**overrun**. Its entry stays in `state.char.affects` with no change to
`expires_at`. `status_state.lua` therefore emits a negative `remaining_seconds`
(not clamped). The status pane renders the cell with a `!` suffix instead of
`Xm`. The affect is removed — and its observed duration recorded — when
`affect_down` fires. The 2.5× safety net is the only tick-driven removal.

## Rendering

`state.char.affects` is the data source for the timers pane renderer. See
[docs/timers-pane.md](timers-pane.md) for the rendering phase details.

Each `affect_init`, `affect_refresh`, and `affect_down` event also emits a
`◆ TAG: name verb.` line to the UI pane via `char_ui()` — see
[docs/ui-messaging.md](ui-messaging.md) for the format and colour palette.

---
Back to [architecture.md](../architecture.md).
