# ADR 0002 — Lua core vs scripts split

Date: 2026-04-22  
Status: Accepted

## Context

`lua/scripts/` contained two fundamentally different kinds of files:

1. **Always-on GMCP collectors** — no alias, no `register_script()` call.
   These populate `state.*` fields that the rest of the system reads.
   Examples: `core_state.lua`, `char_state.lua`, `comm_log.lua`,
   `world_state.lua`.

2. **Opt-in automation modules** — player-facing features that register an
   alias and call `register_script(meta)`, appearing in `cp` help and the
   launcher's Scripts page. Examples: `autostab.lua`, `autobow.lua`.

Mixing them in one directory made the distinction invisible from the file tree,
forced readers to open each file to understand its role, and blocked future
opt-in/opt-out machinery from having a clean target directory.

## Decision

Split `lua/scripts/` into two directories:

- **`lua/core/`** — always-on files only. A file belongs here if and only if
  it has no alias and never calls `register_script()`.
- **`lua/scripts/`** — opt-in modules only. A file belongs here if and only
  if it calls `register_script(meta)`.

`brain.lua` loads `lua/core/*.lua` first (alphabetical), then
`lua/scripts/*.lua` (alphabetical). Load order matters: scripts may read
`state.*` fields populated by core collectors at load time.

The startup `dbg` line reports both counts:
`"N core + M scripts loaded"`.

`scripts.cache` is unaffected — core files never call `register_script()` so
they do not appear in the cache, which is the intent.

## Consequences

- The rule for where a new file belongs is unambiguous from the tree.
- Future per-module enable/disable machinery can target `lua/scripts/` without
  touching always-on infrastructure.
- Load order guarantee is explicit and documented.

## Rejected alternatives

**In-file `_core = true` flag** — a convention invisible from the tree.
Requires opening every file to classify it; easy to forget.

**Manifest file** — an extra file listing which scripts are core. Creates a
sync burden: every new file must also be registered in the manifest.

**`lua/scripts/core/` subdirectory** — same mental model as a flat split
but keeps both tiers under the "scripts" umbrella, obscuring that core files
are not scripts at all.

## Out of scope

The actual opt-in selection mechanism (per-module enable/disable at session
start) is deferred. This ADR only establishes the directory structure and load
order that future work will build on.
