# ADR 0038 — Drop the 29-column right-column width floor

## Status

Accepted

**Supersedes 0031** (the `RIGHT_FLOOR_WITH_STATUS = 29` constant and status
branch in the menu-visibility formula are removed). The renderer-adaptive part
of ADR 0023 stands; only the bridge-layer floor is no longer in force.

## Context

The 29-column floor existed because the status pane renderer was authored
against a fixed width. ADR 0023 made the renderer fully adaptive (it reads
`shutil.get_terminal_size().columns` on every frame and distributes width
proportionally), but left the bridge-layer floor at 29 in three places:

- `bridge/apply_layout.sh` — auto-widened the right column to 29 when status
  opened into a narrower column.
- `bridge/on_pane_resize.sh` — clamped `ui_width` to ≥ 29 on border drag
  while status was open.
- `bridge/on_window_resize.sh` — used 29 as `RIGHT_FLOOR` (collapse and
  restore threshold) when status was present; same value in the post-restore
  re-derive.
- `bridge/input_pane.py` — used `RIGHT_FLOOR_WITH_STATUS = 29` as the
  menu-visibility threshold when `show_status` was set.

This caused unintuitive drag behaviour: the user drags the border left, the
right column snaps back to 29. Opening status on a narrow column silently
moved the border. The collapse threshold was asymmetric — two different floors
depending on which panes happened to be open, making the threshold hard to
reason about.

## Decision

`ui_width` from `bridge/layout.conf` is the sole authority for right-column
width. No clamp on drag, no auto-widen on status open, no status-branch in the
narrow-terminal collapse or restore thresholds. The input-pane menu visibility
formula uses the same single threshold.

Specifically:

- `apply_layout.sh` — width floor block removed. Only the input-row pin remains.
- `on_pane_resize.sh` — `HAS_STATUS` lookup and ≥ 29 clamp removed.
- `on_window_resize.sh` — `RIGHT_FLOOR` is always `$ui_width`; `HAS_STATUS`
  lookup removed; restore path uses `RESTORE_FLOOR=$ui_width` unconditionally.
- `input_pane.py` — `RIGHT_FLOOR_WITH_STATUS` constant removed; `_menu_visible()`
  simplified to `(cols - MAIN_MIN - 1) >= _menu_ui_width`. `_menu_show_status`
  and its polling are retained (still drives the CHAR button's on/off state).

## Consequences

- The user can drag the right column to any width; status renders adaptively
  (content chopping accepted per ADR 0023).
- Opening or closing the status pane never moves the border.
- The narrow-terminal collapse threshold is a pure function of `ui_width`,
  regardless of which panes are open.
- The input-pane menu hides and shows on the same single threshold as the
  right column collapse.

## Rejected alternatives

**Keep 29 only as the collapse threshold (not for drag)** — asymmetric: drag
is unclamped but collapse still has a status-sensitive floor. Hard to reason
about; the user's experience of "it collapses at different widths depending on
status" remains.

**Drop collapse entirely** — loses the safety net that prevents unusable
layouts on very narrow terminals. The collapse/restore path is retained; only
the status-branch within it is removed.
