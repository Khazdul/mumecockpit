# 0041 — Post-attach initial layout build

**Status:** Accepted
**Date:** 2026-05-04

## Context

`bridge/tmux_start.sh` previously read `stty size </dev/tty` before any client
had attached, baked the result into `tmux new-session -x/-y`, and immediately
ran `split-window` / `resize-pane` against those dimensions. This worked
reliably on Alacritty because Alacritty negotiates PTY size before launching
WSL. On other terminals — notably PowerShell/conhost calling
`wsl -- /root/MUME/bridge/launch.sh` — the PTY size has not been communicated
to the kernel by the time bash runs, so `stty size` returns stale or default
`80×24` dimensions. Tmux then scales the pre-built pane tree proportionally
when the real client attaches, producing a distorted layout that only
stabilises after the user manually resizes the window.

`tmux display-message -p '#{window_width}'` is authoritative for terminal
dimensions, but only after at least one client has attached.

The old `sleep 0.3 &&` prefix on the tt++ launch command was a timed barrier
ensuring panes existed before tt++/Lua began writing output. With the layout
build deferred to post-attach, a sentinel-based handshake replaces the timer.

## Decision

Build the initial pane layout *after* the first client attaches:

- `tmux_start.sh` registers a one-shot `client-attached` hook that fires
  `bridge/build_initial_layout.sh`.
- `build_initial_layout.sh` reads the true terminal width via
  `tmux display-message -p '#{window_width}'`, runs all `split-window`,
  `resize-pane`, and `open_pane.sh` calls, applies divider styling, then
  touches `bridge/.layout_ready` and disarms itself with
  `tmux set-hook -u client-attached`.
- Pane 0 runs `bridge/wait_for_layout.sh`, which polls `.layout_ready` at
  50 ms intervals (40 iterations, 2 s total timeout) and then execs `tt++`.
  If the sentinel never appears the cockpit still comes up via the timeout
  fallback — only without the right-column panes.
- `build_initial_layout.sh` is idempotent: if the cockpit already has more
  than one pane (re-attach after detach) it exits immediately without
  touching the layout.
- `tmux new-session` no longer takes `-x`/`-y` arguments; tmux creates the
  session at its default size and the post-attach build sizes everything
  correctly.
- `bridge/.layout_ready` is added to the gitignored runtime files list and
  to the stale-sentinel cleanup at the top of `tmux_start.sh`.

## Consequences

- **Terminal-agnostic startup.** The layout is always built against the
  true attached-client dimensions, regardless of terminal PTY-sync timing.
  Alacritty, Windows Terminal, and conhost all produce a correct layout on
  first paint.
- **Brief single-pane state.** There is a short interval (~50–100 ms) between
  attach and pane creation during which the cockpit shows only pane 0.
  This is visible but acceptable.
- **Idempotent re-attach.** `tmux detach` followed by `tmux attach` does not
  rebuild the layout; the pane-count guard exits immediately.
- **`-d`/`-u` run-only overrides no longer apply to the layout.** These flags
  set env vars that were previously consumed by `tmux_start.sh` in the same
  process. `build_initial_layout.sh` runs in a new process from a tmux hook
  and sources `startup.conf` directly; the in-process overrides are not
  forwarded. The flags remain supported for direct `start.sh` invocations
  but now affect only the session command, not the pane layout.

## Alternatives considered

**(a) Wait for a stable `stty size` pre-attach.** Polling or sleeping until
`stty size` returns non-default dimensions. Rejected: the settle time is
terminal-dependent and unknowable; any fixed delay is a guess that fails on
slow or exotic terminals.

**(b) Use `on_window_resize.sh` as a corrective pass post-attach.** Let the
layout be built wrong, then correct it when the resize event fires. Rejected:
this patches the symptom rather than the root cause; the corrective resize
would be visible as a flicker and would misfire on terminals that do not
trigger a resize event.

**(c) Keep `-x/-y` and refresh after attach.** Keep the pre-attach build but
add a post-attach correction. Rejected: the same fundamental race — `stty size`
is not authoritative pre-attach — causes the initial build to be wrong.
Correcting it post-attach adds complexity without eliminating the root problem.
