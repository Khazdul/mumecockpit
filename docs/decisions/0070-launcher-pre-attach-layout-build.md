# 0070 — Launcher provides dimensions for pre-attach layout build

**Status:** Accepted. Supplements ADR 0041 (does not supersede).
**Date:** 2026-05-13

## Context

ADR 0041 moved the cockpit's initial layout build from pre-attach
to post-attach because `stty size` was unreliable in cold
WSL/conhost contexts — the PTY size had not been negotiated by the
time bash ran. The trade-off ADR 0041 accepted was a visible
cascade of pane splits on first paint, described as "acceptable".

With the prompt_toolkit launcher (ADR 0069) now running first in
the cold-start path, terminal dimensions are known reliably
*before* tmux is touched: prompt_toolkit just rendered a
full-screen UI against them. The visible split cascade can
therefore be eliminated for the launcher path. The `--no-menu`
and Windows-shortcut paths still face ADR 0041's PTY-sync problem;
their post-attach build remains the only safe option.

## Decision

Two-mode initial layout build, branched on a new env-var
contract.

- `bridge/launcher/launcher.py` reads `app.output.get_size()` and
  sets `LAUNCHER_COLS` and `LAUNCHER_ROWS` in the environment
  before `exec`ing `tmux_start.sh` on the Enter-game cold-start
  path.
- `bridge/launcher/tmux_start.sh` branches on those vars. When
  both are present: `tmux new-session -d -x $LAUNCHER_COLS -y
  $LAUNCHER_ROWS …`, run `build_initial_layout.sh` synchronously
  against the detached session, then `tmux attach`. The user sees
  one frame transition from launcher to a fully-built cockpit.
  When the vars are absent: register the one-shot
  `client-attached` hook for the post-attach build (ADR 0041's
  path).
- `bridge/launcher/build_initial_layout.sh` prefers the env vars
  when present and falls back to
  `tmux display-message -p '#{window_width}' / '#{window_height}'`
  otherwise. All other logic (idempotency guard via `PANE_COUNT
  > 1`, divider styling, sentinel touch on
  `bridge/runtime/.layout_ready`) is unchanged.

## Consequences

- **Gained.** Invisible layout build from the launcher; cockpit
  appears fully-formed on first paint.
- **Unchanged.** Resume, Mirror, `--no-menu`, Windows shortcut,
  update-restart, return-to-menu — all behave as before. The
  `client-attached` hook fallback continues to handle every case
  where the env vars are not provided.
- **New contract.** `LAUNCHER_COLS` and `LAUNCHER_ROWS` are now
  part of the launcher → `tmux_start.sh` handoff. Documented in
  `docs/launcher.md`.

## Alternatives considered

**Always build pre-attach, derive dimensions from `stty size` when
the env vars are absent.** Rejected — directly reintroduces the
failure mode ADR 0041 documented. Cold WSL/conhost contexts would
regress.

**Push dimension passing through `start.sh` so `--no-menu` also
benefits.** Rejected for the same reason — `start.sh` has no
equivalent of prompt_toolkit's reliable dimension probe, so it
would still need a fallback path. The two-mode split keeps the
fast path fast and the safe path safe.

## Relation to other ADRs

- **Supplements ADR 0041** by relaxing its trade-off for the path
  where dimensions are known reliably. The post-attach hook
  remains the binding contract for every other caller.
- **Depends on ADR 0069** — the dimension probe assumes the
  launcher is a prompt_toolkit Application.
