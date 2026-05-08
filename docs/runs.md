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
        └── <YYYY-MM-DD>T<HH-MM-SS>.jsonl  ← sealed run; created on clean disconnect
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

### `kill` (Phase 3)

Kill attribution is added in a follow-up phase once `run_state.lua` emits
`kill_attributed`. Not present in Phase 2 logs.

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

## Orphan handling (Phase 4)

If the brain dies while MUME is still connected, `current.jsonl` is left
unsealed. Phase 4 will detect this on the next `run_started` and seal it with
an `orphan_close` row before starting the new run. See ADR 0044 §"Orphan
`current.jsonl` handling" for the planned mechanics.

## `cp -r` mid-run (Phase 4)

Restarting the brain while MUME is connected resets all Lua state. Phase 4
adds a boot-time recovery path: if `bridge/runtime/connection.state` is
present at brain startup, `run_log` opens `current.jsonl` for append and
resumes logging without a new `run_start` row. Deferred to keep Phase 2
simple.

---
Back to [architecture.md](../architecture.md).
