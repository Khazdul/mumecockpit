# 0069 — Launcher rewritten in prompt_toolkit

**Status:** Accepted
**Date:** 2026-05-13

## Context

The pre-tmux launcher (`bridge/launcher/launcher.sh` +
`bridge/launcher/menu_render.sh`, ~1000 lines) was a hand-rolled bash
TUI: responsive shrinking via progressive row-hiding, manual
alt-screen / cursor / mouse-mode handling, and pure ANSI escapes for
every fragment of styling. Every addition — submenus, mouse support,
scrolling, visual polish — added meaningful friction. The
progressive-hide logic carried a known bug that had been parked
pending live terminal observation.

`prompt_toolkit` was already the rendering framework for the four
right-column data panes (ADR 0037) and the in-game popup (ADR 0062).
Same vocabulary, same palette, same event-loop integration. A
planned History submenu (out of scope for this ADR) needs a
frame-stack model that the bash launcher could not accommodate
cleanly.

## Decision

Rewrite the launcher as a `prompt_toolkit` full-screen `Application`
at `bridge/launcher/launcher.py`. Keep `bridge/launcher/launcher.sh`
as a thin wrapper that `exec`s the Python entry, so `start.sh`, the
return-to-menu chain in `tmux_start.sh`, the Windows shortcut
target, and the update-success restart path stay unchanged.

The UI is a frame stack — `main`, `profile`, `profile_create_name`,
`profile_create_choose`, `profile_create_copy_picker`,
`profile_delete_confirm`, `options`, `scripts`, `about`,
`update_running`, `update_result`, `exit_confirm` — routed through
a single `DynamicContainer`. Each frame owns its own `KeyBindings`
filter so navigation, scroll, and ESC behave per-frame. The pattern
mirrors ADR 0062's popup architecture.

The colour palette is extracted to `bridge/launcher/palette.py` and
shared with the in-game popup. Progressive row-hiding is dropped:
the launcher uses a minimum-size gate (cols < 60 or rows < 18 shows
a "Terminal too small" placeholder) plus prompt_toolkit's native
vertical-centring fill above the minimum.

## Consequences

- **Gained.** Native click-to-activate on every selectable row.
  Best-effort hover highlight on terminals that report cell-motion
  mouse events. Visual consistency with the existing
  prompt_toolkit panes. A much shorter path for future additions —
  a new submenu is one container + one bindings filter + one push.
  The previously parked responsive-row-hiding bug is dissolved
  with the new minimum-size gate.
- **Lost.** The DOS-style boxed layout-mockup in the Options page
  (Options is now a flat minimalist list; reorganisation is scoped
  for a future chat). `bridge/launcher/menu_render.sh` deleted —
  nothing else sourced it after the popup migration.
- **Cost.** Python cold-start adds ~150–250 ms to launcher open.
  Acceptable — the launcher is pre-tmux, the user is loading the
  cockpit anyway, and the latency is below the perception
  threshold for a deliberate action.

## Alternatives considered

**Stay in bash, fix the responsive bug, add features
incrementally.** Rejected. The ceiling on bash-script interactivity
(no mouse, no click-to-select, no clean scroll, manual everything)
was already limiting; a History submenu and any future
profile-editor would compound the friction. Same logic as ADR 0062.

**Use `textual` or `rich`.** Rejected for the same reasons as
ADR 0062 — another framework to learn, no integration with the
prompt_toolkit panes already in the stack.

## Relation to other ADRs

- **Builds on ADR 0062** (in-game popup in prompt_toolkit) — same
  frame-stack architecture, same palette translation pattern, same
  thin-wrapper-script approach.
- **Builds on ADR 0037** (right-column prompt_toolkit
  convergence) — extends the framework's reach to pre-tmux UI.
- **Dissolves the parked responsive-row-hiding bug** that was a
  known issue under the bash launcher.
