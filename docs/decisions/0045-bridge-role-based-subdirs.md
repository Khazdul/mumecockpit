# ADR 0045 — bridge/ role-based subdirectories

**Status:** Accepted  
**Date:** 2026-05-07

## Context

`bridge/` accumulated 25+ files at its root, mixing pre-tmux menu logic,
pane renderers, layout helpers, release tools, and background services with no
structural signal about file roles. Reading the tree required knowing the
codebase; finding "what fires on resize" or "where does the Windows shortcut
point" required grep.

## Decision

Split `bridge/` top-level files into four role-based subdirectories:

| Bucket | Path | Role |
|---|---|---|
| launcher | `bridge/launcher/` | Pre-tmux menu, tmux orchestration, Windows entry point |
| panes | `bridge/panes/` | Python prompt_toolkit pane renderers |
| layout | `bridge/layout/` | Pane / layout state mutations |
| release | `bridge/release/` | Release and update operations |
| services | `bridge/services/` | Cockpit-spawned background tasks |

Runtime state files (`*.state`, `*.cache`, `*.conf`, dot-sentinels,
`.update_preserve/`) remain in `bridge/` root unchanged. A future PR may
introduce `bridge/runtime/`; deferred to keep this change reviewable.

`bridge/ipc/` and `bridge/smoke.sh` are unchanged.

## Four placement decisions

**a. `bridge/launch.sh` → `bridge/launcher/launch.sh`.**  
Windows desktop shortcuts target this file. Existing shortcuts will break on
the next update; new installs are correct. Acceptable given the current user
count. The Windows installer (`install/installer-core.ps1`) and the Linux
bootstrap (`install/bootstrap-linux.sh`) are updated to point to the new path.

**b. `bridge/toggle_pane.sh` and `bridge/focus_input.sh` → `bridge/layout/`.**  
Classified by function (pane/layout mutation) rather than caller. Both are
invoked by tmux bindings and the in-game popup, not only by layout hooks.

**c. Runtime state stays in `bridge/` root.**  
`.state`, `.cache`, `.conf`, dot-sentinels, and `.update_preserve/` are
not moved. Dozens of Lua, Python, and shell files reference them via
`$HOME/MUME/bridge/…`; moving them would give zero structural benefit at
high coordination cost. A future `bridge/runtime/` consolidation is possible
but deferred.

**d. `bridge/read_config.sh` → `bridge/launcher/`, `bridge/read_version.sh`
and `bridge/ping_monitor.sh` → `bridge/services/`.**  
`read_config.sh` is sourced at launcher boot and tt++ startup — launcher bucket.
`read_version.sh` emits a tt++ variable at startup — services bucket (version
infrastructure).  `on_pane_resize.sh`, not in the original file listing, is
classified into `bridge/layout/` (it is a border-drag handler, directly
analogous to `on_window_resize.sh`).

## Compatibility shims

`bridge/launcher.sh` and `bridge/tmux_start.sh` remain as thin shims:

```bash
#!/usr/bin/env bash
# Compat shim — moved to bridge/launcher/ in v0.7.0. Remove once
# all clients have updated past this release.
exec bash "$(cd "$(dirname "$0")" && pwd)/launcher/$(basename "$0")"
```

These two paths are the only ones an in-memory v0.6.x process might re-exec
after an update lands (e.g. `tmux_start.sh` execs `launcher.sh` on
return-to-menu). No other compat shims are provided — the upgrade-path concern
is specific to these two scripts.

**Planned removal:** in the release after v0.7.0 once all active clients have
updated through at least one cycle that includes the shims.

## Alternatives rejected

**Flat `bridge/` with role-prefix naming** (e.g. `launcher_tmux_start.sh`,
`layout_toggle_pane.sh`). Rejected: names become noisy; `ls bridge/` still
shows a wall of files; discovery is no better than grep.

**`bridge/runtime/` in this same PR.** Rejected: runtime state is referenced
from many places (Lua, Python, shell) and provides no structural benefit to the
reader from being in a subdir. Deferred.

## Consequences

- `bridge/` root now contains only runtime state + `ipc/` + `smoke.sh` + two
  compat shims. Any new executable goes into one of the five subdirectories.
- All path references updated: `start.sh`, `ttpp/core/`, `lua/` (none needed —
  all Lua refs were to runtime state), `bridge/` internals, `install/`,
  `docs/`, `bridge/panes/input_pane.py`.
- Windows desktop shortcuts created before v0.7.0 must be recreated. The
  installer will create correct shortcuts on re-run.
- `bridge/smoke.sh` walks `find bridge -name '*.sh'` recursively; all moved
  scripts are found automatically. The `source bridge/launcher/menu_render.sh`
  syntax-check line is updated to the new path.
