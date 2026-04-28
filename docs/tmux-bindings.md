# tmux Bindings

Cockpit's tmux configuration hides the tmux layer from the player: defaults that
would confuse a non-tmux user are disabled, and all text-selection paths are
routed through cockpit helpers. Consult this file when changing any tmux binding
or when a player reports unexpected tmux behaviour.

See [docs/input-pane.md](input-pane.md) for the key-forwarding model (prompt_toolkit
and tt++ own all keyboard input); see [bridge/focus_input.sh](../bridge/focus_input.sh)
for the click-to-refocus helper this work composes with.

---

## Philosophy

Cockpit presents one terminal window. The player types in the input pane and reads
in the game / comm / ui / dev panes — tmux is invisible infrastructure. Defaults
that expose tmux to the player (prefix key, right-click menus, copy-mode entry
from unexpected clicks) are disabled or overridden.

## Active root-table bindings

| Event | Action | Set in |
|-------|--------|--------|
| `Escape` | Open in-game popup (`ingame_menu.sh`) | `bridge/tmux_start.sh` |
| `MouseDragEnd1Border` | Resize panes (`on_pane_resize.sh`) | `bridge/tmux_start.sh` |
| `MouseUp1Pane` | Refocus input pane (`focus_input.sh`), gated on `pane_title != input` | `bridge/input_pane.py` |
| `MouseDragEnd1Pane` | Copy selection + refocus input pane, gated on `pane_title != input` | `bridge/input_pane.py` |
| `WheelUpPane` | Stock copy-mode entry; no-op in the cockpit status pane | `bridge/tmux_start.sh` |
| `WheelDownPane` | Pass-through in copy-mode; no-op in the cockpit status pane | `bridge/tmux_start.sh` |

The two click/drag bindings (`MouseUp1Pane`, `MouseDragEnd1Pane`) are registered
by `bridge/input_pane.py` at input-pane startup and removed by
`bridge/toggle_pane.sh` when the input pane closes (`cp -i`). With no input pane
there is nowhere to refocus, so removing the bindings is cleaner than leaving them.

## Disabled defaults

| Binding | Reason |
|---------|--------|
| `MouseDown3Pane` | Right-click context menu — no useful action for the player |
| `MouseDown3Status` | Right-click on tmux status bar |
| `MouseDown3StatusLeft` | Right-click on left status segment |
| `MouseDown3StatusRight` | Right-click on right status segment |
| prefix (`Ctrl+b`) | Disabled via `prefix None`; tt++ macros and prompt_toolkit own all keys |

## Mouse interaction model

- **Click any non-input pane:** selects the pane and returns focus to the input pane.
- **Drag in game / comm / ui / dev:** tmux enters copy-mode automatically on drag
  start; on drag end `copy-pipe-and-cancel` copies the selection to the system
  clipboard via OSC 52 and cancels copy-mode; focus returns to the input pane.
- **Double-click:** selects the word under the cursor and copies to system clipboard via tmux defaults. Focus does not return to the input pane after these — click anywhere or press a key in the input pane to refocus.
- **Triple-click:** selects the full line and copies to system clipboard via tmux defaults. Focus does not return to the input pane after these — click anywhere or press a key in the input pane to refocus.
- **Scroll wheel in game / comm / ui / dev:** enters copy-mode and scrolls scrollback
  (stock tmux behaviour, preserved). The `-e` flag exits copy-mode when scrolled back
  to the bottom.
- **Scroll wheel in cockpit status pane:** no-op — the status pane has no meaningful
  scrollback, and letting the wheel enter copy-mode there is confusing.

The input pane is intentionally excluded from the drag / double-click / triple-click
overrides so that prompt_toolkit's own click and selection behaviour is not disturbed.

## Keyboard model

The prefix key is disabled (`prefix None`). All keyboard input is handled by:

- **prompt_toolkit** (when the input pane has focus) — editing, history, key forwarding.
- **tt++ `#macro` bindings** (in the game pane) — received as raw key events.
- **tmux root binding:** `Escape` → in-game popup from any pane.

No player key combination can accidentally trigger a tmux action.

## Clipboard portability

`set-clipboard on` (a tmux server option) causes tmux to emit OSC 52 escape
sequences to the terminal emulator whenever text is copied to a paste buffer.
Terminals that support OSC 52 push the text to the system clipboard directly:

| Terminal | OSC 52 support |
|----------|----------------|
| Alacritty | Supported |
| Windows Terminal | Supported |
| kitty | Supported |
| iTerm2 | Supported |
| Modern xterm / GNOME Terminal | Supported |
| macOS Terminal.app | **Not supported** |

**macOS Terminal.app fallback:** use `Shift+drag` to select text — this routes
through the terminal's own selection mechanism and always reaches the system
clipboard regardless of tmux's clipboard setting.

---

Back to [architecture.md](../architecture.md).
