# Input Pane

Full specification for `bridge/input_pane.py` — the prompt_toolkit-based
command input pane. Touch this file when changing key forwarding behaviour,
Enter semantics, history navigation, or the DECKPAM/keypad setup.

A dedicated input pane (`bridge/input_pane.py`) replaces typing directly
in the TT++ pane. It runs as a separate tmux pane at the bottom of the
left column, 1 row tall.

**Behaviour:**
- Commands are typed here and forwarded to TT++ via `tmux send-keys`
- After sending, the command remains visible with the whole buffer selected,
  indicating it can be repeated or immediately overwritten
- Pressing Enter again repeats the last command
- Pressing any printable key while the buffer is selected replaces it and
  starts a new command (prompt_toolkit default selection replacement)
- Page Up / Page Down scroll the TT++ pane without leaving the input pane
- On startup, a tmux `MouseUp1Pane` binding is registered so that clicking
  any other pane returns focus to the input pane automatically. The binding
  calls `bridge/focus_input.sh`, which resolves the input pane's current
  index at click time — so pane index shifts caused by cp -u / cp -d
  close+open cycles never cause focus to land on the wrong pane

**Dependencies:**
- Python 3 (system)
- `prompt_toolkit` — install with:
  `pip install prompt_toolkit pyperclip --break-system-packages`
- `pyperclip` — for reading the system clipboard on paste (Ctrl+V).
  On WSL, pyperclip's first call spawns `powershell.exe Get-Clipboard`
  (~200–500 ms); acceptable for a one-off paste action.

**Recommended terminal config:** prompt_toolkit emits a steady-cursor
request that persists while the input pane is running and is inherited
by other panes when focus shifts. Terminals with app-override blinking
(e.g. Alacritty `blinking = "On"`) will therefore show a steady cursor
in the input pane, tt++ after `cp -i` off, and bash after `cp -e`. Set
the terminal to force blinking (Alacritty: `blinking = "Always"`) if
a blinking cursor is preferred. The client works fully without this
setting — it is purely cosmetic.

**Known limitation:** drag-select in the TT++ pane does not auto-return
focus to the input pane. Click once in the input pane to return.

## Keypad application mode

On startup, the input pane writes DECKPAM (`\e=`) to stdout to enable
keypad application mode. An atexit handler writes DECKPNM (`\e>`) to
restore numeric mode on shutdown. This is unconditional — the terminal
protocol has no way to query current keypad state, and re-enabling is
idempotent.

Application mode causes numpad keys to emit SS3 escape sequences
(`\eOp`..`\eOy` for digits, `\eOj`..`\eOo` for operators, `\eOM` for
enter) which the input pane can bind individually.

## Key forwarding policy

Keys are split into three disjoint categories:

| Category   | Handled by         | Examples                                              |
|------------|--------------------|-------------------------------------------------------|
| Editing    | prompt_toolkit     | printable chars, Backspace, Ctrl+E/W, Alt+Backspace   |
| Selection  | prompt_toolkit     | Shift+arrows, Ctrl+Shift+arrows (native selection)    |
| History    | input_pane.py      | Up, Down                                              |
| Scrollback | input_pane.py      | PageUp, PageDown (forwarded to tt++ pane's buffer)    |
| Clipboard  | input_pane.py      | Ctrl+C (copy), Ctrl+X (cut), Ctrl+V (paste)           |
| Forwarded  | tt++ via send-keys | F1–F12, numpad (SS3), Alt+letter (subset), Ctrl+letter (subset) |

Forwarded keys invoke `tmux send-keys -t mume:cockpit.0 <name>` with no
`Enter` appended — a single keypress is delivered to tt++, which then
consults its `#macro` table as if the key had been pressed directly.

## Command input behaviour

The input pane implements line editing, command history, and a selection-
based recall model on top of prompt_toolkit.

### Enter semantics

| Buffer state | Action |
|--------------|--------|
| Non-empty    | Send text, append to history (consecutive-dedup), refill buffer with sent text — whole buffer selected |
| Empty        | Send a bare newline to tt++. Do NOT re-send the previous command. |

Empty Enter sending a bare newline is load-bearing: MUME uses it to
cancel delayed commands (e.g. spell casts). Re-sending last_cmd on
empty Enter would silently break that.

### Recall state = whole-buffer selection

A buffer is in "recall state" when its entire text is selected. This
happens after:
- The post-Enter refill (Enter on a non-empty buffer)
- Up/Down history navigation
- Shift+Home, Shift+End, or Ctrl+A

Recall state uses prompt_toolkit's native `SelectionState` — no custom
highlight processor. The visual appearance is whatever the terminal uses
for selected text, consistent with any other selection in the input pane.

When the buffer is selected:
- **Typing any printable key** replaces the selection (prompt_toolkit default)
- **Backspace or Delete** deletes the selection (prompt_toolkit default)
- **Left, Right, Home, End** clear the selection and move the cursor
  (prompt_toolkit default)
- **Shift+arrows** adjust the selection boundary (prompt_toolkit default)
- **Ctrl+C** copies the selected text to the system clipboard

Shift+Home selects the whole buffer with the cursor at the start;
Shift+End and Ctrl+A select the whole buffer with the cursor at the end.
No-op on empty buffer.

### History navigation

History is a list of previously-sent commands with **consecutive-dedup**
— identical commands sent back-to-back collapse to a single entry, but
non-consecutive duplicates are preserved. `look, north, look` keeps
both `look` entries; `look, look, look` collapses to one.

`Up` walks toward older entries, `Down` toward newer:

- **Up from refilled state** (just after Enter, whole buffer selected):
  steps directly to the entry before the newest, skipping the already-displayed
  entry.
- **Up from a typed draft**: saves the draft as `pending_input` and shows
  the newest entry.
- **Up during active browsing**: steps one entry older, clamped at the oldest.
- **Down during active browsing**: steps one entry newer. At the newest,
  one more Down restores `pending_input` (the saved draft or empty). One
  more Down after that clears the buffer entirely.
- **Down outside of browsing**: no-op.

Any text change during browsing exits recall state and resets navigation
— the next Up starts fresh from the newest entry.

History is in-memory only; it does not persist across restarts and
has no size cap.

## Clipboard operations

| Key    | Action                                                               |
|--------|----------------------------------------------------------------------|
| Ctrl+C | Copy selected text to system clipboard. No-op if no selection.       |
| Ctrl+X | Copy selected text to clipboard, then delete selection. No-op if no selection. |
| Ctrl+V | Paste clipboard text, replacing current selection (if any).          |

**Write path (OSC 52):** Ctrl+C and Ctrl+X write to the clipboard by
emitting an OSC 52 escape sequence. tmux (with `set-clipboard on`, set in
`bridge/tmux_start.sh`) forwards OSC 52 to the terminal emulator, which
sets the system clipboard. The same path tmux's `copy-pipe` already uses.

**Read path (pyperclip):** Ctrl+V reads via `pyperclip.paste()`. On WSL,
pyperclip delegates to `powershell.exe Get-Clipboard` on first use
(~200–500 ms one-off latency). Requires `pyperclip` to be installed:
`pip install pyperclip --break-system-packages`.

Ctrl+C does **not** exit the input pane. Ctrl+D is also a no-op (does
not trigger EOFError).

## Forwarded key classes

- **F-keys:** F1–F12. Shift+F-keys are not forwarded (terminal-dependent,
  no uniform tmux send-keys representation).
- **Numpad:** 0–9, `.`, `+`, `-`, `*`, `/`, Enter. Bound as raw SS3
  escape tuples (`("escape", "O", "p")` etc.) since prompt_toolkit has
  no named keys for numpad. Requires DECKPAM and Num Lock on.
- **Alt+letter:** all letters except `b`, `d`, `f` (reserved for
  readline-style word editing) and `o` (see Known Limitations).
- **Ctrl+letter:** `g`, `l`, `o`. Other Ctrl+letters are either reserved
  by the terminal, used by prompt_toolkit editing, or bound to clipboard
  ops (`c-c`, `c-x`, `c-v`).

`bridge/input_pane.py` is the source of truth for the exact lists.

## Design consequences

- tt++ sees forwarded keys as if pressed directly. `#macro` bindings
  work unchanged from standard tt++ usage — define them in `.tin` files
  or live in the session.
- tt++ `#macro` features that assume tt++ owns the input line have no
  equivalent here. Specifically, the `^` prefix ("trigger only at start
  of input line") is non-functional because the input line lives in
  prompt_toolkit.
- Shift+letter cannot be a macro target — terminals do not distinguish
  it from the uppercase form.
- Bare ESC is not available as a tt++ macro target. ESC is captured at
  the tmux root-keybinding level (`tmux bind-key -T root Escape`) to open
  the in-game popup menu uniformly from any pane (game, input, ui, dev).
  This bypasses prompt_toolkit's escape-disambiguation timer entirely.
  `escape-time` is set to 10 ms in `tmux_start.sh` for fast disambiguation
  of multi-character escape sequences (Alt+letter, numpad SS3) within tmux.

## Known limitations

- **Alt+o is not forwarded.** prompt_toolkit's key parser cannot
  reliably distinguish `("escape", "o")` from `("escape", "O", "o")`
  (numpad division). Other Alt+letters whose final character also
  appears as the third character of a numpad sequence have been
  verified not to collide — this bug is specific to lowercase `o`.
- **Numpad requires Num Lock on.** With Num Lock off, the numpad emits
  cursor/navigation sequences instead, which are not bound as macros.
- **Cursor flicker at popup open/close.** A single-frame cursor flash is
  visible when the popup opens and closes. Cause is the terminal emulator
  defaulting cursor-visible state on new pty creation; tmux display-popup
  spawns a fresh pty each open. Cursor-hide escapes fire as early as possible
  inside the popup but cannot preempt the emulator's initial state. Accepted
  as a cosmetic limitation.
- **OSC 52 clipboard write requires terminal support.** See
  `docs/tmux-bindings.md` — macOS Terminal.app does not support OSC 52.
  Ctrl+C / Ctrl+X will not reach the system clipboard on that terminal.

---
Back to [architecture.md](../architecture.md).
