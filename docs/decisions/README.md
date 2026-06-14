# Architecture Decision Records

Short, append-only records of non-obvious design decisions. The
"Current state" section below lists the ADRs currently in force,
grouped by area, so a new reader can find the active decision for any
topic without walking the full supersession history. Read individual
ADRs for context, alternatives, and consequences.

## Current state

Active ADRs by area. Click through for context, alternatives, and consequences.

### Layout & pane geometry

- [ADR 0071](0071-per-pane-desired-heights.md) — Per-pane desired heights with adaptive cold-start allocation — `desired_<pane>` values in `layout.conf` drive a two-phase cold-start algorithm; drags persist the new desired. (supersedes 0055, partially supersedes 0030)
- [ADR 0072](0072-toggle-equalize-fallback.md) — Equalize-before-split fallback for runtime opens — `open_pane.sh` redistributes to fair share before refusing a split; non-zero exit prevents `toggle_pane.sh` from persisting an unrealised show flag. (refines 0055)
- [ADR 0030](0030-right-column-heights-free.md) — Right-column heights free — mid-session pane heights are tmux-managed and user-resizable; cold-start and WINCH re-apply from `desired_<pane>` via ADR 0071. (supersedes 0004, 0005; partially superseded by 0071)
- [ADR 0006](0006-char-pane-on-top.md) — Char pane on top — right-column order is status → ui → dev, with a single resizable ui↔dev border.
- [ADR 0023](0023-char-pane-dynamic-width.md) — Char pane adaptive width — the status pane reads its width dynamically; both paired rows and affect cells use a uniform lw+1+rw split.
- [ADR 0029](0029-input-pane-full-width.md) — Input pane spans full window width — the input pane is a window-level vsplit sibling spanning the full width below the top container.
- [ADR 0038](0038-drop-right-column-width-floor.md) — Drop right-column width floor — `ui_width` is the sole right-column width authority; no status-conditional floor, drag clamp, or auto-widen. (supersedes 0031)
- [ADR 0036](0036-drag-end-sweep.md) — Drag-end sweeps stuck copy-mode panes — drag-end events sweep all panes out of copy-mode and return focus to the input pane.
- [ADR 0137](0137-character-pane-height-reservation.md) — Character-pane height reservation — Phase 2 reserves the status pane its desired height before the other panes scale proportionally; identical geometry when everything fits, skipped if status was dropped. (amends 0071)

### Right-column rendering

- [ADR 0037](0037-right-column-prompt-toolkit-convergence.md) — All right-column panes use prompt_toolkit — all four right-column panes (status, buffs, comm, ui) are prompt_toolkit apps with uniform overflow indicators. (supersedes 0033)
- [ADR 0012](0012-unified-right-column-tui.md) (parked) — Unified right-column TUI — keep separate tmux panes and mitigate flicker at the renderer level rather than restructuring the right column.
- [ADR 0133](0133-timers-countdown.md) — Timers-pane countdown (Clock) overlay; expiring-blink removed — a per-type opt-in (`timers_<type>_clock`) right-justifies a countdown over the existing drain bar in `timers_pane.py`; ≤90s whole seconds, >90s nearest-minute (half up), narrow-cell ladder, right-edge/corner handling. Pure presentation off the already-serialised data and the existing 1 Hz tick — no new redraw machinery, nothing on the tt++ hot path, no Lua. The final-30s blink (modelled on ADR 0033) is removed. (relates to 0126, 0033)
- [ADR 0136](0136-in-pane-borders.md) — In-pane pane borders — each right-column pane draws its own half-block frame (`▀▄▌▐` edges, adaptive quadrant corners `▛▜▙▟` falling back to `█`) and header in-pane, replacing tmux `pane-border-status` (now permanently off); border colour = pane colour +0x14 (terminal-default derived from `terminal_bg`), corner support resolved at startup by `frame_corners.py` (fontconfig else fontTools), per-pane `border_<key>` via a Border column in the Panes grid. (relates to 0099, 0126, 0038, 0086, 0125)

### Input pane

- [ADR 0022](0022-input-pane-recall-as-selection.md) — Input pane recall as native selection — recall state is modeled as prompt_toolkit whole-buffer selection; Ctrl+C/X/V are clipboard operations.
- [ADR 0024](0024-input-pane-always-on.md) — Input pane is always-on — the input pane is an integral, always-on component; `cp -i` and `show_input` are removed.
- [ADR 0025](0025-page-keys-drive-tmux-copy-mode.md) — Page keys drive tmux copy-mode — Page Up/Down drive tmux copy-mode as the canonical game-pane scrollback, mirroring wheel semantics.
- [ADR 0102](0102-wsl-clipboard-win32yank.md) — Fast WSL clipboard read via win32yank — Ctrl+V on WSL reads via a pinned win32yank binary with a pyperclip fallback; bracketed paste (Ctrl+Shift+V) remains the instant path. (refines 0022)

### GMCP & game state

- [ADR 0003](0003-gmcp-driven-mume-connection-state.md) — GMCP-driven MUME connection state — connection state is driven by GMCP (`Char.Name`/`Core.Goodbye`), not tt++ session events, so MMapper mode reports correctly.
- [ADR 0008](0008-session-xp-attribution.md) — Session XP attribution across group kills — XP is accumulated continuously and folded by a 500 ms debounced timer on `mob_death`, distributing evenly across simultaneous kills.
- [ADR 0034](0034-clock-renderer-side-countdown.md) — Clock renderer-side countdown — the input-pane clock computes remaining time from a target epoch in `status.state`; a renderer-side async tick drives 1 Hz decrements with no phase wobble.
- [ADR 0094](0094-labeled-npcs-in-group.md) — Labelled NPCs in `state.group.members` — `type:"npc"` entries with a non-null `label` are included alongside allies; background NPCs without labels remain invisible. (v1 re-sync limitation superseded by 0095)
- [ADR 0095](0095-promote-demote-npcs-on-label-change.md) — Promote / demote NPCs on `Group.Update` label change — excluded NPCs are held in a file-local `_excluded` table; an update that adds a non-empty label promotes (emits `group_member_added`), one that clears it demotes (emits `group_member_removed`). (supersedes the v1 limitation of 0094)
- [ADR 0096](0096-room-scoped-group-membership.md) — GMCP group membership is room-scoped — `Group.*` reflects the player's current room, not the whole roster; ids are transient presence handles reassigned on each re-add. Consumers needing stable identity must key on `label` or `name`.
- [ADR 0117](0117-achievement-capture-via-gmcp.md) — Achievement capture via GMCP `Event.Achieved` — passive collector in `lua/core/world_state.lua` re-emits the `achievement` event from the GMCP `what` field; the two-stage tt++ trigger is removed. (supersedes 0050)

### Comm pane & archive

- [ADR 0009](0009-comm-state-as-pane-contract.md) — comm.state as the stable pane contract — `bridge/comm.state` is the atomically-written Lua-to-renderer contract; the renderer polls it by mtime.
- [ADR 0010](0010-comm-filter-persistence.md) — Sparse-map persistence for comm filters — `comm_filters.conf` stores only explicitly-toggled channels; a missing key means enabled, so new server channels appear automatically.
- [ADR 0129](0129-comm-channel-menu-and-header-toggle.md) — Menu-driven comm channel filters and channel-header toggle — a Communication menu (launcher + popup, via `comm_channels.py`) adds further Python writers to `comm_filters.conf`; `comm_pane.py` re-reads it live on its 250 ms poll (bumping its own mtime after self-writes). The new show-channel-header preference lives in a separate `comm_prefs.conf` (default on), keeping 0010's channel-map schema clean. Menu-side channel tables are restated, not imported (no shared import path). (extends 0010, relates to 0126)
- [ADR 0013](0013-comm-display-normalization.md) — Comm display normalization in the renderer — the renderer normalises talker prefixes, language suffixes, and NPC descriptors; raw GMCP data is preserved verbatim in the archive.
- [ADR 0040](0040-comm-pane-owns-line-wrapping.md) — Comm pane owns line wrapping — the renderer word-wraps via `_wrap_fragments`; `_row_count` delegates to the same helper so scroll math is always exact.

### Affects & buffs

- [ADR 0026](0026-anchored-core-actions.md) — Anchored core `#action` patterns — all core `#action` patterns are anchored `^…$` to prevent false triggers from player-quoted text.
- [ADR 0027](0027-drop-driven-affect-expiry.md) — Drop-driven affect expiry — affects with a drop string expire on the drop message; the tick is a 2.5× safety net only.
- [ADR 0032](0032-buffs-pane-extracted-from-status.md) — Buffs pane extracted from status — affects are visualised in a dedicated buffs pane (`cp -b`); the status pane no longer renders affects.
- [ADR 0118](0118-armour-damage-drop-sample-gate.md) — Armour damage-drop sample gate — for affects flagged `damage_droppable`, drops earlier than the data-table `duration` are treated as damage-triggered and not recorded as samples; the floor on the sample side keeps the learned mean from being dragged below the spell's true maximum. (builds on 0027)
- [ADR 0123](0123-shared-cast-feedback-ownership.md) — Shared cast-feedback ownership — `lua/core/spellcast.lua` registers each shared cast-failure / recall / concentration line exactly once and emits a neutral event (`spell_cast_failed`/`spell_cast_started`/`spell_cast_recalled`); blindness, charm, and stored-spells subscribe instead of re-registering, avoiding tt++ one-action-per-pattern shadowing. spellcast owns a kind-tagged cast-attempt FIFO; the accepted trade-off is a cross-pop between it and stored-spells' separate queue.
- [ADR 0124](0124-controlled-without-charm-followers.md) — Controlled-without-charm followers share the charm tracker via in-handler name dispatch — recognised in `_charm_on_followed` before the in-flight gate; permanent vs 99-min policy in a `CONTROLLED` table; wood-elf leave line with the cap as safety net. Chose one matcher over band-4 priority (ADR 0115).

### Lua architecture

- [ADR 0002](0002-lua-core-vs-scripts-split.md) — Lua core vs scripts split — always-on GMCP collectors live in `lua/core/`; opt-in automation modules live in `lua/scripts/`, auto-loaded core-first.
- [ADR 0007](0007-event-bus.md) — Lua event bus for core MUD triggers — a central `events.subscribe`/`emit` bus in `brain.lua` owns all cross-cutting trigger patterns; scripts subscribe rather than registering duplicates.
- [ADR 0043](0043-unified-character-event-marker.md) — Unified character-event marker as `char_ui` — `char_ui(category, name, verb)` is the single helper owning the `◆` prefix for all character-state lifecycle events.
- [ADR 0046](0046-gmcp-dispatch-via-events.md) — GMCP dispatch via events bus — one primary writer per module owns `gmcp.handlers`; `gmcp.dispatch` always emits `gmcp_<module_snake>` after the primary writer; downstream effects subscribe instead of wrapping handlers.
- [ADR 0093](0093-script-metadata-headers-and-opt-in-loading.md) — Static metadata headers and opt-in script loading — `lua/scripts/*.lua` declare metadata in `@`-tagged header comments parsed without executing the file; enable state in `scripts.conf` (runtime shadows shipped template); `register_script()` retired.
- [ADR 0131](0131-keymanager-locate-capture.md) — keymanager locate capture: arm on data, whole-line `%0`, self-removing terminator — locate rows are self-identifying, so a pattern-triggered `#action` gags each and forwards the whole line (`%0` spans the line via a leading anchored wildcard) to Lua; a fire-time-installed `^$` terminator renders then removes itself, kept in `{core}` and atomic per ADR 0097. No sent-output snoop, no hot-path handler. (builds on 0049/0050/0097)
- [ADR 0132](0132-keymanager-safekey.md) — keymanager safekey: always resolvable, freshest re-election on expiry — the safekey is a sticky per-character name designation that auto-elects the first stored key and re-elects the freshest live key (announced once) when its target expires, so the `psafe`/`tsafe`/`qtsafe` escape hatch is never dead while any key exists; named casts do not auto-substitute. (relates to 0131)

### Sessions & profile persistence

- [ADR 0014](0014-system-owned-profile-autosave.md) — System-owned profile auto-save — the `SESSION DEACTIVATED` auto-save handler lives in `system.tin`; user profiles must not register their own.
- [ADR 0018](0018-update-preserves-user-files.md) — update.sh preserves user-created files — user-created files in `ttpp/profiles/` and `lua/scripts/` are snapshotted before the git reset and restored after.
- [ADR 0042](0042-blank-profile-template.md) — Blank-profile template and runtime-seeded default.tin — `bridge/launcher/templates/blank_profile.tin` is the sole source for new-profile content; `default.tin` is seeded from it on first launch.
- [ADR 0048](0048-ttpp-profiles-path-rename.md) — ttpp/profiles/ path rename — `ttpp/sessions/` renamed to `ttpp/profiles/` to match the profile/session vocabulary from ADR 0044; one-shot migration in both launchers.

### Data layout & runs

- [ADR 0044](0044-runs-and-character-scoped-persistence.md) — Runs and character-scoped persistence — play sessions are "runs", all persistent state is per-character, and files live under `data/`. (supersedes 0011 in scope)
- [ADR 0054](0054-remove-cp-r-full-reload.md) — Remove cp -r full system reload — the full-reload alias and its brain-startup rehydration are removed; restart-via-launcher is the only supported recovery path. (invalidates §"cp -r mid-run" of 0044)
- [ADR 0056](0056-previous-run-id-linking.md) — previous_run_id links each run to its predecessor — `run_start` rows include the most recent sealed run-id for the same character, so consumers can stitch link-loss runs without a writer-side grace window.
- [ADR 0130](0130-exit-rating-session-anchor.md) — Exit-rating anchors to the session's latest persisted run — `_exit_anchor()` uses the active run when connected and `run_stats.most_recent_sealed_run()` gated by `.session_start` when disconnected (false-negative bias); rating 0 inherits the chain's existing rating across the whole chain so a continued session survives the 14-day sweep, rather than no-opping. (supersedes 0119)

### Launcher & terminal UX

- [ADR 0019](0019-launcher-polls-version-cache-mtime.md) — Launcher polls version.cache mtime — the launcher rebuilds the menu when `version.cache` mtime changes, so the Update row appears without a relaunch.
- [ADR 0021](0021-stty-over-tput-for-terminal-dimensions.md) — Use stty for terminal dimensions — `stty size </dev/tty` is used instead of `tput cols`, which returns wrong values in macOS non-interactive subshells.
- [ADR 0039](0039-cp-aliases-persistent.md) — cp -X aliases always persist — all `cp -X` aliases pass `--persist` to `toggle_pane.sh`; every toggle from any entry point writes to `startup.conf`.
- [ADR 0062](0062-popup-menu-prompt-toolkit.md) — In-game popup rewritten in prompt_toolkit — `ingame_menu.py` is the popup body; `ingame_menu.sh` is a thin exec wrapper. (Wheel-limitation half superseded by ADR 0114.)
- [ADR 0069](0069-launcher-prompt-toolkit.md) — Launcher rewritten in prompt_toolkit — `launcher.py` is the menu body; `launcher.sh` is a thin exec wrapper. Frame stack mirrors ADR 0062; colour palette extracted to `palette.py` and shared with the popup.
- [ADR 0073](0073-statistics-rendering-duplicated.md) — Statistics rendering is duplicated between popup and launcher History — the in-game popup Statistics frame and the launcher's History detail frame share data (ADR 0065) but each renders its own. Different hosts and use cases justify the duplication; conditions for future consolidation are recorded.
- [ADR 0085](0085-shared-menu-chrome.md) — Shared menu chrome between launcher and popup — `bridge/launcher/menu_chrome.py` exposes title/footer/button helpers (and two new palette tokens, `C_OK` / `C_CURSOR_CELL`) so both surfaces share title spacing, footer anchoring, and the two-mode cursor grammar.
- [ADR 0086](0086-panes-grid.md) — Panes configuration as a single colour grid — `bridge/launcher/panes_grid.py` renders a pane × colour grid (rows = panes, columns = the 7 palette entries; 0 or 1 cells checked per row). Replaces the per-pane Options subframes on both surfaces; shared render, per-surface commit (launcher deferred, popup immediate + live tmux). Adds `C_PANE_OFF` to `palette.py`.
- [ADR 0126](0126-timers-layout-menu.md) — Timers layout menu; defaults duplicated across bridge packages — `bridge/launcher/timers_layout_grid.py` renders a group × colour grid with a trailing `◄ N ►` column stepper (rows = the 6 timer groups, columns = 9 palette entries) for both Options surfaces. Reuses `panes_grid.apply_cell_toggle`; shared render, per-surface commit (launcher deferred, popup immediate + live via the pane's `timers_layout.conf` poll). Adds `TIMERS_COLOR_ORDER` to `palette.py`. The config defaults / cols-clamp are intentionally duplicated from `bridge/panes/timers_pane.py` (no shared import path). (builds on 0086)
- [ADR 0099](0099-terminal-bg-detection-osc11.md) — Terminal-background detection via OSC 11 — the launcher probes the host terminal background once at startup on `/dev/tty` and writes the effective hex to `layout.conf:terminal_bg`; consumers (tmux separator, credits canvas, spotlight outline, editor current-line band) read that single value. Configurable `terminal_bg_fallback` in `startup.conf` (default `#000000`) covers the WSL2 + Alacritty installer base, where ConPTY blocks the OSC 11 reply.
- [ADR 0100](0100-banner-unification.md) — Banner unification across launcher and popup — `bridge/launcher/launcher_banner.py` is the single Python source for the animated starfield + wordmark banner; both the launcher main page (12 Hz tick) and the in-game popup's `main` frame (6 Hz tick) render it. The retired `banner.py` ends the wordmark duplication between the two `prompt_toolkit` surfaces; the tt++ welcome screen deliberately keeps its own static, starless `#showme` wordmark.
- [ADR 0101](0101-startup-conf-fresh-install-defaults.md) — Single source of truth for `startup.conf` fresh-install defaults — `bridge/launcher/templates/startup.conf` is the shipped template; `tmux_start.sh` copies it when `bridge/runtime/startup.conf` is missing and `launcher.py` parses it for `_CONF_DEFAULTS`. Every right-column pane defaults on except the developer pane; the `${show_*:-N}` guards in `build_initial_layout.sh` are aligned with the template and now only matter for upgraded installs missing a key.

### Bridge services & startup

- [ADR 0001](0001-constant-ping-monitor.md) — Constant ping monitor — a single long-lived ping monitor runs for the tmux session and writes to a shared cache file; the popup reads it on demand.
- [ADR 0041](0041-post-attach-layout-build.md) — Post-attach initial layout build — the initial pane layout is built after the first client attaches, reading tmux's authoritative post-attach window dimensions.
- [ADR 0070](0070-launcher-pre-attach-layout-build.md) — Two-mode initial layout build — when the launcher provides `LAUNCHER_COLS`/`LAUNCHER_ROWS` the layout is built pre-attach against the detached session; otherwise the ADR 0041 post-attach hook fallback runs. (supplements 0041)
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
- [ADR 0103](0103-windows-flicker-terminal.md) — Windows inbound-burst flicker: move the terminal off the ConPTY path — the Windows deployment runs the cockpit's terminal as a Linux GUI app under WSLg so ConPTY is no longer in the render path; no in-app flicker workaround.
- [ADR 0104](0104-windows-deployment-foot-wslg.md) — Windows deployment: foot under WSLg, fullscreen, supervisor-owned — foot via a WSLg `.desktop` Start Menu entry, fullscreen-only, lifecycle owned by `bridge/supervisor.sh` with a `.relaunch_terminal` sentinel and `MUME_TERMINAL=foot-managed`. (builds on 0103)
- [ADR 0105](0105-launcher-resume-hint.md) — Cross-relaunch frame restoration via a resume-hint file — `bridge/runtime/.launcher_resume` carries `frame` + `cursor` across the foot relaunch so Apply lands back on Terminal Settings instead of the main menu. (builds on 0104)

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
