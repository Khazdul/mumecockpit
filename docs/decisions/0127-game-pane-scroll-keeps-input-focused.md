# 0127 — Game-pane scroll keeps input focused; Escape and send exit copy-mode

**Status:** Accepted
**Date:** 2026-06-02

## Context

The game pane (`mume:cockpit.0`, title `MUME`) is the only raw-tt++ pane; its
scrollback is tmux copy-mode (ADR 0025 made tmux copy-mode the canonical
game-pane scrollback). All right-column panes are prompt_toolkit applications
(ADR 0037) whose wheel scroll is handled internally and never enters tmux
copy-mode.

Three paths broke the "input pane is always focused" invariant for the game
pane and could raise tmux's `(goto line)` prompt:

- **Mouse wheel** entered copy-mode via a mouse event, selecting the game pane
  and stealing focus to tt++; typed letters then landed in copy-mode.
- **Sending a command or a forwarded macro key while scrolled** delivered the
  keys into copy-mode instead of tt++.
- **Escape** was the global popup binding, so it could not exit a scroll.

PageUp / PageDown already kept input focused (they enter copy-mode without
selecting the pane) but shared the Escape and send-while-scrolled gaps.

## Decision

Keep tmux copy-mode as the canonical game-pane scrollback (ADR 0025 preserved).
Close the three gaps for the **game pane only**:

1. **Wheel** (`WheelUpPane` / `WheelDownPane` in
   `bridge/launcher/tmux_start.sh`): after the stock wheel action, refocus the
   input pane, gated on `pane_title == MUME`. The game pane stays in copy-mode
   (scroll position and the copy-mode position indicator are preserved); only
   tmux focus returns to input. The `status` no-op gate and all prompt_toolkit
   panes keep byte-for-byte stock behaviour.
2. **Escape** (root binding in `bridge/launcher/tmux_start.sh`):
   context-sensitive. If the game pane is in copy-mode → `send-keys -X cancel`
   (the existing `pane-mode-changed` hook refocuses input on exit, so no
   duplicate refocus); otherwise → the existing `display-popup`.
3. **Command / forwarded-key send** (`_snap_game_pane_to_tail` in
   `bridge/panes/input_pane.py`): a server-gated helper cancels the game pane's
   copy-mode before delivering input, called from `send()` and every
   forwarded-key handler (F-keys/Ctrl, Alt+letter, numpad). No-op at the live
   tail; it lives in the Python input transport, not on the tt++ hot path.

See `docs/tmux-bindings.md` and `docs/input-pane.md` for the binding and
key-forwarding documentation.

## Consequences

- The "input pane is always focused" invariant now holds for the game pane
  across every scroll-entry path (wheel and PageUp), matching what click,
  drag-end, and copy-mode-exit already guaranteed (`focus_input.sh`; ADR 0036).
- Wheel and PageUp scroll states are symmetric: both leave input focused with
  the game pane in copy-mode, and Escape or a command-send exits both
  identically.
- `(goto line)` can no longer appear from typing or sending while scrolled.
- While scrolled, Escape now takes two presses to reach the popup (first exits
  the scroll, second opens the popup). This is intended.
- The game pane's title (`MUME`) is now load-bearing for the wheel and Escape
  bindings — consistent with the right column already identifying panes by
  title rather than index.

## Alternatives considered

- **Un-gate the `pane-mode-changed` hook to refocus on copy-mode *entry*** (in
  place of adding refocus to the wheel binding). Rejected: entry-refocus would
  also fire on drag-start (drags auto-enter copy-mode), refocusing input
  mid-drag and regressing the drag-selection UX that ADR 0036 deliberately
  handles at drag-end.
- **Add the wheel refocus to all panes.** Rejected: the prompt_toolkit panes
  handle wheel internally and never enter copy-mode, so they cannot exhibit the
  focus-steal; intervening on their wheel path would only risk disturbing their
  internal mouse handling.
- **Move game-pane scrollback off tmux copy-mode into tt++ `#buffer` or a
  `#split`-based pager**, so scrolling never steals focus. Rejected: tt++'s
  scrollback scroll-locks (freezes incoming text) and `#split` "bars" are
  paint-only status regions with no scrollback of their own; a
  live-tail-while-scrolling pager would need per-line capture (hot-path work,
  cf. ADR 0050) plus a custom renderer, would collide with the existing
  tmux-pane cockpit layout, and would reverse ADR 0025 for no real gain.

## Relation to other ADRs

- **ADR 0025** (page keys drive tmux copy-mode) — preserved, not superseded;
  this builds on it.
- **ADR 0036** (drag-end sweep) — complementary; `--sweep` owns the drag path
  while this owns wheel / Escape / send.
- **ADR 0037** (right-column prompt_toolkit convergence) — explains why the
  right-column panes are immune to the focus-steal.
