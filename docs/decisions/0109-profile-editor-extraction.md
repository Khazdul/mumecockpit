# ADR 0109 — Extract ProfileEditor into its own module

**Status:** Accepted  
**Date:** 2026-05-27

## Context

The profile editor grew to ~5 000 lines of Python inside `launcher.py`, making
the file hard to navigate and making it impossible to reuse the editor inside the
in-game popup (`ingame_menu.sh` / a future popup bridge) without importing the
entire launcher Application.

## Decision

Extract all editor code from `launcher.py` into `bridge/launcher/profile_editor.py`
as the `ProfileEditor` class.

### EditorHost protocol

`ProfileEditor` never imports `launcher`. All access to launcher infrastructure
goes through a duck-typed `EditorHost` object passed to `ProfileEditor.__init__`:

| property / method | purpose |
|---|---|
| `host.app` | prompt_toolkit `Application` (None when not running) |
| `host.app_loop` | asyncio event loop (None before `run_async`) |
| `host.terminal_bg` | hex background for colour-swatch rendering |
| `host.term_cols()` | terminal width |
| `host.term_rows()` | terminal height |
| `host.push_overlay_frame()` | push `profile_editor_macro_keybind` frame |
| `host.pop_overlay_frame()` | pop the overlay frame |
| `host.focus_current_frame()` | transfer focus after a frame change |
| `host.is_active()` | True when `profile_editor` is the current frame |
| `host.is_overlay_active()` | True when the macro-keybind overlay is current |

### launcher.py wiring

- `_LauncherEditorHost` implements `EditorHost` by forwarding to launcher
  module globals.
- `_profile_action_edit()` creates a fresh `ProfileEditor` and calls
  `_push_frame("profile_editor")`.
- The `profile_editor` and `profile_editor_macro_keybind` frames in `main()`
  use `DynamicContainer` lambdas so each new `ProfileEditor` instance's
  windows are picked up without rebuilding the layout.
- `_focus_current_frame()` calls `instance.main_window()` /
  `instance.overlay_window()` instead of the old module-level globals.

### Test harness

`test_profile_editor.py` gains a `_TestHost` (no-op Application, fake clock
support, overlay-state tracking) and a `_reset_editor_state` factory that
creates a fresh `ProfileEditor` per test. All per-instance state is accessed
via `_ed.*`; module-level constants/helpers use `profile_editor.*`.

## Consequences

- `launcher.py` shrinks from ~15 500 to ~9 500 lines.
- `profile_editor.py` is ~6 100 lines and has no dependency on `launcher`.
- The in-game popup can import and instantiate `ProfileEditor` with its own
  `EditorHost` without pulling in the launcher's Application.
- 566 existing tests continue to pass unchanged in intent (test harness
  updated mechanically to use the new class API).
