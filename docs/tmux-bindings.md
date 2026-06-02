# tmux Bindings

Cockpit's tmux configuration hides the tmux layer from the player: defaults that
would confuse a non-tmux user are disabled, and all text-selection paths are
routed through cockpit helpers. Consult this file when changing any tmux binding
or when a player reports unexpected tmux behaviour.

See [docs/input-pane.md](input-pane.md) for the key-forwarding model (prompt_toolkit
and tt++ own all keyboard input); see [bridge/layout/focus_input.sh](../bridge/layout/focus_input.sh)
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
| `Escape` | If the game pane is in copy-mode, exit the scroll (`send-keys -X cancel`; `pane-mode-changed` then refocuses input); otherwise open the in-game popup (`ingame_menu.sh`) | `bridge/launcher/tmux_start.sh` |
| `MouseDragEnd1Border` | Resize panes (`on_pane_resize.sh`), then sweep + refocus input (`focus_input.sh --sweep`) | `bridge/launcher/tmux_start.sh` |
| `MouseUp1Pane` | Refocus input pane (`focus_input.sh`), gated on `pane_title != input` | `bridge/panes/input_pane.py` |
| `MouseDragEnd1Pane` (copy-mode table) | Copy selection + refocus input (`focus_input.sh`) | `bridge/panes/input_pane.py` |
| `MouseDragEnd1Pane` (root table) | Sweep stuck copy-mode panes + refocus input (`focus_input.sh --sweep`) | `bridge/panes/input_pane.py` |
| `MouseDragEnd1Status` | Sweep + refocus input (`focus_input.sh --sweep`) | `bridge/launcher/tmux_start.sh` |
| `MouseDragEnd1StatusLeft` | Sweep + refocus input (`focus_input.sh --sweep`) | `bridge/launcher/tmux_start.sh` |
| `MouseDragEnd1StatusRight` | Sweep + refocus input (`focus_input.sh --sweep`) | `bridge/launcher/tmux_start.sh` |
| `WheelUpPane` | Stock copy-mode entry; no-op in the cockpit status pane; on the game pane (`MUME`) also refocuses the input pane | `bridge/launcher/tmux_start.sh` |
| `WheelDownPane` | Pass-through in copy-mode; no-op in the cockpit status pane; on the game pane (`MUME`) also refocuses the input pane | `bridge/launcher/tmux_start.sh` |

## Active hooks

| Hook | Trigger | Action | Gating | Set in |
|------|---------|--------|--------|--------|
| `pane-mode-changed` | Any pane enters or exits copy-mode | Refocus input pane (`focus_input.sh`) | `pane_in_mode != 1` (exit only) and `pane_title != input` (avoid self-refocus) | `bridge/launcher/tmux_start.sh` |

The two click/drag bindings (`MouseUp1Pane`, `MouseDragEnd1Pane`) are registered
by `bridge/panes/input_pane.py` at input-pane startup and remain for the lifetime of the
cockpit session. The pane no longer closes during normal use.

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
- **Scroll wheel in the game pane (`MUME`):** enters copy-mode and scrolls scrollback
  (stock tmux behaviour, preserved). The `-e` flag exits copy-mode when scrolled back
  to the bottom. When copy-mode exits (by scrolling back to the bottom or any other
  path), the `pane-mode-changed` hook fires and returns focus to the input pane.
  Additionally, the `MUME` branch of the wheel bindings refocuses the input pane on
  every tick, so scrolling never steals focus to tt++ (typed letters keep landing in
  the input buffer, not in copy-mode where they would raise the `(goto line)` prompt).
  The copy-mode scroll position is preserved; only tmux focus returns to input.
- **Scroll wheel in comm / timers / ui / dev:** handled internally by the
  prompt_toolkit `ListControl` (ADR 0037) — never enters tmux copy-mode, so these
  panes keep focus behaviour entirely to themselves and are not touched by the wheel
  bindings.
- **Scroll wheel in cockpit status pane:** no-op — the status pane has no meaningful
  scrollback, and letting the wheel enter copy-mode there is confusing.

### Drag-end surface matrix

tmux fires drag-end on the **release** surface, not the drag-start surface. This creates a matrix problem: a drag that starts in the main pane (entering copy-mode) can release on a different pane, a border, or the status bar. The originating pane is left in copy-mode with an active selection, and tmux focus does not return to the input pane.

Independently, prompt_toolkit panes (comm, timers) have `mouse_support=True` and forward mouse events via `send-keys -M`. They never enter tmux copy-mode, so the copy-mode `MouseDragEnd1Pane` binding never fires for drags that start and end inside them.

The fix is `focus_input.sh --sweep`, which iterates all panes in `mume:cockpit` and calls `copy-pipe-and-cancel` on every non-input pane where `pane_in_mode == 1`. `copy-pipe-and-cancel` preserves the selection (copies via OSC 52) and exits copy-mode. Every drag-end surface — other panes (root table), borders, and status bar — runs `--sweep` before refocusing the input pane.

**Invariant:** after any drag-end, the input pane has tmux focus and no other pane is stuck in copy-mode with a stale selection.

**Deliberate asymmetry:** `MouseUp1Pane` (plain click) does **not** use `--sweep`. Sweeping on click would cancel an in-progress scrollback session if the user clicks another pane while browsing history in the main pane. The sweep is restricted to drag-end events only. Within drag-end, `MouseUp1Pane` keeps its `pane_title != input` gate (a click on input is a local typing action) while `MouseDragEnd1Pane` (root table) has no gate — drag-end on the input pane necessarily originated in another pane and always warrants sweep.

## Page Up / Page Down from the input pane

Page Up and Page Down operate on the game pane's tmux copy-mode — the same
scrollback as the mouse wheel. They share identical entry and exit behaviour:

- **Page Up** calls `tmux copy-mode -e -t <game pane>` (idempotent — a no-op
  when already in copy-mode) then `send-keys -X page-up`. The `-e` flag means
  scrolling past the bottom auto-exits copy-mode.
- **Page Down** is gated on `#{pane_in_mode}` — it is a silent no-op when the
  game pane is not in copy-mode, matching the wheel's behaviour at the live tail.
- When copy-mode exits via Page Down past the bottom, the `pane-mode-changed`
  hook fires and refocuses the input pane, identical to wheel-down exit.

Mouse wheel and keyboard scrollback are therefore interchangeable: scrolling up
with the wheel and then pressing Page Up continues from the same position, and
vice versa.

While the game pane is scrolled, sending a command (Enter) or pressing any
forwarded macro key (F1–F12, numpad, Alt+letter, Ctrl+letter) first snaps the
game pane back to the live tail — `input_pane.py` issues a server-gated
`if-shell -F '#{pane_in_mode}' 'send-keys -X cancel'` before delivering the
keys, so the input reaches tt++ instead of landing in copy-mode (which would
raise the `(goto line)` prompt). The gate makes this a no-op at the live tail.

The input pane is intentionally excluded from the drag / double-click / triple-click
overrides so that prompt_toolkit's own click and selection behaviour is not disturbed.

## Keyboard model

The prefix key is disabled (`prefix None`). All keyboard input is handled by:

- **prompt_toolkit** (when the input pane has focus) — editing, history, key forwarding.
- **tt++ `#macro` bindings** (in the game pane) — received as raw key events.
- **tmux root binding:** `Escape` → exit a game-pane scroll if one is active, else
  in-game popup from any pane (see the root-table binding above).

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
