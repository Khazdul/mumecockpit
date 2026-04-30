# ADR 0031 — Input-pane menu visibility threshold (formula duplication)

## Status

Accepted

## Context

`bridge/on_window_resize.sh` is the authoritative source for the right-column
collapse formula:

```
available_right = window_cols - MAIN_MIN - 1
floor           = 29 if status pane is open, else ui_width
collapse        = available_right < floor
```

PR 2 adds visibility gating to the input-pane menu bar so it hides in the same
gesture that collapses the right panes. This requires evaluating the same
formula inside `bridge/input_pane.py`, creating a third site (alongside
`on_window_resize.sh` and `bridge/apply_layout.sh`) that encodes the
right-column layout logic.

## Decision

Duplicate the formula and its constants (`MAIN_MIN`, `RIGHT_FLOOR_WITH_STATUS`)
directly in `bridge/input_pane.py`. Read the inputs (`startup.conf` for
`show_status`, `layout.conf` for `ui_width`) from the existing file-based
state that `on_window_resize.sh` already writes, rather than introducing a
new signal or state protocol.

## Trade-offs

**Drift risk** — constants at three sites can diverge. Mitigated by:
- The formula is short (one line, two constants).
- Inputs are file-based (`startup.conf`, `layout.conf`) so the authoritative
  script and the Python consumer read the same ground truth.
- A comment in `input_pane.py` points at `on_window_resize.sh` and this ADR.

**No IPC complexity** — avoiding a dedicated state file or signal protocol
keeps the bridge architecture simple. A new file would add a write path,
a race window during rapid resizes, and another polling entry.

## Rejected alternatives

**Sentinel file (`bridge/.collapsed_panes`)** — written by `on_window_resize.sh`
when right panes are collapsed. Rejected: the sentinel is absent when no right
panes are open, so the menu would persist visible in that edge case even when
the terminal is too narrow.

**Dedicated state file written by `on_window_resize.sh`** — e.g.
`bridge/.menu_visible`. Rejected: adds an extra write path, a race window
during rapid resizes, and another polling entry for a one-bit value that can
be derived from data already polled.

**Helper script (`bridge/menu_visible.sh`) shelled out from Python** — would
centralise the logic in one place. Rejected: spawns a subprocess on every
resize redraw check, adding latency and process overhead for a trivial
calculation.

## Constants

```python
# bridge/input_pane.py
MAIN_MIN                = 30   # duplicates on_window_resize.sh MAIN_MIN
RIGHT_FLOOR_WITH_STATUS = 29   # duplicates on_window_resize.sh RIGHT_FLOOR (status branch)
```

`ui_width` is not a constant — it is read at runtime from `bridge/layout.conf`
(polled every 250 ms), the same file `on_window_resize.sh` sources.
