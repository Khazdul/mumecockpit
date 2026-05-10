# ADR 0024 — Input pane is always-on

## Context

The input pane (`bridge/input_pane.py`) could previously be toggled on and off
via `cp -i`, the launcher Options page, and the in-game popup Options submenu.
The toggle was controlled by a `show_input` key in `bridge/startup.conf`.

This two-state surface created ongoing maintenance cost:

- Mouse/focus bindings (`MouseUp1Pane`, `MouseDragEnd1Pane`) had to be registered
  at pane startup and removed at pane close, because leaving them active with no
  input pane would send focus nowhere.
- `bridge/focus_input.sh` could be invoked by a click when no input pane existed,
  producing a tmux warning that surfaced to the user (exit 1).
- Every script or shell component that needed to interact with the input pane had
  to guard against the possibility that it might not exist.

## Decision

The input pane is an integral, always-on component of the cockpit. It is opened
unconditionally at startup. The following affordances are removed:

- `cp -i` alias in `ttpp/core/system.tin`
- `input)` case in `bridge/toggle_pane.sh`
- "Input pane" row in the in-game popup Options submenu (`bridge/ingame_menu.sh`)
- "Input pane" row in the launcher Options page (`bridge/launcher.sh`)
- `show_input` key from `bridge/startup.conf` creation and `_save_conf` paths

## Consequences

- Mouse-binding lifecycle is simplified: bindings are registered once at
  input-pane startup and never need to be removed during normal operation.
- `focus_input.sh` no longer has a practical failure path where the input pane
  is absent (hardening deferred to the follow-up PR).
- One fewer `startup.conf` key to document and test.
- Existing `startup.conf` files that still contain a stale `show_input=` line
  are harmless — the key is sourced into the shell environment but never used,
  and will be silently dropped on the next `_save_conf` write.

## Alternatives considered

- **Keep `show_input` as a no-op key for backward compat.** Rejected — config
  file keys are a contract. A no-op key implies the value is respected; removing
  it is the honest signal that the option no longer exists.
- **Soft-deprecation with a startup warning.** Rejected — it provides no benefit
  to the user and adds noise to a code path that just became simpler.
