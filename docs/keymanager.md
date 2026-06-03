# Keymanager

A port-key library: capture `locate life` results, store the keys per
character under names, list them, and cast teleport / portal / scry / watch-room
to them — with a persistent "safekey" escape hatch that always resolves to a
live key.

Keymanager is an **opt-in Pattern-2 script** in
[`lua/scripts/keymanager.lua`](../lua/scripts/keymanager.lua) (see
[docs/scripts.md](scripts.md) and [docs/ipc.md](ipc.md)). The split is the usual
one: tt++ does the latency-light reflex — recognise and gag the raw locate rows,
fire the blank-line terminator — and Lua owns everything else: the pick buffer,
the per-character key library, the safekey designation, and all rendering. There
is no `state.*` involvement; private state lives in file-local tables, since no
other consumer reads it.

## Capture pipeline

A `locate life` is cast normally (`cast 'locate life' troll`). The result rows
are self-identifying — each ends in `key: '<key>'` — so keymanager **arms on the
data, not on input**. There is no sent-output snoop and no `locatel` alias; a
zero-match locate simply renders nothing.

The row trigger, registered session-scoped into `{core}`, is:

```tintin
#action {^%1  key: '%2'$} {#line gag;#lua {scripts.keymanager.row("%0")};#class {core} {open};#action {^$} {#line gag;#lua {scripts.keymanager.render()};#unaction {^$}};#class {core} {close}}
```

On each matched row it:

1. **Gags** the raw line (`#line gag`).
2. **Forwards the whole line** as `%0` to `M.row`. In a tt++ `#action`, `%0` is
   the matched *segment*, not the full line — a leading anchored wildcard (`^%1`)
   makes the match span the entire line so `%0` carries it intact. Lua re-parses
   it with `ROW_PAT`
   (`^(.-)%s+%-%s+(.-)%s%s+(.-)%s%s+key:%s+'(.+)'$` → name / room-type / distance
   / key). The line is passed as one opaque payload because it contains both
   single quotes and a colon and must never be colon-split (see
   [docs/ipc.md](ipc.md)).
3. **Installs the blank-line terminator** at fire time. The pick buffer is
   rebuilt on the first row of each block (`in_block` opens it); a subsequent
   blank line fires the self-removing `^$` action, which gags the blank line,
   renders the buffer, and `#unaction`s itself.

The terminator is installed only while a locate block is in flight, because
blank lines are common in MUME — an always-live `^$` would dispatch to Lua on
every one. Its fire-time registration is wrapped in its own `;`-joined
`#class {core} {open};…;#class {core} {close}` pair so it lands in `{core}`
(never serialising into the saved profile) and runs atomically on one input
line. See [ADR 0131](decisions/0131-keymanager-locate-capture.md).

A standalone `^You feel very confused and can't concentrate any more.$` gag is
registered unconditionally alongside the row trigger, swallowing the
interrupted-concentration line that a failed locate emits.

All three registrations are re-armed on each `run_started` via `session_cmd`, so
they stay in `{core}` and survive reconnect, mirroring
[`lua/scripts/mercenaries.lua`](../lua/scripts/mercenaries.lua).

## Rendering

Both views are boxed, zebra-striped panels mirroring
[`lua/scripts/mercenaries.lua`](../lua/scripts/mercenaries.lua)'s border and
band helpers (`_top_border` / `_bottom_border` / `_bottom_hint` / `_header_row`
/ `_zebra_row`, dynamic-width). Cell widths are measured with `_vlen`, which
strips tt++ `<…>` markup before counting UTF-8 code points; the one display
string carrying literal `<…>` (the hint label) is measured with `_rawlen`
instead.

The two views share **one colour convention** — the same column is the same
colour in both:

| Column        | Colour            | Notes                                            |
|---------------|-------------------|--------------------------------------------------|
| Name          | soft cyan         | the standout; never white                        |
| Distance      | soft blue         |                                                  |
| Room-type     | muted             |                                                  |
| Key           | grey              | least important                                  |
| index `[n]`   | dark              | turns **green** when the row's key is stored     |
| Safe `X`      | green             | marks the safekey row in `keys`                  |
| Expires       | soft blue         | turns **orange** under 1 h remaining             |
| zebra band    | A / B alternating | odd / even data rows                             |

**Locate panel** (`LOCATE (n)`) columns are `[idx] Name Dist Room-type Key`,
with the `kpick <n> <name> to store` hint on the bottom border. When a row's key
already matches a non-expired library entry the row is "stored": its index turns
green **and the Key column shows the KEYNAME (green) instead of the raw key**, so
a glance tells you which results you have already named.

**Keys panel** (`KEY LIBRARY`) columns are `Name Room-type Key Expires Safe`,
sorted by name. (Distance is a locate-only attribute and is not persisted, so it
has no column here.) The Safe column carries a green `X` on the current safekey
row.

Status and cast feedback are separate one-liners, not boxes. `_status` prints
the framed `## KEYS: …` prefix (white body); `_notice` prints a clean line with
no prefix — a dim-header body with the keyname in the cyan Name colour — used by
the cast aliases.

## Persistence

The library is per character at
`data/characters/<char>/portkeys.json`, written atomically (temp file +
`os.rename`), mirroring [`lua/core/charm.lua`](../lua/core/charm.lua)'s shape.
The **v2** schema is:

```json
{ "safekey": "<name|null>", "keys": { "<name>": { "key": "...", "room_type": "...", "stored_at": 0, "expires_at": 0 } } }
```

`keys` is forced to encode as a JSON object even when empty (so reconnect always
finds a definitive object rather than dkjson's `[]`). The library is reloaded on
`gmcp_char_name` — reset to a clean slate first, so a character with no file
starts empty.

Expiry is **lazy: there is no active timer.** This is a deliberate difference
from [charm](charm.md), which ticks. A picked key lives 12 h; expired entries
are pruned only on load, on display, and on use (`_prune_library`, plus the
single-entry checks in `_get`). The trade-off is acceptable because a stale key
costs nothing until you look at it or cast to it, and pruning at those moments is
exact enough.

A legacy **v1** file (the bare keys dict, with no `keys` field) is detected by
the absence of a `keys` key, loaded as the keys dict with no safekey, and
re-saved in v2 form on the spot.

## Safekey semantics

The safekey is a **sticky per-character NAME designation** that always resolves
to a live key while any key exists. `_ensure_safekey` enforces the contract:
prune first, then if the designation is unset or no longer live, re-elect the
**freshest** remaining live key (max `expires_at`), or `nil` only on an empty
library.

- The **first** key stored into an empty library auto-becomes the safekey.
- `skey` / `safekey <name>` retargets it to a live key (an expired or unknown
  name is refused); `skey` with no argument reports the current safekey.
- On expiry or removal of the designated key it re-elects the freshest live key
  and announces the switch **once** (`Safekey expired; switched to X.`).
- A `krename` of the safekey follows the rename; the designation survives
  reconnect.

Named casts (`teleport` / `portal` / `scry` / `watchr`) do **not**
auto-substitute — an expired named key fails cleanly. The "always usable"
contract is scoped to the safekey only. See
[ADR 0132](decisions/0132-keymanager-safekey.md).

## Alias reference

| Alias                          | Effect                                                                                                          |
|--------------------------------|---------------------------------------------------------------------------------------------------------------|
| `kpick <n> <name>`             | Store pick #n's key under `<name>` (12 h expiry). `Stored <key> as <name> (expires in 12 h).` / `Replaced …`. |
| `kpick` (no args) / `keypick`  | Re-show the last pick list (stored rows now marked).                                                           |
| `keys`                         | List stored keys with time remaining and a Safe column. `Your key library is empty.` when empty.              |
| `skey <name>` / `safekey`      | Designate `<name>` as safekey (`Safekey set to: <name>.`); no arg reports it (`Current safekey: <name>.`).    |
| `kremove <name>`               | Remove a key. `Removed <name>.`; if it was the safekey, `… safekey switched to <new>.`                        |
| `krename <name> <newname>`     | Rename a key. `Renamed <old> → <new>.` Refuses missing/unknown/same-name/clobber.                             |
| `teleport <name>`              | `cast n 'teleport' <key>` — notice `Teleporting to <name>.` (named, strict).                                   |
| `portal <name>`                | `cast n 'portal' <key>` — notice `Portalling to <name>.` (named, strict).                                      |
| `scry <name>`                  | `cast n 'scry' <key>` — notice `Scrying <name>.` (named, strict).                                              |
| `watchr <name>`                | `cast n 'watch room' <key> <name>` — notice `Watching <name>.` (named, strict).                               |
| `psafe`                        | Portal to the safekey (`cast n 'portal' <key>`) — notice `Teleporting to safe key: <name>.`*                  |
| `tsafe` (also **Alt+s**)       | Teleport to the safekey (`cast n 'teleport' <key>`).                                                           |
| `qtsafe`                       | Quiet teleport to the safekey (`cast q 'teleport' <key>`) — notice flags a white `quickly`.                   |

\* `psafe` / `tsafe` / `qtsafe` resolve the safekey through `_ensure_safekey`,
so `No safekey set.` only ever fires on an empty library. `Alt+s` is bound to a
`{core}` macro re-armed with the triggers; the input pane already forwards it.

---

Touched when changing keymanager capture, rendering, persistence, the safekey,
or the cast aliases.

Back to [architecture.md](../architecture.md).
