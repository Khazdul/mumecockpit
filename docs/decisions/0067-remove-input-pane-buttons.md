# 0067 — Remove input-pane menu buttons; clock-only right strip

**Status:** Accepted
**Date:** 2026-05-13

## Context

The input pane's right end carried a 31-column strip with five
clickable pane-toggle buttons (CHR / BUF / GRP / COM / UI) plus a
day/night clock. The buttons each fired
`bridge/layout/toggle_pane.sh <pane> --persist` on mouse-down and
reflected the persisted `show_*` state from
`bridge/runtime/startup.conf`, polled every 250 ms by mtime.

The same five pane toggles are also reachable from two other
surfaces: the in-game popup Options submenu and the `cp -X` family
of aliases (`cp -u`, `cp -d`, `cp -m`, `cp -c`, `cp -b`, `cp -g`,
`cp -h`). Both are discoverable: popup is one ESC away from the game
pane; `cp -h` lists all `cp -X` flags. The button strip was a third
parallel toggle surface.

The strip carried real implementation cost:

- A `ConditionalContainer` filter and the visibility formula
  `cols - MAIN_MIN - 1 >= ui_width` — duplicated from
  `bridge/layout/on_window_resize.sh` (the duplication trade-off was
  documented in [ADR 0031](0031-input-menu-width-threshold.md), and
  the width-floor cleanup in
  [ADR 0038](0038-drop-right-column-width-floor.md) trimmed it
  further but did not eliminate it).
- Two extra mtime poll paths in `_poll_menu` reading
  `startup.conf` and `layout.conf`.
- Five button click handlers, a handler factory, four button colour
  constants, and the button-rendering loop in `_menu_text`.
- The visibility gate hid the entire strip — including the
  clock — at narrow terminal widths.

## Decision

**Remove the five buttons.** The right strip is reduced to the
clock alone, occupying 7 columns (1-col gutter + 5-col time text +
1-col day/night icon). The input buffer extends to fill all width
up to the gutter.

The clock is now rendered at every terminal width. The
`ConditionalContainer` visibility gate is removed; the layout
becomes:

```python
layout = Layout(
    HSplit([
        VSplit([input_window, clock_window]),
    ])
)
```

The `_poll_menu` task is renamed `_poll_clock` and reads only
`status.state`. The `startup.conf` and `layout.conf` mtime branches
are deleted along with the `_menu_show_*` and `_menu_ui_width`
globals.

The `_clock_tick` boundary-aligned 1 Hz invalidate task is
unchanged.

## Trade-offs

**Lost:**

- At-a-glance pane-state colour cue. Users who relied on the ON/OFF
  button colours to confirm which panes are open lose that signal.
  The popup Options submenu still shows current state on open, and
  the panes themselves are visible feedback.
- One-click mouse pane toggling. Toggling a pane now requires
  either ESC → Options → <pane>, or typing `cp -X`.

**Gained:**

- Simpler `input_pane.py`: removes ~110 lines covering the button
  factory, handlers, colour constants, the conditional container,
  the button-rendering loop, and two of the three mtime poll
  branches.
- One fewer formula duplicated across the codebase. The
  `MAIN_MIN` / `ui_width` floor formula previously embedded in
  `input_pane.py` is no longer present there. The drift-risk
  concern recorded in [ADR 0031](0031-input-menu-width-threshold.md)
  is lifted for this file. (The same formula remains in
  `on_window_resize.sh`, where it is load-bearing for the right-
  column collapse behaviour — that copy was always the
  authoritative one.)
- The clock is now visible at every terminal width, including the
  narrow widths where the previous visibility gate would have
  hidden it together with the buttons.

## Rationale

Two toggle surfaces (popup Options, `cp -X` aliases) already cover
all five panes, and both are discoverable. The button strip earned
its cost when it was the only graphical/mouse-driven affordance for
these toggles; with the popup framework in place
([ADR 0062](0062-popup-menu-prompt-toolkit.md),
[ADR 0066](0066-popup-frame-focus-on-push.md)), the popup Options
submenu is the mouse-driven affordance, and the button strip was
duplicated work.

The visual real estate gained back (24 columns) goes to the input
buffer — useful when typing long commands at narrow terminal widths.

## Future

The right strip may host different content later — a connection-
status indicator, a notification badge, a session label. We are not
re-instantiating the clickable-button pattern preemptively as part
of this change; any future content there will be designed for its
own purpose.

## Relation to other ADRs

- **Supersedes [ADR 0031](0031-input-menu-width-threshold.md)** for
  the input pane. The formula duplication trade-off recorded there
  no longer applies — the formula is gone from `input_pane.py`.
- **Supersedes the input-pane portion of
  [ADR 0038](0038-drop-right-column-width-floor.md).** ADR 0038's
  threshold cleanup was a precursor; this ADR removes the gate
  entirely.
- **Independent of [ADR 0034](0034-clock-renderer-side-countdown.md).**
  The renderer-side countdown logic is preserved verbatim; only
  its surrounding container changes.
- **Independent of [ADR 0039](0039-cp-aliases-persistent.md).** The
  `cp -X` aliases continue to write `startup.conf` via
  `toggle_pane.sh --persist`; this ADR removes one of the surfaces
  ADR 0039 enumerated, leaving popup Options and `cp -X` aliases.
