try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.processors import Processor, Transformation
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import string
import subprocess

TMUX_TARGET = "mume:cockpit.0"

class HighlightLastCmd(Processor):
    def __init__(self, get_last_cmd):
        self.get_last_cmd = get_last_cmd

    def apply_transformation(self, ti):
        last = self.get_last_cmd()
        if ti.document.text == last and last:
            text = "".join(f[1] for f in ti.fragments)
            return Transformation([("bg:white fg:black", text)])
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

def send(line):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, line, "Enter"])

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

def main():
    global last_cmd
    setup_mouse_binding()
    session = PromptSession(
        input_processors=[HighlightLastCmd(lambda: last_cmd)],
        key_bindings=kb,
    )
    while True:
        try:
            text = session.prompt(
                "> ",
                default=last_cmd,
            )
        except (KeyboardInterrupt, EOFError):
            break
        if text:
            send(text)
            last_cmd = text
        elif last_cmd:
            send(last_cmd)

if __name__ == "__main__":
    main()