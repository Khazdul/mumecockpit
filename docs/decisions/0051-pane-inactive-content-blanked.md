# 0051 — Right-column data panes blank content when run is inactive

## Status

Accepted.

## Decision

The four right-column data panes — `status`, `buffs`, `group`, `comm` —
blank their **content area** when no MUME run is active. A run is considered
active iff `bridge/runtime/connection.state` exists. When the file is absent
every `FormattedTextControl` text provider returns `[("", "")]` and every
overflow-indicator `ConditionalContainer` is gated off via the same flag.

Pane structure (tmux borders, `cp -h` header status, sizes, splits) is
**unchanged** in either state. The off-state is a pure content-rendering
change.

The signal is polled by each pane's existing asyncio tick (50 ms / 100 ms /
100 ms / 250 ms for status / buffs / group / comm). On each poll the pane
re-checks `os.path.exists(CONNECTION_STATE_PATH)`; on transition it updates
`_run_active` and calls `app.invalidate()`.

## Why `connection.state` existence

`bridge/runtime/connection.state` is already written and cleared by
`mark_mume_connected()` and `mark_mume_disconnected()` in
`lua/brain/connection.lua`. Those two transitions are the same beat that
emits the `"X logged in."` and `"X logged out."` `system_ui` lines. Reusing
the existing file means:

- No new state-file plumbing.
- The light-up / dark-down moment is byte-for-byte aligned with the UI-pane
  notification the user already sees.
- The `cp -r` mid-run resume gap (where `connection.state` was being cleared
  unconditionally at brain startup) is closed by the companion fix in
  `lua/core/run_log.lua`, which calls `_write_connection_state()` after
  resume.

## Why content-only, not pane chrome

Pane structure is owned by tmux and `bridge/launcher/apply_layout.sh`.
Toggling the pane (open/close, resize, splits) on connection state would
conflict with `cp -h` header logic, the user's pane-toggle preferences in
`startup.conf`, and the resize/drag handlers. Keeping chrome stable and
blanking only the content area sidesteps all of that.

## Rejected alternatives

- **Separate `bridge/runtime/run.state` file** — redundant. We would need a
  new writer beat in Lua plus another atomic write per connection
  transition. `connection.state` is already authoritative for that beat.
- **Lua-side `run_indicator` module writing a fresh signal file** — extra
  plumbing for no behavioural gain. The existing connect/disconnect
  transitions are exactly the moments we want to gate on.
- **Toggling pane chrome (height → 0 or close on disconnect)** — fights
  `cp -h`, `apply_layout.sh`, and the user's persisted toggle preferences.
  Transient pane closing on every disconnect is also visually jarring and
  changes geometry unrelated to the run.

## Implementation notes

- Each pane defines a module-level `CONNECTION_STATE_PATH` constant and a
  `_run_active = False` flag.
- The poll loop checks `os.path.exists(CONNECTION_STATE_PATH)` on every
  tick (alongside the existing `mtime` check on the pane's own state file)
  and invalidates the app on transition.
- Every `FormattedTextControl` text provider in the file is prefixed with
  `if not _run_active: return [("", "")]`.
- Every overflow-indicator `ConditionalContainer` filter is rewritten as
  `Condition(lambda: _run_active and <existing predicate>)`.

## Companion fix

`lua/core/run_log.lua` now calls `_write_connection_state()` at the end of
its cp -r mid-run resume block. Without that, `connection.state` would
remain absent for the rest of the resumed run (because brain.lua's
`_clear_connection_state()` runs unconditionally at startup) and the panes
would stay dark.

---
Back to [architecture.md](../architecture.md).
