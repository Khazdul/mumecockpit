# ADR 0039 — cp -X aliases always persist to startup.conf

**Status:** Accepted

## Context

Three toggle paths existed before this change: the in-game popup Options
submenu, the launcher Options page, and the input-pane menu buttons. All three
called `toggle_pane.sh --persist` and wrote `bridge/startup.conf`. A fourth
path — the `cp -u`, `cp -d`, `cp -m`, `cp -c`, `cp -b`, and `cp -h` aliases
in `ttpp/core/system.tin` — called `toggle_pane.sh` *without* `--persist`,
making it runtime-only.

This asymmetry was never a deliberate design goal. It was a historical
artefact from before the popup and menu-button paths existed. Users who
toggled via `cp -X` saw their layout reset on the next cockpit start, with no
indication that the change was not persisted.

## Decision

All six `cp -X` aliases now pass `--persist` to `toggle_pane.sh`. Runtime-only
toggling is no longer reachable from any user-facing surface. Every toggle
path — popup, launcher Options, input-pane menu buttons, and `cp -X` aliases —
is now equivalent and writes to `startup.conf`.

`toggle_pane.sh` retains the `--persist` flag-handling code. A future caller
(e.g. test harness, scripted layout demo) can still opt out of persistence by
omitting the flag, without needing to re-introduce parallel code paths.

## Consequences

- Every toggle, regardless of entry point, writes to `startup.conf`.
  Predictable, consistent behaviour.
- Users can no longer "try out" a layout change without committing it via a
  `cp -X` alias. No caller has been identified that needs the old behaviour;
  the popup/launcher paths were already always persistent.

## Rejected alternatives

- **Keep the asymmetry and document it more loudly.** Rejected — the
  asymmetry is the bug, not the documentation.
- **Add a `cp -X!` runtime-only variant.** Rejected — no demonstrated need;
  adds surface area with no identified use case.
