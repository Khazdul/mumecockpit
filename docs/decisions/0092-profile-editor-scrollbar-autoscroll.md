# 0092 — Profile editor scrollbar click-and-hold: self-terminating target

**Status:** Accepted
**Date:** 2026-05-22

## Context

Phase H of the profile-editor rework adds click-and-hold auto-scroll
to the three scrollbars in the profile editor — the Editor-mode buffer
scrollbar, the Lite-mode entry-list scrollbar, and the Lite-mode
Body-field scrollbar. Holding the mouse button on a track row above
or below the thumb pages the viewport once immediately, then — after
a short initial delay — auto-repeats the page-step toward the held
position, stopping when the thumb covers that row.

The interesting design question is **how to stop**. prompt_toolkit
delivers no "button held" event stream: between a `MOUSE_DOWN` and
the matching `MOUSE_UP` there are no events at all if the pointer
stays still. `MOUSE_UP` does fire on release, but it reaches *only*
the fragment under the pointer at that moment — if the pointer
drifted off the scrollbar between press and release, the scrollbar
never sees the up event. A naive "repeat until `MOUSE_UP`" design
would therefore run forever the first time the user releases over
chrome or over a different fragment than the one they pressed.

## Decision

**Bound the auto-scroll by a TARGET — the held track row. Each tick
re-reads the CURRENT thumb geometry against that target and pages one
viewport toward it; the step function returns `False` (stop) once the
thumb covers the target row, or when the scroll has clamped at its
bound. `MOUSE_UP`, when received, still disarms early as a fast-path,
but it is never the sole stop signal.**

A missed `MOUSE_UP` degrades to "scrolled to the clicked position and
stopped" — exactly the outcome of a single click. The runaway-timer
failure mode is impossible by construction: the target is a fixed
cell coordinate, the thumb monotonically approaches it under
page-steps, and a clamped scroll terminates the loop on the next
tick.

Implementation: a launcher-level controller — `_autoscroll_arm`,
`_autoscroll_tick`, `_autoscroll_disarm`, plus a module-level
`_autoscroll_target` slot — schedules its ticks through the existing
`_app_loop.call_later` mechanism (same as `_editor_flash`). Each
scrollbar has its own `step_fn` that captures NO geometry — the
captured `thumb_top` would go stale as the thumb moves. `MOUSE_MOVE`
handlers on the track fragments call `_autoscroll_set_target` to
let the target follow the pointer; this is best-effort because some
terminals don't report motion during a button hold.

The shared `Scrollbar` widget (`bridge/launcher/widgets/scrollbar.py`)
is unchanged. Auto-scroll is launcher-side state because the design
hinges on a stable application-level event loop and the widget is
deliberately leaf — application-agnostic, reusable across surfaces
that don't have an `_app_loop`.

## Alternatives considered

### Repeat until `MOUSE_UP` (rejected)

Arm on `MOUSE_DOWN`, disarm on `MOUSE_UP`. Simple, but a single
missed `MOUSE_UP` — pointer off the bar at release, terminal that
doesn't deliver motion during a button hold, focus change — leaves
the timer running forever, paging the viewport until the user
clicks somewhere new. The failure mode is severe (UI appears to be
malfunctioning) and the trigger is environmental. Rejected.

### Repeat for a fixed total count or fixed wall-clock duration (rejected)

Arm with a "scroll up to N more times" budget. Stops eventually but
doesn't track the user's actual intent — N too low and a long buffer
needs multiple clicks to traverse; N too high and a small buffer
keeps ticking after the user has clearly arrived. The target-based
design naturally adapts to any buffer length: small buffers stop on
the first or second tick, large buffers keep going until the held
row is reached.

### Move the controller into the `Scrollbar` widget (rejected)

The widget could own the timer and the target. Rejected to keep the
widget leaf: it has no reference to an application event loop, and
some current call sites (statistics frame, history detail) don't
need auto-scroll. Pushing event-loop awareness into the widget would
either require every call site to inject a scheduler or would couple
the widget to prompt_toolkit's `get_app` global. Neither is worth
it for a feature that only applies in the profile editor.

## Consequences

- A quick click-and-release pages exactly once, unchanged from
  Phase G.
- Holding the button above or below the thumb pages once immediately,
  then auto-repeats roughly every 100 ms after a ~300 ms initial
  delay, stopping when the thumb reaches the held row.
- Releasing the button stops the auto-scroll early when `MOUSE_UP`
  reaches the scrollbar fragment; otherwise the self-terminating
  target stops it on its own.
- A click-and-hold on the thumb itself is a no-op — drag is out of
  scope; arming only fires on track clicks above/below.
- Auto-scroll moves only the viewport offset, never the cursor —
  consistent with the Phase G wheel/scrollbar cursor decoupling.
- Auto-scroll never outlives the editor frame: `_autoscroll_disarm`
  is called from `_enter_profile_editor`, `_profile_editor_save_and_close`,
  and `_editor_flip_mode`. The handle is also implicitly torn down
  on app exit because `_app_loop` goes away.
- The controller is module-scoped — `_autoscroll_tick` is directly
  invokable from tests, which drive arm + step behaviour without
  sleeping for the timer. Coverage lives in
  `test_profile_editor.py:TestEditorScrollbarAutoScroll`.

## Future work

If a second editor surface ever needs the same hold-to-repeat
behaviour, the controller is already generic — it takes a `step_fn`
closure and stores a single target row. The non-portable piece is
the per-scrollbar step function, which re-reads the geometry it
cares about each tick. Other read-only scrollables (statistics
frame, history detail) could opt in with their own step functions
if the use case warrants it.
