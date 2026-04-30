try:
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout.processors import BeforeInput
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output import ColorDepth
    from prompt_toolkit.selection import SelectionState
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit pyperclip --break-system-packages")
    exit(1)

import atexit
import asyncio
import base64
import json
import os
import signal
import string
import subprocess
import sys

TMUX_TARGET = "mume:cockpit.0"
_PRINTABLE  = [c for c in string.printable if c.isprintable()]

BRIDGE_DIR        = os.path.dirname(os.path.abspath(__file__))
STATUS_STATE_PATH = os.path.join(BRIDGE_DIR, "status.state")
STARTUP_CONF_PATH = os.path.join(BRIDGE_DIR, "startup.conf")
LAYOUT_CONF_PATH  = os.path.join(BRIDGE_DIR, "layout.conf")
MENU_POLL_MS      = 0.25
MENU_WIDTH        = 29

# Layout constants duplicated from bridge/on_window_resize.sh and
# bridge/apply_layout.sh. Keep in sync; see ADR 0031.
MAIN_MIN                = 30   # main/tt++ pane floor
RIGHT_FLOOR_WITH_STATUS = 29   # right column floor when status pane is open

# Button colours — toggle-state indicator
BTN_BG_ON  = "#006464"   # rgb(0,100,100) — ON state background
BTN_BG_OFF = "#003232"   # rgb(0,50,50)   — OFF state background
BTN_FG_ON  = "#d8d8d8"   # ON text — light grey, slightly brighter
BTN_FG_OFF = "#bfbfbf"   # OFF text — light grey

# Sun/Moon colours — source of truth: bridge/status_pane.py C_SUN / C_MOON
C_SUN_HEX  = "#ffb000"   # \x1b[38;2;255;176;0m
C_MOON_HEX = "#4a90e2"   # \x1b[38;2;74;144;226m

# Menu state — updated by _poll_menu asyncio task
_menu_time_period    = None
_menu_time_remaining = None
_menu_show_status    = False
_menu_show_comm      = False
_menu_show_ui        = False
_menu_ui_width       = 50
_menu_status_mtime   = None
_menu_conf_mtime     = None
_menu_layout_mtime   = None

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
        target = max(0, buf.cursor_position - 1)
        _drop_selection_to(buf, target)
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
    # Mirror wheel-up: enter copy-mode with auto-exit (-e), then scroll one
    # page up. copy-mode -e is idempotent — already-in-copy-mode is a no-op.
    # Page Down past bottom auto-exits and pane-mode-changed refocuses input.
    subprocess.run(["tmux", "copy-mode", "-e", "-t", TMUX_TARGET])
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "-X", "page-up"])


@kb.add("pagedown")
def _handle_pagedown(event):
    # Only scroll in copy-mode. At the live tail there is nothing below
    # the cursor — Page Down is a no-op.
    subprocess.run([
        "tmux", "if-shell",
        "-t", TMUX_TARGET,
        "-F", "#{pane_in_mode}",
        f"send-keys -t {TMUX_TARGET} -X page-down",
    ])


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


@kb.add("c-c", eager=True)
def _handle_ctrl_c(event):
    buf = event.app.current_buffer
    if not buf.selection_state:
        return
    a, b = buf.document.selection_range()
    text = buf.text[a:b]
    if text:
        _copy_to_clipboard(event, text)


@kb.add("c-x", eager=True)
def _handle_ctrl_x(event):
    buf = event.app.current_buffer
    if not buf.selection_state:
        return
    a, b = buf.document.selection_range()
    text = buf.text[a:b]
    if text:
        _copy_to_clipboard(event, text)
        buf.cut_selection()


@kb.add("c-v", eager=True)
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


@kb.add(Keys.BracketedPaste)
def _handle_bracketed_paste(event):
    """Terminal-level paste (Ctrl+Shift+V, middle-click). Replaces
    selection if any, then inserts at cursor — same semantics as Ctrl+V."""
    buf = event.current_buffer
    text = event.data
    if not text:
        return
    if _has_selection(buf):
        buf.cut_selection()
    buf.insert_text(text)


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


# ---------------------------------------------------------------------------
# Menu bar helpers
# ---------------------------------------------------------------------------

def _parse_startup_conf(path):
    conf = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key:
                    conf[key] = val.strip()
    except OSError:
        pass
    return conf


def _conf_bool(conf, key):
    try:
        return int(conf.get(key, "0")) != 0
    except (ValueError, TypeError):
        return False


def _make_btn_handler(pane):
    def _handler(mouse_event):
        if mouse_event.event_type != MouseEventType.MOUSE_DOWN:
            return
        subprocess.Popen([
            "bash", os.path.join(BRIDGE_DIR, "toggle_pane.sh"),
            pane, "--persist",
        ])
    return _handler


_BTN_STATUS = _make_btn_handler("status")
_BTN_COMM   = _make_btn_handler("comm")
_BTN_UI     = _make_btn_handler("ui")


def _menu_visible():
    try:
        cols = os.get_terminal_size().columns
    except OSError:
        return True
    floor = RIGHT_FLOOR_WITH_STATUS if _menu_show_status else _menu_ui_width
    return (cols - MAIN_MIN - 1) >= floor


def _menu_text():
    """Fragments for the 29-col right-aligned CHAR/BUFFS/COM/UI/clock menu bar.

    Layout: █CHAR▌█BUFFS▌█COM▌█UI█ <time> <icon>
    Total = 6+7+5+4+1+6 = 29 columns.
    """
    buttons = [
        ("CHAR",  _menu_show_status, _BTN_STATUS),
        ("BUFFS", False,             None),
        ("COM",   _menu_show_comm,   _BTN_COMM),
        ("UI",    _menu_show_ui,     _BTN_UI),
    ]
    frags    = []
    last_idx = len(buttons) - 1
    for i, (label, on, handler) in enumerate(buttons):
        bg         = BTN_BG_ON  if on else BTN_BG_OFF
        fg         = BTN_FG_ON  if on else BTN_FG_OFF
        trail      = "▌" if i == last_idx else "▌"
        btn_style  = f"bg:{bg} fg:{fg}"
        edge_style = f"fg:{bg}"
        frags.append((edge_style, "█"))
        if handler is not None:
            frags.append((btn_style, label, handler))
        else:
            frags.append((btn_style, label))
        frags.append((edge_style, trail))
    frags.append(("", " "))
    if _menu_time_period is not None and _menu_time_remaining is not None:
        icon       = "☼" if _menu_time_period == "day" else "☾"
        icon_style = f"fg:{C_SUN_HEX}" if _menu_time_period == "day" else f"fg:{C_MOON_HEX}"
        rem        = str(_menu_time_remaining)[:5]
        frags.append(("bold fg:#ffffff", f"{rem:<5}"))
        frags.append((icon_style, icon))
    else:
        frags.append(("", "      "))  # 6 blank spaces — same slot as time+icon
    return frags


# ---------------------------------------------------------------------------
# Menu state polling (250 ms asyncio task)
# ---------------------------------------------------------------------------

async def _poll_menu(app):
    global _menu_time_period, _menu_time_remaining
    global _menu_show_status, _menu_show_comm, _menu_show_ui, _menu_ui_width
    global _menu_status_mtime, _menu_conf_mtime, _menu_layout_mtime

    while True:
        changed = False

        # status.state — time_period and time_remaining
        try:
            smtime = os.stat(STATUS_STATE_PATH).st_mtime
        except OSError:
            smtime = None

        if smtime != _menu_status_mtime:
            _menu_status_mtime = smtime
            if smtime is not None:
                try:
                    with open(STATUS_STATE_PATH) as fh:
                        data = json.load(fh)
                    tp = data.get("time_period")
                    tr = data.get("time_remaining")
                    if tp != _menu_time_period or tr != _menu_time_remaining:
                        _menu_time_period    = tp
                        _menu_time_remaining = tr
                        changed = True
                except Exception:
                    pass  # keep last good state; silent recovery
            else:
                if _menu_time_period is not None or _menu_time_remaining is not None:
                    _menu_time_period    = None
                    _menu_time_remaining = None
                    changed = True

        # startup.conf — show_status, show_comm, show_ui
        try:
            cmtime = os.stat(STARTUP_CONF_PATH).st_mtime
        except OSError:
            cmtime = None

        if cmtime != _menu_conf_mtime:
            _menu_conf_mtime = cmtime
            conf = _parse_startup_conf(STARTUP_CONF_PATH)
            ss = _conf_bool(conf, "show_status")
            sc = _conf_bool(conf, "show_comm")
            su = _conf_bool(conf, "show_ui")
            if ss != _menu_show_status or sc != _menu_show_comm or su != _menu_show_ui:
                _menu_show_status = ss
                _menu_show_comm   = sc
                _menu_show_ui     = su
                changed = True

        # layout.conf — ui_width (controls menu visibility floor)
        try:
            lmtime = os.stat(LAYOUT_CONF_PATH).st_mtime
        except OSError:
            lmtime = None

        if lmtime != _menu_layout_mtime:
            _menu_layout_mtime = lmtime
            if lmtime is not None:
                lconf = _parse_startup_conf(LAYOUT_CONF_PATH)
                try:
                    uw = int(lconf.get("ui_width", 50))
                except (ValueError, TypeError):
                    uw = 50
                if uw != _menu_ui_width:
                    _menu_ui_width = uw
                    changed = True

        if changed:
            app.invalidate()

        await asyncio.sleep(MENU_POLL_MS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    input_window = Window(
        BufferControl(
            buffer=buf,
            input_processors=[
                BeforeInput("> "),
            ],
        ),
        height=1,
    )

    menu_window = Window(
        content=FormattedTextControl(text=_menu_text, focusable=False),
        width=MENU_WIDTH,
        height=1,
    )

    menu_container = ConditionalContainer(
        content=menu_window,
        filter=Condition(_menu_visible),
    )

    layout = Layout(
        HSplit([
            VSplit([input_window, menu_container]),
        ])
    )

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        mouse_support=True,
        color_depth=ColorDepth.DEPTH_24_BIT,
    )

    async def _run():
        task = asyncio.ensure_future(_poll_menu(app))
        try:
            await app.run_async()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
