# 0025 — Page Keys Drive tmux Copy-Mode

**Status:** Accepted  
**Date:** 2026-04-29

## Context

Two scrollbacks coexisted for the game pane:

- **tmux pane scrollback** — driven by the mouse wheel. Entered via
  `copy-mode -e`; exits automatically when scrolled back to the live tail.
- **tt++ `#buffer` scrollback** — driven by tt++'s built-in page-up / page-down
  macros. Completely independent of the tmux scrollback position.

The input pane previously forwarded `PageUp` and `PageDown` to tt++ via
`tmux send-keys`, which triggered tt++'s `#buffer up` / `#buffer down` macros.
This produced surprising UX: a position scrolled to with the mouse wheel was
not the position that Page Up resumed from, and vice versa. Players using both
input methods had to mentally track two cursors in what appeared to be one pane.

## Decision

The cockpit treats the **tmux pane scrollback as the canonical history** for the
game pane. Page Up / Page Down from the input pane drive tmux copy-mode,
mirroring wheel semantics exactly.

- **Page Up** calls `tmux copy-mode -e -t <game pane>` (idempotent — a no-op
  when already in copy-mode, matching stock wheel-up entry with the auto-exit
  flag) then `send-keys -X page-up`.
- **Page Down** is gated on `#{pane_in_mode}` via `tmux if-shell`. When the
  game pane is not in copy-mode the command is a silent no-op, matching
  wheel-down behaviour at the live tail.

tt++'s `#buffer` scrollback remains internally available but is no longer
surfaced to the player via the Page keys.

## Consequences

- **One scrollback to reason about.** Mouse wheel and Page keys are
  interchangeable — scrolling up with the wheel and then pressing Page Up
  continues from the same position, and vice versa.
- **Exit behaviour composes with the PR 2 `pane-mode-changed` hook.** Any
  Page-Down-past-bottom auto-exit refocuses the input pane identically to a
  wheel-down exit.
- **tt++ buffer commands are unchanged but unexposed.** `#buffer find`,
  `#buffer home`, `#buffer end`, and other tt++-buffer-only commands remain
  functional when invoked manually inside the tt++ session. If keyboard
  shortcuts for buffer navigation (e.g. Ctrl+End / Ctrl+Home → `history-bottom`
  / `history-top` in copy-mode) are ever needed, they would follow the same
  tmux-copy-mode pattern.

## Alternatives considered

**Forward Page keys to tt++ (status quo).** Rejected — produces the
dual-scrollback confusion that motivated this change.

**Drive both scrollbacks in lockstep.** Rejected — there is no API to keep tmux
pane scrollback and tt++ `#buffer` cursors in sync; the complexity outweighs any
benefit.

**Drive only tt++ scrollback for keys, only tmux for wheel, document the
difference.** Rejected — divergent scrollbacks for the same pane is exactly the
bug we are fixing.
