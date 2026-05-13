# Bridge Services

Background services and persisted configuration files in `bridge/`. Touch
this file when changing the version check, self-update flow, ping monitor,
`scripts.cache` format, `startup.conf` keys, or layout persistence.

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

Written by `brain.lua` at every client startup (inside `load_scripts()` after
`_register_cockpit_help()`). Parsed by the Scripts page in `bridge/launcher/launcher.sh`.

Format (line-prefixed, one block per script, alphabetical by alias):
```
SCRIPT:autostab
SUMMARY:backstab/escape loop
HELP:Usage: as<dir>
HELP:...
SCRIPT:autobow
...
```

## startup.conf keys (`bridge/runtime/startup.conf`, gitignored)

| Key               | Default    | Description                              |
|-------------------|------------|------------------------------------------|
| `connection_mode` | `mmapper`  | `mmapper` (localhost:4242) or `direct` (mume.org:4242) |
| `show_ui`         | `1`        | Whether to open the UI pane              |
| `show_dev`        | `0`        | Whether to open the dev pane             |
| `show_status`     | `0`        | Whether to open the status pane          |
| `show_pane_dividers` | `1`     | Whether the pane-header bar (labels above each right-column pane) is visible at startup. `cp -h` persists the new state via `toggle_pane.sh headers --persist`. Key name retained for backward compatibility. |
| `profile`         | `default`  | Which file in `ttpp/profiles/` to load; also the tt++ session name |

Toggle panes (with persistence) via `cp -u`, `cp -d`, `cp -m`, `cp -c`, `cp -b`, `cp -h`.

`profile` and `connection_mode` are read by `ttpp/core/config.tin` at tt++
startup via `bridge/launcher/read_config.sh`, which materialises the `_profile`,
`_host`, `_port`, and `_ses_cmd` tt++ variables used by the `connect` alias.
`_ses_cmd` is `ses` for mmapper mode and `ssl` for direct mode (TLS).

## Layout system (`bridge/runtime/layout.conf`, gitignored)

Pane dimensions are persisted across restarts and adapt to terminal resizes.
State is stored in `bridge/runtime/layout.conf` (gitignored, recreated on first startup).

### layout.conf keys
| Key             | Default | Description                                            |
|-----------------|---------|--------------------------------------------------------|
| `ui_width`      | 33      | Absolute column width of the right pane column. Drag-adjustable. Sole authority for right-column width — no minimum enforced by pane state. |
| `window_cols`   | 0       | Last known terminal width — distinguishes WINCH from border drag. |

### Behaviour
- **Initial build** — `bridge/launcher/build_initial_layout.sh` is fired by a one-shot `client-attached` hook registered in `bridge/launcher/tmux_start.sh`. It reads the true terminal width and height from tmux (authoritative only post-attach), then runs a pre-flight skip pass: panes whose count exceeds the right-column row budget are dropped in priority order (lowest first: dev → group → buffs → comm → status → ui) and the skip is logged to `logs/debug.log`. `startup.conf` is not modified, so a wider terminal on the next start gets the skipped panes back. Survivors are created uniformly via `bridge/launcher/open_pane.sh`. After `input`, a single equalize pass divides remaining rows evenly across the right-column panes (residual goes to the last pane). The hook then touches `bridge/runtime/.layout_ready` to release `bridge/launcher/wait_for_layout.sh` so tt++ can start, applies divider styling, and disarms itself; subsequent attaches skip the build via an idempotency guard (pane-count check). See ADR 0041 and ADR 0055.
- **Right-column budget** — `bridge/layout/right_column_budget.sh` exports `rc_count`, `rc_window_height`, `rc_max_panes`, and `rc_fits_one_more` (constants `MIN_PER_PANE=2`, `TITLE_OVERHEAD=1`, `INPUT_RESERVE=1`). The cold-start skip and the runtime open gate share this helper. `bridge/launcher/open_pane.sh` consults `rc_fits_one_more` for every right-column TYPE (`status|buffs|group|comm|ui|dev`) and refuses the split with a `logs/ui.log` warning when the budget would be exceeded — preventing tmux's "no space" recovery from displacing the input row.
- **Right-column heights** — Right-column pane heights are tmux-managed and freely resizable. `apply_layout.sh` does not set or restore any right-column height; it only pins the input row to 1 row.
- **Terminal resize** — `window-resized` hook fires `bridge/layout/on_window_resize.sh`, which re-applies `ui_width` (main pane width) and then calls `bridge/layout/apply_layout.sh` to re-pin the input row.
- **Border drag** — `MouseDragEnd1Border` binding fires `bridge/layout/on_pane_resize.sh`, which saves the new `ui_width` to `layout.conf`. Vertical (height) drags are not detected and write nothing to `layout.conf`. `bridge/layout/apply_layout.sh` is called afterward to re-pin the input row.
- **Input pane** — always pinned to 1 row on every terminal resize. Never participates in layout calculations.
- **Narrow-terminal collapse** — when `bridge/layout/on_window_resize.sh` detects that the available right-column width falls below `ui_width` it writes `bridge/runtime/.collapsed_panes` (one pane name per line) and kills all right panes. The restore threshold is always `ui_width`, regardless of which panes were open. When the terminal widens back above `ui_width`, the sentinel is read, each listed pane is re-opened in order via `bridge/launcher/open_pane.sh`, and the sentinel is deleted. `open_pane.sh` exits silently at entry while the sentinel exists, so manual toggle commands (`cp -u`/`-d`/`-c`) are no-ops during the narrow state.
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
bridge/runtime/buffs.state
bridge/runtime/comm.state
bridge/runtime/comm_filters.conf
bridge/runtime/connection.state
bridge/runtime/status.state
bridge/runtime/layout.conf
bridge/runtime/startup.conf
bridge/runtime/version.cache
bridge/runtime/ping.cache
bridge/runtime/scripts.cache
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
