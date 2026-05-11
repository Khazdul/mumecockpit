# Architecture Decision Records

Short, append-only records of non-obvious design decisions. The
"Current state" section below lists the ADRs currently in force,
grouped by area, so a new reader can find the active decision for any
topic without walking the full supersession history. Read individual
ADRs for context, alternatives, and consequences.

## Current state

Active ADRs by area. Click through for context, alternatives, and consequences.

### Layout & pane geometry

- [ADR 0030](0030-right-column-heights-free.md) — Right-column heights free — pane heights are tmux-managed; `apply_layout.sh` only pins the input row. (supersedes 0004, 0005)
- [ADR 0006](0006-char-pane-on-top.md) — Char pane on top — right-column order is status → ui → dev, with a single resizable ui↔dev border.
- [ADR 0023](0023-char-pane-dynamic-width.md) — Char pane adaptive width — the status pane reads its width dynamically; both paired rows and affect cells use a uniform lw+1+rw split.
- [ADR 0029](0029-input-pane-full-width.md) — Input pane spans full window width — the input pane is a window-level vsplit sibling spanning the full width below the top container.
- [ADR 0038](0038-drop-right-column-width-floor.md) — Drop right-column width floor — `ui_width` is the sole right-column width authority; no status-conditional floor, drag clamp, or auto-widen. (supersedes 0031)
- [ADR 0036](0036-drag-end-sweep.md) — Drag-end sweeps stuck copy-mode panes — drag-end events sweep all panes out of copy-mode and return focus to the input pane.

### Right-column rendering

- [ADR 0037](0037-right-column-prompt-toolkit-convergence.md) — All right-column panes use prompt_toolkit — all four right-column panes (status, buffs, comm, ui) are prompt_toolkit apps with uniform overflow indicators. (supersedes 0033)
- [ADR 0012](0012-unified-right-column-tui.md) (parked) — Unified right-column TUI — keep separate tmux panes and mitigate flicker at the renderer level rather than restructuring the right column.

### Input pane

- [ADR 0022](0022-input-pane-recall-as-selection.md) — Input pane recall as native selection — recall state is modeled as prompt_toolkit whole-buffer selection; Ctrl+C/X/V are clipboard operations.
- [ADR 0024](0024-input-pane-always-on.md) — Input pane is always-on — the input pane is an integral, always-on component; `cp -i` and `show_input` are removed.
- [ADR 0025](0025-page-keys-drive-tmux-copy-mode.md) — Page keys drive tmux copy-mode — Page Up/Down drive tmux copy-mode as the canonical game-pane scrollback, mirroring wheel semantics.

### GMCP & game state

- [ADR 0003](0003-gmcp-driven-mume-connection-state.md) — GMCP-driven MUME connection state — connection state is driven by GMCP (`Char.Name`/`Core.Goodbye`), not tt++ session events, so MMapper mode reports correctly.
- [ADR 0008](0008-session-xp-attribution.md) — Session XP attribution across group kills — XP is accumulated continuously and folded by a 500 ms debounced timer on `mob_death`, distributing evenly across simultaneous kills.
- [ADR 0034](0034-clock-renderer-side-countdown.md) — Clock renderer-side countdown — the input-pane clock computes remaining time from a target epoch in `status.state`; a renderer-side async tick drives 1 Hz decrements with no phase wobble.

### Comm pane & archive

- [ADR 0009](0009-comm-state-as-pane-contract.md) — comm.state as the stable pane contract — `bridge/comm.state` is the atomically-written Lua-to-renderer contract; the renderer polls it by mtime.
- [ADR 0010](0010-comm-filter-persistence.md) — Sparse-map persistence for comm filters — `comm_filters.conf` stores only explicitly-toggled channels; a missing key means enabled, so new server channels appear automatically.
- [ADR 0013](0013-comm-display-normalization.md) — Comm display normalization in the renderer — the renderer normalises talker prefixes, language suffixes, and NPC descriptors; raw GMCP data is preserved verbatim in the archive.
- [ADR 0040](0040-comm-pane-owns-line-wrapping.md) — Comm pane owns line wrapping — the renderer word-wraps via `_wrap_fragments`; `_row_count` delegates to the same helper so scroll math is always exact.

### Affects & buffs

- [ADR 0026](0026-anchored-core-actions.md) — Anchored core `#action` patterns — all core `#action` patterns are anchored `^…$` to prevent false triggers from player-quoted text.
- [ADR 0027](0027-drop-driven-affect-expiry.md) — Drop-driven affect expiry — affects with a drop string expire on the drop message; the tick is a 2.5× safety net only.
- [ADR 0032](0032-buffs-pane-extracted-from-status.md) — Buffs pane extracted from status — affects are visualised in a dedicated buffs pane (`cp -b`); the status pane no longer renders affects.

### Lua architecture

- [ADR 0002](0002-lua-core-vs-scripts-split.md) — Lua core vs scripts split — always-on GMCP collectors live in `lua/core/`; opt-in automation modules live in `lua/scripts/`, auto-loaded core-first.
- [ADR 0007](0007-event-bus.md) — Lua event bus for core MUD triggers — a central `events.subscribe`/`emit` bus in `brain.lua` owns all cross-cutting trigger patterns; scripts subscribe rather than registering duplicates.
- [ADR 0043](0043-unified-character-event-marker.md) — Unified character-event marker as `char_ui` — `char_ui(category, name, verb)` is the single helper owning the `◆` prefix for all character-state lifecycle events.
- [ADR 0046](0046-gmcp-dispatch-via-events.md) — GMCP dispatch via events bus — one primary writer per module owns `gmcp.handlers`; `gmcp.dispatch` always emits `gmcp_<module_snake>` after the primary writer; downstream effects subscribe instead of wrapping handlers.

### Sessions & profile persistence

- [ADR 0014](0014-system-owned-profile-autosave.md) — System-owned profile auto-save — the `SESSION DEACTIVATED` auto-save handler lives in `system.tin`; user profiles must not register their own.
- [ADR 0018](0018-update-preserves-user-files.md) — update.sh preserves user-created files — user-created files in `ttpp/profiles/` and `lua/scripts/` are snapshotted before the git reset and restored after.
- [ADR 0042](0042-blank-profile-template.md) — Blank-profile template and runtime-seeded default.tin — `bridge/launcher/templates/blank_profile.tin` is the sole source for new-profile content; `default.tin` is seeded from it on first launch.
- [ADR 0048](0048-ttpp-profiles-path-rename.md) — ttpp/profiles/ path rename — `ttpp/sessions/` renamed to `ttpp/profiles/` to match the profile/session vocabulary from ADR 0044; one-shot migration in both launchers.

### Data layout & runs

- [ADR 0044](0044-runs-and-character-scoped-persistence.md) — Runs and character-scoped persistence — play sessions are "runs", all persistent state is per-character, and files live under `data/`. (supersedes 0011 in scope)
- [ADR 0054](0054-remove-cp-r-full-reload.md) — Remove cp -r full system reload — the full-reload alias and its brain-startup rehydration are removed; restart-via-launcher is the only supported recovery path. (invalidates §"cp -r mid-run" of 0044)
- [ADR 0056](0056-previous-run-id-linking.md) — previous_run_id links each run to its predecessor — `run_start` rows include the most recent sealed run-id for the same character, so consumers can stitch link-loss runs without a writer-side grace window.

### Launcher & terminal UX

- [ADR 0019](0019-launcher-polls-version-cache-mtime.md) — Launcher polls version.cache mtime — the launcher rebuilds the menu when `version.cache` mtime changes, so the Update row appears without a relaunch.
- [ADR 0021](0021-stty-over-tput-for-terminal-dimensions.md) — Use stty for terminal dimensions — `stty size </dev/tty` is used instead of `tput cols`, which returns wrong values in macOS non-interactive subshells.
- [ADR 0039](0039-cp-aliases-persistent.md) — cp -X aliases always persist — all `cp -X` aliases pass `--persist` to `toggle_pane.sh`; every toggle from any entry point writes to `startup.conf`.
- [ADR 0062](0062-popup-menu-prompt-toolkit.md) — In-game popup rewritten in prompt_toolkit — `ingame_menu.py` is the popup body; `ingame_menu.sh` is a thin exec wrapper. Mouse wheel deliberately not supported (tmux display-popup limitation).

### Bridge services & startup

- [ADR 0001](0001-constant-ping-monitor.md) — Constant ping monitor — a single long-lived ping monitor runs for the tmux session and writes to a shared cache file; the popup reads it on demand.
- [ADR 0041](0041-post-attach-layout-build.md) — Post-attach initial layout build — the initial pane layout is built after the first client attaches, reading tmux's authoritative post-attach window dimensions.
- [ADR 0045](0045-bridge-role-based-subdirs.md) — bridge/ role-based subdirectories — split bridge/ top-level into launcher/, panes/, layout/, release/, services/ buckets; runtime state stays in bridge/ root; compat shims for launcher.sh and tmux_start.sh.
- [ADR 0047](0047-bridge-runtime-consolidation.md) — bridge/runtime/ consolidation — all *.state/*.cache/*.conf/dot-sentinels/.update_preserve/ moved from bridge/ root into bridge/runtime/; gitignore collapsed to one block; one-shot startup migration for v0.6.x installs.

### Self-update & release

- [ADR 0016](0016-default-branch-renamed-to-main.md) — Default branch renamed to main — the GitHub default branch was renamed from master to main; no source file changes were needed.
- [ADR 0017](0017-update-checks-out-tags.md) — update.sh checks out release tags — `update.sh` checks out the latest release tag named in `version.cache`, not the tip of main.

### Installer & platform

- [ADR 0015](0015-windows-installer-scope.md) — Windows installer supports Windows 11 22H2+ only — the installer requires Windows 11 build 22621+; no slow-path for older Windows.
- [ADR 0020](0020-platform-support-policy.md) — Platform support policy — Linux/WSL is Tier 1; macOS is Tier 2 with portable helpers required in place of GNU-specific flags.
- [ADR 0028](0028-windows-shortcut-delegation.md) — Windows shortcut delegates to Linux-side launcher — the desktop shortcut invokes `bridge/launcher/launch.sh` directly, eliminating shell-quoting bugs in the alacritty → wsl chain.
- [ADR 0035](0035-tt-from-source.md) — Build tt++ from source when unsuitable — the bootstrap probes for a TLS-linked tt++ and builds from a pinned source tag when absent or unsuitable.

## When to add an ADR

Add an ADR when a decision:
- Constrains future choices (e.g. "Lua, not Python").
- Has a non-obvious rationale (the "why" isn't recoverable from the code).
- Was a trade-off — document what the alternatives were.

Don't ADR everything. Routine choices go in code comments or the relevant
`docs/*.md`.

## Format

Filename: `NNNN-short-slug.md`, zero-padded sequence number.

Body template:

    # NNNN — Title

    **Status:** Accepted | Superseded by NNNN | Deprecated
    **Date:** YYYY-MM-DD

    ## Context
    What forces are at play? What problem are we solving?

    ## Decision
    What did we decide? Stated plainly.

    ## Consequences
    What becomes easier. What becomes harder. What we're locked out of.

    ## Alternatives considered
    One paragraph per serious alternative, and why it wasn't chosen.

## Rules

- Once committed, ADRs are **append-only**. If a decision changes, write a
  new ADR that *supersedes* the old one; update the old one's Status line
  only.
- Keep ADRs short (half a page, one page max).
