try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.styles import Style
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:
    print("prompt_toolkit is required: pip install prompt_toolkit")
    exit(1)

import string
import subprocess

TMUX_TARGET = "mume:cockpit.0"

style = Style.from_dict({
    "default-text": "fg:ansiyellow",
})

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

def send(line):
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, line, "Enter"])

def main():
    global last_cmd
    session = PromptSession(key_bindings=kb)
    while True:
        try:
            text = session.prompt(
                "> ",
                default=last_cmd,
                style=style,
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
