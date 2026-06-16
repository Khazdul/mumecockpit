# 0141 — Game-pane scrollback raised via a tmux bootstrap config

**Status:** Accepted
**Date:** 2026-06-16

## Context

The game pane (pane 0, title `MUME`) is the only raw-tt++ pane. Its
player-visible scrollback is tmux copy-mode ([ADR 0025](0025-page-keys-drive-tmux-copy-mode.md) /
[ADR 0127](0127-game-pane-scroll-keeps-input-focused.md)), **not** tt++'s
`#buffer`. tmux's default `history-limit` is 2000 lines — too short for a long
PvP session, where a player wants to scroll back far past the recent tail.

Two non-obvious tmux facts shape the fix:

- **`history-limit` is read once, at pane creation, and is never resized on a
  live pane.** Verified empirically: setting the option after `new-session`
  leaves the existing pane at 2000; only panes created *afterward* inherit the
  new value.
- **Pane 0 is born from `new-session` itself**, before any post-creation
  `set-option` line in `tmux_start.sh` can run. So whatever sets the limit must
  already be in effect when `new-session` executes.

A first attempt set `set-option -g history-limit 100000` *before* `new-session`.
That failed at runtime: no tmux server exists yet, so the command errored
(`error connecting to .../default`, visible as a startup flash) and the option
was never set. Moving it *after* `new-session` would not help pane 0, which is
already created by then.

## Decision

Ship a minimal config file —
`bridge/launcher/templates/tmux_bootstrap.conf` — containing only:

```
set -g history-limit 100000
```

`tmux_start.sh` reads it via `tmux -f <bootstrap conf> new-session` on **both**
`new-session` invocations (the `-x`/`-y` pre-attach branch and the fallback
branch). Because `-f` is parsed *before* `new-session` creates pane 0, the game
pane inherits `history-limit 100000` at creation. The right-column panes built
later by `build_initial_layout.sh` inherit the same global value.

Two verified facts make this safe:

- `-f` honours `-x`/`-y` — the pre-attach sizing branch still works.
- All subsequent `set-option` lines in `tmux_start.sh` still apply normally; the
  bootstrap conf carries *only* the one option that must exist before pane 0.

## Consequences

- The game pane scrollback now holds 100000 lines; wheel and Page Up scroll back
  far past the old 2000 ceiling. tmux allocates history lazily — the cap is a
  ceiling, not a pre-allocation, so memory grows only with lines actually
  produced.
- Passing `-f` suppresses tmux's default read of `~/.tmux.conf` for this server.
  Acceptable because the cockpit sets every option explicitly and hides tmux from
  the player (see docs/tmux-bindings.md "Philosophy"), but it is a real behaviour
  change for any user with a personal `~/.tmux.conf` — recorded here so it is not
  a future surprise.
- The bootstrap conf is the one tmux option that must exist *before*
  `new-session`; everything else stays as `set-option` lines after it. If a
  future option needs the same pre-creation timing, it belongs in this file.

## Alternatives considered

**`set-option -g history-limit` before `new-session`.** Rejected: no server
exists yet, so the command errors and the option is never set — this was the
original failed attempt.

**The same option after `new-session`.** Rejected: `history-limit` is locked at
pane creation; pane 0 stays at 2000 (verified).

**Rebuild the game pane as a later split** so it inherits the global option.
Rejected: large blast radius, reorders the [ADR 0041](0041-post-attach-layout-build.md)
post-attach layout flow, for no gain over `-f`.

**Raise tt++'s `#config buffer_size` instead.** Rejected: tt++'s buffer is not
the player-visible scrollback ([ADR 0025](0025-page-keys-drive-tmux-copy-mode.md) /
[ADR 0127](0127-game-pane-scroll-keeps-input-focused.md)) and nothing harvests
it; raising it would pay memory for an invisible buffer. `buffer_size` stays at
default until a concrete consumer exists.

## Relation to other ADRs

- **Builds on [ADR 0025](0025-page-keys-drive-tmux-copy-mode.md) /
  [ADR 0127](0127-game-pane-scroll-keeps-input-focused.md)** — tmux copy-mode is
  the canonical game-pane scrollback; this deepens it.
- **Touches the [ADR 0041](0041-post-attach-layout-build.md) startup path** (the
  `new-session` invocations) without changing its post-attach layout-build logic.
