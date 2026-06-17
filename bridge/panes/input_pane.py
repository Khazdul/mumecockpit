try:
    from prompt_toolkit import Application
    from prompt_toolkit.auto_suggest import AutoSuggest, AutoSuggestFromHistory
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.document import Document
    from prompt_toolkit.history import History
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
    from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.layout.processors import AppendAutoSuggestion
    from prompt_toolkit.keys import Keys
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
import math
import os
import signal
import string
import subprocess
import sys
import termios
import time

TMUX_TARGET = "mume:cockpit.0"
_PRINTABLE  = [c for c in string.printable if c.isprintable()]

BRIDGE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR       = os.path.join(BRIDGE_DIR, "runtime")
STATUS_STATE_PATH = os.path.join(RUNTIME_DIR, "status.state")
STARTUP_CONF_PATH = os.path.join(RUNTIME_DIR, "startup.conf")
CLOCK_POLL_MS     = 0.25
CLOCK_WIDTH       = 7   # 1 gutter + 5 time text + 1 icon
PROMPT_TEXT       = "> "
PROMPT_WIDTH      = len(PROMPT_TEXT)

# Sun/Moon colours — source of truth: bridge/panes/status_pane.py C_SUN / C_MOON
C_SUN_HEX  = "#ffb000"   # \x1b[38;2;255;176;0m
C_MOON_HEX = "#4a90e2"   # \x1b[38;2;74;144;226m

# Clock state — updated by _poll_clock asyncio task
_clock_time_period        = None
_clock_time_transition_at = None   # float (unix epoch) or None
_clock_time_precision     = None   # "MINUTE"/"HOUR"/None
_clock_status_mtime       = None

def _is_wsl():
    try:
        with open("/proc/version") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


_IS_WSL = _is_wsl()
_WIN32YANK_PATH = os.path.expanduser("~/MUME/bin/win32yank.exe")


last_cmd = ""
history: list = []           # sent commands, oldest -> newest
history_index = None         # None = at pending_input; else index into history
pending_input = ""           # draft saved when Up first pressed from None-state
_programmatic = False        # suppress on_text_changed during programmatic refills
_draft_restored = False      # True after Down steps out of history to pending_input
filter_prefix = None         # None = not filtered-browsing; str = locked prefix while filtered
_tab_completing = False      # True after a Tab word-accept until the next user edit


class _LiveHistory(History):
    """prompt_toolkit History view over the pane's in-memory `history` list,
    so AutoSuggestFromHistory draws on the SAME store the pane already keeps
    (no second history). get_strings() returns the live list oldest-first;
    AutoSuggestFromHistory reverses it, so the most recent matching entry wins.

    Buffer-side history loading/navigation is deliberately inert: this pane
    drives Up/Down itself (see _handle_up / _handle_down), so we yield nothing
    from load_history_strings and never store_string here."""

    def load_history_strings(self):
        return []

    def store_string(self, string):
        pass

    def get_strings(self):
        return list(history)


class _AfterSpaceAutoSuggest(AutoSuggest):
    """AutoSuggestFromHistory gated on the buffer containing a space: suppress
    any suggestion until a space has been typed, then delegate to a plain
    AutoSuggestFromHistory. A trailing space is sufficient — `kill ` suggests
    the most recent `kill ...` entry. Because the prefix includes the space,
    `kill ` matches `kill orc` but not `killer` — the space cleanly separates
    verb-completion from same-prefix words."""

    def __init__(self):
        self._inner = AutoSuggestFromHistory()

    def get_suggestion(self, buffer, document):
        if " " not in document.text:
            return None
        return self._inner.get_suggestion(buffer, document)


def _autosuggest_enabled():
    """Read `input_autosuggest` straight from bridge/runtime/startup.conf.

    Deliberately self-contained: no read_config.sh, no tt++ #var, no IPC —
    nothing on the hot path. Read once at startup; a change takes effect on
    the next cockpit start. Absent file / absent key / any non-"1" value →
    off (the default)."""
    try:
        with open(STARTUP_CONF_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == "input_autosuggest":
                    return val.strip() == "1"
    except OSError:
        pass
    return False


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
    if _IS_WSL:
        try:
            result = subprocess.run(
                [_WIN32YANK_PATH, "-o", "--lf"],
                capture_output=True, text=True, check=False,
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
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
    elif buf.suggestion and buf.suggestion.text:
        # At end-of-line with an inline history suggestion: accept it.
        # (Our binding shadows prompt_toolkit's default forward-char-or-accept,
        # so the accept is replicated here.)
        buf.insert_text(buf.suggestion.text)


@kb.add("home")
def _home(event):
    _drop_selection_to(event.current_buffer, 0)


@kb.add("end")
def _end(event):
    buf = event.current_buffer
    if (not _has_selection(buf)
            and buf.document.is_cursor_at_the_end
            and buf.suggestion and buf.suggestion.text):
        # Already at end-of-line with an inline history suggestion: accept it.
        buf.insert_text(buf.suggestion.text)
        return
    _drop_selection_to(buf, len(buf.text))


@kb.add("tab")
def _handle_tab(event):
    global _tab_completing
    buf = event.current_buffer
    if (not _has_selection(buf)
            and buf.document.is_cursor_at_the_end
            and buf.suggestion and buf.suggestion.text):
        # Suggestion acceptable — accept the NEXT WORD: leading whitespace
        # run + the following run of non-whitespace chars.
        sug = buf.suggestion.text
        n = len(sug)
        i = 0
        while i < n and sug[i].isspace():
            i += 1
        word_start = i
        while i < n and not sug[i].isspace():
            i += 1
        if word_start < n:
            # Non-empty word remains. Insert first, THEN set the flag:
            # insert_text fires the non-programmatic reset (clearing the
            # flag), so the handler must re-set it afterwards. The suggester
            # recomputes the remaining suggestion via the same sync path as
            # the Right/End full-accept.
            buf.insert_text(sug[:i])
            _tab_completing = True
        # Whitespace-only remainder → exhausted: no-op.
        return
    if _tab_completing:
        # A completion was just exhausted with no edit since — no-op.
        return
    # Not mid-completion: forward Tab to tt++ as a macro key.
    _snap_game_pane_to_tail()
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "Tab"])


@kb.add("up")
def _handle_up(event):
    global history_index, pending_input, _draft_restored, filter_prefix
    buf = event.app.current_buffer
    if not history:
        return
    if filter_prefix is not None:
        # Already filtered-browsing: step to the next OLDER match.
        for i in range(history_index - 1, -1, -1):
            if history[i].startswith(filter_prefix):
                history_index = i
                _set_buffer_text_selected(buf, history[i])
                return
        return  # no older match — stay on the current oldest match
    if buf.suggestion and buf.suggestion.text:
        # A suggestion is active: attempt to ENTER filtered browse.
        prefix = buf.text
        matches = [i for i in range(len(history) - 1, -1, -1)
                   if history[i].startswith(prefix)]
        if len(matches) >= 2:
            filter_prefix = prefix
            history_index = matches[1]
            _set_buffer_text_selected(buf, history[history_index])
        # len < 2: suggestion is the only match — no-op, leave buffer as-is.
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
    global history_index, pending_input, _draft_restored, filter_prefix
    buf = event.app.current_buffer
    if filter_prefix is not None:
        # Filtered-browsing: step to the next NEWER match.
        newer = None
        for i in range(history_index + 1, len(history)):
            if history[i].startswith(filter_prefix):
                newer = i
                break
        most_recent = max(i for i in range(len(history))
                          if history[i].startswith(filter_prefix))
        if newer is not None and newer != most_recent:
            history_index = newer
            _set_buffer_text_selected(buf, history[newer])
        else:
            # Only the suggested most-recent match is newer (or nothing is) —
            # return to the typed prefix and re-display its suggestion.
            prefix_text = filter_prefix
            filter_prefix = None
            history_index = None
            _draft_restored = False
            _set_buffer_text(buf, prefix_text)
            if buf.auto_suggest is not None:
                buf.suggestion = buf.auto_suggest.get_suggestion(buf, buf.document)
        return
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


def _select_to_start(buf):
    # cursor → start: selection [0, anchor], cursor at start.
    if not buf.text:
        return
    anchor = buf.cursor_position
    if anchor == 0:
        return
    buf.cursor_position = 0
    buf.selection_state = SelectionState(anchor)


def _select_to_end(buf):
    # cursor → end: selection [anchor, n], cursor at end.
    if not buf.text:
        return
    anchor = buf.cursor_position
    n = len(buf.text)
    if anchor == n:
        return
    buf.cursor_position = n
    buf.selection_state = SelectionState(anchor)


@kb.add("s-home")
def _handle_shift_home(event):
    _select_to_start(event.app.current_buffer)


@kb.add("s-up")
def _handle_shift_up(event):
    _select_to_start(event.app.current_buffer)


@kb.add("s-end")
def _handle_shift_end(event):
    _select_to_end(event.app.current_buffer)


@kb.add("s-down")
def _handle_shift_down(event):
    _select_to_end(event.app.current_buffer)


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
    global last_cmd, history_index, pending_input, _draft_restored, filter_prefix
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
        filter_prefix = None
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


def _snap_game_pane_to_tail():
    """If the game pane is scrolled (in copy-mode), exit it so delivered input
    reaches tt++ at the live tail instead of landing in copy-mode (which would
    raise the "(goto line)" prompt). Server-side gate via #{pane_in_mode} → a
    trivial no-op when not scrolled, so no extra round-trip or flicker at the
    live tail."""
    subprocess.run([
        "tmux", "if-shell", "-F", "-t", TMUX_TARGET, "#{pane_in_mode}",
        f"send-keys -t {TMUX_TARGET} -X cancel",
    ])


def send(line):
    _snap_game_pane_to_tail()
    # User-typed text MUST be sent literally (-l). Without it, tmux
    # interprets an argument that matches a key name (DC, Up, Tab,
    # Enter, F1, ...) as that KEY instead of as text — e.g. typing
    # "dc" sends the Delete key, not the command. `--` guards a line
    # beginning with "-". The trailing Enter is a SEPARATE call and
    # is intentionally NOT literal: it must register as the Enter key.
    if line:
        subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "-l", "--", line])
    subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, "Enter"])


# Keys forwarded to tt++ so that #macro bindings fire from the input pane.
# Reserved editing/history/scrollback keys are NOT listed here and remain
# handled by prompt_toolkit.
# c-c, c-x, c-v handle clipboard ops in the input pane and are not forwarded.
FORWARDED_KEYS = [
    ("f1", "F1"), ("f2", "F2"), ("f3", "F3"), ("f4", "F4"),
    ("f5", "F5"), ("f6", "F6"), ("f7", "F7"), ("f8", "F8"),
    ("f9", "F9"), ("f10", "F10"), ("f11", "F11"), ("f12", "F12"),

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
        _snap_game_pane_to_tail()
        subprocess.run(["tmux", "send-keys", "-t", TMUX_TARGET, tk])

for _letter in ALT_FORWARDED_LETTERS:
    @kb.add("escape", _letter)
    def _fwd_alt(event, lt=_letter):
        _snap_game_pane_to_tail()
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
        _snap_game_pane_to_tail()
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
    focus = os.path.expanduser("~/MUME/bridge/layout/focus_input.sh")
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

    # Drag-end fires on the release pane, not the drag-start pane. A drag
    # that starts in main/char/ui/dev and releases on input is not in copy-mode
    # at release time, so the copy-mode binding does not fire. Drop the gate:
    # any drag-end on input originated elsewhere and warrants sweep.
    subprocess.run([
        "tmux", "bind-key", "-n", "MouseDragEnd1Pane",
        f"run-shell '{focus} --sweep'",
    ])


def _restore_keypad():
    sys.stdout.write('\033>')
    sys.stdout.flush()


def _on_text_changed(buf):
    global history_index, pending_input, _draft_restored, filter_prefix
    global _tab_completing
    if _programmatic:
        return
    history_index = None
    pending_input = buf.text
    _draft_restored = False
    filter_prefix = None
    _tab_completing = False


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

def _clock_text():
    """Fragments for the 7-col right-aligned clock: ' <time><icon>'.

    Layout: 1-col gutter, 5-col left-aligned time text, 1-col day/night icon.
    Returns six trailing blanks when any of period / transition_at / precision
    is null.
    """
    frags = [("", " ")]  # 1-col leading gutter
    if (_clock_time_period is not None
            and _clock_time_transition_at is not None
            and _clock_time_precision is not None):
        icon       = "☼" if _clock_time_period == "day" else "☾"
        icon_style = f"fg:{C_SUN_HEX}" if _clock_time_period == "day" else f"fg:{C_MOON_HEX}"
        remaining  = max(0.0, _clock_time_transition_at - time.time())
        if _clock_time_precision == "MINUTE":
            total_min = int(remaining // 60)
            sec       = int(remaining % 60)
            text      = f"{total_min}:{sec:02d}"
        elif _clock_time_precision == "HOUR":
            rem_min = max(1, math.ceil(remaining / 60))
            text    = f"~{rem_min}"
        else:
            text = ""
        text = text[:5]
        frags.append(("bold fg:#ffffff", f"{text:<5}"))
        frags.append((icon_style, icon))
    else:
        frags.append(("", "      "))  # 6 blank spaces — same slot as time+icon
    return frags


# ---------------------------------------------------------------------------
# Clock state polling (250 ms asyncio task)
# ---------------------------------------------------------------------------

async def _clock_tick(app):
    """Invalidate just after each wall-clock second boundary so the clock countdown
    updates at uniform real-second cadence regardless of file-poll phase."""
    while True:
        now = time.time()
        sleep_s = 1.0 - (now - int(now))
        await asyncio.sleep(sleep_s + 0.01)
        app.invalidate()


async def _poll_clock(app):
    global _clock_time_period, _clock_time_transition_at, _clock_time_precision
    global _clock_status_mtime

    while True:
        changed = False

        # status.state — time_period, time_transition_at, time_precision
        try:
            smtime = os.stat(STATUS_STATE_PATH).st_mtime
        except OSError:
            smtime = None

        if smtime != _clock_status_mtime:
            _clock_status_mtime = smtime
            if smtime is not None:
                try:
                    with open(STATUS_STATE_PATH) as fh:
                        data = json.load(fh)
                    tp = data.get("time_period")
                    ta = data.get("time_transition_at")
                    pr = data.get("time_precision")
                    if tp != _clock_time_period or ta != _clock_time_transition_at or pr != _clock_time_precision:
                        _clock_time_period        = tp
                        _clock_time_transition_at = ta
                        _clock_time_precision     = pr
                        changed = True
                except Exception:
                    pass  # keep last good state; silent recovery
            else:
                if _clock_time_period is not None or _clock_time_transition_at is not None:
                    _clock_time_period        = None
                    _clock_time_transition_at = None
                    _clock_time_precision     = None
                    changed = True

        if changed:
            app.invalidate()

        await asyncio.sleep(CLOCK_POLL_MS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global last_cmd

    # Close the cooked-mode echo window. Until prompt_toolkit installs raw mode
    # inside app.run_async(), the tty stays in cooked mode with ECHO on. The gap
    # is dominated by setup_mouse_binding()'s synchronous `tmux bind-key`
    # subprocess calls; keys typed in that window are kernel-echoed (painting a
    # stray glyph left of the prompt) and queued in stdin (prepended to the first
    # command). Clearing ECHO as the very first action — before any subprocess —
    # suppresses the echo; the tcflush just before app.run_async() drains the
    # queued bytes. Restore on exit so we never leave the shell in -echo.
    try:
        _saved_termios = termios.tcgetattr(sys.stdin.fileno())
        _noecho = list(_saved_termios)
        _noecho[3] &= ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _noecho)
        atexit.register(
            termios.tcsetattr, sys.stdin.fileno(), termios.TCSANOW, _saved_termios
        )
    except (termios.error, OSError):
        pass

    setup_mouse_binding()

    # Enable keypad application mode so numpad keys send distinct escape
    # sequences (e.g. \eOq for KP1 vs '1'). Restored to numeric mode on exit.
    sys.stdout.write('\033=')
    sys.stdout.flush()
    atexit.register(_restore_keypad)

    # Opt-in inline history autosuggestion, gated by startup.conf
    # (default off). Read once here; no live re-read. When off, no
    # auto_suggest is attached and the append-suggestion processor is
    # omitted, so buf.suggestion stays None and the Right/End accept
    # branches are inert.
    autosuggest_on = _autosuggest_enabled()

    buf = Buffer(
        name="input",
        history=_LiveHistory(),
        auto_suggest=_AfterSpaceAutoSuggest() if autosuggest_on else None,
    )
    buf.on_text_changed += lambda _: _on_text_changed(buf)

    prompt_window = Window(
        content=FormattedTextControl(text=PROMPT_TEXT, focusable=False),
        width=PROMPT_WIDTH,
        height=1,
    )

    # Renders buffer.suggestion greyed (class:auto-suggestion) after the
    # cursor. Not in BufferControl's default processor set, so add it only
    # when autosuggest is enabled.
    input_processors = [AppendAutoSuggestion()] if autosuggest_on else []

    input_window = Window(
        BufferControl(
            buffer=buf,
            input_processors=input_processors,
        ),
        height=1,
    )

    clock_window = Window(
        content=FormattedTextControl(text=_clock_text, focusable=False),
        width=CLOCK_WIDTH,
        height=1,
    )

    layout = Layout(
        HSplit([
            VSplit([prompt_window, input_window, clock_window]),
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
        poll_task  = asyncio.ensure_future(_poll_clock(app))
        clock_task = asyncio.ensure_future(_clock_tick(app))
        try:
            await app.run_async()
        finally:
            for t in (poll_task, clock_task):
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    # Drain any keystrokes queued during the cooked-mode window and erase the
    # row so the initial render starts clean. Must be the last thing before
    # prompt_toolkit takes the tty — nothing that spawns a subprocess may run
    # between here and app.run_async().
    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (termios.error, OSError):
        pass
    sys.stdout.write('\r\x1b[2K')
    sys.stdout.flush()

    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
