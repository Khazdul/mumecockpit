# 0142 — Live re-apply of input autosuggest (poll, not dispatch)

**Status:** Accepted
**Date:** 2026-06-18

## Context

The inline history autosuggest is gated by `input_autosuggest` in
`startup.conf`. The input pane originally read this key once at startup —
deliberately with no `read_config.sh`, no tt++ `#var`, and no IPC — to keep
the latency-critical keystroke path clean; a change took effect only at the
next cockpit start, and the toggle lived only on the launcher Options frame.

We wanted the toggle exposed from the in-game popup and applied live to the
running pane, consistent with the popup's other toggles (Group / Communication
/ Timers), which apply live.

## Decision

- The in-game popup gets an in-place `[X]`/`[ ]` Input autosuggest row that
  writes `input_autosuggest` to `startup.conf` immediately (the popup's
  immediate-write idiom). The launcher keeps its deferred-on-ESC write and
  next-start semantics.
- The running input pane re-reads `input_autosuggest` live on its existing
  background loop (`_poll_clock`), mtime-gated: stat `startup.conf` each tick,
  re-parse only when the mtime changes, and flip the module flag +
  `invalidate()` only when the boolean actually changes.
- The on/off state becomes a runtime-flippable module flag rather than a
  construction-time branch: `_AfterSpaceAutoSuggest` and `AppendAutoSuggestion`
  are always attached, and the flag is checked first inside `get_suggestion`
  (off → return `None` before the space check and the history scan, so the
  processor stays inert). This avoids mutating `BufferControl.input_processors`
  at runtime.

## Consequences

- The popup toggle applies within ~one poll tick, no restart — matching the
  Group / Communication / Timers panes.
- The launcher stays next-start: it runs pre-tmux, so the pane reads the fresh
  value at its own startup regardless. The launcher (deferred) / popup (live)
  asymmetry mirrors the existing Group / Comm / Timers asymmetry, so it is
  consistent with the established pattern, not a new one.
- The pane's "read config once at startup" contract becomes "read at startup,
  re-read live" — the first config it re-reads live. It stays off the hot path:
  the re-read runs in the event loop between keystrokes (like the clock poll)
  and the flag check is on the render path only; the keystroke → tt++
  forwarding path is untouched. The off state is, if anything, cheaper than a
  naive always-on, because the flag short-circuits before the history scan.

## Alternatives considered (rejected)

- **Dispatch (`cp -*-apply` via `tmux send-keys` → tt++ → reload), as
  readability does.** Rejected: the readability reload runs inside the tt++
  session; the input pane is a separate Python process not reachable that way
  and would still need an inbound channel. The poll matches the display panes,
  is self-contained to the Python side, and needs no new IPC.
- **Mutating `BufferControl.input_processors` live** to add/remove
  `AppendAutoSuggestion` on each toggle. Rejected as fiddly and unnecessary:
  always-attach + flag-gate is simpler and the off-state processor is inert.
- **Keeping the toggle launcher-only (next-start).** Rejected: it would be the
  only popup-reachable toggle without live apply, inconsistent with the
  popup's other toggles.
