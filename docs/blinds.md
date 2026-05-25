# Blinds Tracker

Tracks blinded targets with fixed 90 s timers. Two deliberately decoupled
layers: the inbound "<name> seems to be blinded!" line creates a bar
unconditionally (Layer 1); the outgoing cast snoop supplies the numeric
prefix (`2.orc`) when one was typed (Layer 2). MUME serialises spellcasting,
so a plain FIFO of attempt prefixes is correct, not heuristic.

This document covers the data layer and event bus; rendering is handled by
the buffs pane — see [`docs/buffs-pane.md`](buffs-pane.md) for the rendering
spec.

## Data flow

```
                                       outgoing cast text
                                              │
                                              ▼
                                   user_input subscriber
                                   — parse blindness cast
                                              │
                                              ▼
                                   _pending_blinds FIFO
                                              │
inbound MUME line                             │
"... seems to be blinded!"                    │
      │                                       │
      ▼                                       │
tt++ #action (GAME_SESSION, priority 3)       │
  — registered by                             │
    _register_blinds_actions()                │
    at SESSION CONNECTED                      │
      │                                       │
      ▼ _blinds_on_blinded("<raw name>")     │
      │   — strips "An "/"A " article         │
      │   — pops one prefix from FIFO (or ◀───┘
      │     false if empty)
      ▼
state.char.blinds  ──►  events.emit("blinds_changed")
                    ──►  buffs_state.lua serialises
```

## State schema

### `state.char.blinds`

Array of currently-blinded target entries:

```lua
{
    name              = "2.orc",  -- includes any numeric prefix that was
                                  -- typed on the cast; bare game name if
                                  -- the cast was uncast-prefixed or
                                  -- unobserved
    started_at        = 1714000000,
    expected_duration = 90,        -- always 90; blindness has fixed duration
    expires_at        = 1714000090,
}
```

Initialised to `{}` at module load and on every `gmcp_char_name` (login).
`state.char.reset()` (called on disconnect) wipes it via the standard
non-function-key sweep in `char_state.lua`. **Not persisted** — blinds are
session-only state; a disconnect wipes them.

### Pending-attempts FIFO

A file-local `_pending_blinds` array. Each element is either a string
number prefix (e.g. `"2."`) or `false` (the cast carried no explicit
number). `false` is used rather than `nil` so `#fifo` and `table.remove`
work normally.

## Layer 2 — outgoing cast snoop

Subscribes to `user_input` (see [docs/events.md](events.md#user_input)).
A line is recognised as a blindness cast when:

- the first whitespace token is a prefix of `cast` (1–4 chars, case-folded:
  `c`, `ca`, `cas`, `cast`);
- it contains a single-quoted token that, lowercased, is a prefix of
  `blindness` of length ≥ 3 (`'bli'` matches, `'bl'` does not);
- any words between the cast token and the quoted spell (a spellspeed) are
  ignored — no spellspeed list is enforced.

The trimmed text after the closing quote yields the prefix:

- `^(\d+\.)` (e.g. `2.orc`, `1.troll`) → that exact prefix is pushed onto
  the FIFO;
- anything else (bare name, empty, or no target) → `false` is pushed.

A named `#delay {blind_que_flush}` is re-armed on every push. After 10 s of
no new pushes the FIFO is cleared, so an unanswered cast does not strand a
stale prefix that mis-labels the next successful blind.

## Layer 1 — landed-blindness handler

A single `#action` registered by `_register_blinds_actions()` at priority 3:

```
^%1 seems to be blinded!$  →  _blinds_on_blinded("%1")
```

Handler steps:

1. **Normalise the name** — strip a leading `An ` or `A ` article only when
   followed by whitespace, so player names like `Anaru` or `Aragorn` are
   left intact.
2. **Pop the FIFO** — `num = table.remove(_pending_blinds, 1)` if the FIFO
   is non-empty, else `false`. The bar is created regardless of FIFO state
   (Layer 1 must always work).
3. **Append the entry** with `name = (num or "") .. normalised_name`,
   `started_at = now`, `expected_duration = 90`, `expires_at = now + 90`.
4. **Arm the prune tick** — `#delay {blinds_tick} {#lua {_blinds_tick()}} {2}`.
   Named non-numeric delays replace an existing delay of the same name, so
   re-arming on every landing is idempotent.
5. **Emit `blinds_changed`**.

## FIFO-pop triggers

Three independent paths pop the front of the FIFO. All three are guarded
on `#_pending_blinds > 0` — a pop on an empty FIFO is a silent no-op,
because the trigger may belong to a different spell.

### 1. Success line

Pop happens inside `_blinds_on_blinded` alongside the bar insertion (see
[Layer 1](#layer-1--landed-blindness-handler)). The popped prefix becomes
the bar's name.

### 2. Failure lines

One `#action` per known cast-failure line. Each fires as a signal (no
captures) and pops the front of the FIFO.

| Pattern (anchored) | Cause |
|---|---|
| `^Argh! You cannot concentrate any more...$` | concentration loss |
| `^Nah... You feel too relaxed to do that.$` | sitting / resting |
| `^In your dreams, or what?$` | spell not memorised |
| `^Alas, not enough mana flows through you...$` | out of mana |
| `^Your spell backfired!$` | backfire |
| `^Nothing seems to happen.$` | resisted / no effect |
| `^Nobody here by that name.$` | invalid target |
| `^You flee %1.$` | fled mid-cast |
| `^You are too afraid.$` | fear effect |
| `^Your victim is already blind.$` | target already blind |

### 3. Empty input (cast cancel)

Pressing Enter on an empty line tells MUME to abort the current cast;
the next queued cast (if any) proceeds. The blinds module subscribes to
the `user_input_empty` event bus topic — emitted by `brain.lua` from the
`RECEIVED INPUT` registration in `ttpp/core/input_ipc.tin` — and pops the
FIFO front. **The 10 s idle-flush `#delay` is not re-armed**: a cancel
is not a cast, and re-arming would extend the flush window for the
remaining queued attempts.

Accepted narrow desync: if the player has a non-blind cast in flight
with blinds queued behind it and then aborts, a blind prefix is popped
instead of the in-flight cast's owner. Low-stakes — Layer 1 still draws
the bar regardless, just possibly without (or with the wrong) numeric
prefix.

### Idle flush

If a typed cast never produces any of the above signals, the 10 s
idle-flush `#delay` clears the entire FIFO so a stuck prefix cannot
indefinitely mis-label a later landing.

## Periodic tick

A named `#delay {blinds_tick}` runs every 2 seconds in GAME_SESSION while
at least one blind is active. The sole job is to remove entries whose
`expires_at <= now`. Blindness has no in-game drop string — the 90 s timer
is the only removal path — so there is no overrun / no 2.5× safety net.

- Re-armed every cycle if `state.char.blinds` is non-empty (named delays
  replace, so re-arming is idempotent).
- Cancelled on `char_reset` (only effective when GAME_SESSION is still set;
  the SESSION DISCONNECTED fallback finds GAME_SESSION nil, but the session
  dying clears its delays automatically).
- Emits `blinds_changed` only on a prune cycle (the renderer's blink/drain
  is wall-clock-driven and does not need ticking events).

## Registration global

`_register_blinds_actions()` is a global Lua function defined in
`lua/core/blinds.lua`. It is called by the `_register_blinds_actions`
alias in `ttpp/core/blinds.tin`, invoked from `SESSION CONNECTED` in
`ttpp/core/system.tin` (after `_register_stat_reconcile_actions`).

The function lives in `lua/core/` (not `lua/scripts/`) because it is
infrastructure: it has no player-facing alias and exists only to populate
the game session's action list.

## Rendering

`state.char.blinds` is serialised into `bridge/runtime/buffs.state` as a
third top-level array `blinds`. The buffs pane renders it as a fourth
group after Stored, using the standard timed-affect cell renderer
(drain bar + expiring-blink). See
[docs/buffs-pane.md](buffs-pane.md#per-group-palette) for the cell
appearance and the palette entry.

## UI-pane announcements

Two `char_ui("blind", name, verb)` lines surface to the UI pane via the
standard `◆`-family character-state helper (see
[docs/ui-messaging.md](ui-messaging.md#character-events)):

- **Landing** — `_blinds_on_blinded` emits `char_ui("blind", name, "up")`
  after the entry is appended and `blinds_changed` is emitted. `name` is
  the full entry name including any numeric prefix (e.g. `2.orc`).
- **Tick prune at 90 s** — `_blinds_tick` emits
  `char_ui("blind", name, "down")` for each entry removed at expiry,
  using the entry's name (snapshotted before `table.remove`).

Renders as:

```
◆ BLIND: 2.orc up.
◆ BLIND: 2.orc down.
```

The `BLIND` tag renders in the same cyan (`#00CCCC`) as the buffs-pane
Blinds group, so the UI-pane line and the pane bar read as one surface.

No UI line is emitted on:
- a failed cast (failure-line FIFO pop is silent);
- an empty-input cancel (`user_input_empty` FIFO pop is silent);
- disconnect (the state wipe via `char_reset` is silent).

---
Back to [architecture.md](../architecture.md).
