# Input Pane

The input pane is an always-on integral part of the cockpit; there is no toggle.

Full specification for `bridge/panes/input_pane.py` — the prompt_toolkit-based
command input pane. Touch this file when changing key forwarding behaviour,
Enter semantics, history navigation, or the DECKPAM/keypad setup.

A dedicated input pane (`bridge/panes/input_pane.py`) replaces typing directly
in the TT++ pane. It runs as a separate tmux pane spanning the full window width at the bottom
of the cockpit, 1 row tall.

**Behaviour:**
- Commands are typed here and forwarded to TT++ via `tmux send-keys`
- After sending, the command remains visible with the whole buffer selected,
  indicating it can be repeated or immediately overwritten
- Pressing Enter again repeats the last command
- Pressing any printable key while the buffer is selected replaces it and
  starts a new command (prompt_toolkit default selection replacement)
- Page Up / Page Down drive the game pane's tmux copy-mode (the same scrollback
  as the mouse wheel) without leaving the input pane. Page Down past the live
  bottom auto-exits copy-mode, and the `pane-mode-changed` hook refocuses the
  input pane
- On startup, a tmux `MouseUp1Pane` binding is registered so that clicking
  any other pane returns focus to the input pane automatically. The binding
  calls `bridge/layout/focus_input.sh`, which resolves the input pane's current
  index at click time — so pane index shifts caused by cp -u / cp -d
  close+open cycles never cause focus to land on the wrong pane

**Dependencies:**
- Python 3 (system)
- `prompt_toolkit` — install with:
  `pip install prompt_toolkit pyperclip --break-system-packages`
- `pyperclip` — for reading the system clipboard on paste (Ctrl+V).
  On non-WSL platforms (macOS, native Linux) this is the only read
  path. On WSL it is the silent fallback when the win32yank fast path
  is unavailable (see Clipboard operations).
- `win32yank.exe` (WSL only) — fast clipboard reader at
  `~/MUME/bin/win32yank.exe`. Provisioned by the installer, not a pip
  dependency. When absent, Ctrl+V falls through to pyperclip silently.

**Recommended terminal config:** prompt_toolkit emits a steady-cursor
request that persists while the input pane is running and is inherited
by other panes when focus shifts. Terminals with app-override blinking
(e.g. Alacritty `blinking = "On"`) will therefore show a steady cursor
in the input pane and bash after `cp -e`. Set the terminal to force
blinking (Alacritty: `blinking = "Always"`) if a blinking cursor is
preferred. The client works fully without this setting — it is purely cosmetic.

## Keypad application mode

On startup, the input pane writes DECKPAM (`\e=`) to stdout to enable
keypad application mode. An atexit handler writes DECKPNM (`\e>`) to
restore numeric mode on shutdown. This is unconditional — the terminal
protocol has no way to query current keypad state, and re-enabling is
idempotent.

Application mode causes numpad keys to emit SS3 escape sequences
(`\eOp`..`\eOy` for digits, `\eOj`..`\eOo` for operators, `\eOM` for
enter) which the input pane can bind individually.

## Startup hygiene

The pane's pty starts in cooked mode with ECHO on; prompt_toolkit only
installs raw mode once `app.run_async()` runs. The window between pty
creation and that point is dominated by `setup_mouse_binding()`'s
synchronous `tmux bind-key` subprocess calls — long enough for a keystroke
to land. Without defense, a key typed in that window was echoed by the
kernel at column 0, leaving a stray character to the left of the `> ` prefix
(e.g. `a> `), and could also be read by prompt_toolkit as the first buffer
character — prepended to the first command.

`main()` (in `bridge/panes/input_pane.py`) defends in two parts:

1. **Clear ECHO first.** The very first action in `main()` — before
   `setup_mouse_binding()`, the DECKPAM write, and all object construction —
   clears the `ECHO` lflag on stdin via `termios.tcgetattr` /
   `termios.tcsetattr(TCSANOW)`. With echo off, no keystroke during the
   subprocess window is painted to the row. The saved attributes are
   restored on exit (atexit) so the terminal is never left in `-echo` if
   the process exits back to a shell.
2. **Flush + erase last.** Immediately before `app.run_async()`,
   `termios.tcflush(..., TCIFLUSH)` drops any bytes queued in stdin during
   interpreter/import startup and the echo-off window, and `\r\x1b[2K`
   clears any glyph echoed before step 1 could run.

Both positions are load-bearing, not incidental. The ECHO clear must be the
**first** action in `main()` (any subprocess before it reopens the echo
window), and **nothing that spawns a subprocess may run between the
flush/erase and `app.run_async()`** (a subprocess there would let fresh
keystrokes re-queue after the drain).

## Key forwarding policy

Keys are split into three disjoint categories:

| Category   | Handled by         | Examples                                              |
|------------|--------------------|-------------------------------------------------------|
| Editing    | prompt_toolkit     | printable chars, Backspace, Ctrl+E/W, Alt+Backspace   |
| Selection  | prompt_toolkit     | Shift+arrows, Ctrl+Shift+arrows (native selection)    |
| History    | input_pane.py      | Up, Down                                              |
| Scrollback | input_pane.py      | PageUp, PageDown (drive tmux copy-mode in the game pane — same buffer as the mouse wheel) |
| Clipboard  | input_pane.py      | Ctrl+C (copy), Ctrl+X (cut), Ctrl+V (paste)           |
| Forwarded  | tt++ via send-keys | F1–F12, numpad (SS3), Alt+letter (subset), Ctrl+letter (subset) |

Forwarded keys invoke `tmux send-keys -t mume:cockpit.0 <name>` with no
`Enter` appended — a single keypress is delivered to tt++, which then
consults its `#macro` table as if the key had been pressed directly.

Both forwarded keys and the command-send path (`send()`, including the empty
bare-newline) first call `_snap_game_pane_to_tail()`, a server-gated
`tmux if-shell -F '#{pane_in_mode}' 'send-keys -X cancel'` on the game pane:
if the pane is scrolled (in tmux copy-mode), exit the scroll so the keys reach
tt++ at the live tail instead of landing in copy-mode (which would raise the
`(goto line)` prompt). The `#{pane_in_mode}` gate makes it a no-op at the live
tail, so there is no extra round-trip or flicker on the normal hot path.

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
- **Typing any printable key** replaces the selection
- **Backspace or Delete** deletes the selection
- **Left, Right, Home, End** clear the selection and move the cursor
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

### Inline history autosuggestion

**Opt-in, default off.** Gated by `input_autosuggest` in `startup.conf`
(`1` → on, `0` / absent → off). The pane reads the key **once at startup**,
directly from `bridge/runtime/startup.conf` (`_autosuggest_enabled()`) — not
via `read_config.sh` or tt++ `#var`, so nothing touches the hot path. The
toggle lives on the launcher Options frame (in-place `[X]` / `[ ]` row, see
[launcher.md](launcher.md)); a change takes effect on the next cockpit start
(no live re-apply into the running pane). When off, no `auto_suggest` is
attached and `AppendAutoSuggestion` is omitted, so `buffer.suggestion` stays
`None` and the Right/End accept branches below are inert.

When on, as the user types, the most recent history entry that starts with
the current buffer text is shown greyed inline after the cursor (fish-style),
via prompt_toolkit's `AutoSuggestFromHistory`. **No suggestion is shown until
at least 2 characters are typed** — a thin `_MinLenAutoSuggest` wrapper gates
on `len(document.text) < 2` and otherwise delegates to the inner
`AutoSuggestFromHistory`, so a single keystroke never fires off the full
history. It draws on the **same**
in-memory `history` list described above — a thin `_LiveHistory` (a
`History` subclass whose `get_strings()` returns the live list) is wired to
the buffer so there is no second history store. `BufferControl` does not
include the suggestion renderer by default, so `AppendAutoSuggestion` is
added to its `input_processors`; the grey is the default
`class:auto-suggestion` style (`#666666`).

- **Right** (at end-of-line) or **End** (cursor already at end) accepts the
  full suggestion into the buffer. It is NOT sent — Enter still sends.
  prompt_toolkit's default forward-char-or-accept binding is shadowed by
  this pane's own `right`/`end` handlers, so the accept is replicated there.
- **Tab is not bound to accept** — Tab remains a forwarded macro key to tt++
  (see Key forwarding policy / `FORWARDED_KEYS`).
- **No suggestion is shown in recall state** (whole-buffer selection after a
  send or Up/Down). This needs no custom suppression: every programmatic
  refill goes through the document setter, which fires `_text_changed()`
  (clearing `buffer.suggestion`), and the suggester only re-runs on
  `insert_text` — so a recall refill never produces a suggestion. The
  suggestion reappears once the user types fresh text.
- Backspace/Delete clear the current suggestion until the next inserted
  character (stock prompt_toolkit behaviour — the suggester is triggered only
  by `insert_text`).

## Clipboard operations

| Key    | Action                                                               |
|--------|----------------------------------------------------------------------|
| Ctrl+C | Copy selected text to system clipboard. No-op if no selection.       |
| Ctrl+X | Copy selected text to clipboard, then delete selection. No-op if no selection. |
| Ctrl+V | Paste clipboard text, replacing current selection (if any).          |

**Write path (OSC 52):** Ctrl+C and Ctrl+X write to the clipboard by
emitting an OSC 52 escape sequence. tmux (with `set-clipboard on`, set in
`bridge/launcher/tmux_start.sh`) forwards OSC 52 to the terminal emulator, which
sets the system clipboard. The same path tmux's `copy-pipe` already uses.

**Read path:** Ctrl+V resolves the clipboard via a platform-aware chain
inside `_read_clipboard()`:

1. **WSL fast path (win32yank).** When `/proc/version` contains
   `microsoft` (detected once at module load), the pane shells out to
   `~/MUME/bin/win32yank.exe -o --lf`. The `--lf` flag normalises
   Windows CRLF line endings to LF before insertion. On exit-0 the
   stdout is returned directly — paste is near-instant. The binary is
   provisioned by the installer, not a pip dependency.
2. **pyperclip fallback.** If the win32yank binary is missing, exits
   non-zero, or raises, the call falls through silently to
   `pyperclip.paste()`. No error is surfaced to the user. On WSL,
   pyperclip delegates to `powershell.exe Get-Clipboard` on first
   use (~200–500 ms one-off latency).
3. **Non-WSL (macOS, native Linux).** Behaviour is unchanged —
   `pyperclip.paste()` is called directly with no WSL probe.

`pyperclip` remains a required dependency for the fallback and for
non-WSL platforms:
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

`bridge/panes/input_pane.py` is the source of truth for the exact lists.

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

## Clock strip

A 7-column right-aligned clock occupies the rightmost end of the input pane's
single row, sharing it with the input buffer. The input buffer takes all
remaining width; the clock strip is a fixed-width `VSplit` sibling.

### Layout

`bridge/panes/input_pane.py` structures the Application layout as:

```
HSplit([
    VSplit([
        prompt_window,   # fixed width = 2 cols ("> "), FormattedTextControl
        input_window,    # flex width — prompt_toolkit BufferControl
        clock_window,    # fixed width = 7 cols, FormattedTextControl
    ]),
])
```

The `> ` prompt is a structural fixed-width sibling Window — not a
`BeforeInput` processor inside the BufferControl. Keeping it outside
the BufferControl's render domain means it cannot be pushed off by
the buffer's horizontal scroll when typed text exceeds the visible
input width. See [ADR 0068](decisions/0068-prompt-dedicated-window.md).

`mouse_support=True` is set on the Application — required for cursor
positioning inside the input buffer (consistent with `comm_pane`). Focus
never leaves the input buffer — `prompt_window` and `clock_window` are
both non-focusable.

The clock is rendered at every terminal width; there is no width-dependent
visibility gate.

### Visual layout

```
> <input flex…> 4:33☼
```

| Segment | Cols | Notes |
|---------|------|-------|
| ` ` | 1 | leading gutter |
| `<time>` | 5 | left-aligned time text, blank when unavailable |
| `<icon>` | 1 | day/night icon, blank when unavailable |

Total: 7 columns. When any of `time_period`, `time_transition_at`, or
`time_precision` is null, the clock strip renders as the 1-col gutter
followed by six blank spaces (matching the time+icon slot width).

### Clock

The clock renders the time remaining until the next day/night transition,
sourced from `bridge/runtime/status.state`:

| Field | Key in `status.state` |
|-------|----------------------|
| Period | `time_period` — `"day"` or `"night"` |
| Transition target | `time_transition_at` — unix epoch integer (or null) |
| Precision | `time_precision` — `"MINUTE"` or `"HOUR"` (or null) |

The renderer computes `remaining = max(0, time_transition_at - time.time())`
locally and formats per precision:

| `time_precision` | Format | Example |
|------------------|--------|---------|
| `"MINUTE"` | `total_min:sec` → `"H:MM"` | `"4:33"`, `"0:05"` |
| `"HOUR"` | `"~N"` (N = max(1, ceil(remaining/60))) | `"~3"` |

The icon is pinned to the rightmost column and `text` is left-aligned in the
preceding 5 columns, right-padded with spaces. E.g. `4:33 ☼` or `15:21☼`.
Time text is bold white. The sun icon (☼) is rendered in `#ffb000`; the
moon icon (☾) in `#4a90e2` — matching the status pane's Time row colours.

When any of `time_period`, `time_transition_at`, or `time_precision` is null
(precision below HOUR), or when `status.state` is missing or unreadable, the
clock area renders as six blank spaces. No partial value or lone icon is shown.

The renderer runs two asyncio tasks for clock updates:

- **`_poll_clock`** (250 ms mtime-based) — picks up changes to
  `time_transition_at` (rare: only on day/night flips or precision upgrades).
- **`_clock_tick`** (boundary-aligned 1 Hz) — wakes just after each wall-clock
  second boundary and calls `app.invalidate()`, so the countdown decrements at
  uniform cadence regardless of file-poll phase. Same pattern as the timers blink
  tick in `bridge/panes/timers_pane.py` (see [docs/timers-pane.md](timers-pane.md)).

See [ADR 0067](decisions/0067-remove-input-pane-buttons.md) for the
removal of the prior CHR/BUF/GRP/COM/UI button strip. Pane toggles are
covered by the popup Options menu and the `cp -X` aliases.

---
Back to [architecture.md](../architecture.md).
