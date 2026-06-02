# 0128 — Fresh start: scoped session recovery from the launcher

**Status:** Accepted
**Date:** 2026-06-02

## Context

A cockpit layout can become corrupted at runtime — panes swapped, the
MUME/tt++ pane (`mume:cockpit.0`) gone, the input pane in its place. The
trigger is not yet diagnosed; that is separate work.

What makes it more than a transient annoyance is that the corruption *survives
a restart*. The `mume` tmux session stays alive, and the launcher's
existing-session branch offered only `Resume MUME` / `Mirror MUME` — both of
which `tmux attach` to the live session. `build_initial_layout.sh` is guarded
to no-op on re-attach (`PANE_COUNT > 1`), so nothing rebuilds the layout: the
player re-attaches straight back into the broken arrangement. The only escape
was raw `tmux kill-session -t mume` or `wsl --shutdown` — unacceptable for a
player who does not know tmux.

(A clean tt++ exit already disposes of the session via the `PROGRAM TERMINATION`
event's `kill-session`. The wedge is precisely the case where that path is not
reached.)

## Decision

Add a `Fresh start` item to the launcher main frame, shown only when a session
exists and inserted directly below the `Resume`/`Mirror` row. It runs a scoped
`kill-session -t mume` and rebuilds the cockpit via the normal cold-start path.
It is offered **alongside** Resume, not as a replacement.

- **Scoped kill.** `_kill_mume_session()` runs `tmux kill-session -t mume` only
  — never `kill-server`. The belt-and-braces re-check guarantees the session is
  gone before the rebuild.
- **Shared cold-start.** `_cold_start_exec()` (exports `LAUNCHER_COLS` /
  `LAUNCHER_ROWS`, execs `tmux_start.sh`) is used by both the no-session
  `Enter MUME` branch and the Fresh start rebuild, so the two paths cannot
  diverge. `tmux_start.sh` starts the ping monitor; the launcher does not spawn
  it on this path.
- **Inline two-step confirm.** The first Enter arms a confirm and relabels the
  row to a consequence prompt; the highlight is pinned to that row; a second
  Enter confirms; ESC, navigation, or activating another row cancels. When a
  client is attached elsewhere the prompt additionally warns that the session
  may be active in another terminal. The interaction stays on the main frame —
  no frame-stack push.

Blast radius is confined to `bridge/launcher/launcher.py`.

## Consequences

- A player can always recover a wedged cockpit with one menu action — no raw
  tmux, no `wsl --shutdown`.
- The clean-slate guarantee comes from `tmux_start.sh` (kill old session →
  create fresh); Fresh start simply *exposes* that path from the
  existing-session state, where previously only attach was reachable.
- Resume's value is preserved. A closed terminal, dropped SSH, or detach with a
  still-live link reattaches without dropping the connection — which matters in
  PvP. Resume stays the default highlight, so the common case is one Enter and
  unchanged.
- Killing the session is irreversible: the live MUME connection is dropped. The
  two-step confirm and the attached-elsewhere warning are the guard against a
  mis-press.
- This does not fix the underlying layout corruption. Fresh start is recovery,
  not prevention; diagnosing the corruption remains open.

## Alternatives considered

**Remove Resume and always rebuild on entry.** The original instinct. Rejected:
it discards a real resilience feature (reconnect-after-drop, valuable in PvP) to
work around a layout bug. The actual defect is that corruption is sticky with no
escape — a scoped recovery path fixes that directly without sacrificing Resume.

**`tmux kill-server`.** Rejected. The cockpit runs as the named session `mume`
on the user's default tmux server (no dedicated socket), so `kill-server` would
also destroy unrelated tmux sessions the player may have open. `kill-session -t
mume` is the correct scope.

**Self-heal / in-place layout repair on attach.** Rejected for now. The existing
layout scripts cannot reconstruct a corrupted arrangement: `build_initial_layout.sh`
no-ops on re-attach and builds from a single pane, and `apply_layout.sh` governs
right-column dimensions, not pane identity or order. A repair path would be
net-new logic written against an undiagnosed bug — better to ship the guaranteed
escape now and revisit repair only if the corruption is characterised.

**A dedicated confirm overlay frame** (à la `history_delete_confirm`). Rejected:
the inline two-step confirm keeps the whole interaction on the main frame with no
frame-stack push and confines the change to `launcher.py`. A rebuildable session
does not warrant the heavier modal that permanent data deletion does.
