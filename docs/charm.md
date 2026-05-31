# Charm Tracker

Tracks charmed mobs with a 99-minute auto-drop ceiling, a count-up timer, and
click-to-drop from the buffs pane. Mirrors the blinds tracker
([`lua/core/blinds.lua`](../lua/core/blinds.lua)) in shape, but its success line
is ambiguous, so it gates on an in-flight cast rather than landing
unconditionally.

This document covers the data layer and event flow; rendering lives in the
buffs pane — see [docs/buffs-pane.md](buffs-pane.md). Pending charm casts ride
the shared cast-attempt FIFO owned by [`lua/core/spellcast.lua`](../lua/core/spellcast.lua);
see [docs/spellcast.md](spellcast.md) and
[ADR 0123](decisions/0123-shared-cast-feedback-ownership.md).

## Cast recognition

`_parse_charm_cast(raw)` recognises an outgoing charm cast on the `user_input`
event. A line matches when:

- the first whitespace token is a prefix of `cast` (1–4 chars, case-folded:
  `c`, `ca`, `cas`, `cast`);
- it contains a single-quoted token that, lowercased, is a prefix of `charm` of
  length ≥ 2 (`'ch'` matches, a bare `'c'` does not).

There is **no numeric prefix and no target extraction** — unlike blindness, the
charmed mob's name comes from the success line, not the cast. A recognised cast
enqueues `{kind="charm"}` onto the shared FIFO:

```lua
events.subscribe("user_input", function(raw)
    if not _parse_charm_cast(raw) then return end
    spellcast.enqueue({ kind = "charm" })
end)
```

## The in-flight gate

The success line `<name> starts following you.` is genuinely ambiguous —
mercenaries, pets, and group members also start following you. So charm only
tracks a follow when one of **our** charm casts is actually in flight at the
front of the queue.

The gate is the `inflight` flag. A self-cast that has begun concentrating
(`spell_cast_started`) or a recalled stored charm (`spell_cast_recalled`) marks
the front charm entry in-flight:

```lua
events.subscribe("spell_cast_started",  function() spellcast.mark_front_inflight("charm") end)
events.subscribe("spell_cast_recalled", function() spellcast.mark_front_inflight("charm") end)
```

The landed-charm handler then pops via `pop_if_front_inflight("charm")`, which
returns the entry only when the front is a charm **and** marked in-flight. A
follow with no in-flight charm at the front is some other follower and is
ignored.

## Success lines

Two `#action` patterns (priority 3) route to the same handler,
`_charm_on_followed("%1")`:

- `^%1 starts following you.$` — the ambiguous follow line.
- `^Your control on %1 is renewed!$` — fires when re-charming an
  already-charmed mob. It is unambiguous, but runs through the same in-flight
  gate and handler, adding a **fresh** entry (a re-cast is a new charm). The
  player drops any stale duplicate manually with the pane's ×.

`_charm_on_followed` strips a leading article from the captured name
**case-insensitively** (`an `/`a `/`the `, each only when followed by
whitespace, so names like `Anaru` or `Theoden` stay intact) — the follow line
carries a sentence-start capitalised article, while the control-renewed line
carries a mid-sentence lowercase one. Because both lines pass through the shared
in-flight gate, only one fires per cast, so no double-add can occur even if both
ever matched.

A charm-specific resist failure, `^%1 seems to be ruled by powers other than
yours...$`, calls `spellcast.fail_front()` directly (queue-only, no event) — it
is not a shared store-failure line, so it drains the FIFO front itself.

## Control-without-charm followers

Some mobs are commanded **without** casting charm. Each produces a fixed,
unambiguous follow line, so unlike charm they need **no** in-flight cast gate —
the line itself is the proof. They share `state.char.charms`, rendering,
persistence, and click-to-drop with charmed mobs, and are added by
`_control_on_followed(name)` (a global, called from `_charm_on_followed` once it
recognises a known controlled-mob name).

The mobs and their behaviours live in the module-local `CONTROLLED` table:

| Mob               | Behaviour                                                        |
| ----------------- | --------------------------------------------------------------- |
| `enslaved shadow` | **Permanent** — no timer, never tick-pruned, dropped only by ×. |
| `wood elf`        | **Timed** — 99-min cap, ticked and auto-dropped like a charm.   |
| `dreadful warg`   | **Permanent**, and **supersedes** `enslaved shadow`.            |

Permanent entries carry **no** `expected_duration`/`expires_at`, so the tick
never prunes them and the buffs pane shows no minutes for them. Timed entries
get the same fields a landed charm does.

`dreadful warg` supersedes `enslaved shadow`: an enslaved shadow can transform
into a dreadful warg in-game, and the warg's follow line is the only signal. So
`_control_on_followed("dreadful warg")` first calls `_remove_first_by_name(
"enslaved shadow")` — which removes the **oldest** matching entry (it cannot
disambiguate duplicates) and surfaces its `char_ui(..., "down")` line — then adds
the warg, with a single `_save_active()`/`charms_changed` covering both. With no
shadow present, only the warg is added.

There are **no** per-mob `#action` lines. The generic
`^%1 starts following you.$` action is the only matcher; `_charm_on_followed`
strips the article and, if the name is in `CONTROLLED`, dispatches to
`_control_on_followed` and returns **before** the cast FIFO is touched (a
controlled-mob follow must not consume a queued charm). tt++ fires only one
matching `#action` per line ([ADR 0115](decisions/0115-core-priority-band.md)),
so a separate per-mob trigger at the same priority would tie on alphabetical
order and risk silently suppressing one side — dispatching by name in Lua avoids
that race by design.

The `wood elf` also has a real in-game **leave** line,
`^A wood elf leaves and vanishes into the distance.$`, routed to the global
`_control_on_left("wood elf")`. This is the **primary** drop path; the 99-min
cap is only a safety ceiling for a missed line (the drop-signal-primary,
tick-cap-fallback pattern of
[ADR 0027](decisions/0027-drop-driven-affect-expiry.md)).
`_control_on_left` removes the oldest matching entry via `_remove_first_by_name`
(which already surfaces the `char_ui(..., "down")` line), then persists and emits
`charms_changed`; with none tracked it is a no-op. Permanent controlled mobs
have no leave line — they are dropped only by the ×.

See [ADR 0124](decisions/0124-controlled-without-charm-followers.md) for the
design rationale (one matcher with in-handler name dispatch over a separate
band-4 trigger, and the permanent-vs-timed policy table).

## The 99-minute cap

Charm has no real in-game duration and no drop string. `CHARM_CAP` is
`99 * 60` seconds; a landed entry sets `expires_at = started_at + CHARM_CAP`.
A named `#delay {charms_tick}` runs `_charms_tick()` every 2 s while at least
one charm is active and prunes any entry whose `expires_at <= now`, emitting a
`char_ui("charm", name, "down")` line per pruned entry. The cap is a ceiling,
not a prediction — it is the only removal path besides an explicit drop.

## Data model

### `state.char.charms`

Array of currently-charmed mob entries:

```lua
{
    id                = 7,           -- monotonic per-session id (see below)
    name              = "orc",       -- mob name, article stripped
    started_at        = 1714000000,
    expected_duration = 5940,         -- always 99 * 60
    expires_at        = 1714005940,  -- started_at + 99 * 60
}
```

`id` is assigned from a module-local `_next_id` counter, used by the buffs
pane's click-to-drop × to target a specific entry. It is **never reused within a
session**; on reload `_next_id` is restored past the highest persisted id so a
restored charm and a freshly-landed one never collide.

Permanent control-without-charm entries (see above) omit `expected_duration`
and `expires_at` entirely — those nil fields are what mark an entry untimed for
the tick (never pruned) and for the buffs pane (no minutes column).

The list is initialised to `{}` at load and on every `gmcp_char_name`, then
repopulated from disk. `char_reset` (disconnect) wipes the in-memory list via
the standard `char_state.lua` sweep, but the disk file survives.

## Persistence

Active charms survive reconnect and a full restart, mirroring blinds and
stored-spells. The store is `data/characters/<char>/charms_active.json`, where
`<char>` is `state.char.name` verbatim.

- **Write** — `_save_active()` does an atomic temp-file + `os.rename` write of
  `state.char.charms`. An empty list is written as `[]` (never deleted), so
  reconnect always finds a definitive file. Called on landing, on tick-prune
  (gated on the `pruned` flag), and on explicit drop. It is **not** called on
  `char_reset` — disconnect must never overwrite the file.
- **Load** — `_load_active(char_name)` runs from the `gmcp_char_name` handler
  (cold start and reconnect), after the in-memory list is reset to `{}`. It
  drops any entry with `expires_at <= os.time()` (its 99 min elapsed during
  downtime), restores `_next_id` past the highest surviving id, arms the tick
  **only when a restored entry has an `expires_at`** (permanent-only state would
  otherwise run an idle 2 s no-op loop forever), and **always emits
  `charms_changed`** at the end. Permanent entries have no `expires_at`, so the
  prune guard never drops them and they survive any downtime. The final
  emit is load-bearing: `charm.lua` loads after `buffs_state.lua` alphabetically,
  so the buffs pane re-serialises regardless of module load order. Logs
  `[CHARM] restored N (M expired)`.

`char_reset` only undelays the tick (when `GAME_SESSION` is still set) and never
touches disk.

## Click-to-drop

The buffs pane's × invokes `_cp_charm_drop <id>` (a `#alias` registered
alongside the actions), which calls `charm_drop(id)`. `charm_drop` removes the
matching entry by id, persists, emits `charms_changed`, and surfaces
`char_ui("charm", name, "down")` — it **sends nothing to the game** (it only
forgets our tracker entry). A no-matching-id call is a silent no-op with a
`dbg` line.

**Known limitation (parked):** the `_cp_charm_drop` command shows up as a
persistent line in the tt++ game scrollback — a tt++ command-echo behaviour not
yet solved. The drop itself works correctly.

## Rendering and announcements

`state.char.charms` is serialised into `bridge/runtime/buffs.state` and rendered
by the buffs pane as a one-per-row group with no bar (name · count-up minutes ·
drop ×). See [docs/buffs-pane.md](buffs-pane.md) for the cell appearance and
palette.

Landing and removal surface to the UI pane via
`char_ui("charm", name, "up" | "down")` — the standard `◆`-family
character-state helper. See
[docs/ui-messaging.md](ui-messaging.md#character-events). No UI line is emitted
on a failed cast (the FIFO pop is silent) or on disconnect (the state wipe is
silent).

## Registration global

`_register_charm_actions()` is a global Lua function defined in
`lua/core/charm.lua`. It is called by the `_register_charm_actions` alias in
`ttpp/core/charm.tin`, invoked from `SESSION CONNECTED` in
`ttpp/core/system.tin` **after** `_register_blinds_actions` (and therefore after
`_register_spellcast_actions`, which owns the shared lines and the queue this
module enqueues onto).

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing automation alias and exists only to
populate the game session's action list.

---
Back to [architecture.md](../architecture.md).
