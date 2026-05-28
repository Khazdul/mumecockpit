# ADR 0114 — display-popup forwards wheel events; popup wheel-scroll wired

**Status:** Accepted

Supersedes the wheel-limitation half of [ADR 0062](0062-popup-menu-prompt-toolkit.md).

## Context

[ADR 0062](0062-popup-menu-prompt-toolkit.md) recorded a "Mouse wheel
does not scroll within the popup" limitation and reasoned that tmux
`display-popup` forwards only click events to the popup application,
not wheel events. Two follow-on workarounds — a global `WheelUpPane` /
`WheelDownPane` rebind, and a trap-based dynamic rebind around the
popup's lifetime — were rejected on cost-benefit grounds because they
solved the wrong problem (forcing tmux to forward what was claimed not
to be forwarded).

Two later observations are incompatible with that claim:

1. The in-game profile editor ([ADR 0110](0110-popup-profile-editor-snapshot-apply.md))
   runs inside the same `display-popup` and scrolls with the mouse
   wheel — the buffer wheel-scroll path is the launcher-shared one
   from `bridge/launcher/profile_editor.py`, unmodified.
2. Click-to-select works across every popup frame today (rows, panes
   grid, scrollbar gutter, statistics tables). prompt_toolkit only
   receives mouse events when the host terminal is in a mouse
   reporting mode and the surrounding process forwards them — both
   conditions are clearly met.

Together those mean `display-popup` already delivers the full
mouse-event stream — clicks, motion, **and wheel** — into the popup's
`prompt_toolkit` application. ADR 0062's limitation does not hold
under the shipped foot / WSLg deployment ([ADR 0104](0104-windows-deployment-foot-wslg.md)).

We don't have a confident root cause for the original wrong reading.
Likely candidates are that the popup `Application` was constructed
without `mouse_support=True` at the time, or a different host
terminal / tmux configuration was in use when the conclusion was
reached. The honest record is: the empirical evidence at the time
pointed one way, the empirical evidence today points the other way,
and the workarounds the original ADR rejected are now moot because
no rebind is needed.

## Decision

Wire mouse-wheel scroll on the popup's scrolling frames — Scripts,
Readability, and Statistics — using the same wheel model the launcher
already documents for its Scripts and Readability pages
([docs/launcher.md](../launcher.md#options_scripts-frame)):

- **Wheel over a list row, list scrollbar, or the list-column
  spacer / Back row** — moves the cursor by **1 row per notch**, the
  same step a single arrow key would take. Matches the launcher's
  `_scripts_row_handler` / `_readability_row_handler` wheel branches.
- **Wheel over a detail panel cell, the detail scrollbar, or the
  title / footer chrome** — scrolls the detail panel by **3 rows per
  notch**. Title and footer forward wheel to the detail surface so
  the chrome is never a dead zone, per the
  [Full-frame mouse hookup](0062-popup-menu-prompt-toolkit.md#implementation-notes-worth-preserving)
  rule ADR 0062 already records.
- **Wheel over a Statistics table** (KILLS / PvPs / ALLIES /
  ACHIEVEMENTS) — scrolls that table by 1 row per notch and sets
  keyboard focus to it. Mirrors the click-sets-focus behaviour
  already on the same tables, so wheel scrolling always tracks the
  table the user is interacting with.

The chrome-forwarding hookup is wired identically across the three
frames so the surface feels uniform: every cell of every row has a
wheel-aware mouse handler, with the cursor decoupled from the
viewport (next cursor-moving keystroke pulls the viewport back).

The rejected alternatives in ADR 0062 (global `WheelUpPane` rebind,
trap-based dynamic rebind, etc.) are moot — they were workarounds for
a constraint that does not exist in the current setup. No tmux
configuration change is needed.

## Consequences

- **Gained.** Wheel scroll on every scrollable popup surface,
  matching the launcher and the rest of the cockpit's prompt_toolkit
  panes. The Scripts and Readability detail panels and the
  Statistics tables now scroll without keyboard activation; the
  launcher and popup are no longer asymmetric on this.
- **Lost.** None — wheel events were already being delivered, just
  not consumed.
- **Cost.** None at runtime. Per-cell mouse handlers were already
  the norm for click-to-select; adding the `SCROLL_UP` / `SCROLL_DOWN`
  branches is a few lines per handler and uses the same dispatch.
- **Failure mode if the limitation ever returns** (different terminal,
  different tmux build, different mouse mode): the wheel handlers
  simply receive no events, and keyboard scroll (`↑` / `↓` /
  `PgUp` / `PgDn`) remains the documented fallback — the same path
  ADR 0062 already specified. No regression.

## Relation to other ADRs

- **Supersedes the wheel-limitation half of [ADR 0062](0062-popup-menu-prompt-toolkit.md).**
  The "Limitation: Mouse wheel does not scroll within the popup"
  bullet and the two rejected wheel workarounds no longer describe
  shipped behaviour. The rest of ADR 0062 (the popup-as-prompt_toolkit
  decision, the frame-stack model, the `eager=True` ESC pattern, the
  full-frame mouse hookup rule) is unchanged and still in force.
- **Builds on [ADR 0110](0110-popup-profile-editor-snapshot-apply.md).**
  The profile editor's wheel-scroll path running inside `display-popup`
  is what proved the limitation no longer held.
- **Mirrors [ADR 0069](0069-launcher-prompt-toolkit.md).** The popup
  wheel model is the launcher's — same 1-row / 3-row steps, same
  chrome-forwarding rule, same cursor / viewport decoupling.
