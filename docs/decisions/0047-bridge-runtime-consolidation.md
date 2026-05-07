# ADR 0047 — bridge/runtime/ consolidation

**Status:** Accepted  
**Date:** 2026-05-07

## Context

ADR 0045 introduced role-based subdirectories under `bridge/` (`launcher/`,
`panes/`, `layout/`, `release/`, `services/`, `ipc/`, `dev/`). At that time
the runtime-generated files (`*.state`, `*.cache`, `*.conf`, dot-sentinels,
`.update_preserve/`) remained at the `bridge/` root, deferred pending the
completion of the restructuring work.

The foundation work tracked in the issues following ADR 0045 (#5–#11) is now
complete:

- `bridge/ipc/` was separated in ADR 0044 (IPC temp files have a five-second
  lifetime, distinct from the persistent runtime state files).
- `bridge/dev/` holds developer fixtures and never receives generated files.
- All other structural work has landed.

The `bridge/` root is now a mix of canonical role-based subdirectories and a
scatter of runtime files, which is confusing and makes gitignore maintenance
fragile. Seventeen individual gitignore lines cover the runtime scatter.

## Decision

Move all runtime-generated files from `bridge/` root into a dedicated
`bridge/runtime/` subdirectory:

- `*.state` — `buffs.state`, `comm.state`, `connection.state`, `status.state`
- `*.cache` — `ping.cache`, `scripts.cache`, `version.cache`
- `*.conf` — `comm_filters.conf`, `layout.conf`, `startup.conf`
- Dot-sentinels — `.collapsed_panes`, `.layout_lock`, `.layout_ready`,
  `.pane_resize_pid`, `.ping_pid`, `.popup_open`, `.return_to_menu`
- `.update_preserve/` — user data preserved during self-update

The directory is tracked via `bridge/runtime/.gitkeep`. Its contents are
covered by a single gitignore block:

```
bridge/runtime/*
!bridge/runtime/.gitkeep
```

This replaces the seventeen per-file lines previously covering the runtime
scatter.

### What stays out of `bridge/runtime/`

- **`bridge/dev/`** — developer fixtures (`comm.state.fixture`, `README.md`).
  These are static test data checked into the repo, not generated at runtime.
- **`bridge/ipc/`** — IPC temp files (`cmd_*.tin`). These have a
  five-second lifetime and a separate ownership model (ADR 0044). Their
  subdirectory already existed before this change.
- **`bridge/smoke.sh`** — developer tool, not a runtime artefact.
- **`bridge/launcher.sh`, `bridge/tmux_start.sh`** — compatibility shims
  (separate removal tracked in issue #14).

### Migration

A one-shot migration block is placed in both `bridge/launcher/launcher.sh` and
`bridge/launcher/tmux_start.sh`, near the top before any runtime file is read:

```bash
mkdir -p bridge/runtime
for f in bridge/*.state bridge/*.cache bridge/*.conf bridge/.[a-zA-Z]*; do
    [ -e "$f" ] || continue
    mv "$f" bridge/runtime/ 2>/dev/null || true
done
[ -d bridge/.update_preserve ] && mv bridge/.update_preserve bridge/runtime/
```

The migration always runs; it is idempotent — the loop is a no-op when
`bridge/` root contains no runtime files, and `mkdir -p` is a no-op when the
directory exists. The original gate (`[ ! -d bridge/runtime ]`) was removed
because `bridge/runtime/.gitkeep` is a tracked file, meaning the directory
always exists after checkout and the gate was always false. It must be in
**both** launchers because after a self-update the user re-execs
`launcher.sh` directly — `start.sh` alone would miss the upgrade case.

`start.sh` and `tmux_start.sh` change their `mkdir -p bridge` calls to
`mkdir -p bridge/runtime` so the directory always exists on fresh checkouts
without relying on the migration path.

## Rationale

- **Cleaner directory listing.** `ls bridge/` shows only directories and the
  two shims; no runtime files pollute the view.
- **Simpler gitignore.** One wildcard block replaces seventeen individual
  exclusion lines; new runtime files are covered automatically.
- **Consistent lifecycle separation.** All runtime-generated state lives in
  one place, parallel to the `data/` and `logs/` patterns established by
  ADR 0044.
- **Smoke-check enforcement.** `bridge/smoke.sh` adds `bridge/runtime` to
  its `required_dirs` array; the `bridge/runtime/.gitkeep` file satisfies the
  non-empty check on a fresh checkout.

## References

- ADR 0045 — bridge role-based subdirectory scheme (this ADR completes it)
- ADR 0044 — runs and character-scoped persistence (parallel lifecycle-based
  separation principle for `data/` and `logs/`)
