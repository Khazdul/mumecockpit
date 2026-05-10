# 0044 — Runs, character-scoped persistence, and the data/ directory

**Status:** Accepted
**Date:** 2026-05-07

## Context

Three sources of friction motivated this redesign:

1. **Vocabulary collision around "session".** The word "session" means at
   least four different things in the codebase: tt++'s session model
   (`SESSION CONNECTED/DISCONNECTED`, `GAME_SESSION`, the `gts`/`lua`/profile
   sessions), the MUME connection state (`bridge/session.state`, driven by
   `Char.Name` and `Core.Goodbye`), the play-session XP/TP totals
   (`state.session`, owned by `lua/core/sess_kills.lua`), and the upcoming
   per-session log and aggregate work the user wants to add. Building more
   functionality on top of `state.session` would compound the ambiguity.

2. **Inconsistent persistence scope.** `comm_archive` is per-profile (ADR
   0011); `affect_times` / `affects_active` and `stored_spells_*` are
   per-character. There is no documented principle for new persistence
   surfaces to follow. With run logging coming in, this needs to be resolved
   before more files land.

3. **`logs/` directory has drifted.** It now mixes real log files
   (`ui.log`, `debug.log`), per-character persistence (`affect_times/`,
   `stored_spells_*/`), per-profile persistence (`comm_archive/`), Lua state
   cache (`clock.state`), and IPC temp files (`cmd_*.tin`). Adding per-run
   JSONL files would make this worse.

## Decision

### Vocabulary: "run" replaces "session" for play sessions

A **run** is one play session — from MUME login (`Char.Name` arrival) to MUME
logout. The word "session" is reserved for tt++'s own concepts
(`SESSION CONNECTED/DISCONNECTED`, `GAME_SESSION`,
`docs/session-lifecycle.md`, etc.) — those names are not ours to change.

Code-side renames:

- `state.session` → `state.run`
- `lua/core/sess_kills.lua` → `lua/core/run_state.lua`
- `bridge/session.state` → `bridge/connection.state`

Cosmetic UI labels stay as-is: the status pane keeps `Sess XP` / `Sess TP`.

### Persistence scope: per character

All speldata, run logs, and the comm archive are scoped per **character
name** (`state.char.name` from `Char.Name`). A "profile" reduces to "which
tt++ settings file is loaded" (`ttpp/profiles/<profile>.tin`) — it is no
longer a persistence boundary.

This supersedes ADR 0011 in the scope dimension only. The mechanics
(JSONL append-only, 7-day window, atomic prune at startup) are unchanged.

**Bootstrap window.** `Char.Name` arrives within ~1 s of login; no message
from any GMCP module of interest (Vitals, Comm.Channel.Text, Event.*)
arrives before it on a fresh connection. Modules that key on character
name guard on `state.char.name` being non-nil and silently drop or buffer
until it is set — the same pattern already used by `affects.lua` and
`stored_spells.lua`.

### Filesystem layout

A new top-level `data/` directory, grouped by **lifecycle** (not by data
type):

```
data/
├── runs/<character>/<run-id>.jsonl       ← append-only run logs; sealed at run-end
├── comm/<character>.jsonl                ← rolling 7-day comm archive (append-only)
├── characters/<character>/               ← current-state cache; read-modify-write
│   ├── affects_active.json
│   ├── affects_learned.json
│   ├── stored_spells_active.json
│   └── stored_spells_learned.json
└── shared/                               ← world-level; not character-bound
    └── clock.state
```

| Bucket | Lifecycle | Scope |
|---|---|---|
| `runs/` | Append-only, sealed at run-end | per character |
| `comm/` | Append-only, 7-day rolling window | per character |
| `characters/` | Read-modify-write current state | per character |
| `shared/` | World-level, all chars share | global |

`logs/` is reduced to real log files only:

```
logs/
├── ui.log
└── debug.log
```

IPC temp files move to a dedicated directory to keep their semantics
distinct from both data and logs:

```
bridge/ipc/
└── cmd_*.tin                             ← tt++ ↔ Lua IPC temps
```

Migration of existing files is performed in a follow-up step
(see Out of scope).

### Run boundaries

Run start is `mark_mume_connected()` — the function called from the
`Char.Name` handler in `lua/core/char_state.lua`. This is the first
reliable "a character is now active" signal MUME provides.

Run end is `mark_mume_disconnected()` — graceful (`Core.Goodbye`),
MMapper text trigger, or `SESSION DISCONNECTED` fallback. All three already
route through this single dispatch point (`docs/session-lifecycle.md`).

Direct consequences:

- A short link-loss + reconnect = two distinct runs. Justified: during
  disconnect the character is not playing, so the runs are semantically
  separate. Trivially mergeable in post-processing if ever wanted.
- Disconnect overnight + manual reconnect from the popup = new run, even
  within the same tt++ session. Same character or different, the new login
  starts a new run. This is the case the user specifically called out.
- Character switches require a disconnect first (MUME constraint), so a
  new `Char.Name` always pairs with a preceding
  `mark_mume_disconnected()`.

### `cp -r` mid-run

> **Invalidated by [ADR 0054](0054-remove-cp-r-full-reload.md).** `cp -r` is no
> longer a supported operation. The mechanics described below are no longer
> implemented. Retained for historical context.

When the brain process is restarted while MUME is still connected, the new
brain checks `bridge/connection.state` at startup:

- **Present** → MUME is connected; resume the in-progress run by opening
  `data/runs/<char>/current.jsonl` for append. No new `run_start` record
  is written. (`Char.Name` is sticky and not re-emitted on a live TCP
  connection, so `mark_mume_connected()` will not fire — we cannot wait
  for it.)
- **Absent** → MUME is disconnected; no run is active. Wait for the next
  `Char.Name` to start a fresh run normally.

The character-name resolution mechanics (which `<char>/current.jsonl`
belongs to the live connection) are deferred to implementation; they fall
out naturally from the file structure plus `connected_at` from
`connection.state`.

### Orphan `current.jsonl` handling

If the brain dies and MUME also disconnects before any clean run-end seals
the file, `current.jsonl` is left orphaned. On the next event that touches
that character's runs directory (next `mark_mume_connected()` or
`mark_mume_disconnected()`), the orphan is sealed:

1. Append a `{"event": "orphan_close", "ts": <now>}` line.
2. Rename `current.jsonl` → `<run-id>.jsonl` using the run's first-line
   `start_at` as the run-id source.

The orphan loses its true end timestamp but no run data is lost.

### Run-id format

ISO-like `<YYYY-MM-DD>T<HH-MM-SS>.jsonl`, e.g.
`2026-05-07T18-32-15.jsonl`. Dashes replace colons for filesystem
portability. Sortable lexicographically, scannable in `ls`, useful for the
future launcher run browser.

## Consequences

- **Single, unambiguous vocabulary for play sessions.** New code uses
  "run" without colliding with any of the four "session" meanings. tt++
  keeps its own term in its own domain.
- **One persistence rule.** New character-bound data goes under
  `data/characters/<char>/` (current state) or `data/runs/<char>/`
  (per-run history). Comm joins this principle. World-level data goes
  under `data/shared/`. No further "where do I put this?" decisions.
- **Brain crash mid-run is data-safe.** The orphan handler seals the
  leftover `current.jsonl` on the next login for the same character.
- **Long disconnect + reconnect is naturally captured as two runs,**
  matching the user's mental model.
- **`logs/` becomes meaningful again.** Tail-readable, no surprises.
- **Bootstrap-window edge is not new complexity.** The
  `guard-on-state.char.name` pattern already exists in `affects.lua` and
  `stored_spells.lua`.
- **Migration cost is one-time.** Existing users have files in the old
  locations; the migration step (separate PR) moves them. Profile-keyed
  comm archives are best-effort renamed to character-keyed using the
  profile name as a fallback character name (see Out of scope).
- **ADR 0011 is partially superseded.** Its mechanics (JSONL, 7-day
  window, atomic prune) survive; its scope (per-profile) does not.

## Alternatives considered

**Per-profile for everything.** Simpler — no bootstrap-window concern,
existing comm archive untouched. Rejected because all upcoming features
(XP per character, kills per character, runs per character) are inherently
character-bound, and forcing them through a profile layer adds an
indirection that buys nothing for a single-character-per-profile workflow
and breaks if the user ever uses one profile across two characters.

**Three-bucket `data/` layout (`runs/`, `charstate/`, `shared/`) with
`comm` folded into `charstate/` or as a standalone `data/comm/`.** Rejected
because comm's lifecycle (append-only, 7-day rolling) is identical to
`runs` and unlike `charstate` (read-modify-write current state). Grouping
top-level by lifecycle makes future tooling (backup scripts, retention
policies, migration) uniform.

**Run boundaries triggered by player command (`cp -run-start` /
`cp -run-stop`).** More control, but in practice no one wants to manually
manage this. `Char.Name`-driven boundaries do the right thing
automatically in every observed scenario.

**Run boundaries with grace window (reconnect within N minutes = same
run).** Considered for the link-loss case; rejected as needless complexity.
Two short runs is an honest model.

**Unix-epoch run-ids.** Shorter, sortable, guaranteed-unique. Rejected
because the launcher will list runs and ISO timestamps are scannable at a
glance.

**Keep IPC temps in `logs/`.** Minimal change. Rejected for the same
reason as the rest: lifecycle separation matters; mixing five-second-
lifetime files with persistent logs and persistent data was the original
mess.

## Out of scope / follow-up

- **Migration PR** for existing on-disk files into the new `data/` tree.
  Idempotent script; runs once on first launch after the rename PR
  ships.
- **Run event schema** — what JSONL events go into `current.jsonl`
  (`run_start`, `run_end`, `kill`, `level_up`, `group_member_seen`,
  etc.). Designed separately when run-tracking lands.
- **Comm ↔ run relation** — whether run aggregates include comm
  excerpts or just a timestamp-range pointer into the comm archive.
  Open question for the run-tracking phase.
- **Launcher run browser** — UI for viewing/comparing runs. Designed
  when run-tracking has data to show.
- **Per-character migration of the profile-keyed comm archive.**
  Best-effort: use the profile name as the character name where they
  coincide; otherwise leave the old file in place under the old name
  and start fresh.

## Relation to other ADRs

- Supersedes **ADR 0011** (per-profile JSONL comm archive) in the scope
  dimension. Mechanics retained.
- Builds on **ADR 0003** (GMCP-driven MUME connection state). The run
  boundaries reuse `mark_mume_connected()` / `mark_mume_disconnected()`
  unchanged.
- Builds on **ADR 0008** (session XP attribution). Attribution logic is
  unchanged; only the namespace name (`state.session` → `state.run`)
  shifts.
