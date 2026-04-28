# ADR 0021 — Use stty for terminal dimensions instead of tput

Date: 2026-04-28
Status: Accepted

## Context

On macOS, `tput cols` returns the termcap default (80) for
`xterm-256color` regardless of the actual terminal width when
called from non-interactive subshells inside the launcher.
GNU ncurses on Linux happens to return the correct value via
fallback paths that BSD ncurses does not implement. Result: the
startup menu and in-game popup rendered against an 80-column
virtual canvas, sitting in the upper-left corner of any wider
terminal.

Verified at runtime via instrumentation: `tput cols` returned 80,
`stty size </dev/tty` returned the correct value, side-by-side
at the same point in the code.

## Decision

Replace all `tput cols` / `tput lines` queries in launcher and
menu code with `term_cols` / `term_lines` helpers in
`bridge/menu_render.sh` that read `stty size </dev/tty`. This
works identically on Linux and macOS; `/dev/tty` always refers to
the controlling terminal regardless of stdout/stderr redirection.

Helpers added next to the rendering primitives, not in a separate
portability namespace, because they are conceptually part of the
same rendering vocabulary as `render_frame` and the colour
constants.

## Consequences

- Centering on macOS works correctly at all terminal widths.
- Linux behaviour is unchanged (the helpers return the same
  values as `tput cols` did before).
- Future code adding terminal-dimension queries must use the
  helpers. `grep -nE 'tput (cols|lines)' bridge/*.sh start.sh`
  should remain empty.

## Rejected alternatives

**Use `</dev/tty` redirection on `tput`.** Tested in the spike
and didn't reliably fix the problem — tput's failure mode varies
between BSD ncurses versions. `stty size` is unambiguous.

**Pass cols/lines as arguments from `_render_main` down through
every helper.** Rejected: invasive refactor for marginal benefit;
helpers in `menu_render.sh` are sourced anyway.
