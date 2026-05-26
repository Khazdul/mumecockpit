# 0105 — Cross-relaunch frame restoration via a resume-hint file

**Status:** Accepted
**Date:** 2026-05-26

## Context

ADR 0104 established the foot relaunch flow: the launcher's Terminal Settings
Apply action rewrites foot.ini, writes the relaunch sentinel, and exits; the
supervisor finds the sentinel and relaunches foot with the new configuration.

The fresh launcher is a new process — it starts on the main menu by default and
has no memory of the pre-Apply UI state. For Apply to feel seamless rather than
dumping the user back at the top of the menu, the launcher must return to the
Terminal Settings frame with the cursor where it was. That UI state has to be
persisted across the process restart.

The relaunch sentinel cannot carry it. The supervisor consumes and **removes**
the sentinel before relaunching foot — that removal is precisely what prevents
an infinite relaunch loop (ADR 0104). By the time the fresh launcher runs, the
sentinel no longer exists, so the launcher can never read it.

## Decision

A second, separate one-shot file — `bridge/runtime/.launcher_resume` — carries
the post-relaunch UI state. The launcher writes it during Apply, distinct from
the relaunch sentinel. The fresh launcher reads it early in startup and deletes
it immediately (one-shot, deleted before acting so a crash mid-startup cannot
re-trigger), then rebuilds the frame stack and restores the cursor.

The file is `key=value` lines — `frame` and `cursor` — matching the project's
other `bridge/runtime/` config-file format.

Two files, two consumers, two lifecycles, deliberately not merged: the relaunch
sentinel is the supervisor's signal (loop or exit); the resume-hint is the fresh
launcher's signal (which frame to open). This mirrors the existing
`.return_to_menu` one-shot — written by the in-game popup, consumed by
`tmux_start.sh` — an established pattern for cross-restart UI intent.

Restoration is gated on `MUME_TERMINAL=foot-managed`: a resume-hint present on a
non-managed launch is ignored and discarded.

## Consequences

- Apply returns the user to the Terminal Settings frame with the cursor
  restored; the relaunch reads as a brief flicker rather than a context loss.
- One more `bridge/runtime/` one-shot to reason about. It is consumed and
  deleted on the next launcher startup; a stale file at worst causes one
  unexpected landing on Terminal Settings, which is harmless.
- The mechanism is generic — `frame` + `cursor`. Later Terminal Settings
  additions (colour, padding, terminal-background subframes) can reuse it
  without a new mechanism.

## Alternatives considered

**Carry the resume payload in the relaunch sentinel.** Rejected: the supervisor
removes the sentinel before the fresh launcher runs, so the launcher would never
see it. Having the supervisor leave the sentinel for the launcher to delete
instead would reintroduce the infinite-relaunch risk that the supervisor's
remove-on-consume behaviour exists to prevent.

**Thread the resume state through the supervisor** (environment variable or
argument). Rejected: the supervisor is deliberately a thin lifecycle owner with
no knowledge of launcher UI state. Passing UI state through it couples two
layers that are currently cleanly separated.

**Persist the UI state in `startup.conf`.** Rejected: `startup.conf` is durable
user configuration. A transient "where was the cursor 200 ms ago" intent does
not belong there and would need explicit clearing on every normal startup.

## Relation to other ADRs

- Builds on **ADR 0104** — the foot relaunch flow whose seam this ADR smooths.
- Uses the same one-shot cross-restart sentinel pattern as the `.return_to_menu`
  mechanism in the launcher / popup exec-chain.
