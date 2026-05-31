# 0062 — In-game popup menu rewritten in prompt_toolkit

**Status:** Accepted
**Date:** 2026-05-12

## Context

The original in-game popup (`bridge/launcher/ingame_menu.sh`) was a
600+ line bash script using ANSI escapes, manual responsive layout,
and direct terminal I/O. It worked, but every addition — submenus,
mouse support, richer rendering, scrolling — added meaningful
friction: responsive shrinking and selection-state plumbing were
hand-rolled, click-to-select was unavailable without a separate
input-parser, and the visual vocabulary drifted from the rest of the
cockpit.

`prompt_toolkit` is already the rendering framework for the input,
status, buffs, and comm panes (ADR 0037 — right-column convergence).
The vocabulary, palette translation, and event-loop integration are
known quantities here.

## Decision

Rewrite the popup body as a `prompt_toolkit` full-screen `Application`
at `bridge/launcher/ingame_menu.py`. Keep `ingame_menu.sh` as a thin
wrapper that `exec`s the Python entry so existing call sites do not
change.

Both call sites are untouched:

- the tmux root `ESC` binding in `bridge/launcher/tmux_start.sh`, and
- the auto-open path in `lua/brain/connection.lua` via
  `mark_mume_disconnected()`.

All sentinels (`bridge/runtime/.popup_open`,
`bridge/runtime/.user_reconnecting`,
`bridge/runtime/.return_to_menu`) and dispatch mechanisms
(`tmux send-keys` for `cp -s` / `cp -e` / `reconnect`,
`toggle_pane.sh --persist` for Options) are preserved verbatim — the
rewrite is rendering-only.

The UI is a frame stack (`main` / `options` / `scripts` /
`exit_confirm`) routed through a `DynamicContainer`; each frame owns
its own `KeyBindings` filter.

## Consequences

- **Gained.** Native click-to-select on every selectable row,
  keyboard-driven scroll in the Scripts frame, visual consistency
  with the four prompt_toolkit panes already in the stack, and a
  much shorter path for future additions (a new submenu is one
  container + one bindings filter + one push).
- **Lost.** ~600 lines of bash and the responsive shrinking logic
  that came with it. The popup is now sized solely by tmux
  `display-popup` geometry.
- **Cost.** Python cold-start adds ~150–250 ms to popup open on
  the developer's machine (measured before commit). Acceptable —
  the popup is user-initiated and the latency is below the
  perception threshold for a deliberate keystroke.
- **Limitation.** Mouse wheel does not scroll within the popup.
  Cause and rejected workarounds are documented in
  `docs/popup-menu.md` Scope trims and below.
  *Superseded in part by [ADR 0114](0114-popup-display-popup-forwards-wheel.md)
  — the wheel limitation no longer holds under the shipped foot/WSLg
  setup; wheel is wired on Scripts, Readability, and Statistics.*

## Alternatives considered

**Stay in bash, add scroll via `dialog` or `whiptail`.** Rejected.
Both tools have poor visual integration with the rest of the
cockpit (different colour model, different glyph set), still no
click-to-select, and still no usable mouse wheel inside a
`display-popup`. The bash-script ceiling did not move.

**Use `textual` or `rich`.** Rejected. `prompt_toolkit` is already
in the stack; adding a second TUI framework increases dependency
surface and visual inconsistency for no functional gain.

**Move the popup out of `tmux display-popup` into a dedicated
tmux pane.** Rejected. Breaks the "floating overlay" UX, requires
new layout-management logic, and conflicts with the existing five
right-column data panes that own the right side of the layout.

**Globally rebind tmux `WheelUpPane` / `WheelDownPane` to forward
wheel into the popup application.** Rejected. The rebind is
global, so wheel scrollback in the game pane and other
non-mouse-mode panes would break for the sake of one scrollable
view. The cost outweighs the gain when keyboard scroll
(UP/DOWN, PageUp/PageDown) already covers the use case.

**Dynamic wheel rebinding via the wrapper script (save bindings
on popup open, restore on close).** Rejected. Trap-based restore
is fragile: `exec` in the wrapper defeats `EXIT` traps, abnormal
exits (SIGKILL, terminal close) leak the modified bindings into
the rest of the session, and the bookkeeping overhead is large
relative to the feature it buys.

## Implementation notes worth preserving

Lessons that apply to prompt_toolkit work elsewhere in the cockpit:

- **`eager=True` on ESC.** Every frame's ESC binding needs
  `eager=True`, otherwise prompt_toolkit's input-disambiguation
  timeout (default 500 ms) introduces perceptible lag on bare ESC.
  Lowering `app.ttimeoutlen` and `app.timeoutlen` to ~50 ms is a
  belt-and-braces complement, not a replacement.
- **Mouse handlers belong on `UIControl`.** In prompt_toolkit 3.x,
  override `mouse_handler` on a `UIControl` subclass (e.g. a
  `FormattedTextControl` subclass). `Window` does not accept a
  `mouse_handler` kwarg.
- **Full-frame mouse hookup for scrollable frames.** If a frame
  wants wheel scroll, the mouse-handling control must be used for
  every row of the frame (title, content, footer). Wheel events
  landing on a row whose control does not handle them are
  absorbed without bubbling. Documented here for completeness even
  though tmux consumes wheel before it reaches the popup in this
  case — the rule still applies to the other prompt_toolkit panes.
- **Cursor hiding.** The terminal cursor is hidden automatically
  only when the focused `Window` uses a control without a cursor
  (`FormattedTextControl`). Either use a cursorless control
  uniformly across frames, or set `always_hide_cursor=True`
  explicitly on the relevant `Window`s.
- **Fragment handlers must decline unhandled events.** Even when the correct
  control handles every row (the note above), a per-fragment mouse handler inside
  it can still swallow events. When a fragment carries a handler (the
  `(style, text, handler)` 3-tuple), prompt_toolkit's
  `FormattedTextControl.mouse_handler` returns *that handler's* return value for
  any event over the fragment. A handler that branches on specific event types
  (e.g. `MOUSE_DOWN`/`MOUSE_MOVE`) and falls off the end returns an implicit
  `None`, which counts as "consumed" — so a `mouse_handler` override guarded by
  `if result is not NotImplemented: return result` short-circuits and never
  reaches its own wheel/scroll branch. Fragment handlers must therefore
  `return NotImplemented` for every event type they do not consume. (Worked
  example: timers-pane wheel scroll worked in the grid, whose cells are mostly
  handler-less, but was silently swallowed in the herblore add-view, where every
  row cell carried a click/hover handler.)

## Relation to other ADRs

- **ADR 0037** (right-column prompt_toolkit convergence) — same
  rendering framework for the same reasons (mouse, scroll, async
  invalidate, visual consistency). The popup is not part of the
  right column, but the rationale carries over.
- **ADR 0058** (reconnect UX) and the popup auto-open contract in
  `docs/session-lifecycle.md` are unaffected — sentinels and
  dispatch points are preserved by design.
