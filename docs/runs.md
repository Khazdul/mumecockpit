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
  "event":     "run_start",
  "ts":        1746640335,
  "character": "Fingolfin",
  "level":     35,
  "xp":        1234567,
  "tp":        890,
  "schema":    1
}
```

| Field | Type | Notes |
|-------|------|-------|
| `ts` | integer | `os.time()` when the row is written (local epoch) |
| `character` | string | `state.char.name` |
| `level` | integer or absent | `state.char.level`; absent if not yet received |
| `xp` | integer or absent | `state.char.xp` from `Char.Vitals`; absent if not yet received |
| `tp` | integer or absent | `state.char.tp` from `Char.Vitals`; absent if not yet received |
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

## Per-run text log (.log)

**Purpose.** Full-fidelity raw capture of all server output for the run — a
foundation for a future replay player.

**Filename.** `<archive_dir>/<run-id>.log`, where `<run-id>` is the same
ISO-like timestamp as the paired `.jsonl` file. The integer seconds part of
any `.log` timestamp is directly comparable to the `ts` field of `.jsonl`
rows.

**Format.** One line per server line:

```
<epoch_seconds>.<microseconds_6> <raw_line>
```

ANSI escape codes are preserved; `%0` in the `RECEIVED LINE` event carries
the raw byte stream. Example:

```
1746640335.123456 \e[1;33mYou feel better.\e[0m
```

**Mechanism.** Pure tt++ native pipeline — no Lua dispatch on the line hot
path, preserving PvP responsiveness. A `RECEIVED LINE` event handler
registered in the game session computes a microsecond timestamp via
`#format %U` + string slicing (`%.10s` / `%.-6s`), then writes
`<secs>.<usecs> <raw_line>` to the `.log` via `#line log`. Lua's sole role
is lifecycle: it sets the tt++ variable `_run_log_path` at run start
(`_open_log`) and clears it at run end (`_close_log`) via `tintin_cmd`. The
event handler is a no-op when the variable is unset.

**Lifecycle.** Armed on the first `Char.Vitals` tick after login (parallel to
the `run_start` JSONL row), disarmed on `run_ending` (after the `run_end`
row is written). There is a short login-screen gap before arming — same as
the `.jsonl`.

**cp -r mid-run.** `#kill event` clears the RECEIVED LINE handler, but
the `cp -r` alias re-registers it via `_register_run_log_capture`. The Lua
resume block re-arms `_run_log_path` via `_open_log`, so capture continues
seamlessly after reload.

**Orphan handling.** A `.log` left after a brain crash has no `orphan_close`
marker (unlike `.jsonl`). Pair with the `.jsonl` to determine cleanliness: a
`.log` without a matching sealed `.jsonl` is orphaned.

**Known limitations.**

- Server output only; player input is not captured.
- No replay player tooling yet.
- Pre-first-Vitals login screen output is not captured.

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

## cp -r mid-run resume

Restarting the brain while MUME is still connected (`cp -r`) resets all Lua
state but the TCP connection survives. Because `Char.Name` is sticky and not
re-emitted on a live connection, `mark_mume_connected()` never fires, so the
normal `run_started` path cannot be used.

The recovery signal is `state.char.name`. At brain startup, `brain.lua` reads
`bridge/runtime/connection.state` and, if a `character_name` is present,
writes it to `state.char.name` before calling `load_scripts()`. By the time
`run_log.lua` loads, `bridge/runtime/connection.state` has already been
cleared — its *presence* cannot be tested — but `state.char.name` survives as
the signal.

At the bottom of `run_log.lua`, after all subscribers are registered, the
module checks `state.char.name`:

- **Set** → MUME was connected; open `data/runs/<name>/current.jsonl` for
  continued append. No new `run_start` row is written.
  - If `current.jsonl` is missing (crash before first Vitals): arm
    `_pending_baseline = true` so the next Vitals tick writes a fresh
    `run_start`.
  - If `current.jsonl` exists but its first line is unparseable: use
    `os.time()` as the fallback `_run_start_ts` (the eventual sealed filename
    becomes approximate; row data is preserved).
- **Nil** → fresh start; skip the resume path entirely.

After resume, the run continues as normal: subsequent kills and level-ups
append to the same file, and `run_ending` seals it to
`<original-run-start-ts>.jsonl` on disconnect.

**Known limitation after cp -r-resume + disconnect.** Because
`bridge/runtime/connection.state` is gone, the next `mark_mume_disconnected()`
returns early on its idempotency guard and does not emit `run_ending` or the
"logged out" `system_ui` line. Run data integrity is preserved via orphan
handling at the *next* login for that character, but those UI lines are
missed. This is a pre-existing limitation in the connection.state model and is
not addressed here. See ADR 0044 for context.

See ADR 0044 §"cp -r mid-run".

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
