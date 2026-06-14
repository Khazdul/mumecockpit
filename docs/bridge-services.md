# Bridge Services

Background services and persisted configuration files in `bridge/`. Touch
this file when changing the version check, self-update flow, ping monitor,
`scripts.cache` / `scripts.conf` format, `startup.conf` keys, or layout
persistence.

## Version check (`bridge/services/version_check.sh` + `bridge/runtime/version.cache`)

On every launcher startup, `bridge/launcher/launcher.sh` fires `version_check.sh` in
the background (`&`, `disown`). The script queries the GitHub releases API for
`Khazdul/mumecockpit` with a 3-second timeout. On success it writes
`bridge/runtime/version.cache` atomically (temp-file + rename):

    latest=vX.Y.Z
    checked_at=<epoch seconds>

TTL is 6 hours — later invocations within the window exit silently without
hitting the network. `--force` bypasses the cache.

Only `/releases/latest` is used. If the repo has no formal GitHub releases,
the endpoint returns 404 and the script exits silently without writing the
cache — the About page then shows the current version only. Any other failure
(offline, rate-limit, parse) leaves the cache unchanged and exits silently.

If `bridge/runtime/version.cache` holds a stale or wrong value, delete the file; the
launcher re-runs the check on its next start.

Consumers:
- Launcher About page: version is displayed top-right on the title row,
  always visible without scrolling. Shows current version always, appends
  "Update available: vX.Y.Z" in `_MR_ACCENT` when cache indicates a newer tag.

The consumer does not block on the network. If the cache is missing or stale
the UI still shows the current version; background refresh catches up within
seconds. The launcher polls the cache file's mtime in its main loop (~200ms
cadence) and rebuilds the menu items array if the cache is updated, so the
Update row appears on the first launcher run if the GitHub query completes
while the menu is open.

## Self-update (`bridge/release/update.sh`)

When `bridge/runtime/version.cache` indicates a newer tag than the VERSION file, the
launcher inserts an "Update" row into the main menu directly below the
Start/Continue/Mirror row. Selecting it runs `bridge/release/update.sh`, which:

1. Verifies `version.cache` actually indicates a newer version (comparison
   strips a single leading "v" from both operands, so "0.1.0" matches
   "v0.1.0").
2. Runs three safety guards — all must pass:
   - Developer fingerprint: `git config user.email` must NOT match any
     commit author in the repo history.
   - Working tree clean: no uncommitted changes, no untracked files
     outside `.gitignore`. Files in `ttpp/profiles/` and `lua/scripts/`
     are excluded from this check — auto-save writes there as part of
     normal operation.
   - Local commits: zero commits ahead of the latest release tag.
3. `git fetch --tags`
4. `git checkout` / `git reset --hard` to `refs/tags/<latest>`
5. Prompts user to restart the launcher. Any-key press re-execs
   `launcher.sh`, loading the fresh code.

Guard failure aborts with a specific exit code (20/21/22) and message.
Git failures exit 30.

### User data preservation

Before the `git reset --hard`, `update.sh` snapshots files that must survive
the reset to `bridge/runtime/.update_preserve/`, then copies them back after the reset
succeeds. The preserve dir is then deleted on clean exit.

**Shipped vs user-created.** Each file in `ttpp/profiles/` and `lua/scripts/`
is classified by checking whether it exists in the target release tag
(`git cat-file -e "refs/tags/$TAG:$path"`):

- **Exists in tag → shipped.** Overwritten by the reset without preservation.
  These are product files (e.g. `autostab.lua`, `bogger.tin`) that should
  receive their new tagged versions.
- **Does not exist in tag → user-created.** Preserved across the reset. These
  are files the user created via the launcher's Profile page or by writing a
  new script (e.g. `ttpp/profiles/myhero.tin`, `lua/scripts/mybot.lua`).

**`ttpp/profiles/default.tin` is always preserved**, even though it ships in
the repo as a starting template. The auto-save hook writes the user's live
session data to it; its in-repo contents are irrelevant after first launch.

**Failure mode.** If `git checkout` or `git reset --hard` exits non-zero, the
script aborts and prints to stderr:

    Update interrupted. Preserved user files are in
    bridge/runtime/.update_preserve/. Restore manually if needed.

Recovery: `cp -rp bridge/runtime/.update_preserve/. .` from the repo root, then
`rm -rf bridge/runtime/.update_preserve`.

**Limitation.** Edits made directly to shipped files (e.g. modifying
`autostab.lua` in place) are silently overwritten on the next update. Users
who want to customize a shipped script should copy it under a new name first.

**Why tag-checkout, not main-reset.** update.sh consumes exactly the same
artifact that version_check.sh advertises — the latest GitHub release tag.
This gives the update channel stable-release semantics: end users only ever
see code that was explicitly tagged and released. Unreleased commits on main
are never shipped to clients, and there is no window during which main HEAD
could have a VERSION older than the most recent tag (which would cause an
update loop). Developers stay on main; clients stay on tags.

**Post-update repo state.** After a successful update the working tree is on
a detached HEAD pointing at the release tag. This is intentional and not an
error condition for end users — they track releases, not a branch. Only
developers should ever run on a branch, and the email fingerprint guard
already prevents them from running update.sh.

The in-game popup does NOT expose an Update affordance. Update runs
pre-tmux, from the launcher only, so the cockpit never has to deal with
mid-session binary changes.

**Developer note:** the email fingerprint check is the primary protection
for active developers. If you clone on a fresh machine without setting
`git config user.email`, guards (b) and (c) still protect against
accidental damage. If all three guards somehow pass on a dev machine
(unlikely) and Update runs: the checkout discards nothing that wasn't already
tagged, and leaves you on the release tag's detached HEAD. Recovery:
`git reflog` still contains your old HEAD; `git checkout main` returns you
to the branch.

## Ping monitor (`bridge/services/ping_monitor.sh` + `bridge/runtime/ping.cache`)

A background process pings `mume.org` once per second and writes cache values
to `bridge/runtime/ping.cache`. The cockpit's in-game popup reads the cache each render
and shows the latency + a one-word quality label as part of the status header:

    Profile: default  ·  MMapper  ·  Link: 38ms (stable)

**Lifecycle.** The monitor is spawned by `bridge/launcher/tmux_start.sh` after the tmux
cockpit session is set up, and by `bridge/launcher/launcher.sh` on the Continue/Mirror
attach paths. A single-instance guard (`bridge/runtime/.ping_pid` lockfile) ensures
duplicate spawns are no-ops. The process self-terminates within ~1 s of the
`tmux:mume` session disappearing, so `cp -e`, SIGKILL, or any other shutdown
path stops it cleanly without explicit cleanup code.

**Cache format** (atomically written via temp-file + rename):

    latest=<integer ms or TIMEOUT>
    quality=<label or empty>
    samples=<comma-separated ring buffer, up to 60 entries>

**Quality algorithm.** Over the last 60 samples (1 minute):
- `loss%` = fraction of TIMEOUT samples
- `spread` = p95 − p50 of non-TIMEOUT samples (captures jitter and spikes
  without over-reacting to single outliers)

| Label   | Spread (ms) | Loss (%) | Colour in popup |
|---------|-------------|----------|-----------------|
| stable  | < 8         | = 0      | _MR_BODY        |
| ok      | < 20        | < 5      | _MR_BODY        |
| jittery | < 50        | < 15     | _MR_YELLOW      |
| spiking | < 120       | < 30     | _MR_YELLOW      |
| poor    | otherwise   | otherwise| _MR_ERR         |
| dead    | any         | >= 80    | _MR_ERR         |

Fewer than 10 samples → no label (buffer warming up).
"timeout" (current sample is TIMEOUT but history exists) shown in _MR_ERR
regardless of quality label.

Rationale for p95−p50: adapts to the user's own baseline (30 ms vs 300 ms
doesn't matter — the label describes *consistency*, not speed). Thresholds are
informed by the project owner's subjective calibration: ~20 ms deviation from
baseline is "noticeable unstable"; ~50 ms is "directly felt"; >100 ms is
"very bad."

**Failure modes.**
- `ping` binary missing / offline / DNS fails → samples are TIMEOUT, status
  header shows "Link: timeout (dead)" after buffer fills.
- SIGKILL'd monitor → stale PID file. Next launch detects dead PID (via
  `kill -0`) and takes over cleanly.
- Two cockpit sessions started simultaneously (rare) → only one monitor; the
  other's start call exits at the PID guard.

## scripts.cache (`bridge/runtime/scripts.cache`, gitignored)

Written by `brain.lua` at every client startup (inside `load_scripts()`).
Contains the **full catalog** — every script in `lua/scripts/`, enabled or
disabled — so the launcher's Scripts page and the in-game popup's Scripts
view can render every installed script regardless of its current enable
state (ADR 0093). Parsed by `bridge/launcher/launcher.py` and
`bridge/launcher/ingame_menu.py`.

Format (line-prefixed, one block per script, alphabetical by name):
```
SCRIPT:autobow
ENABLED:0
SUMMARY:Bow/crossbow shoot-and-escape loop
ALIAS:ash<dir>|e.g. ashe = autobow east (set target first)
HELP:Weapon type is auto-detected on the first shot:
HELP:...
SCRIPT:autostab
ENABLED:1
...
```

`SCRIPT:` starts a new record. `ENABLED:` is `0` or `1`. `SUMMARY:`,
`ALIAS:` (`name|description`), and `HELP:` may appear zero-to-many times.

## scripts.conf (`bridge/runtime/scripts.conf`, gitignored)

Per-script enable state. Flat key=value file, same conventions as
`startup.conf` and `layout.conf`.

```
# Comments and blank lines are ignored.
autobow=0
autostab=0
coinlooter=1
```

Resolution at brain startup (ADR 0093):

1. `bridge/runtime/scripts.conf` if it exists, else
2. `bridge/launcher/templates/scripts.conf` (shipped template, every
   example script disabled — mirrors ADR 0042's blank-profile pattern),
   else
3. a script absent from both files defaults to **enabled**.

The runtime file is written by the launcher's Scripts view. The brain
only reads. See [docs/scripts.md](scripts.md) for the script-author
contract.

## startup.conf keys (`bridge/runtime/startup.conf`, gitignored)

The `Default` column below is the value shipped in
`bridge/launcher/templates/startup.conf` — the single source of truth for
fresh-install defaults (ADR 0101). `tmux_start.sh` copies the template on
first run when `bridge/runtime/startup.conf` is absent;
`bridge/launcher/launcher.py` parses the same template at import time to
populate its in-memory defaults dict, so the launcher's Options frame and
the cockpit boot path agree.

| Key                  | Default     | Description                              |
|----------------------|-------------|------------------------------------------|
| `connection_mode`    | `mmapper`   | `mmapper` (localhost:4242), `direct` (mume.org:4242, TLS), or `custom` (uses `connection_host`/`connection_port`, plain telnet) |
| `connection_host`    | `localhost` | Host consulted when `connection_mode=custom`. Editable from the launcher Options → Connection → Custom subframe. |
| `connection_port`    | `4242`      | Port consulted when `connection_mode=custom`. Numeric 1–65535, validated by the input subframe. |
| `show_status`        | `1`         | Whether to open the Character (status) pane |
| `show_timers`         | `1`         | Whether to open the timers pane           |
| `show_group`         | `1`         | Whether to open the group pane           |
| `show_comm`          | `1`         | Whether to open the comm pane            |
| `show_ui`            | `1`         | Whether to open the UI pane              |
| `show_dev`           | `0`         | Whether to open the dev pane             |
| `border_<key>`       | (absent)    | Per-pane in-pane border toggle (`border_status`, `border_timers`, `border_group`, `border_comm`, `border_ui`; `dev` is never framed). `1` → on, `0` → off. **Written only when explicitly toggled** (launcher Panes grid or popup Border cell) so an untouched pane stays absent and resolves via the fallback chain. Resolution: `border_<key>=1` → on; absent → fall back to `show_pane_dividers`; that absent too → default on. Reserves border rows via `rc_frame_extra` (see the Layout system). |
| `show_pane_dividers` | (absent)    | **Retired global fallback.** Was the single on/off for the pane-header bar; superseded by per-pane `border_<key>`. No longer seeded fresh or surfaced in the UI, but still honoured as the fallback when a pane has no `border_<key>` (e.g. a carried-over `=0` keeps every untoggled pane's border off). Key name retained for backward compatibility. |
| `frame_corners`      | `auto`      | In-pane frame corner style: `auto` (detect whether the active terminal font covers the quadrant corner glyphs `▛▜▙▟`), `quadrant` (force seamless quadrant corners), or `block` (force plain half-block corners). Resolved at launcher startup by `bridge/launcher/frame_corners.py` into `frame_corners_resolved` in `layout.conf`; see [docs/pane-frame.md](pane-frame.md). |
| `pane_color_status`  | `black`     | Per-pane background colour (name). Resolved to a hex by `PANE_COLORS` in `bridge/launcher/palette.py` and mirrored as a case in `bridge/launcher/open_pane.sh` `_pane_bg_for`. `black` clears the tmux bg override so the terminal default shows through. Unknown values fall back to `black`. |
| `pane_color_timers`   | `red`       | Per-pane background colour for the timers pane. |
| `pane_color_group`   | `green`     | Per-pane background colour for the group pane. |
| `pane_color_comm`    | `blue`      | Per-pane background colour for the comm pane. |
| `pane_color_ui`      | `black`     | Per-pane background colour for the UI pane. |
| `pane_color_dev`     | `grey`      | Per-pane background colour for the dev pane. |
| `profile`            | `default`   | Which file in `ttpp/profiles/` to load; also the tt++ session name |
| `terminal_bg_fallback` | `#000000` | Hex colour used as the host-terminal background when OSC 11 detection fails (WSL2 + Alacritty routes through ConPTY, which never relays the reply; this is the bundled end-user environment). Default `#000000` matches the bundled Alacritty background, so the inter-pane separator, credits canvas, and spotlight outline are invisible against the terminal with no configuration. Validated against `^#[0-9a-fA-F]{6}$` at startup; invalid values silently fall back to `#000000`. Detection wins when it succeeds, so the value only takes effect under non-detecting terminals. |

Toggle panes (with persistence) via `cp -u`, `cp -d`, `cp -m`, `cp -c`, `cp -t`, `cp -g`. (The old global `cp -h` border/header toggle is retired — in-pane borders are now per-pane via `border_<key>`, toggled from the Panes grid's Border column.) Reset right-column heights to shipped defaults via `cp -reset-heights`.

`profile`, `connection_mode`, `connection_host`, and `connection_port` are
read by `ttpp/core/config.tin` at tt++ startup via
`bridge/launcher/read_config.sh`, which materialises the `_profile`,
`_host`, `_port`, and `_ses_cmd` tt++ variables used by the `connect` alias.
`_ses_cmd` is `ses` for mmapper and custom modes and `ssl` for direct mode
(TLS); the custom mode reads `_host` / `_port` from `connection_host` /
`connection_port`.

**Persistence asymmetry between surfaces.** The launcher Options page
batches every edit and writes to `startup.conf` on Back / ESC; visible
effect (pane open/close, pane background tint, connection mode) lands
on the next cockpit start. The in-game popup Panes submenu writes each
toggle / colour selection immediately and re-tints the open pane
on the spot via `tmux select-pane -P bg=…` /
`toggle_pane.sh <pane> --persist`. Both surfaces ultimately write the
same keys.

## Layout system (`bridge/runtime/layout.conf`, gitignored)

Pane dimensions are persisted across restarts and adapt to terminal resizes.
State is stored in `bridge/runtime/layout.conf` (gitignored, recreated on first startup).

### layout.conf keys
| Key              | Default | Description                                            |
|------------------|---------|--------------------------------------------------------|
| `ui_width`       | 33      | Absolute column width of the right pane column. Drag-adjustable. Sole authority for right-column width — no minimum enforced by pane state. |
| `window_cols`    | 0       | Last known terminal width — distinguishes WINCH from border drag. |
| `desired_status` | 6       | Algorithmic target for status pane content rows (excludes title row); drag-persisted. See ADR 0071. |
| `desired_timers`  | 8       | Algorithmic target for timers pane content rows; drag-persisted. |
| `desired_group`  | 6       | Algorithmic target for group pane content rows; drag-persisted. |
| `desired_comm`   | 10      | Algorithmic target for comm pane content rows; drag-persisted. |
| `desired_ui`     | 5       | Algorithmic target for ui pane content rows; drag-persisted. |
| `desired_dev`    | 3       | Algorithmic target for dev pane content rows; drag-persisted. |
| `frame_corners_resolved` | (resolved) | The concrete corner style — `quadrant` or `block` — that the in-pane frame draws, resolved from `startup.conf:frame_corners` by `bridge/launcher/frame_corners.py` (`resolve_and_persist`) at launcher startup and written here in place (append-or-replace, never raises). `auto` runs the font-coverage check (does the active terminal font's own file carry `▛▜▙▟`? → `quadrant`, else `block`); `quadrant` / `block` are taken verbatim. `bridge/panes/pane_frame.py` `corners()` reads this live each draw, so a popup corner-style change (which re-runs `resolve_and_persist`) re-renders every framed pane within one poll tick. `build_initial_layout.sh` only seeds missing keys, so this value survives layout-conf (re)creation. Mirrors the OSC 11 `terminal_bg` lifecycle (ADR 0099). See [docs/pane-frame.md](pane-frame.md). |
| `terminal_bg`    | (probed) | Effective host-terminal background as `#rrggbb`. Written by `bridge/launcher/launcher.py` once at launcher startup: it probes via OSC 11 on `/dev/tty` (before prompt_toolkit takes over the tty) with a ~0.25 s bounded timeout, then writes `_terminal_bg = detected or terminal_bg_fallback` — detection wins when it succeeds, the `startup.conf:terminal_bg_fallback` value (default `#000000`) is used when it does not. WSL2 + Alacritty is the canonical non-detecting environment: Alacritty routes WSL2 through ConPTY, which never relays the OSC 11 reply. The outcome of each probe is logged to `logs/debug.log` as `terminal-bg: detected <hex>` or `terminal-bg: detection failed, using fallback <hex>`. Consumed by `bridge/layout/apply_border_style.sh` to style the inter-pane separator row, by `bridge/panes/pane_frame.py` as the lift source for the **terminal-default** pane's in-pane border (a pane with no `bg` override has no fill to lift, so the border edge is derived from `terminal_bg`; see [docs/pane-frame.md](pane-frame.md)), and by the launcher itself for the credits canvas and the spotlight info-box outline. Not written on the `--no-menu`/`-d`/`-u` paths (launcher is skipped); `apply_border_style.sh` then falls back to `fg=black bg=black`. `build_initial_layout.sh` only seeds missing keys, so this value survives layout-conf (re)creation. |

### Behaviour
- **Initial build** — `bridge/launcher/build_initial_layout.sh` is fired by a one-shot `client-attached` hook registered in `bridge/launcher/tmux_start.sh`. It reads the true terminal width and height from tmux (authoritative only post-attach), then runs the two-phase cold-start algorithm (ADR 0071). **Phase 1 (survivor selection):** while the per-pane effective minimum sum — `sum(MIN_HEIGHT[p] + rc_frame_extra(p))` over requested panes, recomputed each iteration because `rc_frame_extra` depends on which framed panes remain — exceeds `rc_available_rows(N)`, the lowest-priority pane is dropped (drop order: dev → group → timers → comm → status → ui) and the skip is logged to `logs/debug.log`. `startup.conf` is not modified, so a taller terminal on the next start gets the skipped panes back. **Phase 2 (allocation):** allocation runs against the *content* budget — `rc_available_rows(N)` minus every framed survivor's per-pane border reservation (`rc_frame_extra`; see the Right-column budget bullet). The status (Character) pane is reserved first when present: its `desired_status` is set aside (clamped so the other panes keep their mins) before the remaining panes scale linearly between `MIN_HEIGHT[p]` and `desired[p]`; residual content rows drop into the highest-priority survivor **among that remaining set** (ui > status > comm > timers > group > dev). This keeps a tight budget from squeezing the character pane rather than the others (ADR 0137, ADR 0071). Each pane is finally pinned to its content allocation **plus** its border reservation, so the in-pane frame never eats content height. **Phase 3 (creation):** panes are created in visual order via `bridge/launcher/open_pane.sh --batch`, with `bridge/layout/equalize_right_column.sh` run between splits so intermediate panes stay above tmux's split floor. After the input pane is created, `pane-border-status` is set permanently **off** (borders are drawn in-pane now, reserved via `rc_frame_extra` — there is no tmux header row), `bridge/layout/apply_border_style.sh` paints the inter-pane separator row to match `terminal_bg`, then `bridge/layout/apply_desired_heights.sh` pins each pane to its ALLOC. The hook touches `bridge/runtime/.layout_ready` to release `bridge/launcher/wait_for_layout.sh` so tt++ can start, and disarms itself; subsequent attaches skip the build via an idempotency guard (pane-count check). See ADR 0041 and ADR 0071.
- **Right-column budget** — `bridge/layout/right_column_budget.sh` exports per-pane constants and helpers shared by cold-start and runtime open paths. `MIN_HEIGHT` (status=2; timers/group/comm/ui/dev=1) is the per-pane content-row floor. `DEFAULT_DESIRED` (status=6, timers=8, group=6, comm=10, ui=5, dev=3) seeds `desired_<pane>` on first startup and is the reset target for `cp -reset-heights`. `DROP_ORDER` (dev → group → timers → comm → status → ui) and its reverse `PRIORITY_ORDER` drive survivor selection and residual placement. `IS_FRAMED` marks the panes that get an in-pane border (everything except `dev`, a raw tail that is never framed). `rc_frame_extra(p)` returns the per-pane row overhead the in-pane border reserves: **2** (top + bottom) for a framed pane whose border resolves **on**, **0** otherwise. Border resolution is per-pane: `border_<p>=1` → on; when `border_<p>` is absent it falls back to `show_pane_dividers` (the retired global key); when that is also absent it defaults to on. The reservation is carved out of the content budget during allocation and added back when pinning each pane's final tmux height, so the frame never consumes content rows. `rc_available_rows(N)` is the single budget formula — `rows − (N−1) − 2` (inter-pane borders + input area; `pane-border-status` is permanently off, so there is no top-header row) — consumed by `build_initial_layout.sh`, `equalize_right_column.sh`, and `apply_desired_heights.sh` so cold-start and reset paths agree. `rc_max_panes` / `rc_fits_one_more` (count-gate, using legacy `MIN_PER_PANE=2`) remain for the runtime open path in `open_pane.sh`. `rc_target_can_be_split` gates a split against a specific predecessor's body height; on refusal, `open_pane.sh` falls back to `equalize_right_column.sh` and re-checks before exiting 1 (ADR 0072).
- **Right-column heights** — Heights at cold start are set by the algorithm from `desired_<pane>` values; mid-session drags are free (no snap-back) and persist as the new `desired_<pane>` via `on_pane_resize.sh`. WINCH re-applies `desired_<pane>` so the layout responds symmetrically to terminal resizes. `apply_layout.sh` only pins the input row to 1 row.
- **Terminal resize** — `window-resized` hook fires `bridge/layout/on_window_resize.sh`, which re-applies `ui_width` (main pane width), calls `bridge/layout/apply_layout.sh` to re-pin the input row, then calls the local `_reapply_desired_heights` helper (which invokes `apply_desired_heights.sh` when any right-column pane is open). The same hook handles narrow-terminal restore: during a restore the panes are reopened with `open_pane.sh --batch`, equalized between opens via `equalize_right_column.sh`, and finally re-pinned by the trailing `_reapply_desired_heights` call.
- **Border drag** — `MouseDragEnd1Border` binding fires `bridge/layout/on_pane_resize.sh`. The script snapshots `ui_width` and every right-column pane's current content height into the corresponding `desired_<pane>` key in `layout.conf`. A horizontal-only drag (main↔right border) changes no heights, so those writes are no-ops; a vertical drag updates the two neighbours that changed. `bridge/layout/apply_layout.sh` is called afterward to re-pin the input row.
- **Pane-border style** — `bridge/layout/apply_border_style.sh` is the single authority for tmux's `pane-border-style` and `pane-active-border-style`. It reads `terminal_bg` from `layout.conf` and styles both as `fg=<terminal_bg> bg=<terminal_bg>` so the inter-pane separator row blends into the host terminal background; when `terminal_bg` is empty or not a `#rrggbb` literal (only reached on the launcher-skipped `-d` / `-u` / `--no-menu` paths) it falls back to `fg=black bg=black`. Called from `bridge/launcher/build_initial_layout.sh` after `pane-border-status` is set, and from the `headers` branch of `bridge/layout/toggle_pane.sh` whenever the divider is re-enabled. No other script should set `pane-border-style`.
- **Input pane** — always pinned to 1 row on every terminal resize. Never participates in layout calculations.
- **Narrow-terminal collapse** — when `bridge/layout/on_window_resize.sh` detects that the available right-column width falls below `ui_width` it writes `bridge/runtime/.collapsed_panes` (one pane name per line) and kills all right panes. The restore threshold is always `ui_width`, regardless of which panes were open. When the terminal widens back above `ui_width`, the sentinel is read, each listed pane is re-opened in order via `bridge/launcher/open_pane.sh --batch` with `equalize_right_column.sh` between opens, the sentinel is deleted, and `apply_desired_heights.sh` settles the final geometry. `open_pane.sh` exits silently at entry while the sentinel exists, so manual toggle commands (`cp -u`/`-d`/`-c`) are no-ops during the narrow state.
- **Loop prevention** — `bridge/runtime/.layout_lock` is used as a lockfile to prevent `on_window_resize.sh` triggering `on_pane_resize.sh` in a feedback loop.
- **`-f` on the input split, not on right-column splits.** `bridge/launcher/open_pane.sh` uses `split-window -v -f` for the input pane so it becomes a window-level full-width split below the top container. Right-column splits in the no-right-column branch must NOT use `-f`; `-f` there would span across the input row, breaking the layout. See ADR 0029.

## Gitignored runtime files

All runtime-generated files live under `bridge/runtime/` (ADR 0047).
The directory itself is tracked via `bridge/runtime/.gitkeep`; its contents
are covered by a single `.gitignore` block:

```
bridge/runtime/*
!bridge/runtime/.gitkeep
```

Representative files:

```
bridge/runtime/timers.state
bridge/runtime/comm.state
bridge/runtime/comm_filters.conf
bridge/runtime/connection.state
bridge/runtime/status.state
bridge/runtime/layout.conf
bridge/runtime/startup.conf
bridge/runtime/version.cache
bridge/runtime/ping.cache
bridge/runtime/scripts.cache
bridge/runtime/scripts.conf
bridge/runtime/.layout_ready
bridge/runtime/.layout_lock
bridge/runtime/.pane_resize_pid
bridge/runtime/.ping_pid
bridge/runtime/.popup_open
bridge/runtime/.collapsed_panes
bridge/runtime/.return_to_menu
bridge/runtime/.update_preserve/
```

---
Back to [architecture.md](../architecture.md).
