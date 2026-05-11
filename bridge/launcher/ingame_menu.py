#!/usr/bin/env python3
# bridge/launcher/ingame_menu.py — in-game popup menu (prompt_toolkit rewrite).
# Launched via tmux display-popup. Do not invoke directly outside that context.
# Behavioural contract: docs/popup-menu.md.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import DynamicContainer, Layout
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import asyncio
import atexit
import os
import shutil
import signal
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BRIDGE_DIR            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR           = os.path.join(BRIDGE_DIR, "runtime")
POPUP_SENTINEL        = os.path.join(RUNTIME_DIR, ".popup_open")
RETURN_TO_MENU_SENT   = os.path.join(RUNTIME_DIR, ".return_to_menu")
CONNECTION_STATE_PATH = os.path.join(RUNTIME_DIR, "connection.state")
PING_CACHE_PATH       = os.path.join(RUNTIME_DIR, "ping.cache")
STARTUP_CONF_PATH     = os.path.join(RUNTIME_DIR, "startup.conf")
SCRIPTS_CACHE_PATH    = os.path.join(RUNTIME_DIR, "scripts.cache")
TOGGLE_PANE_SCRIPT    = os.path.join(BRIDGE_DIR, "layout", "toggle_pane.sh")

TMUX_TARGET  = "mume:cockpit.0"
TMUX_SESSION = "mume:cockpit"
TMUX_OPTROOT = "mume"

# ---------------------------------------------------------------------------
# Colour palette (translated from menu_render.sh _MR_* ANSI constants)
# ---------------------------------------------------------------------------
C_TITLE   = "bold fg:#00d7d7"   # _MR_TITLE  — cyan
C_ACTIVE  = "bold fg:#ffffff"   # _MR_ACTIVE — bright white
C_ITEM    = "fg:#bcbcbc"        # _MR_ITEM   — colour 250
C_BODY    = "fg:#8a8a8a"        # _MR_BODY   — colour 245
C_HINT    = "fg:#585858"        # _MR_HINT   — dim, colour 240
C_ACCENT  = "bold fg:#ffaf00"   # _MR_ACCENT — colour 214, bold
C_YELLOW  = "bold fg:#ffd75f"   # _MR_YELLOW
C_ERR     = "bold fg:#ff5f5f"   # _MR_ERR

# ---------------------------------------------------------------------------
# ASCII title (mirrors menu_render.sh draw_ascii_title)
# ---------------------------------------------------------------------------
_MUME_LINES = [
    '███╗   ███╗██╗   ██╗███╗   ███╗███████╗',
    '████╗ ████║██║   ██║████╗ ████║██╔════╝',
    '██╔████╔██║██║   ██║██╔████╔██║█████╗  ',
    '██║╚██╔╝██║██║   ██║██║╚██╔╝██║██╔══╝  ',
    '██║ ╚═╝ ██║╚██████╔╝██║ ╚═╝ ██║███████╗',
    '╚═╝     ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝',
]
_COCKPIT_LINES = [
    '██ ███ ██ █ █ ██ █ ███',
    '█  █ █ █  ██  ██ █  █ ',
    '██ ███ ██ █ █ █  █  █ ',
]

# ---------------------------------------------------------------------------
# Options frame: tmux pane name -> label (order matters for navigation)
# ---------------------------------------------------------------------------
_PANE_TOGGLES = [
    ("status",  "Character pane"),
    ("buffs",   "Buffs pane"),
    ("group",   "Group pane"),
    ("comm",    "Comm pane"),
    ("ui",      "UI pane"),
    ("dev",     "Dev pane"),
    ("headers", "Pane dividers"),
]

# ---------------------------------------------------------------------------
# Mutable application state
# ---------------------------------------------------------------------------
_current_frame    = "main"
_frame_stack      = []          # navigation stack: [(frame, ...) for ancestor frames]
_sel_main         = 0
_sel_options      = 0
_options_scroll   = 0
_scripts_scroll   = 0
_save_flash_until = 0.0
_app              = None
_options_window   = None        # set in main(); referenced for render_info
_scripts_window   = None        # set in main(); referenced for render_info


# ---------------------------------------------------------------------------
# Terminal dimensions
# ---------------------------------------------------------------------------
def _term_cols():
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80


def _term_rows():
    try:
        return shutil.get_terminal_size().lines
    except OSError:
        return 24


# ---------------------------------------------------------------------------
# File helpers (silent on parse/IO errors)
# ---------------------------------------------------------------------------
def _parse_keyval(path):
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k:
                    out[k] = v.strip()
    except OSError:
        pass
    return out


def _is_connected():
    if not os.path.exists(CONNECTION_STATE_PATH):
        return False
    data = _parse_keyval(CONNECTION_STATE_PATH)
    ca = data.get("connected_at", "")
    try:
        return int(ca) > 0
    except (TypeError, ValueError):
        return False


def _write_sentinel(path):
    try:
        with open(path, "w"):
            pass
    except OSError:
        pass


def _remove_sentinel(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# tmux probes / dispatch (1 s timeout, silent failure)
# ---------------------------------------------------------------------------
def _tmux_pane_titles():
    try:
        r = subprocess.run(
            ["tmux", "list-panes", "-t", TMUX_SESSION, "-F", "#{pane_title}"],
            capture_output=True, text=True, timeout=1.0,
        )
        return [ln for ln in r.stdout.splitlines() if ln]
    except (subprocess.SubprocessError, OSError):
        return []


def _tmux_border_status():
    try:
        r = subprocess.run(
            ["tmux", "show-option", "-t", TMUX_OPTROOT, "pane-border-status"],
            capture_output=True, text=True, timeout=1.0,
        )
        parts = r.stdout.strip().split()
        if len(parts) >= 2:
            return parts[1]
    except (subprocess.SubprocessError, OSError):
        pass
    return "off"


def _send_to_game(cmd):
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", TMUX_TARGET, cmd, "C-m"],
            timeout=1.0,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def _toggle_pane(target):
    try:
        subprocess.run(
            ["bash", TOGGLE_PANE_SCRIPT, target, "--persist"],
            timeout=5.0,
        )
    except (subprocess.SubprocessError, OSError):
        pass


# ---------------------------------------------------------------------------
# Frame stack
# ---------------------------------------------------------------------------
def _push_frame(frame):
    global _current_frame
    _frame_stack.append(_current_frame)
    _current_frame = frame
    if _app:
        _app.invalidate()


def _pop_frame():
    global _current_frame
    if _frame_stack:
        _current_frame = _frame_stack.pop()
    else:
        _current_frame = "main"
    if _app:
        _app.invalidate()


# ---------------------------------------------------------------------------
# Centering helper
# ---------------------------------------------------------------------------
def _pad_centre(text, cols=None):
    if cols is None:
        cols = _term_cols()
    n = max(0, (cols - len(text)) // 2)
    return " " * n


# ---------------------------------------------------------------------------
# Main frame
# ---------------------------------------------------------------------------
def _main_items():
    if _is_connected():
        return [
            ("Continue",     "continue"),
            ("Reconnect",    "reconnect"),
            ("Save profile", "save"),
            ("Options",      "options"),
            ("Scripts",      "scripts"),
            ("Exit session", "exit"),
        ]
    return [
        ("Reconnect",    "reconnect"),
        ("Save profile", "save"),
        ("Options",      "options"),
        ("Scripts",      "scripts"),
        ("Exit session", "exit"),
    ]


def _activate_main_item(action):
    global _save_flash_until, _scripts_scroll, _options_scroll, _sel_options
    if action == "continue":
        _app.exit()
    elif action == "reconnect":
        _send_to_game("reconnect")
        _app.exit()
    elif action == "save":
        _send_to_game("cp -s")
        _save_flash_until = time.monotonic() + 1.0
        if _app:
            _app.invalidate()
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(1.05, _app.invalidate)
            except RuntimeError:
                pass
    elif action == "options":
        _options_scroll = 0
        _sel_options = 0
        _push_frame("options")
    elif action == "scripts":
        _scripts_scroll = 0
        _push_frame("scripts")
    elif action == "exit":
        _push_frame("exit_confirm")


def _main_text():
    cols  = _term_cols()
    frags = []

    # ASCII title
    frags.append(("", "\n"))
    for line in _MUME_LINES:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((C_TITLE, line))
        frags.append(("", "\n"))
    for line in _COCKPIT_LINES:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((C_TITLE, line))
        frags.append(("", "\n"))
    frags.append(("", "\n"))

    # Status header
    conf = _parse_keyval(STARTUP_CONF_PATH)
    profile    = conf.get("profile") or "default"
    conn_mode  = conf.get("connection_mode") or "mmapper"
    mode_label = "Direct" if conn_mode == "direct" else "MMapper"

    connected = _is_connected()
    base = (f"Profile: {profile}  ·  {mode_label}"
            if connected else
            f"Profile: {profile}  ·  Disconnected")

    ping    = _parse_keyval(PING_CACHE_PATH) if os.path.exists(PING_CACHE_PATH) else {}
    latest  = ping.get("latest", "")
    quality = ping.get("quality", "")

    plain = base
    if latest:
        plain += "  ·  Link: " + ("timeout" if latest == "TIMEOUT" else f"{latest}ms")
        if quality:
            plain += f" ({quality})"
    frags.append(("", _pad_centre(plain, cols)))
    frags.append((C_BODY, base))
    if latest:
        frags.append((C_BODY, "  ·  Link: "))
        if latest == "TIMEOUT":
            frags.append((C_ERR, "timeout"))
        else:
            frags.append((C_BODY, f"{latest}ms"))
        if quality:
            if quality in ("stable", "ok"):
                q_style = C_BODY
            elif quality in ("jittery", "spiking"):
                q_style = C_YELLOW
            else:
                q_style = C_ERR
            frags.append((C_BODY, " ("))
            frags.append((q_style, quality))
            frags.append((C_BODY, ")"))
    frags.append(("", "\n\n"))

    # Menu rows
    items   = _main_items()
    sel_idx = _sel_main
    if sel_idx >= len(items):
        sel_idx = len(items) - 1
    flash_active = time.monotonic() < _save_flash_until

    for i, (label, action) in enumerate(items):
        is_active = (i == sel_idx)
        if action == "save" and flash_active:
            display = "Saved ✓"
            style   = C_ACCENT
        else:
            display = label
            style   = C_ACTIVE if is_active else C_ITEM
        prefix = "<< " if is_active else "   "
        suffix = " >>" if is_active else "   "
        full   = f"{prefix}{display}{suffix}"

        def _make_handler(idx=i, act=action):
            def _handler(ev):
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _sel_main
                _sel_main = idx
                _activate_main_item(act)
                if _app:
                    _app.invalidate()
            return _handler

        h = _make_handler()
        frags.append(("", _pad_centre(full, cols)))
        frags.append((style, prefix, h))
        frags.append((style, display, h))
        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))

    # Footer
    footer = "↑↓ Navigate · Enter Select · ESC Dismiss"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))

    return frags


# ---------------------------------------------------------------------------
# Options frame
# ---------------------------------------------------------------------------
def _options_rows():
    """Return list of (kind, payload) describing each row in order.
    kinds:
      "pane"      payload=(target, label)
      "sep"
      "back"
    """
    rows = []
    for target, label in _PANE_TOGGLES:
        rows.append(("pane", (target, label)))
    rows.append(("back", None))
    return rows


def _options_selectable_indices():
    """Indices in _options_rows() that are user-selectable (skip separators)."""
    return [i for i, (k, _) in enumerate(_options_rows()) if k != "sep"]


def _options_activate(row_idx):
    rows = _options_rows()
    if not (0 <= row_idx < len(rows)):
        return
    kind, payload = rows[row_idx]
    if kind == "pane":
        target, _ = payload
        _toggle_pane(target)
        if _app:
            _app.invalidate()
    elif kind == "back":
        _pop_frame()


def _options_title_text():
    cols  = _term_cols()
    title = "─── Options ───"
    return [
        ("", "\n\n"),
        ("", _pad_centre(title, cols)),
        (C_TITLE, title),
        ("", "\n"),
    ]


def _options_content_text():
    cols       = _term_cols()
    rows       = _options_rows()
    titles_set = set(_tmux_pane_titles())
    headers_on = (_tmux_border_status() != "off")

    # Build labels for width measurement (uncentred, fixed-width column)
    labels = []
    for kind, payload in rows:
        if kind == "pane":
            target, lbl = payload
            if target == "headers":
                on = headers_on
            else:
                on = (target in titles_set)
            box = "[x]" if on else "[ ]"
            labels.append(f"{box} {lbl}")
        elif kind == "sep":
            labels.append("")
        elif kind == "back":
            labels.append("    Back")

    maxw = max((len(l) for l in labels), default=0)
    pad  = max(0, (cols - (maxw + 6)) // 2)   # +6 for "<< ... >>" decoration

    frags = []
    sel   = _sel_options
    sel_indices = _options_selectable_indices()
    if sel >= len(sel_indices):
        sel = len(sel_indices) - 1
    sel_row = sel_indices[sel] if sel_indices else -1

    for i, (kind, payload) in enumerate(rows):
        if kind == "sep":
            frags.append(("", "\n"))
            continue

        label    = labels[i]
        is_active = (i == sel_row)
        style    = C_ACTIVE if is_active else C_ITEM
        prefix   = "<< " if is_active else "   "
        suffix   = " >>" if is_active else "   "

        def _make_handler(row_idx=i, sel_pos=sel_indices.index(i) if i in sel_indices else 0):
            def _handler(ev):
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _sel_options
                _sel_options = sel_pos
                _options_activate(row_idx)
                if _app:
                    _app.invalidate()
            return _handler

        h = _make_handler()
        frags.append(("", " " * pad))
        frags.append((style, prefix, h))
        frags.append((style, label, h))
        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    return frags


def _options_footer_text():
    cols   = _term_cols()
    footer = "↑↓ Navigate · Enter/Space Toggle · ESC Back"
    return [
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ]


# ---------------------------------------------------------------------------
# Scripts frame
# ---------------------------------------------------------------------------
def _scripts_parsed_lines():
    """Read scripts.cache and return list of (tag, text) tuples,
    matching the bash format A:/S:/H:/B:/M:."""
    out = []
    if not os.path.exists(SCRIPTS_CACHE_PATH) or os.path.getsize(SCRIPTS_CACHE_PATH) == 0:
        out.append(("M", "No scripts cached yet — start the client once to populate."))
        return out
    in_script = False
    try:
        with open(SCRIPTS_CACHE_PATH) as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("SCRIPT:"):
                    if in_script:
                        out.append(("B", ""))
                    in_script = True
                    out.append(("A", line[len("SCRIPT:"):]))
                elif line.startswith("SUMMARY:"):
                    out.append(("S", line[len("SUMMARY:"):]))
                elif line.startswith("HELP:"):
                    out.append(("H", line[len("HELP:"):]))
    except OSError:
        pass
    return out


def _scripts_visible_rows():
    # Content window height = popup rows − title (3) − footer (2).
    return max(1, _term_rows() - 3 - 2)


def _scripts_content_text():
    """Render script entries in a centred 60-col block, sliced by _scripts_scroll."""
    global _scripts_scroll
    cols   = _term_cols()
    pad    = max(0, (cols - 60) // 2)
    p      = " " * pad
    parsed = _scripts_parsed_lines()

    # One fragment list per visual line; we slice by _scripts_scroll below.
    visual_lines = []
    for tag, text in parsed:
        if tag == "A":
            visual_lines.append([("", p), (C_ACCENT, "▶ "), (C_ACTIVE, text.upper())])
        elif tag == "S":
            visual_lines.append([("", p + "  "), (C_BODY, text)])
        elif tag == "H":
            visual_lines.append([("", p + "  "), (C_ITEM, text)])
        elif tag == "B":
            visual_lines.append([])
        elif tag == "M":
            visual_lines.append([("", p), (C_BODY, text)])

    # Re-clamp in case content or terminal size shrank since last scroll.
    max_scroll = max(0, len(visual_lines) - _scripts_visible_rows())
    if _scripts_scroll > max_scroll:
        _scripts_scroll = max_scroll

    sliced = visual_lines[_scripts_scroll:]
    frags  = []
    for i, line_frags in enumerate(sliced):
        frags.extend(line_frags)
        if i < len(sliced) - 1:
            frags.append(("", "\n"))
    return frags


def _scripts_title_text():
    cols  = _term_cols()
    title = "─── Scripts ───"
    return [
        ("", "\n"),
        ("", _pad_centre(title, cols)),
        (C_TITLE, title),
        ("", "\n"),
    ]


def _scripts_has_overflow():
    return len(_scripts_parsed_lines()) > _scripts_visible_rows()


def _scripts_footer_text():
    cols   = _term_cols()
    footer = "↑↓ Scroll · ESC Back" if _scripts_has_overflow() else "ESC  Back"
    return [
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ]


# ---------------------------------------------------------------------------
# Exit-confirm frame
# ---------------------------------------------------------------------------
def _exit_confirm_text():
    cols  = _term_cols()
    msg   = "Exit to main menu?  Y to confirm, any other key to cancel."
    warn  = "Attention! This terminates the current session."
    hint  = "↑↓ · ESC  Back to menu"
    return [
        ("", "\n\n"),
        ("", _pad_centre(msg, cols)),
        (C_ACTIVE, msg),
        ("", "\n\n"),
        ("", _pad_centre(warn, cols)),
        (C_ERR, warn),
        ("", "\n\n"),
        ("", _pad_centre(hint, cols)),
        (C_HINT, hint),
    ]


# ---------------------------------------------------------------------------
# Scrollable control: handles mouse-wheel SCROLL_UP/SCROLL_DOWN.
# ---------------------------------------------------------------------------
class _ScrollControl(FormattedTextControl):
    def __init__(self, *args, get_scroll, set_scroll, get_max, **kwargs):
        super().__init__(*args, **kwargs)
        self._get_scroll = get_scroll
        self._set_scroll = set_scroll
        self._get_max    = get_max

    def mouse_handler(self, ev):
        result = super().mouse_handler(ev)
        if result is NotImplemented:
            if ev.event_type == MouseEventType.SCROLL_UP:
                cur = self._get_scroll()
                if cur > 0:
                    self._set_scroll(max(0, cur - 1))
                    if _app:
                        _app.invalidate()
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                cur = self._get_scroll()
                mx  = self._get_max()
                if cur < mx:
                    self._set_scroll(min(mx, cur + 1))
                    if _app:
                        _app.invalidate()
                return None
        return result


def _window_max_scroll(win):
    if win is None or win.render_info is None:
        return 0
    info = win.render_info
    return max(0, info.content_height - info.window_height)


def _get_scripts_scroll():
    return _scripts_scroll


def _set_scripts_scroll(v):
    global _scripts_scroll
    _scripts_scroll = v


def _scripts_max_scroll():
    return max(0, len(_scripts_parsed_lines()) - _scripts_visible_rows())


def _scroll_scripts(delta):
    global _scripts_scroll
    mx = _scripts_max_scroll()
    new_val = max(0, min(mx, _scripts_scroll + delta))
    if new_val != _scripts_scroll:
        _scripts_scroll = new_val
        if _app:
            _app.invalidate()


def _get_options_scroll():
    return _options_scroll


def _set_options_scroll(v):
    global _options_scroll
    _options_scroll = v


def _options_max_scroll():
    return _window_max_scroll(_options_window)


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------
def _in_frame(name):
    return Condition(lambda: _current_frame == name)


kb = KeyBindings()


# Main frame
@kb.add("up", filter=_in_frame("main"))
def _main_up(event):
    global _sel_main
    n = len(_main_items())
    if n:
        _sel_main = (_sel_main - 1) % n


@kb.add("down", filter=_in_frame("main"))
def _main_down(event):
    global _sel_main
    n = len(_main_items())
    if n:
        _sel_main = (_sel_main + 1) % n


@kb.add("enter", filter=_in_frame("main"))
@kb.add(" ",     filter=_in_frame("main"))
def _main_select(event):
    items = _main_items()
    idx   = _sel_main if _sel_main < len(items) else len(items) - 1
    if 0 <= idx < len(items):
        _activate_main_item(items[idx][1])


@kb.add("escape", filter=_in_frame("main"), eager=True)
def _main_escape(event):
    event.app.exit()


# Options frame
@kb.add("up", filter=_in_frame("options"))
def _opt_up(event):
    global _sel_options
    n = len(_options_selectable_indices())
    if n:
        _sel_options = (_sel_options - 1) % n


@kb.add("down", filter=_in_frame("options"))
def _opt_down(event):
    global _sel_options
    n = len(_options_selectable_indices())
    if n:
        _sel_options = (_sel_options + 1) % n


@kb.add("enter", filter=_in_frame("options"))
@kb.add(" ",     filter=_in_frame("options"))
def _opt_select(event):
    sel_indices = _options_selectable_indices()
    if not sel_indices:
        return
    idx = _sel_options if _sel_options < len(sel_indices) else len(sel_indices) - 1
    _options_activate(sel_indices[idx])


@kb.add("escape", filter=_in_frame("options"), eager=True)
def _opt_escape(event):
    _pop_frame()


# Scripts frame
@kb.add("up", filter=_in_frame("scripts"))
def _scr_up(event):
    _scroll_scripts(-1)


@kb.add("down", filter=_in_frame("scripts"))
def _scr_down(event):
    _scroll_scripts(1)


@kb.add("pageup", filter=_in_frame("scripts"))
def _scr_pageup(event):
    _scroll_scripts(-10)


@kb.add("pagedown", filter=_in_frame("scripts"))
def _scr_pagedown(event):
    _scroll_scripts(10)


@kb.add("escape", filter=_in_frame("scripts"), eager=True)
def _scr_escape(event):
    _pop_frame()


# Exit-confirm frame
@kb.add("y", filter=_in_frame("exit_confirm"))
@kb.add("Y", filter=_in_frame("exit_confirm"))
def _ec_confirm(event):
    _write_sentinel(RETURN_TO_MENU_SENT)
    _send_to_game("cp -e")
    event.app.exit()


@kb.add("escape", filter=_in_frame("exit_confirm"), eager=True)
def _ec_escape(event):
    _pop_frame()


@kb.add("<any>", filter=_in_frame("exit_confirm"))
def _ec_cancel(event):
    _pop_frame()


# Global Ctrl+C: prompt_toolkit's raw mode swallows SIGINT, so the
# signal handler never fires from the keyboard. Bind c-c explicitly.
@kb.add("c-c")
def _global_ctrl_c(event):
    event.app.exit()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def _cleanup():
    _remove_sentinel(POPUP_SENTINEL)


def _signal_exit(signum, frame):
    _cleanup()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Layout / main
# ---------------------------------------------------------------------------
def _build_main_container():
    # focusable=False + always_hide_cursor so the terminal cursor doesn't
    # blink on the main frame (submenus already use focusable=False FTCs).
    return Window(
        content=FormattedTextControl(text=_main_text, focusable=False),
        wrap_lines=False,
        always_hide_cursor=True,
    )


def _build_options_container():
    global _options_window

    title_window = Window(
        content=_ScrollControl(
            text=_options_title_text,
            focusable=False,
            get_scroll=_get_options_scroll,
            set_scroll=_set_options_scroll,
            get_max=_options_max_scroll,
        ),
        height=3,
        wrap_lines=False,
    )
    content_window = Window(
        content=_ScrollControl(
            text=_options_content_text,
            focusable=True,
            get_scroll=_get_options_scroll,
            set_scroll=_set_options_scroll,
            get_max=_options_max_scroll,
        ),
        wrap_lines=False,
        get_vertical_scroll=lambda w: min(_options_scroll, _window_max_scroll(w)),
    )
    footer_window = Window(
        content=_ScrollControl(
            text=_options_footer_text,
            focusable=False,
            get_scroll=_get_options_scroll,
            set_scroll=_set_options_scroll,
            get_max=_options_max_scroll,
        ),
        height=2,
        wrap_lines=False,
    )
    _options_window = content_window
    return HSplit([title_window, content_window, footer_window])


def _build_scripts_container():
    global _scripts_window

    title_window = Window(
        content=_ScrollControl(
            text=_scripts_title_text,
            focusable=False,
            get_scroll=_get_scripts_scroll,
            set_scroll=_set_scripts_scroll,
            get_max=_scripts_max_scroll,
        ),
        height=3,
        wrap_lines=False,
    )
    # No get_vertical_scroll: _scripts_content_text already slices by
    # _scripts_scroll, so the Window just renders the visible chunk.
    content_window = Window(
        content=_ScrollControl(
            text=_scripts_content_text,
            focusable=True,
            get_scroll=_get_scripts_scroll,
            set_scroll=_set_scripts_scroll,
            get_max=_scripts_max_scroll,
        ),
        wrap_lines=False,
    )
    footer_window = Window(
        content=_ScrollControl(
            text=_scripts_footer_text,
            focusable=False,
            get_scroll=_get_scripts_scroll,
            set_scroll=_set_scripts_scroll,
            get_max=_scripts_max_scroll,
        ),
        height=2,
        wrap_lines=False,
    )
    _scripts_window = content_window
    return HSplit([title_window, content_window, footer_window])


def _build_exit_confirm_container():
    return Window(
        content=FormattedTextControl(text=_exit_confirm_text, focusable=True),
        wrap_lines=False,
    )


def main():
    global _app

    _write_sentinel(POPUP_SENTINEL)
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_exit)
    signal.signal(signal.SIGHUP,  _signal_exit)
    signal.signal(signal.SIGINT,  _signal_exit)

    frames = {
        "main":         _build_main_container(),
        "options":      _build_options_container(),
        "scripts":      _build_scripts_container(),
        "exit_confirm": _build_exit_confirm_container(),
    }

    root   = DynamicContainer(lambda: frames[_current_frame])
    layout = Layout(root)

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        color_depth=ColorDepth.DEPTH_24_BIT,
    )
    # Lower the input-parser flush timeout so bare ESC fires near-instantly
    # instead of waiting the prompt_toolkit default of 500 ms to disambiguate
    # from escape sequences. tmux's escape-time is already 10 ms; 50 ms here
    # is generous on top of that.
    app.ttimeoutlen = 0.05
    app.timeoutlen  = 0.05
    _app = app

    try:
        app.run()
    finally:
        _cleanup()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        _cleanup()
        raise
