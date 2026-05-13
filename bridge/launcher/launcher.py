#!/usr/bin/env python3
# bridge/launcher/launcher.py — pre-tmux startup menu (prompt_toolkit rewrite).
# Invoked via bridge/launcher/launcher.sh. Behavioural contract: docs/launcher.md.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import DynamicContainer, Layout, VerticalAlign
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import asyncio
import atexit
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import threading

# Make sibling modules importable when run directly via the wrapper.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palette import (  # noqa: E402
    C_TITLE, C_ACTIVE, C_ITEM, C_BODY, C_HINT, C_ACCENT,
    C_YELLOW, C_ERR, C_QUOTE, C_QUOTE_ATTR, C_HOVER,
)
from widgets.scrollbar import Scrollbar  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR         = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR         = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR        = os.path.dirname(BRIDGE_DIR)
RUNTIME_DIR        = os.path.join(BRIDGE_DIR, "runtime")
CONF_PATH          = os.path.join(RUNTIME_DIR, "startup.conf")
VERSION_CACHE_PATH = os.path.join(RUNTIME_DIR, "version.cache")
SCRIPTS_CACHE_PATH = os.path.join(RUNTIME_DIR, "scripts.cache")
VERSION_FILE       = os.path.join(PROJECT_DIR, "VERSION")
PROFILES_DIR       = os.path.join(PROJECT_DIR, "ttpp", "profiles")
QUOTES_PATH        = os.path.join(SCRIPT_DIR, "quotes.txt")
ABOUT_PATH         = os.path.join(SCRIPT_DIR, "about.txt")
TEMPLATE_BLANK     = os.path.join(SCRIPT_DIR, "templates", "blank_profile.tin")
UPDATE_SH          = os.path.join(BRIDGE_DIR, "release", "update.sh")
VERSION_CHECK_SH   = os.path.join(BRIDGE_DIR, "services", "version_check.sh")
PING_MONITOR_SH    = os.path.join(BRIDGE_DIR, "services", "ping_monitor.sh")

MIN_COLS = 60
MIN_ROWS = 18

PROFILE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

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
# Options layout
# ---------------------------------------------------------------------------
_OPT_TOGGLES = [
    ("show_status",         "Character pane"),
    ("show_buffs",          "Buffs pane"),
    ("show_group",          "Group pane"),
    ("show_comm",           "Comm pane"),
    ("show_ui",             "UI pane"),
    ("show_dev",            "Dev pane"),
    ("show_pane_dividers",  "Pane headers"),
]
_OPT_RADIOS = [
    ("mmapper", "MMapper  (localhost:4242)"),
    ("direct",  "Direct   (mume.org:4242)"),
]

_CONF_DEFAULTS = {
    "connection_mode":    "mmapper",
    "show_status":        "1",
    "show_buffs":         "1",
    "show_group":         "1",
    "show_comm":          "1",
    "show_ui":            "1",
    "show_dev":           "0",
    "show_pane_dividers": "1",
    "profile":            "default",
}

# ---------------------------------------------------------------------------
# Mutable application state
# ---------------------------------------------------------------------------
_app             = None
_current_frame   = "main"
_frame_stack     = []
_deferred_exec   = None      # (executable, [argv]) — performed after app.run_async returns

_cockpit_version = "0.0.0"
_cache_mtime     = None
_quote_text      = ""
_quote_attr      = ""

_conf = dict(_CONF_DEFAULTS)

# Main frame
_main_items      = []
_sel_main        = 0
_hover_main      = -1
_last_main_label = None

# Profile frame
_profiles            = []
_sel_profile         = 0
_hover_profile       = -1
# Profile create
_create_name_buf     = ""
_create_name_err     = ""
_create_src_profiles = []
_sel_copy            = 0
_hover_copy          = -1
_new_profile_name    = ""

# Profile delete
_delete_target       = ""
_delete_locked       = False   # True when target is "default" (info screen)

# Options
_sel_options         = 0
_hover_options       = -1

# Scripts
_scripts_lines       = []
_scripts_scroll      = 0
_scripts_sb          = None

# About
_about_lines         = []
_about_scroll        = 0
_about_cols          = 0
_about_sb            = None

# Update flow
_update_rc           = None
_update_output       = ""

# Windows
_main_window         = None
_profile_window      = None
_profile_create_name_window      = None
_profile_create_choose_window    = None
_profile_create_copy_window      = None
_profile_delete_window           = None
_options_window      = None
_scripts_window      = None
_about_window        = None
_update_running_window = None
_update_result_window  = None
_exit_confirm_window   = None
_too_small_window      = None

_app_loop = None


# ---------------------------------------------------------------------------
# One-shot migrations (run before the Application starts)
# ---------------------------------------------------------------------------
def _one_shot_migrations():
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    patterns = [
        os.path.join(BRIDGE_DIR, "*.state"),
        os.path.join(BRIDGE_DIR, "*.cache"),
        os.path.join(BRIDGE_DIR, "*.conf"),
    ]
    for pat in patterns:
        for path in glob.glob(pat):
            try:
                shutil.move(path, os.path.join(RUNTIME_DIR, os.path.basename(path)))
            except OSError:
                pass
    # Dot-prefix entries at bridge/ root whose first char after the dot is a letter
    try:
        for entry in os.listdir(BRIDGE_DIR):
            if (not entry.startswith(".") or len(entry) < 2
                    or not entry[1].isalpha()):
                continue
            src = os.path.join(BRIDGE_DIR, entry)
            try:
                shutil.move(src, os.path.join(RUNTIME_DIR, entry))
            except OSError:
                pass
    except OSError:
        pass

    # ttpp/sessions/ → ttpp/profiles/ (ADR 0048)
    sessions = os.path.join(PROJECT_DIR, "ttpp", "sessions")
    if os.path.isdir(sessions) and not os.path.isdir(PROFILES_DIR):
        try:
            os.rename(sessions, PROFILES_DIR)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------
def _parse_conf(path):
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


def _load_conf():
    global _conf
    if not os.path.exists(CONF_PATH):
        _conf = dict(_CONF_DEFAULTS)
        _save_conf()
        return
    parsed = _parse_conf(CONF_PATH)
    merged = dict(_CONF_DEFAULTS)
    merged.update(parsed)
    # One-shot migration: profile=mume → profile=default
    if merged.get("profile") == "mume":
        merged["profile"] = "default"
        _conf = merged
        _save_conf()
        return
    _conf = merged


def _save_conf():
    try:
        with open(CONF_PATH, "w") as fh:
            fh.write("# Phase 1 cosmetic options — launcher display only\n")
            for key in (
                "connection_mode", "show_status", "show_buffs", "show_group",
                "show_comm", "show_ui", "show_dev", "show_pane_dividers", "profile",
            ):
                fh.write(f"{key}={_conf.get(key, _CONF_DEFAULTS[key])}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Version / cache
# ---------------------------------------------------------------------------
def _read_version_file():
    try:
        with open(VERSION_FILE) as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _strip_v(s):
    return s[1:] if s.startswith("v") else s


def _latest_release_tag():
    if not os.path.exists(VERSION_CACHE_PATH):
        return ""
    return _parse_conf(VERSION_CACHE_PATH).get("latest", "")


def _update_available():
    latest = _latest_release_tag()
    if not latest:
        return False
    return _strip_v(latest) != _strip_v(_cockpit_version)


def _cache_mtime_now():
    try:
        return os.path.getmtime(VERSION_CACHE_PATH)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------
def _spawn_version_check():
    try:
        with open(os.devnull, "wb") as devnull:
            subprocess.Popen(
                ["bash", VERSION_CHECK_SH],
                stdout=devnull, stderr=devnull, stdin=devnull,
                start_new_session=True, cwd=PROJECT_DIR,
            )
    except OSError:
        pass


def _spawn_ping_monitor():
    try:
        with open(os.devnull, "wb") as devnull:
            subprocess.Popen(
                ["bash", PING_MONITOR_SH],
                stdout=devnull, stderr=devnull, stdin=devnull,
                start_new_session=True, cwd=PROJECT_DIR,
            )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# tmux session probes
# ---------------------------------------------------------------------------
def _has_session():
    try:
        r = subprocess.run(
            ["tmux", "has-session", "-t", "mume"],
            capture_output=True, timeout=1.0,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _attached_count():
    try:
        r = subprocess.run(
            ["tmux", "list-clients", "-t", "mume"],
            capture_output=True, text=True, timeout=1.0,
        )
        return len([l for l in r.stdout.splitlines() if l])
    except (subprocess.SubprocessError, OSError):
        return 0


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------
def _load_random_quote():
    global _quote_text, _quote_attr
    try:
        with open(QUOTES_PATH) as fh:
            lines = [
                l.strip() for l in fh
                if l.strip() and not l.lstrip().startswith("#")
            ]
    except OSError:
        return
    if not lines:
        return
    sel = random.choice(lines)
    if "|" in sel:
        _quote_text, _, _quote_attr = sel.partition("|")
        _quote_text = _quote_text.strip()
        _quote_attr = _quote_attr.strip()
    else:
        _quote_text = sel
        _quote_attr = ""


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------
def _list_profiles():
    try:
        names = []
        for f in os.listdir(PROFILES_DIR):
            if f.endswith(".tin"):
                names.append(f[:-4])
        return sorted(names)
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Terminal size
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


def _size_ok():
    return _term_cols() >= MIN_COLS and _term_rows() >= MIN_ROWS


# ---------------------------------------------------------------------------
# Frame stack
# ---------------------------------------------------------------------------
def _focus_current_frame():
    if not _app:
        return
    win = {
        "main":                       _main_window,
        "profile":                    _profile_window,
        "profile_create_name":        _profile_create_name_window,
        "profile_create_choose":      _profile_create_choose_window,
        "profile_create_copy_picker": _profile_create_copy_window,
        "profile_delete_confirm":     _profile_delete_window,
        "options":                    _options_window,
        "scripts":                    _scripts_window,
        "about":                      _about_window,
        "update_running":             _update_running_window,
        "update_result":              _update_result_window,
        "exit_confirm":               _exit_confirm_window,
    }.get(_current_frame)
    if win is None:
        return
    try:
        _app.layout.focus(win)
    except Exception:
        pass


def _push_frame(frame):
    global _current_frame
    _frame_stack.append(_current_frame)
    _current_frame = frame
    _focus_current_frame()
    if _app:
        _app.invalidate()


def _pop_frame():
    global _current_frame
    _current_frame = _frame_stack.pop() if _frame_stack else "main"
    _focus_current_frame()
    if _app:
        _app.invalidate()


def _reset_to_main():
    global _current_frame
    _frame_stack.clear()
    _current_frame = "main"
    _focus_current_frame()
    if _app:
        _app.invalidate()


# ---------------------------------------------------------------------------
# Centering helpers
# ---------------------------------------------------------------------------
def _pad_centre(text, cols=None):
    if cols is None:
        cols = _term_cols()
    n = max(0, (cols - len(text)) // 2)
    return " " * n


# ---------------------------------------------------------------------------
# Hover handling
# ---------------------------------------------------------------------------
def _set_hover(frame, idx):
    """Set hover index for the named frame; invalidate if changed."""
    global _hover_main, _hover_profile, _hover_options, _hover_copy
    changed = False
    if frame == "main" and _hover_main != idx:
        _hover_main = idx; changed = True
    elif frame == "profile" and _hover_profile != idx:
        _hover_profile = idx; changed = True
    elif frame == "options" and _hover_options != idx:
        _hover_options = idx; changed = True
    elif frame == "profile_create_copy_picker" and _hover_copy != idx:
        _hover_copy = idx; changed = True
    if changed and _app:
        _app.invalidate()


def _row_style(is_active, is_hovered, inactive_style=None):
    if is_active:
        return C_ACTIVE
    if is_hovered:
        return C_HOVER
    return inactive_style or C_ITEM


# ---------------------------------------------------------------------------
# Main frame
# ---------------------------------------------------------------------------
def _rebuild_main_items(*, preserve_label=True):
    global _main_items, _sel_main, _last_main_label
    prev = (_main_items[_sel_main]
            if preserve_label and 0 <= _sel_main < len(_main_items)
            else _last_main_label)
    if _has_session():
        first = "Resume game" if _attached_count() == 0 else "Mirror game (attached elsewhere)"
    else:
        first = "Enter game"
    items = [first]
    if _update_available():
        items.append("Update")
    items.extend(["Profile", "Options", "Scripts", "About", "Quit"])
    _main_items = items
    if prev and prev in items:
        _sel_main = items.index(prev)
    else:
        _sel_main = min(_sel_main, len(items) - 1)
        if _sel_main < 0:
            _sel_main = 0
    _last_main_label = _main_items[_sel_main]


def _check_cache_change():
    global _cache_mtime
    m = _cache_mtime_now()
    if m != _cache_mtime:
        _cache_mtime = m
        _rebuild_main_items()


def _activate_main(idx):
    global _sel_main, _deferred_exec
    if idx < 0 or idx >= len(_main_items):
        return
    _sel_main = idx
    label = _main_items[idx]
    if label in ("Enter game", "Resume game", "Mirror game (attached elsewhere)"):
        if _has_session():
            _spawn_ping_monitor()
            _deferred_exec = ("tmux", ["tmux", "attach", "-t", "mume"])
        else:
            # Cold start: hand the launcher's known terminal dimensions to
            # tmux_start.sh so it can build the cockpit layout pre-attach.
            # See docs/launcher.md "Initial layout build".
            try:
                size = _app.output.get_size()
                os.environ["LAUNCHER_COLS"] = str(size.columns)
                os.environ["LAUNCHER_ROWS"] = str(size.rows)
            except Exception:
                pass
            _deferred_exec = ("bash", ["bash", "bridge/launcher/tmux_start.sh"])
        _app.exit()
    elif label == "Update":
        _start_update()
    elif label == "Profile":
        _enter_profile_frame()
    elif label == "Options":
        _enter_options_frame()
    elif label == "Scripts":
        _enter_scripts_frame()
    elif label == "About":
        _enter_about_frame()
    elif label == "Quit":
        _push_frame("exit_confirm")


def _main_text():
    _check_cache_change()
    cols = _term_cols()
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

    items = _main_items
    sel_idx = _sel_main if 0 <= _sel_main < len(items) else 0

    for i, label in enumerate(items):
        is_active = (i == sel_idx)
        is_hover  = (i == _hover_main)
        style = _row_style(is_active, is_hover)
        prefix = "<< " if is_active else "   "
        suffix = " >>" if is_active else "   "
        full = f"{prefix}{label}{suffix}"

        def _make_handler(row=i):
            def _h(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("main", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _activate_main(row)
            return _h

        h = _make_handler()
        frags.append(("", _pad_centre(full, cols)))
        frags.append((style, prefix, h))
        frags.append((style, label, h))
        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))

    # Quote
    if _quote_text:
        quoted = f'"{_quote_text}"'
        frags.append(("", _pad_centre(quoted, cols)))
        frags.append((C_QUOTE, quoted))
        frags.append(("", "\n"))
        if _quote_attr:
            attr = f"— {_quote_attr}"
            frags.append(("", _pad_centre(attr, cols)))
            frags.append((C_QUOTE_ATTR, attr))
            frags.append(("", "\n"))
        frags.append(("", "\n"))

    footer = "↑↓ Navigate · Enter/Space Select"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Profile frame
# ---------------------------------------------------------------------------
def _enter_profile_frame():
    global _profiles, _sel_profile
    _profiles = _list_profiles()
    cur = _conf.get("profile", "default")
    _sel_profile = 0
    for i, name in enumerate(_profiles):
        if name == cur:
            _sel_profile = i
            break
    _push_frame("profile")


def _profile_total():
    return len(_profiles) + 2   # profiles + Create + Back


def _activate_profile(idx):
    global _sel_profile
    if idx < 0 or idx >= _profile_total():
        return
    _sel_profile = idx
    if idx < len(_profiles):
        _conf["profile"] = _profiles[idx]
        _save_conf()
        if _app:
            _app.invalidate()
    elif idx == len(_profiles):
        _enter_profile_create_name()
    else:
        _pop_frame()


def _profile_text():
    cols = _term_cols()
    title = "─── Profile ───"
    footer = "↑↓ Navigate · Enter Select · D Delete · ESC Back"
    cur = _conf.get("profile", "default")
    create_label = "[+] Create new profile"
    back_label   = "    Back"

    labels = []
    for name in _profiles:
        labels.append(f"({'•' if name == cur else ' '}) {name}")
    labels.append(create_label)
    labels.append(back_label)
    maxw = max((len(l) for l in labels), default=0)
    pad = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    total = _profile_total()
    create_idx = len(_profiles)
    back_idx   = create_idx + 1

    for i, label in enumerate(labels):
        if i == create_idx or i == back_idx:
            frags.append(("", "\n"))   # blank line before Create / before Back

        is_active = (i == _sel_profile)
        is_hover  = (i == _hover_profile)
        inactive  = C_ACCENT if i == create_idx else C_ITEM
        style = _row_style(is_active, is_hover, inactive)
        prefix = "<< " if is_active else "   "
        suffix = " >>" if is_active else "   "

        def _make_handler(row=i):
            def _h(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("profile", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _activate_profile(row)
            return _h

        h = _make_handler()
        frags.append(("", " " * pad))
        frags.append((style, prefix, h))
        frags.append((style, label, h))
        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Profile create — name entry
# ---------------------------------------------------------------------------
def _enter_profile_create_name():
    global _create_name_buf, _create_name_err
    _create_name_buf = ""
    _create_name_err = ""
    _push_frame("profile_create_name")


def _validate_profile_name(name):
    if not name:
        return "Name cannot be empty."
    if not PROFILE_NAME_RE.match(name):
        return "Must start with a letter; only letters, numbers, _ allowed."
    if os.path.exists(os.path.join(PROFILES_DIR, f"{name}.tin")):
        return f'Profile "{name}" already exists.'
    return ""


def _profile_create_name_text():
    cols = _term_cols()
    title  = "─── Create New Profile ───"
    hint   = "letters and _ only · must start with a letter · max 32"
    footer = "Enter  Confirm · ESC  Cancel"
    line   = f"> {_create_name_buf}_"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(line, cols)))
    frags.append((C_HINT, "> "))
    frags.append((C_ACTIVE, _create_name_buf))
    frags.append((C_HINT, "_"))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(hint, cols)))
    frags.append((C_HINT, hint))
    if _create_name_err:
        frags.append(("", "\n\n"))
        frags.append(("", _pad_centre(_create_name_err, cols)))
        frags.append((C_YELLOW, _create_name_err))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Profile create — blank or copy choice
# ---------------------------------------------------------------------------
def _enter_profile_create_choose():
    _push_frame("profile_create_choose")


def _profile_create_choose_text():
    cols = _term_cols()
    title   = "─── Create New Profile ───"
    name_l  = f"Name:  {_new_profile_name}"
    footer  = "B  Blank profile · C  Copy from existing · ESC  Cancel"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(name_l, cols)))
    frags.append((C_HINT, "Name:  "))
    frags.append((C_ACTIVE, _new_profile_name))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


def _create_blank_profile(name):
    target = os.path.join(PROFILES_DIR, f"{name}.tin")
    os.makedirs(PROFILES_DIR, exist_ok=True)
    if os.path.exists(TEMPLATE_BLANK):
        try:
            shutil.copyfile(TEMPLATE_BLANK, target)
        except OSError:
            with open(target, "w") as fh:
                fh.write(f"#nop {name}.tin — MUME Cockpit profile\n")
    else:
        with open(target, "w") as fh:
            fh.write(f"#nop {name}.tin — MUME Cockpit profile\n")


def _profile_create_finish_blank():
    _create_blank_profile(_new_profile_name)
    _conf["profile"] = _new_profile_name
    _save_conf()
    _reset_to_profile_after_create()


def _reset_to_profile_after_create():
    """Pop create frames and refresh the profile list/selection."""
    global _profiles, _sel_profile, _frame_stack, _current_frame
    while _frame_stack and _current_frame.startswith("profile_create"):
        _current_frame = _frame_stack.pop()
    if _current_frame != "profile":
        # Defensive — collapse anything stale back to main.
        _current_frame = "profile"
    _profiles = _list_profiles()
    cur = _conf.get("profile", "default")
    _sel_profile = 0
    for i, name in enumerate(_profiles):
        if name == cur:
            _sel_profile = i
            break
    _focus_current_frame()
    if _app:
        _app.invalidate()


# ---------------------------------------------------------------------------
# Profile create — copy picker
# ---------------------------------------------------------------------------
def _enter_profile_create_copy_picker():
    global _create_src_profiles, _sel_copy
    _create_src_profiles = _list_profiles()
    _sel_copy = 0
    _push_frame("profile_create_copy_picker")


def _activate_copy_picker(idx):
    global _sel_copy
    if idx < 0 or idx >= len(_create_src_profiles) + 1:
        return
    _sel_copy = idx
    if idx < len(_create_src_profiles):
        src = os.path.join(PROFILES_DIR, f"{_create_src_profiles[idx]}.tin")
        dst = os.path.join(PROFILES_DIR, f"{_new_profile_name}.tin")
        try:
            shutil.copyfile(src, dst)
            _conf["profile"] = _new_profile_name
            _save_conf()
        except OSError:
            pass
        _reset_to_profile_after_create()


def _profile_create_copy_text():
    cols = _term_cols()
    title = "─── Create New Profile ───"
    if not _create_src_profiles:
        msg = "No profiles available to copy from."
        hint = "Any key to continue"
        frags = []
        frags.append(("", "\n\n"))
        frags.append(("", _pad_centre(title, cols)))
        frags.append((C_TITLE, title))
        frags.append(("", "\n\n\n"))
        frags.append(("", _pad_centre(msg, cols)))
        frags.append((C_YELLOW, msg))
        frags.append(("", "\n\n\n"))
        frags.append(("", _pad_centre(hint, cols)))
        frags.append((C_HINT, hint))
        return frags

    footer = "↑↓ Navigate · Enter  Select · ESC  Cancel"
    head   = "Copy from:"
    labels = list(_create_src_profiles)
    maxw   = max(len(l) for l in labels)
    pad    = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(head, cols)))
    frags.append((C_HINT, head))
    frags.append(("", "\n\n"))

    for i, label in enumerate(labels):
        is_active = (i == _sel_copy)
        is_hover  = (i == _hover_copy)
        style = _row_style(is_active, is_hover)
        prefix = "<< " if is_active else "   "
        suffix = " >>" if is_active else "   "

        def _make_handler(row=i):
            def _h(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("profile_create_copy_picker", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _activate_copy_picker(row)
            return _h

        h = _make_handler()
        frags.append(("", " " * pad))
        frags.append((style, prefix, h))
        frags.append((style, label, h))
        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Profile delete confirm
# ---------------------------------------------------------------------------
def _enter_profile_delete_confirm():
    global _delete_target, _delete_locked
    if _sel_profile >= len(_profiles):
        return
    name = _profiles[_sel_profile]
    _delete_target = name
    _delete_locked = (name == "default")
    _push_frame("profile_delete_confirm")


def _confirm_profile_delete():
    global _profiles, _sel_profile
    if _delete_locked:
        return
    target = os.path.join(PROFILES_DIR, f"{_delete_target}.tin")
    try:
        os.remove(target)
    except OSError:
        pass
    if _conf.get("profile") == _delete_target:
        _conf["profile"] = "default"
        _save_conf()
    _profiles = _list_profiles()
    total = len(_profiles) + 2
    if _sel_profile >= total:
        _sel_profile = total - 1
    _pop_frame()


def _profile_delete_text():
    cols = _term_cols()
    title = "─── Profile ───"
    if _delete_locked:
        msg = "You can't delete the default profile."
        hint = "Any key to continue"
        msg_style = C_YELLOW
    else:
        msg = f"Delete profile '{_delete_target}'?  (y/N)"
        hint = "Y to confirm · any other key to cancel"
        msg_style = C_ACTIVE
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(msg, cols)))
    frags.append((msg_style, msg))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(hint, cols)))
    frags.append((C_HINT, hint))
    return frags


# ---------------------------------------------------------------------------
# Options frame
# ---------------------------------------------------------------------------
def _options_count():
    return len(_OPT_TOGGLES) + len(_OPT_RADIOS) + 1  # +Back


def _enter_options_frame():
    global _sel_options
    _sel_options = 0
    _push_frame("options")


def _activate_option(idx):
    global _sel_options
    if idx < 0 or idx >= _options_count():
        return
    _sel_options = idx
    if idx < len(_OPT_TOGGLES):
        key, _ = _OPT_TOGGLES[idx]
        _conf[key] = "0" if _conf.get(key) == "1" else "1"
        if _app:
            _app.invalidate()
        return
    r = idx - len(_OPT_TOGGLES)
    if r < len(_OPT_RADIOS):
        mode, _ = _OPT_RADIOS[r]
        _conf["connection_mode"] = mode
        if _app:
            _app.invalidate()
        return
    _save_conf()
    _pop_frame()


def _options_text():
    cols = _term_cols()
    title  = "─── Options ───"
    footer = "↑↓ Navigate · Enter/Space Toggle · ESC Back"

    rows = []  # (label, kind)
    for key, label in _OPT_TOGGLES:
        box = "[x]" if _conf.get(key) == "1" else "[ ]"
        rows.append((f"{box} {label}", "toggle"))
    cur_mode = _conf.get("connection_mode", "mmapper")
    for mode, label in _OPT_RADIOS:
        dot = "(•)" if cur_mode == mode else "( )"
        rows.append((f"{dot} {label}", "radio"))
    rows.append(("    Back", "back"))

    maxw = max(len(r[0]) for r in rows)
    pad  = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    radio_start = len(_OPT_TOGGLES)
    back_idx    = _options_count() - 1

    for i, (label, _) in enumerate(rows):
        if i == radio_start or i == back_idx:
            frags.append(("", "\n"))   # blank before radios / before Back

        is_active = (i == _sel_options)
        is_hover  = (i == _hover_options)
        style = _row_style(is_active, is_hover)
        prefix = "<< " if is_active else "   "
        suffix = " >>" if is_active else "   "

        def _make_handler(row=i):
            def _h(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _activate_option(row)
            return _h

        h = _make_handler()
        frags.append(("", " " * pad))
        frags.append((style, prefix, h))
        frags.append((style, label, h))
        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Scripts frame
# ---------------------------------------------------------------------------
def _enter_scripts_frame():
    global _scripts_lines, _scripts_scroll, _scripts_sb
    _scripts_lines = _parse_scripts_cache()
    _scripts_scroll = 0
    _scripts_sb = Scrollbar(
        len(_scripts_lines), _scripts_visible_rows(), _scripts_visible_rows()
    )
    _push_frame("scripts")


def _parse_scripts_cache():
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
    # Title (3) + footer (2) = 5 reserved rows.
    return max(1, _term_rows() - 5)


def _scripts_title_text():
    cols = _term_cols()
    title = "─── Scripts ───"
    return [
        ("", "\n"),
        ("", _pad_centre(title, cols)),
        (C_TITLE, title),
        ("", "\n"),
    ]


def _scripts_content_text():
    global _scripts_scroll
    cols = _term_cols()
    pad  = max(0, (cols - 60) // 2)
    p    = " " * pad

    visual = []
    for tag, text in _scripts_lines:
        if tag == "A":
            visual.append([("", p), (C_ACCENT, "▶ "), (C_ACTIVE, text.upper())])
        elif tag == "S":
            visual.append([("", p + "  "), (C_BODY, text)])
        elif tag == "H":
            visual.append([("", p + "  "), (C_ITEM, text)])
        elif tag == "B":
            visual.append([])
        elif tag == "M":
            visual.append([("", p), (C_BODY, text)])

    visible = _scripts_visible_rows()
    max_scroll = max(0, len(visual) - visible)
    if _scripts_scroll > max_scroll:
        _scripts_scroll = max_scroll
    if _scripts_sb is not None:
        _scripts_sb.update(len(visual), visible, height=visible)
        _scripts_sb.scroll_to(_scripts_scroll)

    sliced = visual[_scripts_scroll:_scripts_scroll + visible]
    frags = []
    for i, line in enumerate(sliced):
        frags.extend(line)
        if i < len(sliced) - 1:
            frags.append(("", "\n"))
    return frags


def _scripts_footer_text():
    cols = _term_cols()
    overflow = _scripts_sb is not None and _scripts_sb.visible
    footer = "↑↓ Scroll · ESC Back" if overflow else "ESC  Back"
    return [
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ]


def _scroll_scripts(delta):
    global _scripts_scroll
    visible = _scripts_visible_rows()
    mx = max(0, len(_scripts_lines) - visible)
    new_val = max(0, min(mx, _scripts_scroll + delta))
    if new_val != _scripts_scroll:
        _scripts_scroll = new_val
        if _app:
            _app.invalidate()


# ---------------------------------------------------------------------------
# About frame
# ---------------------------------------------------------------------------
def _enter_about_frame():
    global _about_lines, _about_scroll, _about_cols, _about_sb
    _about_lines = []
    _about_scroll = 0
    _about_cols = 0
    _about_sb = Scrollbar(0, _about_visible_rows(), _about_visible_rows())
    _wrap_about_if_needed()
    _push_frame("about")


def _wrap_text(text, width):
    out = []
    line = ""
    for raw in text.splitlines():
        if not raw.strip():
            if line:
                out.append(line); line = ""
            out.append("")
            continue
        if raw[:1].isspace():
            if line:
                out.append(line); line = ""
            out.append(raw)
            continue
        for word in raw.split():
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                out.append(line)
                line = word
    if line:
        out.append(line)
    return out


def _wrap_about_if_needed():
    global _about_lines, _about_cols
    cols = _term_cols()
    width = max(20, min(76, cols - 4))
    if cols == _about_cols and _about_lines:
        return
    _about_cols = cols
    try:
        with open(ABOUT_PATH) as fh:
            body = fh.read()
    except OSError:
        _about_lines = []
        return
    _about_lines = _wrap_text(body, width)


def _about_visible_rows():
    # Title (3) + footer (2) = 5 reserved rows.
    return max(1, _term_rows() - 5)


def _about_title_text():
    cols = _term_cols()
    title = "─── About ───"
    cur   = _cockpit_version
    latest = _latest_release_tag()
    has_update = bool(latest) and _strip_v(latest) != _strip_v(cur)

    tlen = len(title)
    if has_update:
        right = f"{cur}  ·  Update available: {latest}"
    else:
        right = cur
    rlen = len(right)
    tpad = max(0, (cols - tlen) // 2)
    vstart = max(0, cols - 2 - rlen)
    gap = max(1, vstart - tpad - tlen)

    frags = [("", "\n"), ("", " " * tpad), (C_TITLE, title), ("", " " * gap)]
    if has_update:
        frags.append((C_BODY, cur))
        frags.append((C_BODY, "  ·  "))
        frags.append((C_ACCENT, f"Update available: {latest}"))
    else:
        frags.append((C_BODY, cur))
    frags.append(("", "\n"))
    return frags


def _about_content_text():
    global _about_scroll
    _wrap_about_if_needed()
    cols = _term_cols()
    width = max(20, min(76, cols - 4))
    pad = max(0, (cols - width) // 2)
    p = " " * pad

    visible = _about_visible_rows()
    total = len(_about_lines)
    mx = max(0, total - visible)
    if _about_scroll > mx:
        _about_scroll = mx
    if _about_sb is not None:
        _about_sb.update(total, visible, height=visible)
        _about_sb.scroll_to(_about_scroll)

    sliced = _about_lines[_about_scroll:_about_scroll + visible]
    frags = []
    for i, line in enumerate(sliced):
        if not line:
            pass
        elif line[:1].isspace():
            frags.append(("", p))
            frags.append((C_ACCENT, line))
        else:
            stripped = line.lstrip()
            if stripped and stripped[0].isalpha() and stripped == stripped.upper():
                style = C_TITLE
            else:
                style = C_BODY
            frags.append(("", p))
            frags.append((style, line))
        if i < len(sliced) - 1:
            frags.append(("", "\n"))
    return frags


def _about_footer_text():
    cols = _term_cols()
    overflow = _about_sb is not None and _about_sb.visible
    footer = "↑↓ Scroll · ESC Back" if overflow else "ESC  Back"
    return [
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ]


def _scroll_about(delta):
    global _about_scroll
    visible = _about_visible_rows()
    mx = max(0, len(_about_lines) - visible)
    new_val = max(0, min(mx, _about_scroll + delta))
    if new_val != _about_scroll:
        _about_scroll = new_val
        if _app:
            _app.invalidate()


# ---------------------------------------------------------------------------
# Update flow
# ---------------------------------------------------------------------------
def _start_update():
    global _update_rc, _update_output
    _update_rc = None
    _update_output = ""
    _push_frame("update_running")
    thread = threading.Thread(target=_update_worker, daemon=True)
    thread.start()


def _update_worker():
    global _update_rc, _update_output
    try:
        r = subprocess.run(
            ["bash", UPDATE_SH],
            capture_output=True, text=True, cwd=PROJECT_DIR,
        )
        _update_output = (r.stdout or "") + (r.stderr or "")
        _update_rc = r.returncode
    except (subprocess.SubprocessError, OSError) as exc:
        _update_output = str(exc)
        _update_rc = -1
    if _app_loop is not None:
        _app_loop.call_soon_threadsafe(_finish_update)


def _finish_update():
    global _current_frame
    if _current_frame == "update_running":
        _current_frame = "update_result"
        _focus_current_frame()
        if _app:
            _app.invalidate()


def _update_running_text():
    cols = _term_cols()
    msg  = "Updating…"
    return [
        ("", "\n\n"),
        ("", _pad_centre(msg, cols)),
        (C_ACTIVE, msg),
    ]


def _update_result_text():
    cols = _term_cols()
    rc = _update_rc
    if rc == 0:
        title, body_style, footer = "Update complete", C_BODY, "Press any key to restart the launcher."
    elif rc == 10:
        title, body_style, footer = "No update available", C_BODY, "Any key to return."
    elif rc in (20, 21, 22):
        title, body_style, footer = "Update aborted", C_YELLOW, "Any key to return."
    else:
        title, body_style, footer = "Update failed", C_ERR, "Any key to return."

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n\n"))
    for line in _update_output.splitlines() or [""]:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((body_style, line))
        frags.append(("", "\n"))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


def _update_result_keypress():
    global _deferred_exec
    if _update_rc == 0:
        _deferred_exec = ("bash", ["bash", "bridge/launcher/launcher.sh"])
        _app.exit()
    else:
        _pop_frame()


# ---------------------------------------------------------------------------
# Exit confirm
# ---------------------------------------------------------------------------
def _exit_confirm_text():
    cols = _term_cols()
    msg = "Quit? Press Y to confirm, any other key to cancel."
    return [
        ("", "\n\n"),
        ("", _pad_centre(msg, cols)),
        (C_ACTIVE, msg),
    ]


# ---------------------------------------------------------------------------
# Too-small gate
# ---------------------------------------------------------------------------
def _too_small_text():
    cols = _term_cols()
    msg = f"Terminal too small — resize to at least {MIN_COLS}×{MIN_ROWS}"
    return [
        ("", _pad_centre(msg, cols)),
        (C_YELLOW, msg),
    ]


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------
def _in_frame(name):
    return Condition(lambda: _size_ok() and _current_frame == name)


def _too_small():
    return Condition(lambda: not _size_ok())


kb = KeyBindings()


@kb.add("c-c")
def _kb_ctrl_c(event):
    event.app.exit()


@kb.add("c-q")
def _kb_ctrl_q(event):
    event.app.exit()


# Too-small gate — only Ctrl-C / Ctrl-Q accepted; everything else swallowed.
@kb.add("<any>", filter=_too_small())
def _kb_too_small_any(event):
    pass


# Main frame
@kb.add("up", filter=_in_frame("main"))
def _kb_main_up(event):
    global _sel_main, _last_main_label
    n = len(_main_items)
    if n:
        _sel_main = (_sel_main - 1) % n
        _last_main_label = _main_items[_sel_main]


@kb.add("down", filter=_in_frame("main"))
def _kb_main_down(event):
    global _sel_main, _last_main_label
    n = len(_main_items)
    if n:
        _sel_main = (_sel_main + 1) % n
        _last_main_label = _main_items[_sel_main]


@kb.add("enter", filter=_in_frame("main"))
@kb.add(" ",     filter=_in_frame("main"))
def _kb_main_select(event):
    _activate_main(_sel_main)


@kb.add("escape", filter=_in_frame("main"), eager=True)
def _kb_main_escape(event):
    _push_frame("exit_confirm")


# Profile frame
@kb.add("up", filter=_in_frame("profile"))
def _kb_profile_up(event):
    global _sel_profile
    n = _profile_total()
    if n:
        _sel_profile = (_sel_profile - 1) % n


@kb.add("down", filter=_in_frame("profile"))
def _kb_profile_down(event):
    global _sel_profile
    n = _profile_total()
    if n:
        _sel_profile = (_sel_profile + 1) % n


@kb.add("enter", filter=_in_frame("profile"))
@kb.add(" ",     filter=_in_frame("profile"))
def _kb_profile_select(event):
    _activate_profile(_sel_profile)


@kb.add("d", filter=_in_frame("profile"))
@kb.add("D", filter=_in_frame("profile"))
def _kb_profile_delete(event):
    if _sel_profile < len(_profiles):
        _enter_profile_delete_confirm()


@kb.add("escape", filter=_in_frame("profile"), eager=True)
def _kb_profile_escape(event):
    _pop_frame()


# Profile create — name
@kb.add("escape", filter=_in_frame("profile_create_name"), eager=True)
def _kb_pcn_escape(event):
    _pop_frame()


@kb.add("enter", filter=_in_frame("profile_create_name"))
def _kb_pcn_enter(event):
    global _create_name_err, _new_profile_name
    err = _validate_profile_name(_create_name_buf)
    if err:
        _create_name_err = err
        return
    _new_profile_name = _create_name_buf
    _enter_profile_create_choose()


@kb.add("backspace", filter=_in_frame("profile_create_name"))
def _kb_pcn_backspace(event):
    global _create_name_buf, _create_name_err
    if _create_name_buf:
        _create_name_buf = _create_name_buf[:-1]
        _create_name_err = ""


@kb.add("<any>", filter=_in_frame("profile_create_name"))
def _kb_pcn_any(event):
    global _create_name_buf, _create_name_err
    data = event.data or ""
    if len(data) != 1 or not data.isprintable():
        return
    if len(_create_name_buf) >= 32:
        return
    _create_name_buf += data
    _create_name_err = ""


# Profile create — choose blank vs copy
@kb.add("escape", filter=_in_frame("profile_create_choose"), eager=True)
def _kb_pcc_escape(event):
    # Cancel back to the profile list.
    global _frame_stack, _current_frame
    while _frame_stack and _current_frame.startswith("profile_create"):
        _current_frame = _frame_stack.pop()
    _focus_current_frame()
    if _app:
        _app.invalidate()


@kb.add("b", filter=_in_frame("profile_create_choose"))
@kb.add("B", filter=_in_frame("profile_create_choose"))
def _kb_pcc_blank(event):
    _profile_create_finish_blank()


@kb.add("c", filter=_in_frame("profile_create_choose"))
@kb.add("C", filter=_in_frame("profile_create_choose"))
def _kb_pcc_copy(event):
    _enter_profile_create_copy_picker()


# Profile create — copy picker
@kb.add("escape", filter=_in_frame("profile_create_copy_picker"), eager=True)
def _kb_pcp_escape(event):
    _pop_frame()


@kb.add("up", filter=_in_frame("profile_create_copy_picker"))
def _kb_pcp_up(event):
    global _sel_copy
    n = len(_create_src_profiles)
    if n:
        _sel_copy = (_sel_copy - 1) % n


@kb.add("down", filter=_in_frame("profile_create_copy_picker"))
def _kb_pcp_down(event):
    global _sel_copy
    n = len(_create_src_profiles)
    if n:
        _sel_copy = (_sel_copy + 1) % n


@kb.add("enter", filter=_in_frame("profile_create_copy_picker"))
@kb.add(" ",     filter=_in_frame("profile_create_copy_picker"))
def _kb_pcp_enter(event):
    if not _create_src_profiles:
        _pop_frame()
        return
    _activate_copy_picker(_sel_copy)


@kb.add("<any>", filter=_in_frame("profile_create_copy_picker"))
def _kb_pcp_any(event):
    # If no profiles available, any key dismisses.
    if not _create_src_profiles:
        _pop_frame()


# Profile delete confirm
@kb.add("escape", filter=_in_frame("profile_delete_confirm"), eager=True)
def _kb_pd_escape(event):
    _pop_frame()


@kb.add("y", filter=_in_frame("profile_delete_confirm"))
@kb.add("Y", filter=_in_frame("profile_delete_confirm"))
def _kb_pd_yes(event):
    if _delete_locked:
        _pop_frame()
    else:
        _confirm_profile_delete()


@kb.add("<any>", filter=_in_frame("profile_delete_confirm"))
def _kb_pd_any(event):
    _pop_frame()


# Options
@kb.add("up", filter=_in_frame("options"))
def _kb_opt_up(event):
    global _sel_options
    n = _options_count()
    if n:
        _sel_options = (_sel_options - 1) % n


@kb.add("down", filter=_in_frame("options"))
def _kb_opt_down(event):
    global _sel_options
    n = _options_count()
    if n:
        _sel_options = (_sel_options + 1) % n


@kb.add("enter", filter=_in_frame("options"))
@kb.add(" ",     filter=_in_frame("options"))
def _kb_opt_select(event):
    _activate_option(_sel_options)


@kb.add("escape", filter=_in_frame("options"), eager=True)
def _kb_opt_escape(event):
    _save_conf()
    _pop_frame()


# Scripts
@kb.add("up", filter=_in_frame("scripts"))
def _kb_scr_up(event):
    _scroll_scripts(-1)


@kb.add("down", filter=_in_frame("scripts"))
def _kb_scr_down(event):
    _scroll_scripts(1)


@kb.add("pageup", filter=_in_frame("scripts"))
def _kb_scr_pgup(event):
    _scroll_scripts(-10)


@kb.add("pagedown", filter=_in_frame("scripts"))
def _kb_scr_pgdn(event):
    _scroll_scripts(10)


@kb.add("escape", filter=_in_frame("scripts"), eager=True)
def _kb_scr_escape(event):
    _pop_frame()


# About
@kb.add("up", filter=_in_frame("about"))
def _kb_abt_up(event):
    _scroll_about(-1)


@kb.add("down", filter=_in_frame("about"))
def _kb_abt_down(event):
    _scroll_about(1)


@kb.add("pageup", filter=_in_frame("about"))
def _kb_abt_pgup(event):
    _scroll_about(-10)


@kb.add("pagedown", filter=_in_frame("about"))
def _kb_abt_pgdn(event):
    _scroll_about(10)


@kb.add("escape", filter=_in_frame("about"), eager=True)
def _kb_abt_escape(event):
    _pop_frame()


# Update running — no input
@kb.add("<any>", filter=_in_frame("update_running"))
def _kb_upd_run(event):
    pass


# Update result — any key
@kb.add("escape", filter=_in_frame("update_result"), eager=True)
def _kb_upd_esc(event):
    _update_result_keypress()


@kb.add("<any>", filter=_in_frame("update_result"))
def _kb_upd_any(event):
    _update_result_keypress()


# Exit confirm
@kb.add("y", filter=_in_frame("exit_confirm"))
@kb.add("Y", filter=_in_frame("exit_confirm"))
def _kb_ec_yes(event):
    event.app.exit()


@kb.add("escape", filter=_in_frame("exit_confirm"), eager=True)
def _kb_ec_escape(event):
    _pop_frame()


@kb.add("<any>", filter=_in_frame("exit_confirm"))
def _kb_ec_any(event):
    _pop_frame()


# ---------------------------------------------------------------------------
# Layout — frame builders
# ---------------------------------------------------------------------------
def _make_window(text_fn, focusable=True):
    return Window(
        content=FormattedTextControl(text=text_fn, focusable=focusable),
        wrap_lines=False,
        always_hide_cursor=True,
    )


def _centered(window):
    """Vertically center `window` within available space."""
    return HSplit([window], align=VerticalAlign.CENTER)


def _build_simple(text_fn):
    """Build a vertically-centered frame around a single text-fn Window."""
    win = _make_window(text_fn, focusable=True)
    return win, _centered(win)


def _build_scrolling(title_fn, content_fn, footer_fn):
    """Build a [title (fixed) | content (fills) | footer (fixed)] frame."""
    title  = Window(content=FormattedTextControl(text=title_fn,  focusable=False),
                    height=3, wrap_lines=False, always_hide_cursor=True)
    content = Window(content=FormattedTextControl(text=content_fn, focusable=True),
                     wrap_lines=False, always_hide_cursor=True,
                     height=Dimension(weight=1))
    footer = Window(content=FormattedTextControl(text=footer_fn, focusable=False),
                    height=2, wrap_lines=False, always_hide_cursor=True)
    return content, HSplit([title, content, footer])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _app, _app_loop, _cockpit_version, _cache_mtime
    global _main_window, _profile_window
    global _profile_create_name_window, _profile_create_choose_window
    global _profile_create_copy_window, _profile_delete_window
    global _options_window, _scripts_window, _about_window
    global _update_running_window, _update_result_window
    global _exit_confirm_window, _too_small_window

    os.chdir(PROJECT_DIR)
    _one_shot_migrations()
    _load_conf()
    _cockpit_version = _read_version_file()
    _spawn_version_check()
    _load_random_quote()
    _cache_mtime = _cache_mtime_now()
    _rebuild_main_items(preserve_label=False)

    _main_window,                  main_frame                = _build_simple(_main_text)
    _profile_window,               profile_frame             = _build_simple(_profile_text)
    _profile_create_name_window,   pcn_frame                 = _build_simple(_profile_create_name_text)
    _profile_create_choose_window, pcc_frame                 = _build_simple(_profile_create_choose_text)
    _profile_create_copy_window,   pcp_frame                 = _build_simple(_profile_create_copy_text)
    _profile_delete_window,        pd_frame                  = _build_simple(_profile_delete_text)
    _options_window,               options_frame             = _build_simple(_options_text)
    _scripts_window,               scripts_frame             = _build_scrolling(
        _scripts_title_text, _scripts_content_text, _scripts_footer_text
    )
    _about_window,                 about_frame               = _build_scrolling(
        _about_title_text, _about_content_text, _about_footer_text
    )
    _update_running_window,        update_running_frame      = _build_simple(_update_running_text)
    _update_result_window,         update_result_frame       = _build_simple(_update_result_text)
    _exit_confirm_window,          exit_confirm_frame        = _build_simple(_exit_confirm_text)
    _too_small_window,             too_small_frame           = _build_simple(_too_small_text)

    frames = {
        "main":                       main_frame,
        "profile":                    profile_frame,
        "profile_create_name":        pcn_frame,
        "profile_create_choose":      pcc_frame,
        "profile_create_copy_picker": pcp_frame,
        "profile_delete_confirm":     pd_frame,
        "options":                    options_frame,
        "scripts":                    scripts_frame,
        "about":                      about_frame,
        "update_running":             update_running_frame,
        "update_result":              update_result_frame,
        "exit_confirm":               exit_confirm_frame,
    }

    def _root():
        if not _size_ok():
            return too_small_frame
        return frames.get(_current_frame, main_frame)

    layout = Layout(DynamicContainer(_root))

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        color_depth=ColorDepth.TRUE_COLOR,
        refresh_interval=1.0,
    )
    app.ttimeoutlen = 0.05
    app.timeoutlen  = 0.05
    _app = app

    async def _run():
        global _app_loop
        _app_loop = asyncio.get_running_loop()
        _focus_current_frame()
        await app.run_async()

    try:
        asyncio.run(_run())
    finally:
        _app = None
        _app_loop = None

    if _deferred_exec is not None:
        cmd, argv = _deferred_exec
        # Re-enter alt-screen (and hide cursor) before handing off, so the
        # terminal stays in alt-screen across the gap between prompt_toolkit's
        # restore and tmux taking over — no flash of the user's normal shell.
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
        os.execvp(cmd, argv)


if __name__ == "__main__":
    main()
