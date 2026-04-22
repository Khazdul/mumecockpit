# 0001 — Constant ping monitor instead of popup-local

**Status:** Accepted
**Date:** 2026-04-22

## Context

The in-game popup needs to show a Link quality indicator (latency plus a
stability label) in its status header. The first implementation
(historical Phase 4a) ran the ping monitor inside the popup process:
spawned on popup open, terminated on popup close. This had two problems:

- The ring buffer had to re-warm on every popup open, so the first few
  seconds always showed "no data yet".
- Closing the popup lost all history, so you could never tell whether a
  disconnect was preceded by degrading link quality.

## Decision

Run a single long-lived ping monitor tied to the tmux session lifecycle,
not the popup. Writes to a shared cache file
(`bridge/ping.cache`) that both the popup and other consumers read on
demand.

- Spawned by `bridge/tmux_start.sh` (and the Continue/Mirror attach paths
  in `bridge/launcher.sh`).
- Single-instance guard via PID file (`bridge/.ping_pid`).
- Self-terminates within ~1 s of the `tmux:mume` session disappearing,
  so no explicit cleanup is needed on `cp -e` or crash.
- Quality label derived from p95−p50 spread over a 60-sample ring
  buffer, so the label adapts to the user's baseline rather than
  judging absolute latency.

Full details in `docs/bridge-services.md`.

## Consequences

- Popup opens instantly with a live quality label, no warm-up.
- History persists across popup open/close and pane toggles.
- One more background process and one more cache file to manage —
  handled by the PID guard and the session-lifecycle tie-in.
- Quality label cannot be tuned per popup session; it's a single
  shared reading.

## Alternatives considered

**Popup-local monitor** (the original approach). Simplest lifecycle
but ring buffer loses history on every close. Rejected after trying it
— the "warming up" gap was visible in normal use.

**No stability label, just raw latency.** Simpler still, but 38 ms
means different things on different connections. A label based on
deviation from the user's own baseline is more informative at no cost
beyond the p95−p50 calculation.
