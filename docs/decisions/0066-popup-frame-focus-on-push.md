# 0066 — Popup frames focus their primary window on push

**Status:** Accepted
**Date:** 2026-05-12

Supplements [ADR 0062](0062-popup-menu-prompt-toolkit.md).

## Context

The popup framework introduced in [ADR 0062](0062-popup-menu-prompt-toolkit.md)
models the UI as a frame stack — a single `DynamicContainer`
swaps between `main`, `options`, `scripts`, `statistics`, and
`exit_confirm` containers, with `_push_frame` / `_pop_frame`
moving the active frame on a list.

In the initial implementation `_push_frame` updated only the
module-level `_current_frame` variable. That was enough to make
`DynamicContainer` show the right content and enough to make the
frame's own `KeyBindings` filter activate. It was *not* enough to
make prompt_toolkit route mouse events to the new frame.

The reason: prompt_toolkit's mouse-event routing follows the
focused `Window`. At application startup `Application` picks an
initial focus heuristically — in this layout it picked the main
frame's title control. Changing `_current_frame` swaps the
visible container but does not move focus. Clicks on controls
inside a pushed sub-frame's content were routed to whatever
window held focus, which was still a window inside the main
frame. The clicks went nowhere visible to the user; the
sub-frame's mouse handlers never fired.

The symptom was silent. There were no exceptions, no logs, no
visible cursor on the wrong control (FormattedTextControl is
cursorless). The Statistics frame surfaced it because that frame
relies on mouse for click-to-sort column headers, click-to-focus
on tables, and click-to-jump on scrollbar tracks — all of which
quietly did nothing. Once we instrumented the mouse handlers we
also discovered the Options pane toggles via mouse had been
quietly broken since ADR 0062 landed; keyboard-only QA of that
submenu had masked it.

The same trap will sit waiting for any future frame whose
interactivity depends on mouse events.

## Decision

**Every frame builder constructs at least one focusable `Window`
and stores it at module level.** Today the windows are
`_main_window`, `_options_window`, `_scripts_window`,
`_statistics_window`, `_exit_confirm_window`.

**`_push_frame` calls `app.layout.focus()` on the new frame's
primary window** after updating `_current_frame`, before
`_app.invalidate()`. `_pop_frame` does the same on the way back.
The dispatch is factored into a `_focus_current_frame()` helper
that maps `_current_frame` → module-level window and calls
`_app.layout.focus(win)` inside a try/except (the app may not be
running yet during initial layout construction).

```python
def _push_frame(frame):
    global _current_frame
    _frame_stack.append(_current_frame)
    _current_frame = frame
    _focus_current_frame()
    if _app:
        _app.invalidate()
```

**Frames whose interactivity is keyboard-only can technically
skip the contract.** They cannot, in practice — the cost of
marking their primary window `focusable=True` and wiring the
dispatch is one line each, and the cost of *not* doing it is the
next mouse-driven feature added to the frame silently failing
exactly the way Options did. The contract applies uniformly to
keep the failure mode out of the codebase rather than relying on
each author to remember when it is safe to skip.

The contract is captured in [docs/popup-menu.md](../popup-menu.md)
under "Adding a new frame" so future authors discover it from
the same file that documents the frame they are adding.

## Consequences

- **Mouse works uniformly.** Clicks on controls inside any
  pushed sub-frame are routed to that sub-frame's window and its
  registered `mouse_handler` callbacks fire. No more silent
  mis-routing.
- **The contract is explicit and discoverable.** Each frame
  builder declares its primary window; the `_focus_current_frame`
  switch makes the full set visible in one place. A reader who
  opens `ingame_menu.py` to add a frame sees the existing
  pattern; a reader who opens `docs/popup-menu.md` sees the
  written contract that explains *why* the pattern exists.
- **Cost.** New frame authors must remember to add the new
  frame's window to `_focus_current_frame` and to mark its
  primary control `focusable=True`. The doc and the existing
  switch make this easy to remember; missing it shows up at the
  first mouse-driven feature on the new frame, the same
  symptomatic-yet-silent failure mode that motivated this ADR.
  Acceptable: explicit contracts trade a small recurring cost
  for a closed-by-construction bug class.

## Alternatives considered

**Mark every `Window` `focusable=True` and rely on
prompt_toolkit's focus picker.** Skip the explicit dispatch and
let prompt_toolkit decide. Rejected. The focus picker is a
heuristic over the layout tree; it is not specified to follow
`DynamicContainer` content changes and in practice does not.
Even where it happens to work, the choice of "primary" window
inside a frame becomes implicit and order-dependent. Explicit
beats implicit for this class of bug.

**Subclass `DynamicContainer` to auto-focus on content change.**
Build a custom container that, when its `get_container` callable
returns a different sub-tree, walks the new sub-tree for a
focusable window and focuses it. Rejected. More code for the
same outcome; the subclass would need its own contract for "what
counts as the primary window" and would still rely on each frame
author to mark something focusable. The explicit module-level
window + helper switch is shorter and reads more directly.

**Add an integration test that pushes each frame and asserts a
mouse event fires on a known control.** A real fix in spirit,
but the popup is a `tmux display-popup` full-screen application;
driving it in a headless test would require building a
prompt_toolkit harness that none of the other right-column panes
have. Out of scope for this ADR; the explicit contract +
documentation is the minimum viable mitigation. A harness is
worth revisiting if the popup grows more frames.

## Relation to other ADRs

- **Supplements [ADR 0062](0062-popup-menu-prompt-toolkit.md).**
  ADR 0062 introduced the frame-stack rendering model with
  `DynamicContainer` dispatch but did not capture the mouse-
  routing requirement that comes with it. This ADR records the
  missing piece of the framework contract.
- **Independent of [ADR 0037](0037-right-column-prompt-toolkit-convergence.md).**
  The four right-column panes use prompt_toolkit but each is its
  own `Application` with a single root container — there is no
  frame stack and no `DynamicContainer` dispatch, so the
  failure mode this ADR addresses does not arise there.
