# Run Logs

Per-run JSONL event log written by `lua/core/run_log.lua`. One file per play
session (MUME login to logout), archived under `data/runs/<character>/`.

See [docs/decisions/0044-runs-and-character-scoped-persistence.md](decisions/0044-runs-and-character-scoped-persistence.md)
for the authoritative vocabulary, run-boundary rationale, and run-id format.

## File layout

```
data/
└── runs/
    └── <character>/
        ├── current.jsonl               ← active run; exists only while a run is in progress
        ├── <YYYY-MM-DD>T<HH-MM-SS>.jsonl  ← sealed run; created on clean disconnect
        └── <YYYY-MM-DD>T<HH-MM-SS>.log    ← raw text capture for the same run
```

**`current.jsonl`** — open-ended run log. Written from the first `Char.Vitals`
tick after login, appended on each loggable event, sealed on disconnect. Only
one can exist at a time per character. If one is found at the start of a new
run, it is an orphan from a prior unclean session (see Orphan handling below).

**`<run-id>.jsonl`** — sealed run log. The run-id is the ISO-like timestamp of
the `run_start` row: `YYYY-MM-DDThh-mm-ss` (colons replaced with dashes for
filesystem portability, local time). Sortable lexicographically and scannable
with `ls`.

## Run lifecycle

```
mark_mume_connected()
  → events.emit("run_started")
      run_log: initialise archive dir, arm deferred run_start

first Char.Vitals tick
  → events.emit("gmcp_char_vitals")
      run_log: write run_start row to current.jsonl

... play ...
  → Char.StatusVars with higher level
      run_log: append level_up row

mark_mume_disconnected()
  → events.emit("run_ending")
      run_log: append run_end row
              rename current.jsonl → <run-id>.jsonl
```

If the character disconnects before any `Char.Vitals` arrives (edge case:
connect and disconnect within ~1 s), no `current.jsonl` is created and no
rows are written. The module silently returns.

## Event schema

All rows share a top-level `event` field and a Unix epoch `ts` field.

### `run_start`

Written on the first `Char.Vitals` tick after login. Baseline snapshot.

```json
{
  "event":           "run_start",
  "ts":              1746640335,
  "character":       "Fingolfin",
  "level":           35,
  "xp":              1234567,
  "tp":              890,
  "previous_run_id": "2026-05-07T18-32-15",
  "schema":          1
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` when the row is written (local epoch) |
| `character` | string | `state.char.name` |
| `level` | integer or absent | `state.char.level`; absent if not yet received |
| `xp` | integer or absent | `state.char.xp` from `Char.Vitals`; absent if not yet received |
| `tp` | integer or absent | `state.char.tp` from `Char.Vitals`; absent if not yet received |
| `previous_run_id` | string or absent | Run-id of the most recent sealed run for this character (lexicographic max of `<run-id>.jsonl` in the archive dir, taken at write time so a freshly-sealed orphan from the same login counts). Absent when no prior sealed run for this character. Lets consumers stitch link-loss runs without a writer-side grace window. See [ADR 0056](decisions/0056-previous-run-id-linking.md). |
| `schema` | integer | Schema version; current value `1` |

### `level_up`

Written when `Char.StatusVars` reports a higher level than the previous
observation. Death-penalty level decreases are intentionally not logged.

```json
{
  "event": "level_up",
  "ts":    1746643200,
  "level": 36
}
```

### `run_end`

Written immediately before sealing (renaming `current.jsonl`). Marks the
clean end of a run.

```json
{
  "event": "run_end",
  "ts":    1746644100
}
```

### `orphan_close`

Appended by `run_log` immediately before sealing an orphaned `current.jsonl`
(one left by a prior brain crash). Marks the truncation point. No corresponding
Lua event is emitted.

```json
{
  "event": "orphan_close",
  "ts":    1746644200
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` when the orphan was sealed, not when the run ended |

A sealed orphan has no `run_end` row. Readers should treat the absence of
`run_end` (or the presence of `orphan_close`) as an unclean run boundary.

### `kill`

Written once per attributed kill at fold time (~500ms debounce after the
R.I.P. line). Fold timing means the timestamp is the fold time, not the exact
death time.

```json
{
  "event":    "kill",
  "ts":       1746641200,
  "mob_name": "an elven slave",
  "xp_delta": 142
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` at fold time, not exact death time |
| `mob_name` | string | Full mob name with article, as captured by `mob_death` |
| `xp_delta` | integer | XP attributed to this kill; `0` for empty-Vitals folds |

For group kills (multiple mobs dying within the 500ms window), N consecutive
`kill` rows appear with even-split XP; the last row receives the remainder if
`pending_xp` is not divisible by N. Kill ordering within the JSONL matches
`state.run.kills` insertion order (same as `mob_death` arrival order).

### `tp_gained`

Written on each `Char.Vitals` tick where TP increased since the previous tick.
TP-awarding rooms emit a Vitals bump on entry; the delta is always positive.
Drops (trainer-spend or death penalty) are detected and silently rebaselined —
no `tp_gained` row is written for decreases.

```json
{
  "event":    "tp_gained",
  "ts":       1746641800,
  "tp_delta": 3
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` at write time |
| `tp_delta` | integer | Positive integer; Vitals-to-Vitals difference; never zero or negative |

Schema version is unchanged at `1`; old readers that do not recognise this event
type can safely ignore the row.

### `xp_loss`

Written on each `Char.Vitals` tick where XP decreased since the previous tick.
The negative delta is captured before `run_state` rebaselines, so the row
reflects the magnitude of the loss as observed from GMCP. Typical cause is a
death penalty, but any future server-side XP debit (e.g. quest penalty) would
also trigger this event.

```json
{
  "event":    "xp_loss",
  "ts":       1746641500,
  "xp_delta": -42000
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` at write time |
| `xp_delta` | integer | Negative integer; Vitals-to-Vitals difference; never zero or positive |

Schema version is unchanged at `1`; this event is additive.

### `tp_loss`

Written on each `Char.Vitals` tick where TP decreased since the previous tick.
The negative delta is captured before `run_state` rebaselines.

```json
{
  "event":    "tp_loss",
  "ts":       1746641500,
  "tp_delta": -5
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` at write time |
| `tp_delta` | integer | Negative integer; Vitals-to-Vitals difference; never zero or positive |

Note: this event fires for trainer-spend as well as death penalty — the two
are indistinguishable from GMCP alone. Consumers that want to attribute a TP
drop to death specifically must correlate with a nearby `char_death` row.

Schema version is unchanged at `1`; this event is additive.

### `char_death`

Written when the game sends `"You are dead! Sorry..."` — i.e. the character died
(PvE, PvP, or environment). The `level` field records the character's level at
time of death, if known.

```json
{
  "event": "char_death",
  "ts":    1746641500,
  "level": 35
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` when the row is written |
| `level` | integer | `state.char.level` at time of death; **omitted** (not `null`) if not yet received |

Schema version is unchanged at `1`; this event type is additive.

### `pkill`

Written once per attributed PC kill at fold time (~500ms debounce after the
R.I.P. line). Analogous to `kill` but for player characters. The `name` field
holds only the character's base name (first word); `race` holds the race-suffix
as captured from the MUME R.I.P. line (e.g. `"the Orc"`). Unlike `kill`, there
is no `mob_name` field — PCs are not mobs.

```json
{
  "event":    "pkill",
  "ts":       1746641600,
  "name":     "Moraxus",
  "race":     "the Orc",
  "xp_delta": 350
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` at fold time, not exact death time |
| `name` | string | First word of the R.I.P. name (character name, no race-suffix) |
| `race` | string | Remainder of the R.I.P. name after the first word (e.g. `"the Orc"`); empty string `""` if only one word was captured |
| `xp_delta` | integer | XP attributed to this kill; `0` for empty-Vitals folds |

For mixed folds (mob kills and PC kills within the same 500ms window), XP is
split evenly across all kills combined; the last entry processed — mob or PC,
whichever is last — receives the remainder. Schema version is unchanged at `1`.

### `achievement`

Written when the game sends `"You achieved something new!"` and the inner
one-shot action captures the description line that immediately follows.

```json
{"event":"achievement","ts":1746642000,"name":"That was a quick trip!"}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` when the row is written |
| `name` | string | Achievement description line as captured by the inner action |

Schema version is unchanged at `1`; this event is additive.

### `group_changed`

Written when a group member joins or leaves mid-run. Vitals fluctuations
(`Group.Update` with hp/mana changes) do not produce rows.

```json
{"event": "group_changed", "ts": 1746640500, "members": ["Irelm", "Bilbo"]}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` when the row is written |
| `members` | array of strings | Full current group composition at write time, sorted by ascending member id (sequential join order); never contains `null` or missing entries |

Notes:

- Only join (`group_member_added`) and leave (`group_member_removed`) events
  produce rows; vitals updates (`group_member_updated`) do not.
- `members` is the full current composition after the change, not just the
  joining or leaving member.
- The first `Group.Set` that arrives at login (before the first `Char.Vitals`
  tick) does not produce a row; the pre-baseline guard ensures `run_start`
  remains the first row in `current.jsonl`.

Schema version is unchanged at `1`; this event is additive.

## Per-run text log (.log)

**Purpose.** Full-fidelity raw capture of all server output for the run — a
foundation for a future replay player.

**Filename.** `<archive_dir>/<run-id>.log`, where `<run-id>` is the same
ISO-like timestamp as the paired `.jsonl` file. To cross-correlate with
`.jsonl` rows: `int(log_ts / 1_000_000) == jsonl_ts`.

**Format.** One line per captured event. Inbound server lines and outbound
player commands share the file, interleaved in microsecond order. The
direction discriminator is the first character after the timestamp and its
single space separator: `>` marks an outbound command, anything else is
inbound.

```
<microseconds_since_epoch> <raw_line>          # inbound (server output)
<microseconds_since_epoch> > <command>         # outbound (player command)
```

ANSI escape codes in inbound lines are preserved; `%0` in the
`RECEIVED LINE` event carries the raw byte stream, and `%0` in
`SENT OUTPUT` carries the post-expansion command text. Examples:

```
1746640335123456 \e[1;33mYou feel better.\e[0m
1746640335456789 > cast 'shield' self
```

**Mechanism.** Pure tt++ native pipeline — no Lua dispatch on the line hot
path, preserving PvP responsiveness. Two parallel event handlers
registered in the game session do the capture: `RECEIVED LINE` for
inbound server output and `SENT OUTPUT` for outbound player commands.
Each handler computes a microsecond timestamp via `#format %U` (raw
16-digit integer microseconds since epoch), then writes its line to the
`.log` via `#line log`; the outbound handler inserts `> ` between
timestamp and payload so direction is visible at a glance. Lua's sole
role is lifecycle: it sets the tt++ variable `_run_log_path` at run start
(`_open_log`) and clears it at run end (`_close_log`) via `session_cmd()`.
Both handlers are gated by `&_run_log_path` and are a no-op when the
variable is unset. The timestamp prefix is generated by an inline
`#format _ts {%U}` in the event body, not via a function: function
indirection caused tt++ to reuse the same `%U` evaluation across all
events in a tight batch, breaking per-line resolution.

Both event registrations and their inline `#format _ts {%U}` calls are
bracketed in `#class {core} {open}` / `#class {core} {close}`, so the
events, `_run_log_path`, and `_ts` all live in the `{core}` class rather
than the profile class. The `#format _ts` line stays top-level inside
each event body — the class wrap is inline, not function indirection,
and does not affect per-fire `%U` freshness.

`SENT OUTPUT` is registered via `#%1` (i.e. scoped to `GAME_SESSION`) in
the same `_register_run_log_capture` alias as `RECEIVED LINE`. This
session-scoping is what avoids the recursion documented in
[docs/ipc.md](ipc.md): a top-level `#event {SENT OUTPUT}` would also
fire in the `lua` `#run` session, where every `#lua {...}` call counts
as sent output and would self-amplify within seconds of connect.

The same `SENT OUTPUT` event body also dispatches `USER_INPUT:%0` to
`brain.lua` for non-empty payloads, after the `.log`-write branch. This
is the canonical site for `#event {SENT OUTPUT}` in the project — tt++
allows only one handler per event type per session, so any future
SENT OUTPUT consumer (currently the stored-spells `user_input`
subscriber is the only one besides the run-log) must add its branch to
this handler rather than registering a competing one. See
[ADR 0059](decisions/0059-canonical-sent-output-handler.md).

**Lifecycle.** Armed on the first `Char.Vitals` tick after login (parallel to
the `run_start` JSONL row), disarmed on `run_ending` (after the `run_end`
row is written). There is a short login-screen gap before arming — same as
the `.jsonl`.

**Limitations.**

- Outbound capture is post-expansion: a keystroke macro or alias that
  expands into multiple commands produces one `> <cmd>` line per
  resulting command, not the original keystroke.
- No replay player tooling yet.
- Pre-first-Vitals login screen output is not captured.

**Per-session state hygiene.** Capture state lives in the `{core}` class
by construction (see Mechanism above), so profile auto-save
(`#class write {<profile>}`) does not serialize it and there is no stale
state to clear on the next SESSION CONNECTED. The `#unevent` / `#unvar`
lines at the top of `_register_run_log_capture` remain only as
transitional hygiene for legacy profile files containing pre-`{core}`
baked-in state; they will be removed in a future release once all known
profiles have been resaved under the new architecture.
See [ADR 0049](decisions/0049-per-session-state-outside-profile-class.md)
for context, alternatives considered, and the trade-offs.

**Orphan handling.** A `.log` left after a brain crash has no `orphan_close`
marker (unlike `.jsonl`). Pair with the `.jsonl` to determine cleanliness: a
`.log` without a matching sealed `.jsonl` is orphaned.

## Schema versioning

The `schema` field in `run_start` carries an integer version. Current value: `1`.
Consumers should treat an absent or unrecognised `schema` as version 1.
The version increments when the set of possible event types or their required
fields changes in a breaking way.

## File I/O conventions

- Open-append-close per row (no persistent file handle), matching `comm_store.lua`.
- JSON encoding via `dkjson` (`lua/lib/dkjson.lua`).
- Directory created with `os.execute("mkdir -p ...")` on `run_started`.
- Sealing uses `os.rename` (atomic on Linux; same filesystem guaranteed).

## Error handling

| Failure | Behaviour |
|---------|-----------|
| `mkdir -p` fails | Directory creation attempted; subsequent `io.open` fails silently per write |
| `io.open` for append fails | `dbg()` log; row skipped; module keeps running |
| JSON encode fails | `dbg()` log; row skipped (should be impossible with fixed schemas) |
| `os.rename` on seal fails | `ui_warn()` surfaced to the UI pane; `current.jsonl` remains as an orphan |

## Orphan handling

If the brain crashes (or is killed) while MUME is connected, `current.jsonl`
is left unsealed without a `run_end` row. On the next `run_started` event for
that character, `run_log` detects and seals the orphan before starting the new
run:

1. After `mkdir -p` for the archive directory, `run_log` tests whether
   `current.jsonl` already exists.
2. If it does, the original `run_start` timestamp is read from the file's
   first line. If the line is missing or unparseable, `os.time()` is used as a
   fallback (row data is preserved; only the sealed filename becomes
   approximate).
3. An `orphan_close` row is appended to `current.jsonl`.
4. The file is renamed to `<original-run-start-ts>.jsonl`.
   If the rename fails (e.g. filesystem error), a `ui_warn` is surfaced and
   the orphan stays as `current.jsonl`; it will be re-detected and re-sealed
   at the next login.
5. The fresh run then starts normally: `_pending_baseline = true`, new
   `current.jsonl` created on the next Vitals tick.

The sealed orphan run has no `run_end` row — readers must tolerate this (the
JSONL self-healing pattern from ADR 0011). The `orphan_close` row marks where
the log was truncated.

`orphan_close` is written directly by `run_log`, not emitted on the event bus.
It is a JSONL marker, not a Lua event.

See ADR 0044 §"Orphan current.jsonl handling".

---
Back to [architecture.md](../architecture.md).
