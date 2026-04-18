try:
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import BufferControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.layout.processors import BeforeInput, Processor, Transformation
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import atexit
import string
import subprocess
import sys

TMUX_TARGET = "mume:cockpit.0"

class HighlightLastCmd(Processor):
    def __init__(self, get_last_cmd):
        self.get_last_cmd = get_last_cmd

    def apply_transformation(self, ti):
        last = self.get_last_cmd()
        if ti.document.text == last and last:
            return Transformation([
                ("bg:white fg:black", text)
                for _, text in ti.fragments
            ])
        return Transformation(ti.fragments)

last_cmd = ""

kb = KeyBindings()

_PRINTABLE = [c for c in string.printable if c not in string.whitespace]

for _c in _PRINTABLE:
    @kb.add(_c)
    def _handle(event, c=_c):
        buf = event.app.current_buffer
        if buf.text == last_cmd and last_cmd:
            buf.reset()
        buf.insert_text(c)

@kb.add("backspace")
def _handle_backspace(event):
    buf = event.app.current_buffer
    if buf.text == last_cmd and last_cmd:
        buf.reset()
    else:
        buf.delete_before_cursor()

@kb.add("delete")
def _handle_delete(event):
    buf = event.app.current_buffer
    if buf.text == last_cmd and last_cmd:
        buf.reset()
    else:
        buf.delete()

@kb.add("pageup")
def _handle_pageup(event):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "PageUp"])

@kb.add("pagedown")
def _handle_pagedown(event):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "PageDown"])

@kb.add("enter")
def _handle_enter(event):
    global last_cmd
    buf = event.app.current_buffer
    text = buf.text
    if text:
        send(text)
        last_cmd = text
    elif last_cmd:
        send(last_cmd)
    buf.reset()
    if last_cmd:
        buf.set_document(Document(last_cmd), bypass_readonly=True)

def send(line):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, line, "Enter"])

# Keys forwarded to tt++ so that #macro bindings fire from the input pane.
# Reserved editing/history/scrollback keys are NOT listed here and remain
# handled by prompt_toolkit.
FORWARDED_KEYS = [
    ("f1", "F1"), ("f2", "F2"), ("f3", "F3"), ("f4", "F4"),
    ("f5", "F5"), ("f6", "F6"), ("f7", "F7"), ("f8", "F8"),
    ("f9", "F9"), ("f10", "F10"), ("f11", "F11"), ("f12", "F12"),

    # Ctrl+letter (safe subset — excludes editing/history/terminal-reserved)
    ("c-g", "C-g"), ("c-l", "C-l"), ("c-o", "C-o"),
    ("c-v", "C-v"), ("c-x", "C-x"),
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
    index = get_input_pane_index()
    if index is None:
        return
    subprocess.run([
        "tmux", "bind-key", "-n", "MouseUp1Pane",
        "if-shell",
        "[ \"#{pane_title}\" != \"input\" ]",
        "select-pane -t mume:cockpit." + index
    ])

def _restore_keypad():
    sys.stdout.write('\033>')
    sys.stdout.flush()

def main():
    global last_cmd
    setup_mouse_binding()

    # Enable keypad application mode so numpad keys send distinct escape
    # sequences (e.g. \eOq for KP1 vs '1'). Restored to numeric mode on exit.
    sys.stdout.write('\033=')
    sys.stdout.flush()
    atexit.register(_restore_keypad)

    buf = Buffer(name="input")

    layout = Layout(
        HSplit([
            Window(
                BufferControl(
                    buffer=buf,
                    input_processors=[
                        HighlightLastCmd(lambda: last_cmd),
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
