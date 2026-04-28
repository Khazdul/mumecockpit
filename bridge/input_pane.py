try:
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import BufferControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.layout.processors import BeforeInput
    from prompt_toolkit.selection import SelectionState
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit pyperclip --break-system-packages")
    exit(1)

import atexit
import base64
import os
import string
import subprocess
import sys

TMUX_TARGET = "mume:cockpit.0"
_PRINTABLE = [c for c in string.printable if c.isprintable()]

last_cmd = ""
history: list = []           # sent commands, oldest -> newest
history_index = None         # None = at pending_input; else index into history
pending_input = ""           # draft saved when Up first pressed from None-state
_programmatic = False        # suppress on_text_changed during programmatic refills
_draft_restored = False      # True after Down steps out of history to pending_input


def _set_buffer_text(buf, text, cursor_pos=None):
    """Set buffer text and cursor, no selection. For draft restore and clearing."""
    global _programmatic
    _programmatic = True
    try:
        pos = len(text) if cursor_pos is None else cursor_pos
        buf.document = Document(text, pos)
        buf.selection_state = None
    finally:
        _programmatic = False


def _set_buffer_text_selected(buf, text, cursor_at_start=False):
    """Set buffer text and select the whole buffer (recall state)."""
    global _programmatic
    _programmatic = True
    try:
        pos = 0 if cursor_at_start else len(text)
        buf.document = Document(text, pos)
        if text:
            buf.selection_state = SelectionState(len(text) if cursor_at_start else 0)
        else:
            buf.selection_state = None
    finally:
        _programmatic = False


def _is_fully_selected(buf):
    if not buf.text or buf.selection_state is None:
        return False
    a, b = buf.document.selection_range()
    return a == 0 and b == len(buf.text)


def _has_selection(buf):
    return buf.selection_state is not None and buf.text != ""


def _drop_selection_to(buf, position):
    buf.selection_state = None
    buf.cursor_position = max(0, min(position, len(buf.text)))


def _replace_selection(buf, text):
    if _has_selection(buf):
        buf.cut_selection()
    buf.insert_text(text)


def _copy_to_clipboard(event, text):
    if not text:
        return
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    seq = f"\033]52;c;{encoded}\007"
    out = event.app.output
    out.write_raw(seq)
    out.flush()


def _read_clipboard():
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        return ""


kb = KeyBindings()

for _c in _PRINTABLE:
    @kb.add(_c)
    def _handle_printable(event, c=_c):
        _replace_selection(event.current_buffer, c)


@kb.add("backspace")
def _backspace(event):
    buf = event.current_buffer
    if _has_selection(buf):
        buf.cut_selection()
    else:
        buf.delete_before_cursor()


@kb.add("delete")
def _delete(event):
    buf = event.current_buffer
    if _has_selection(buf):
        buf.cut_selection()
    else:
        buf.delete()


@kb.add("left")
def _left(event):
    buf = event.current_buffer
    if _has_selection(buf):
        a, _ = buf.document.selection_range()
        _drop_selection_to(buf, a)
    elif buf.cursor_position > 0:
        buf.cursor_position -= 1


@kb.add("right")
def _right(event):
    buf = event.current_buffer
    if _has_selection(buf):
        _, b = buf.document.selection_range()
        _drop_selection_to(buf, b)
    elif buf.cursor_position < len(buf.text):
        buf.cursor_position += 1


@kb.add("home")
def _home(event):
    _drop_selection_to(event.current_buffer, 0)


@kb.add("end")
def _end(event):
    buf = event.current_buffer
    _drop_selection_to(buf, len(buf.text))


@kb.add("up")
def _handle_up(event):
    global history_index, pending_input, _draft_restored
    buf = event.app.current_buffer
    if not history:
        return
    _draft_restored = False
    if _is_fully_selected(buf) and history_index is None:
        # Just refilled after Enter — step back one entry.
        history_index = max(0, len(history) - 2)
    elif history_index is None:
        # Not browsing. Save current as draft.
        pending_input = buf.text
        history_index = len(history) - 1
    else:
        history_index = max(0, history_index - 1)
    _set_buffer_text_selected(buf, history[history_index])


@kb.add("down")
def _handle_down(event):
    global history_index, pending_input, _draft_restored
    buf = event.app.current_buffer
    if _draft_restored:
        # Second Down after returning to draft — clear buffer.
        _draft_restored = False
        pending_input = ""
        _set_buffer_text(buf, "")
        return
    if history_index is None:
        return
    if history_index < len(history) - 1:
        history_index += 1
        _set_buffer_text_selected(buf, history[history_index])
    else:
        # At newest — step out to pending_input.
        history_index = None
        _draft_restored = True
        _set_buffer_text(buf, pending_input)


@kb.add("s-home")
def _handle_shift_home(event):
    buf = event.app.current_buffer
    if buf.text:
        _set_buffer_text_selected(buf, buf.text, cursor_at_start=True)


@kb.add("s-end")
def _handle_shift_end(event):
    buf = event.app.current_buffer
    if buf.text:
        _set_buffer_text_selected(buf, buf.text)


@kb.add("c-a")
def _handle_ctrl_a(event):
    buf = event.app.current_buffer
    if buf.text:
        _set_buffer_text_selected(buf, buf.text)


@kb.add("pageup")
def _handle_pageup(event):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "PageUp"])


@kb.add("pagedown")
def _handle_pagedown(event):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "PageDown"])


@kb.add("enter")
def _handle_enter(event):
    global last_cmd, history_index, pending_input, _draft_restored
    buf = event.app.current_buffer
    text = buf.text
    if text:
        send(text)
        last_cmd = text
        if not history or history[-1] != text:
            history.append(text)
        buf.reset()
        history_index = None
        pending_input = ""
        _draft_restored = False
        _set_buffer_text_selected(buf, last_cmd)
    else:
        # Empty Enter — bare newline to tt++ (MUME uses this to
        # cancel delayed commands). No refill, no last_cmd repeat.
        send("")


@kb.add("c-c")
def _handle_ctrl_c(event):
    buf = event.app.current_buffer
    if not buf.selection_state:
        return
    a, b = buf.document.selection_range()
    text = buf.text[a:b]
    if text:
        _copy_to_clipboard(event, text)


@kb.add("c-x")
def _handle_ctrl_x(event):
    buf = event.app.current_buffer
    if not buf.selection_state:
        return
    a, b = buf.document.selection_range()
    text = buf.text[a:b]
    if text:
        _copy_to_clipboard(event, text)
        buf.cut_selection()


@kb.add("c-v")
def _handle_ctrl_v(event):
    buf = event.app.current_buffer
    text = _read_clipboard()
    if not text:
        return
    if _has_selection(buf):
        buf.cut_selection()
    buf.insert_text(text)


@kb.add("c-d")
def _handle_ctrl_d(event):
    pass  # no-op; prevent EOFError from exiting the pane


def send(line):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, line, "Enter"])


# Keys forwarded to tt++ so that #macro bindings fire from the input pane.
# Reserved editing/history/scrollback keys are NOT listed here and remain
# handled by prompt_toolkit.
# c-c, c-x, c-v handle clipboard ops in the input pane and are not forwarded.
FORWARDED_KEYS = [
    ("f1", "F1"), ("f2", "F2"), ("f3", "F3"), ("f4", "F4"),
    ("f5", "F5"), ("f6", "F6"), ("f7", "F7"), ("f8", "F8"),
    ("f9", "F9"), ("f10", "F10"), ("f11", "F11"), ("f12", "F12"),
    ("tab", "Tab"),

    # Ctrl+letter (safe subset — excludes editing/history/terminal-reserved)
    ("c-g", "C-g"), ("c-l", "C-l"), ("c-o", "C-o"),
]

# Alt+letter forwarded set (excludes b, d, f which are reserved for word ops).
# "o" is intentionally excluded — collides with numpad-division
# sequence \eOo in prompt_toolkit's key parser. All other letters
# that share their final character with an SS3 numpad sequence
# have been verified not to collide.
ALT_FORWARDED_LETTERS = [
    "a", "c", "e", "g", "h", "i", "j", "k", "l", "m",
    "n", "p", "q", "r", "s", "t", "u", "v", "w",
    "x", "y", "z",
]

for _pt_key, _tmux_key in FORWARDED_KEYS:
    @kb.add(_pt_key)
    def _fwd(event, tk=_tmux_key):
        subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, tk])

for _letter in ALT_FORWARDED_LETTERS:
    @kb.add("escape", _letter)
    def _fwd_alt(event, lt=_letter):
        subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, f"M-{lt}"])

# Numpad in DECKPAM (keypad application mode) sends SS3 sequences.
# prompt_toolkit has no named keys for these — we bind the raw
# escape sequence via the multi-key tuple form.
NUMPAD_FORWARDED_KEYS = [
    # (prompt_toolkit multi-key tuple, tmux key name)
    (("escape", "O", "p"), "KP0"),
    (("escape", "O", "q"), "KP1"),
    (("escape", "O", "r"), "KP2"),
    (("escape", "O", "s"), "KP3"),
    (("escape", "O", "t"), "KP4"),
    (("escape", "O", "u"), "KP5"),
    (("escape", "O", "v"), "KP6"),
    (("escape", "O", "w"), "KP7"),
    (("escape", "O", "x"), "KP8"),
    (("escape", "O", "y"), "KP9"),
    (("escape", "O", "n"), "KP."),
    (("escape", "O", "M"), "KPEnter"),
    (("escape", "O", "j"), "KP*"),
    (("escape", "O", "k"), "KP+"),
    (("escape", "O", "m"), "KP-"),
    (("escape", "O", "o"), "KP/"),
]

for _seq, _kp_key in NUMPAD_FORWARDED_KEYS:
    @kb.add(*_seq)
    def _fwd_kp(event, tk=_kp_key):
        subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, tk])


def get_input_pane_index():
    result = subprocess.run(
        ["tmux", "list-panes", "-t", "mume:cockpit",
         "-F", "#{pane_index} #{pane_title}"],
        capture_output=True, text=True
    )
    for line in result.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1] == "input":
            return parts[0]
    return None


def setup_mouse_binding():
    if get_input_pane_index() is None:
        return
    focus = os.path.expanduser("~/MUME/bridge/focus_input.sh")
    not_input = '[ "#{pane_title}" != "input" ]'

    # Click without drag: just refocus the input pane.
    subprocess.run([
        "tmux", "bind-key", "-n", "MouseUp1Pane",
        "if-shell", not_input, f"run-shell {focus}",
    ])

    # Drag-end fires from the copy-mode table because the drag
    # transitioned the pane into copy-mode. Override the copy-mode
    # default to add the refocus step.
    subprocess.run([
        "tmux", "bind-key", "-T", "copy-mode", "MouseDragEnd1Pane",
        f"send-keys -X copy-pipe-and-cancel ; run-shell {focus}",
    ])


def _restore_keypad():
    sys.stdout.write('\033>')
    sys.stdout.flush()


def _on_text_changed(buf):
    global history_index, pending_input, _draft_restored
    if _programmatic:
        return
    history_index = None
    pending_input = buf.text
    _draft_restored = False


def main():
    global last_cmd
    setup_mouse_binding()

    # Enable keypad application mode so numpad keys send distinct escape
    # sequences (e.g. \eOq for KP1 vs '1'). Restored to numeric mode on exit.
    sys.stdout.write('\033=')
    sys.stdout.flush()
    atexit.register(_restore_keypad)

    buf = Buffer(name="input")
    buf.on_text_changed += lambda _: _on_text_changed(buf)

    layout = Layout(
        HSplit([
            Window(
                BufferControl(
                    buffer=buf,
                    input_processors=[
                        BeforeInput("> "),
                    ],
                    key_bindings=kb,
                ),
                height=1,
            )
        ])
    )

    app = Application(layout=layout, full_screen=False)

    try:
        app.run()
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
