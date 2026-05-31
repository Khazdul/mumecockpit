# Herblore Tracker

Tracks manually-added **herblores** — fixed sequences of timed phases, where
each phase is a buff or debuff with its own duration. When a phase's time
elapses the tracker advances to the next phase; the current phase renders in the
buffs pane exactly like an ordinary affect and moves between the Buffs and
Debuffs groups by itself when a phase flips type.

Mirrors the charm tracker ([`lua/core/charm.lua`](../lua/core/charm.lua)) in
shape — atomic per-character JSON persistence, a named `#delay` tick, restore on
`gmcp_char_name`, undelay on `char_reset`, and a `_register_*_actions`
registration seam — but there is **no cast snoop and no in-flight gate**:
herblores are added and removed entirely by hand. This document covers the data
layer and event flow; rendering lives in the buffs pane — see
[docs/buffs-pane.md](buffs-pane.md).

## Catalog

The catalog is static, module-local in `lua/core/herblores.lua`. Each key is the
**phase-1 base name** — a single token, safe to pass through `tmux send-keys`.
Each phase is `{name, duration (s), type}`:

| Key            | Phases (name · duration · type)                                                         |
| -------------- | --------------------------------------------------------------------------------------- |
| `Healing`      | Healing 3600 buff → Healing (low) 3600 buff                                              |
| `Travelling`   | Travelling 7200 buff → Travelling (med) 1440 buff → Travelling (min) 1440 buff           |
| `Clearthought` | Clearthought 120 buff → Clearthought (low) 240 buff → Clearthought (neg) 360 **debuff**  |
| `Walking`      | Walking 1440 buff → Walking (med) 7200 buff → Walking (min) 1440 buff                    |
| `Haste`        | Haste 360 buff → Haste (recovery) 1080 **debuff**                                        |

`CATALOG_KEYS` keeps a stable key order (Lua table iteration is unordered) and is
exposed through the global `herblore_catalog_keys()` for the buffs pane's PR 2
add-view; `lua/core/buffs_state.lua` serialises it as the static
`herblore_catalog` field.

## Phase derivation

`_derive(key, started_at, now)` is the **single source of truth** for "which
phase is active now", shared by the live tick and the restore path. It walks the
catalog durations from `started_at` and returns
`phase_index, name, type, expires_at, expected_duration` for the active phase,
or `nil` once every phase has elapsed. `expires_at` is the end of the current
phase and `expected_duration` is that phase's full length, so the buffs pane's
bar drains 100 %→0 % across each phase.

## Data model

### `state.char.herblores`

Array of active herblore entries (the **current phase** of each):

```lua
{
    key               = "Clearthought",       -- catalog key (phase-1 base name)
    started_at        = 1714000000,           -- os.time() at add
    phase             = 3,                     -- current phase index
    name              = "Clearthought (neg)", -- current phase name
    type              = "debuff",             -- current phase type
    expires_at        = 1714000720,           -- end of the current phase
    expected_duration = 360,                  -- current phase length
}
```

Only `{key, started_at}` is **persisted**; every other field is derived. The
list is initialised to `{}` at load and on every `gmcp_char_name`, then
repopulated from disk. `char_reset` (disconnect) wipes the in-memory list via the
standard `char_state.lua` sweep, but the disk file survives.

## Add / remove

- `herblore_add(key)` — no-op if `key` is unknown **or** already active (no
  refresh). Otherwise sets `started_at = os.time()`, builds the phase-1 entry,
  persists, arms the tick, emits `herblores_changed`, and announces
  `char_ui("herb", name, "up")`.
- `herblore_remove(key)` — removes the matching entry, persists, emits
  `herblores_changed`, and announces `char_ui("herb", <current name>, "down")`.
  No-op if not active.

Both are global functions, invoked from the `_cp_herblore_add` /
`_cp_herblore_remove` aliases.

## Tick

A named `#delay {herblores_tick}` runs `_herblores_tick()` every 2 s while at
least one herblore is active. Each entry is re-derived:

- `nil` → the herblore fully elapsed: removed, with `char_ui("herb", name,
  "down")`.
- a new phase index → the entry is relabelled in place (`name`/`type`/
  `expires_at`/`expected_duration`/`phase`). **Intermediate phase transitions are
  silent** — the grid cell relabels itself and may move between the Buffs and
  Debuffs groups, with no UI line.

The tick re-arms while any entry remains, and persists + emits
`herblores_changed` only on a change.

> **Announce policy (PR 1).** Only `up` (on add) and `down` (on final drop /
> manual remove) are emitted; intermediate transitions are silent. Whether a
> buff→debuff flip (`Clearthought`→neg, `Haste`→recovery) should announce itself
> is deferred to the doc/ADR step that closes
> [ADR 0043](decisions/0043-unified-character-event-marker.md)'s reserved `herb`
> verb set.

## Persistence

Active herblores survive reconnect and a full restart, mirroring charms. The
store is `data/characters/<char>/herblores_active.json`, where `<char>` is
`state.char.name` verbatim.

- **Write** — `_save_active()` does an atomic temp-file + `os.rename` write of
  `[{key, started_at}, …]`. An empty list is written as `[]` (never deleted), so
  reconnect always finds a definitive file. Called on add, remove, and on each
  tick that changes state. It is **not** called on `char_reset` — disconnect
  must never overwrite the file.
- **Load** — `_load_active(char_name)` runs from the `gmcp_char_name` handler
  (cold start and reconnect), after the in-memory list is reset to `{}`. Each
  persisted `{key, started_at}` is run through `_derive`: dropped if every phase
  elapsed during downtime, otherwise rebuilt at its current phase. Arms the tick
  if anything survived, and **always emits `herblores_changed`** at the end
  (load-bearing: `herblores.lua` loads after `buffs_state.lua` alphabetically, so
  the buffs pane re-serialises regardless of module load order). Logs
  `[HERB] restored N (M expired)`.

`char_reset` only undelays the tick (when `GAME_SESSION` is still set) and never
touches disk.

## Rendering and announcements

`state.char.herblores` is serialised into `bridge/runtime/buffs.state` (current
phase only) and rendered by the buffs pane as ordinary buff/debuff cells — see
[docs/buffs-pane.md](buffs-pane.md). Lifecycle lines go to the UI pane via
`char_ui("herb", name, "up" | "down")` (the `HERB` tag, herb-green `#9CCC65`;
see [docs/ui-messaging.md](ui-messaging.md#character-events)).

## Registration global

`_register_herblore_actions()` is a global Lua function in
`lua/core/herblores.lua`, called by the matching alias in
`ttpp/core/herblores.tin`, invoked from `SESSION CONNECTED` in
`ttpp/core/system.tin` alongside `_register_charm_actions`. It registers the two
manual aliases:

```
#alias {_cp_herblore_add %1}    {#lua {herblore_add("%1")}}    {3}
#alias {_cp_herblore_remove %1} {#lua {herblore_remove("%1")}} {3}
```

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing automation alias and exists only to
populate the game session's alias list.

---
Back to [architecture.md](../architecture.md).
