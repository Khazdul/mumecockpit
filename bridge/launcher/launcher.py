#!/usr/bin/env python3
# bridge/launcher/launcher.py — pre-tmux startup menu (prompt_toolkit rewrite).
# Invoked via bridge/launcher/launcher.sh. Behavioural contract: docs/launcher.md.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import DynamicContainer, Layout, VerticalAlign
    from prompt_toolkit.layout.containers import HSplit, VSplit, Window
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
import bisect
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time

# Make sibling modules importable when run directly via the wrapper.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palette import (  # noqa: E402
    C_TITLE, C_ACTIVE, C_ITEM, C_BODY, C_HINT, C_ACCENT,
    C_YELLOW, C_ERR, C_QUOTE, C_QUOTE_ATTR, C_HOVER, C_SELECTED,
    C_HEADER, C_SECTION, C_DIVIDER, C_WATCH_LOG, C_WATCH_LOG_HOVER,
    C_LOG_CURSOR,
    _S_GAINED, _S_LOSS, _S_LABEL, _S_VALUE, _S_TP_BAR,
    _S_TRACK, _S_MARKER, _S_THUMB, _S_TOTAL, _S_ARROW,
    _S_HINT, _S_PVP, _S_ALLY, _S_STAR,
)
import log_player  # noqa: E402
import run_stats  # noqa: E402
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

# History
_history_sidebar_items   = []        # ["All", "<char>", ...]
_history_sessions        = []        # filtered + sorted SessionSummary list
_history_filter          = "All"
_history_sort            = ("Char", "asc")
_history_sidebar_cursor  = 0
_history_sidebar_scroll  = 0
_history_table_cursor    = 0
_history_table_scroll    = 0
_history_focused         = 0         # 0 = sidebar, 1 = table
_history_hover           = (None, None)   # (panel_idx, row_idx)
_history_table_sb        = None
_history_detail_summary  = None      # SessionSummary pushed into the detail frame
_history_detail_stats    = None      # aggregated RunStats for that summary
_history_detail_log_hover = False    # WATCH LOG button hover flag
# Statistics body — mirrors the popup's _stats_* state.
_history_detail_kills_sort      = ("XP tot", "desc")
_history_detail_pkills_sort     = ("XP", "desc")
_history_detail_focused         = 0  # 0=KILLS, 1=PvPs, 2=ALLIES, 3=ACHIEVEMENTS
_history_detail_kills_sb        = None
_history_detail_pkills_sb       = None
_history_detail_allies_sb       = None
_history_detail_achievements_sb = None
_history_detail_kills_pvps_visible = 2  # last computed visible row count

# log_view (chain log player) — Phase 3
_log_view_playback = None   # log_player.LogPlayback or None
_log_view_scroll   = 0      # visual-line offset into the rendered buffer
_log_view_cols     = 0      # last cols used to wrap; invalidates cache on change
_log_view_lines    = None   # cached visual lines: list[list[(style, run)]]
_log_view_event_rows = None # parallel to events: (visual_start, visual_end_exclusive)
# Playback engine
_log_mode                   = "play"   # "play" | "pause"
_log_play_anchor_wall       = 0.0      # monotonic() at last play-start
_log_play_anchor_offset_us  = 0        # playback time at last play-start
_log_paused_offset_us       = 0        # frozen playback time while paused
_log_cursor_index           = 0        # event index of the cursor (pause mode)
_log_last_playhead_index    = -1       # last index pushed to renderer (tick dirty-check)
_log_tick_task              = None     # asyncio.Task driving play-mode redraws
_LOG_TICK_HZ                = 30
_LOG_PAGE_STEP              = 20       # PgUp/PgDn cursor delta in pause
_history_columns = [
    # (key, base_label, width, align, type)
    ("Char",   "Char",  None, "left",  "text"),
    ("Date",   "Date",  10,   "left",  "text"),
    ("Time",   "Time",  5,    "left",  "text"),
    ("Dur.",   "Dur.",  5,    "left",  "numeric"),
    ("PK",     "PK",    3,    "right", "numeric"),
    ("XP",     "XP",    7,    "right", "numeric"),
]

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
_history_sidebar_window = None
_history_table_window   = None
_history_detail_window  = None
_log_view_window        = None

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
    if _current_frame == "history":
        win = _history_sidebar_window if _history_focused == 0 else _history_table_window
    else:
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
            "history_detail":             _history_detail_window,
            "log_view":                   _log_view_window,
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
    items.extend(["Profile", "History", "Options", "Scripts", "About", "Quit"])
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
    elif label == "History":
        _enter_history_frame()
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
# History frame
# ---------------------------------------------------------------------------
def _history_sidebar_panel_w():
    """Sidebar panel width = max("Filter", "All", longest character name) + 2
    for breathing room. Recomputed each render so resizes and roster changes
    recentre cleanly."""
    chars = _history_sidebar_items[1:]
    inner = max(len("Filter"), len("All"), max((len(c) for c in chars), default=0))
    return inner + 2


def _history_table_panel_w():
    """Total width of the table content (column widths + per-gap separators)."""
    _, total = _history_table_columns_layout()
    return total


def _enter_history_frame():
    global _history_sidebar_items, _history_filter, _history_sort
    global _history_sidebar_cursor, _history_sidebar_scroll
    global _history_table_cursor, _history_table_scroll
    global _history_focused, _history_hover
    global _history_table_sb
    try:
        chars = run_stats.list_characters_with_runs()
    except Exception:
        chars = []
    _history_sidebar_items  = ["All"] + chars
    _history_filter         = "All"
    _history_sort           = ("Char", "asc")
    _history_sidebar_cursor = 0
    _history_sidebar_scroll = 0
    _history_table_cursor   = 0
    _history_table_scroll   = 0
    _history_focused        = 1
    _history_hover          = (None, None)
    _history_table_sb = Scrollbar(
        0, _history_table_visible(), _history_table_visible(),
    )
    _history_refresh_sessions()
    _push_frame("history")


def _history_body_rows():
    # Title (3) + footer (2) = 5 reserved.
    return max(1, _term_rows() - 5)


def _history_sidebar_visible():
    # One row for the "Filter" header.
    return max(1, _history_body_rows() - 1)


def _history_table_visible():
    # One row for the column header.
    return max(1, _history_body_rows() - 1)


def _history_load_sessions_for_filter():
    if _history_filter == "All":
        out = []
        for ch in _history_sidebar_items[1:]:
            try:
                out.extend(run_stats.list_sessions(ch))
            except Exception:
                pass
        return out
    try:
        return list(run_stats.list_sessions(_history_filter))
    except Exception:
        return []


def _history_sort_key(col):
    return {
        "Char": lambda s: s.character.lower(),
        "Date": lambda s: s.start_ts,
        "Time": lambda s: s.start_ts,
        "Dur.": lambda s: s.duration_seconds,
        "PK":   lambda s: s.pkill_count,
        "XP":   lambda s: s.xp_gained,
    }.get(col, lambda s: s.start_ts)


def _history_col_type(col):
    for key, _label, _w, _align, ctype in _history_columns:
        if key == col:
            return ctype
    return "text"


def _history_default_sort_dir(col):
    return "asc" if _history_col_type(col) == "text" else "desc"


def _history_refresh_sessions():
    """Recompute _history_sessions from filter + sort. Resets table scroll
    but preserves table cursor index validity."""
    global _history_sessions, _history_table_scroll, _history_table_cursor
    sessions = _history_load_sessions_for_filter()
    sessions.sort(key=lambda s: s.start_ts, reverse=True)
    col, direction = _history_sort
    sessions.sort(key=_history_sort_key(col), reverse=(direction == "desc"))
    _history_sessions = sessions
    _history_table_scroll = 0
    if _history_table_cursor >= len(sessions):
        _history_table_cursor = max(0, len(sessions) - 1)


def _history_set_filter(name):
    """Apply filter; reset table scroll + cursor; preserve sort."""
    global _history_filter, _history_table_cursor
    if name not in _history_sidebar_items:
        return
    _history_filter       = name
    _history_table_cursor = 0
    _history_refresh_sessions()
    if _app:
        _app.invalidate()


def _history_toggle_sort(col):
    global _history_sort
    cur_col, cur_dir = _history_sort
    if col == cur_col:
        new_dir = "asc" if cur_dir == "desc" else "desc"
    else:
        new_dir = _history_default_sort_dir(col)
    _history_sort = (col, new_dir)
    _history_refresh_sessions()
    if _app:
        _app.invalidate()


def _history_fmt_duration(secs):
    secs = max(0, int(secs))
    if secs < 60:
        return "0 m"
    minutes = secs // 60
    if minutes < 60:
        return f"{minutes} m"
    hours = minutes // 60
    return f"{hours} h"


def _history_fmt_xp(xp):
    """Return (text, style) per spec."""
    try:
        xp = int(xp)
    except (TypeError, ValueError):
        return "0k", _S_LABEL
    if xp > 0 and xp >= 1000:
        return f"{round(xp / 1000)}k", _S_GAINED
    if xp < -999:
        return f"{-round(-xp / 1000)}k", _S_LOSS
    return "0k", _S_LABEL


def _history_fmt_date(ts):
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _history_fmt_time(ts):
    try:
        return time.strftime("%H:%M", time.localtime(int(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _history_char_col_width():
    base = len("Char ▼")
    chars = _history_sidebar_items[1:]
    if chars:
        base = max(base, max(len(c) for c in chars))
    return base


def _history_header_label(base, is_active, sort_dir, align, width):
    txt = base
    if is_active:
        txt += " ▼" if sort_dir == "desc" else " ▲"
    if align == "left":
        return txt[:width].ljust(width)
    return txt[:width].rjust(width)


def _history_scroll_into_view(cursor, scroll, visible):
    if cursor < scroll:
        return cursor
    if cursor >= scroll + visible:
        return cursor - visible + 1
    return scroll


def _history_move_sidebar(delta):
    global _history_sidebar_cursor, _history_sidebar_scroll
    n = len(_history_sidebar_items)
    if not n:
        return
    new_cursor = (_history_sidebar_cursor + delta) % n
    _history_sidebar_cursor = new_cursor
    _history_sidebar_scroll = _history_scroll_into_view(
        new_cursor, _history_sidebar_scroll, _history_sidebar_visible()
    )
    _history_set_filter(_history_sidebar_items[new_cursor])


def _history_jump_sidebar(target):
    global _history_sidebar_cursor, _history_sidebar_scroll
    n = len(_history_sidebar_items)
    if not n:
        return
    new_cursor = max(0, min(n - 1, target))
    _history_sidebar_cursor = new_cursor
    _history_sidebar_scroll = _history_scroll_into_view(
        new_cursor, _history_sidebar_scroll, _history_sidebar_visible()
    )
    _history_set_filter(_history_sidebar_items[new_cursor])


def _history_move_table(delta):
    global _history_table_cursor, _history_table_scroll
    n = len(_history_sessions)
    if not n:
        return
    new_cursor = max(0, min(n - 1, _history_table_cursor + delta))
    _history_table_cursor = new_cursor
    _history_table_scroll = _history_scroll_into_view(
        new_cursor, _history_table_scroll, _history_table_visible()
    )
    if _app:
        _app.invalidate()


def _history_jump_table(target):
    global _history_table_cursor, _history_table_scroll
    n = len(_history_sessions)
    if not n:
        return
    new_cursor = max(0, min(n - 1, target))
    _history_table_cursor = new_cursor
    _history_table_scroll = _history_scroll_into_view(
        new_cursor, _history_table_scroll, _history_table_visible()
    )
    if _app:
        _app.invalidate()


def _history_scroll_panel(panel, delta):
    """Wheel scroll for panel under cursor. Does NOT move cursor."""
    global _history_sidebar_scroll, _history_table_scroll
    if panel == 0:
        mx = max(0, len(_history_sidebar_items) - _history_sidebar_visible())
        _history_sidebar_scroll = max(0, min(mx, _history_sidebar_scroll + delta))
    else:
        mx = max(0, len(_history_sessions) - _history_table_visible())
        _history_table_scroll = max(0, min(mx, _history_table_scroll + delta))
    if _app:
        _app.invalidate()


def _history_set_focus(panel):
    global _history_focused
    if _history_focused == panel:
        return
    _history_focused = panel
    _focus_current_frame()
    if _app:
        _app.invalidate()


def _history_toggle_focus():
    _history_set_focus(1 - _history_focused)


def _history_set_hover(panel, row):
    global _history_hover, _history_detail_log_hover
    new_val = (panel, row)
    changed = False
    if _history_hover != new_val:
        _history_hover = new_val
        changed = True
    # _hover_at(None, None) also drops the WATCH LOG hover style — used by
    # the surrounding fragments in the history_detail frame so the button's
    # hover paint clears the moment the cursor leaves it.
    if new_val == (None, None) and _history_detail_log_hover:
        _history_detail_log_hover = False
        changed = True
    if changed and _app:
        _app.invalidate()


def _hover_at(panel, idx, on_event=None):
    """Mouse handler factory for the history frame.

    On MOUSE_MOVE, sets _history_hover to (panel, idx) — pass None for
    either arg to clear hover. Other events are delegated to on_event(ev)
    if provided. Anything we don't handle returns NotImplemented so that
    _HistScrollControl still sees scroll-wheel events."""
    def _handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _history_set_hover(panel, idx)
            return None
        if on_event is not None:
            return on_event(ev)
        return NotImplemented
    return _handler


def _hover_clear_frags(frags):
    """Wrap each fragment in `frags` so MOUSE_MOVE clears _history_hover.
    Existing handlers (e.g. scrollbar MOUSE_DOWN) are preserved."""
    out = []
    for f in frags:
        style, text = f[0], f[1]
        inner = f[2] if len(f) >= 3 else None
        out.append((style, text, _hover_at(None, None, on_event=inner)))
    return out


def _history_activate_table_row(idx):
    """Move cursor to idx, aggregate the chain, push history_detail."""
    global _history_table_cursor
    global _history_detail_summary, _history_detail_stats, _history_detail_log_hover
    global _history_detail_kills_sort, _history_detail_pkills_sort
    global _history_detail_focused
    if idx < 0 or idx >= len(_history_sessions):
        return
    _history_table_cursor = idx
    summary = _history_sessions[idx]
    try:
        stats = run_stats.aggregate(summary.character, summary.run_ids)
    except Exception:
        stats = None
    _history_detail_summary    = summary
    _history_detail_stats      = stats
    _history_detail_log_hover  = False
    _history_detail_kills_sort  = ("XP tot", "desc")
    _history_detail_pkills_sort = ("XP", "desc")
    _history_detail_focused     = 0
    _hd_ensure_scrollbars()
    for sb in (_history_detail_kills_sb, _history_detail_pkills_sb,
               _history_detail_allies_sb, _history_detail_achievements_sb):
        sb.scroll_to(0)
    _push_frame("history_detail")


# --- Title / footer text ---------------------------------------------------
def _history_title_text():
    cols = _term_cols()
    title = "─── History ───"
    return _hover_clear_frags([
        ("", "\n"),
        ("", _pad_centre(title, cols)),
        (C_TITLE, title),
        ("", "\n"),
    ])


def _history_footer_text():
    cols = _term_cols()
    footer = "↑↓ Navigate · Tab Switch panel · Enter Select · ESC Back"
    return _hover_clear_frags([
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ])


# --- Sidebar render --------------------------------------------------------
def _history_sidebar_text():
    visible = _history_sidebar_visible()
    items   = _history_sidebar_items
    total   = len(items)
    mx      = max(0, total - visible)
    global _history_sidebar_scroll
    if _history_sidebar_scroll > mx:
        _history_sidebar_scroll = mx

    width   = _history_sidebar_panel_w()
    sliced  = items[_history_sidebar_scroll:_history_sidebar_scroll + visible]
    frags   = []
    hover_panel, hover_row = _history_hover
    sidebar_focused = (_history_focused == 0)

    # Header row: "Filter".
    header_style = C_ACTIVE if sidebar_focused else C_SECTION
    header_text  = (" Filter")[:width].ljust(width)

    def _header_click(ev):
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _history_set_focus(0)
            return None
        return NotImplemented

    frags.append((header_style, header_text,
                  _hover_at(None, None, on_event=_header_click)))
    frags.append(("", "\n", _hover_at(None, None)))

    for i, label in enumerate(sliced):
        row_abs   = _history_sidebar_scroll + i
        is_active = (items[row_abs] == _history_filter)
        is_hover  = (hover_panel == 0 and hover_row == row_abs)

        if is_active:
            style = C_SELECTED
        elif is_hover:
            style = C_HOVER
        else:
            style = C_ITEM

        text = " " + label
        text = text[:width].ljust(width)

        def _click(ev, row=row_abs):
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _history_set_focus(0)
                _history_jump_sidebar(row)
                return None
            return NotImplemented

        frags.append((style, text, _hover_at(0, row_abs, on_event=_click)))
        # Pad the rest of the visible area below the last row.
        if i < len(sliced) - 1:
            frags.append(("", "\n", _hover_at(None, None)))

    # Pad remaining height with blank rows so the panel keeps its shape.
    blank_rows = visible - len(sliced)
    for _ in range(blank_rows):
        frags.append(("", "\n", _hover_at(None, None)))
        frags.append(("", " " * width, _hover_at(None, None)))
    return frags


# --- Table render ----------------------------------------------------------
def _history_table_columns_layout():
    """Compute (cols_with_widths, total_width) for current state."""
    char_w = _history_char_col_width()
    cols = []
    total = 0
    for i, (key, base, w, align, ctype) in enumerate(_history_columns):
        width = char_w if key == "Char" else w
        cols.append((key, base, width, align, ctype))
        total += width
        if i < len(_history_columns) - 1:
            total += 1   # one-space gap between columns
    return cols, total


def _history_format_row(session, cols):
    """Return list of (text, style) per column."""
    sort_col = _history_sort[0]
    out = []
    for (key, _base, width, align, _ctype) in cols:
        if key == "Char":
            txt = session.character[:width].ljust(width)
            style = _S_LABEL
        elif key == "Date":
            txt = _history_fmt_date(session.start_ts)[:width].ljust(width)
            style = _S_LABEL
        elif key == "Time":
            txt = _history_fmt_time(session.start_ts)[:width].ljust(width)
            style = _S_LABEL
        elif key == "Dur.":
            txt = _history_fmt_duration(session.duration_seconds)
            txt = txt[:width].ljust(width)
            style = _S_LABEL
        elif key == "PK":
            txt = str(int(session.pkill_count or 0))[:width].rjust(width)
            style = _S_LABEL
        elif key == "XP":
            short, style = _history_fmt_xp(session.xp_gained)
            txt = short[:width].rjust(width)
        else:
            txt = "".ljust(width)
            style = _S_LABEL
        out.append((txt, style))
    return out


def _history_table_text():
    cols_layout, total_w = _history_table_columns_layout()

    frags = []
    sort_col, sort_dir = _history_sort
    table_focused      = (_history_focused == 1)
    clear_hover        = _hover_at(None, None)

    # Empty state — render centred message, no header.
    if not _history_sessions:
        msg = "No runs recorded yet."
        visible = _history_table_visible() + 1  # include header row in the panel
        top_pad = max(0, (visible - 1) // 2)
        for _ in range(top_pad):
            frags.append(("", "\n", clear_hover))
        frags.append(("", " " * max(0, (total_w - len(msg)) // 2), clear_hover))
        frags.append((C_BODY, msg, clear_hover))
        bottom = visible - top_pad - 1
        for _ in range(bottom):
            frags.append(("", "\n", clear_hover))
        return frags

    # Header row.
    header_style = C_ACTIVE if table_focused else C_SECTION
    for i, (key, base, width, align, _ctype) in enumerate(cols_layout):
        is_active_sort = (key == sort_col)
        label = _history_header_label(base, is_active_sort, sort_dir, align, width)

        def _click(ev, col=key):
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _history_set_focus(1)
                _history_toggle_sort(col)
                return None
            return NotImplemented
        cell_handler = _hover_at(None, None, on_event=_click)
        if i > 0:
            frags.append((header_style, " ", cell_handler))
        frags.append((header_style, label, cell_handler))
    frags.append(("", "\n", clear_hover))

    # Data rows.
    visible = _history_table_visible()
    total   = len(_history_sessions)
    mx      = max(0, total - visible)
    global _history_table_scroll
    if _history_table_scroll > mx:
        _history_table_scroll = mx
    if _history_table_sb is not None:
        _history_table_sb.update(total, visible, height=visible)
        _history_table_sb.scroll_to(_history_table_scroll)

    sliced = _history_sessions[_history_table_scroll:_history_table_scroll + visible]
    hover_panel, hover_row = _history_hover

    for vi, session in enumerate(sliced):
        row_abs   = _history_table_scroll + vi
        is_cursor = (row_abs == _history_table_cursor)
        is_hover  = (hover_panel == 1 and hover_row == row_abs)

        if is_cursor:
            row_bg = C_SELECTED
        elif is_hover:
            row_bg = C_HOVER
        else:
            row_bg = None

        def _click(ev, row=row_abs):
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _history_set_focus(1)
                _history_activate_table_row(row)
                return None
            return NotImplemented
        row_handler = _hover_at(1, row_abs, on_event=_click)

        row_frags = _history_format_row(session, cols_layout)
        for i, (txt, default_style) in enumerate(row_frags):
            style = row_bg if row_bg is not None else default_style
            if i > 0:
                frags.append((style, " ", row_handler))
            frags.append((style, txt, row_handler))
        if vi < len(sliced) - 1:
            frags.append(("", "\n", clear_hover))

    # Trailing blank lines so panel keeps its shape.
    blank = visible - len(sliced)
    for _ in range(blank):
        frags.append(("", "\n", clear_hover))

    return frags


def _history_table_scrollbar_text():
    if _history_table_sb is None or not _history_sessions:
        return []
    # Leave the header row's strip blank, then render scrollbar over the data area.
    frags = [("", " "), ("", "\n")]
    frags.extend(_history_table_sb.render())
    return _hover_clear_frags(frags)


# --- Wheel-scrolling control ----------------------------------------------
class _HistScrollControl(FormattedTextControl):
    def __init__(self, *args, panel, **kwargs):
        super().__init__(*args, **kwargs)
        self._panel = panel

    def mouse_handler(self, ev):
        result = super().mouse_handler(ev)
        if result is NotImplemented:
            if ev.event_type == MouseEventType.SCROLL_UP:
                _history_scroll_panel(self._panel, -1)
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                _history_scroll_panel(self._panel, 1)
                return None
        return result


# --- history_detail --------------------------------------------------------
def _hd_fmt_ts(ts, fmt):
    try:
        return time.strftime(fmt, time.localtime(int(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _hd_watch_log_handler(ev):
    """WATCH LOG button — MOUSE_MOVE sets hover; MOUSE_DOWN pushes log_view."""
    global _history_detail_log_hover
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        if not _history_detail_log_hover:
            _history_detail_log_hover = True
            if _app:
                _app.invalidate()
        return None
    if ev.event_type == MouseEventType.MOUSE_DOWN:
        _enter_log_view()
        return None
    return NotImplemented


# --- Statistics body — adapted from ingame_menu.py (see spec) -------------
_HD_STAT_BAR_WIDTH       = 84
_HD_STAT_Y_LABEL_W       = 5
_HD_STAT_TABLE_LEFT_W    = 40
_HD_STAT_TABLE_RIGHT_W   = 40
_HD_STAT_TABLE_GAP       = "  "
_HD_STAT_BLOCKS          = "▁▂▃▄▅▆▇█"

# ALLIES + ACHIEVEMENTS show a fixed 3 rows each. KILLS + PvPs auto-size to
# their data (capped by _hd_compute_kills_pvps_visible() so the section never
# overflows the frame). With no data on either side, the section collapses to
# the title row and divider only.
_HD_ALLIES_ACH_VISIBLE      = 3
_HD_KILLS_PVPS_MIN_VISIBLE  = 2
# Fixed lines around the kills/pvps data rows in _history_detail_text:
# 1 leading "\n" + 1 header row + 1 blank + 5 A/A (title+div+3) + 1 blank
# + 3 KP fixed (title+div+total) + 1 blank + 7 sparklines + 1 blank
# + 4 xp-linjal + 1 blank + 1 footer = 28.
_HD_STATS_FIXED_LINES       = 28


def _hd_compute_kills_pvps_visible():
    """Cap on KILLS/PvPs data rows that fit in the frame."""
    available = _term_rows() - _HD_STATS_FIXED_LINES
    return max(_HD_KILLS_PVPS_MIN_VISIBLE, available)


def _hd_compute_kills_pvps_data_height(stats):
    """Data rows rendered: longer of the two sides, clamped by the cap."""
    if stats is None:
        return 0
    return min(max(len(stats.kills), len(stats.pkills)),
               _hd_compute_kills_pvps_visible())


def _hd_ensure_scrollbars():
    global _history_detail_kills_sb, _history_detail_pkills_sb
    global _history_detail_allies_sb, _history_detail_achievements_sb
    if _history_detail_kills_sb is None:
        _history_detail_kills_sb        = Scrollbar(
            0, _HD_KILLS_PVPS_MIN_VISIBLE, _HD_KILLS_PVPS_MIN_VISIBLE,
            thumb_style=_S_THUMB, track_style=_S_TRACK)
        _history_detail_pkills_sb       = Scrollbar(
            0, _HD_KILLS_PVPS_MIN_VISIBLE, _HD_KILLS_PVPS_MIN_VISIBLE,
            thumb_style=_S_THUMB, track_style=_S_TRACK)
        _history_detail_allies_sb       = Scrollbar(
            0, _HD_ALLIES_ACH_VISIBLE, _HD_ALLIES_ACH_VISIBLE,
            thumb_style=_S_THUMB, track_style=_S_TRACK)
        _history_detail_achievements_sb = Scrollbar(
            0, _HD_ALLIES_ACH_VISIBLE, _HD_ALLIES_ACH_VISIBLE,
            thumb_style=_S_THUMB, track_style=_S_TRACK)


def _hd_refresh_scrollbars(stats, visible):
    global _history_detail_kills_pvps_visible
    if _history_detail_kills_sb is None or stats is None:
        return
    _history_detail_kills_pvps_visible = visible
    _history_detail_kills_sb.update(len(stats.kills),  visible, height=visible)
    _history_detail_pkills_sb.update(len(stats.pkills), visible, height=visible)
    _history_detail_allies_sb.update(len(stats.allies),
                                     _HD_ALLIES_ACH_VISIBLE,
                                     height=_HD_ALLIES_ACH_VISIBLE)
    _history_detail_achievements_sb.update(len(stats.achievements),
                                           _HD_ALLIES_ACH_VISIBLE,
                                           height=_HD_ALLIES_ACH_VISIBLE)


def _hd_focused_scrollbar():
    return (_history_detail_kills_sb,
            _history_detail_pkills_sb,
            _history_detail_allies_sb,
            _history_detail_achievements_sb)[_history_detail_focused]


def _hd_focused_visible_count():
    if _history_detail_focused < 2:
        return _history_detail_kills_pvps_visible
    return _HD_ALLIES_ACH_VISIBLE


def _hd_set_focus(idx):
    global _history_detail_focused
    if _history_detail_focused == idx:
        return
    _history_detail_focused = idx
    if _app:
        _app.invalidate()


# Cumulative career-XP thresholds, indexed by level - 1. Mirror of
# lua/core/level_progress.lua's TABLE_XP; keep in sync.
# stylua: ignore
_HD_TABLE_XP = [
         1,      1000,      3000,      7000,     15000,     30000,     60000,    105000,    165000,    240000,  # 1-10
    330000,    435000,    555000,    690000,    840000,   1040000,   1290000,   1590000,   1940000,   2340000,  # 11-20
   2790000,   3290000,   3840000,   4440000,   5090000,   5790000,   6540000,   7340000,   8190000,   9090000,  # 21-30
  10040000,  11040000,  12090000,  13190000,  14290000,  15390000,  16640000,  17890000,  19145000,  20400000,  # 31-40
  21700000,  23050000,  24400000,  25750000,  27150000,  28550000,  30000000,  31500000,  33000000,  34550000,  # 41-50
  36150000,  37750000,  39400000,  41100000,  42850000,  44600000,  46400000,  48250000,  50000000,  52000000,  # 51-60
  54000000,  56000000,  58000000,  60000000,  62000000,  64000000,  66500000,  68500000,  71000000,  73000000,  # 61-70
  75500000,  77500000,  80000000,  82500000,  85000000,  87500000,  90000000,  92500000,  95000000,  97500000,  # 71-80
 100500000, 103000000, 106000000, 108500000, 111500000, 114000000, 117000000, 120000000, 123000000, 126000000,  # 81-90
 129000000, 132000000, 135000000, 138000000, 141500000, 144500000, 148000000, 151000000, 154500000, 158000000,  # 91-100
]


def _hd_level_threshold(level):
    if level <= 1:
        return _HD_TABLE_XP[0]
    if level >= 100:
        return _HD_TABLE_XP[99]
    return _HD_TABLE_XP[level - 1]


def _hd_level_from_xp(xp):
    if xp <= 0:
        return 1
    L = 1
    while L < 100 and xp >= _HD_TABLE_XP[L]:
        L += 1
    return L


def _hd_xp_to_bar_col(xp, min_lv, hi_lv, bar_w):
    span = max(1, hi_lv - min_lv)
    if xp <= _hd_level_threshold(min_lv):
        return 0
    if xp >= _hd_level_threshold(hi_lv):
        return bar_w
    L = min_lv
    while L < hi_lv - 1 and xp >= _hd_level_threshold(L + 1):
        L += 1
    lo = _hd_level_threshold(L)
    hi = _hd_level_threshold(L + 1)
    frac = (xp - lo) / (hi - lo) if hi > lo else 0.0
    frac = max(0.0, min(1.0, frac))
    level_pos = (L - min_lv) + frac
    return max(0, min(bar_w, int(round(level_pos / span * bar_w))))


def _hd_fmt_xp_short(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n // 1000}k"


def _hd_fmt_duration_hms(secs):
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _hd_bucket_event_sums(events, n_buckets, start_ts, end_ts):
    if n_buckets <= 0 or end_ts <= start_ts:
        return [0] * max(0, n_buckets)
    bucket_dur = (end_ts - start_ts) / n_buckets
    if bucket_dur <= 0:
        return [0] * n_buckets
    buckets = [0] * n_buckets
    for ts, val in events:
        if ts < start_ts or ts > end_ts:
            continue
        idx = int((ts - start_ts) / bucket_dur)
        if idx >= n_buckets:
            idx = n_buckets - 1
        buckets[idx] += val
    return buckets


def _hd_sparkline_rows(values, max_val, rows=3, levels_per_row=8):
    n = len(values)
    if rows <= 0 or n == 0:
        return [""] * max(0, rows)
    total = rows * levels_per_row
    if max_val <= 0:
        cells = [0] * n
    else:
        cells = [
            min(total, max(0, int(round(v / max_val * total))))
            for v in values
        ]
    out = []
    for r in range(rows - 1, -1, -1):
        line = []
        for c in cells:
            sub = c - r * levels_per_row
            if sub <= 0:
                line.append(" ")
            elif sub >= levels_per_row:
                line.append("█")
            else:
                line.append(_HD_STAT_BLOCKS[sub - 1])
        out.append("".join(line))
    return out


def _hd_format_kill_row(name, n, xp_per, xp_tot, width):
    n_col      = 3
    xp_per_col = 7
    xp_tot_col = 9
    name_col   = max(1, width - n_col - xp_per_col - xp_tot_col - 3)
    if len(name) > name_col:
        name = name[:name_col - 1] + "…"
    return (
        f"{name.ljust(name_col)} "
        f"{n.rjust(n_col)} "
        f"{xp_per.rjust(xp_per_col)} "
        f"{xp_tot.rjust(xp_tot_col)}"
    )


def _hd_format_pkill_row(name, n, xp, width):
    n_col    = 3
    xp_col   = 9
    name_col = max(1, width - n_col - xp_col - 2)
    if len(name) > name_col:
        name = name[:name_col - 1] + "…"
    return f"{name.ljust(name_col)} {n.rjust(n_col)} {xp.rjust(xp_col)}"


def _hd_default_sort_dir(col):
    return "asc" if col in ("Mob", "Player") else "desc"


def _hd_toggle_sort(state_tuple, col):
    cur_col, cur_dir = state_tuple
    if col == cur_col:
        return (col, "asc" if cur_dir == "desc" else "desc")
    return (col, _hd_default_sort_dir(col))


def _hd_sorted_kills_items(kills_dict, sort_col, sort_dir):
    keys = {
        "Mob":    lambda kv: kv[0].lower(),
        "N":      lambda kv: kv[1].count,
        "XP/N":   lambda kv: (kv[1].total_xp // kv[1].count) if kv[1].count else 0,
        "XP tot": lambda kv: kv[1].total_xp,
    }
    items = list(kills_dict.items())
    items.sort(key=keys.get(sort_col, keys["XP tot"]),
               reverse=(sort_dir == "desc"))
    return items


def _hd_sorted_pkills_items(pkills_dict, sort_col, sort_dir):
    keys = {
        "Player": lambda kv: kv[0].lower(),
        "N":      lambda kv: kv[1].count,
        "XP":     lambda kv: kv[1].total_xp,
    }
    items = list(pkills_dict.items())
    items.sort(key=keys.get(sort_col, keys["XP"]),
               reverse=(sort_dir == "desc"))
    return items


def _hd_header_label(base, is_active, sort_dir, align, width):
    txt = base
    if is_active:
        txt += " ▼" if sort_dir == "desc" else " ▲"
    if align == "left":
        return txt[:width].ljust(width)
    return txt[:width].rjust(width)


def _hd_make_focus_handler(idx):
    """Cell handler: MOUSE_DOWN → set focus; wheel → scroll this table.
    Other events → NotImplemented so MOUSE_MOVE bubbles to the hover-clear
    wrapper applied at the end of _history_detail_text."""
    def _handler(ev):
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _hd_set_focus(idx)
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            sb = (_history_detail_kills_sb,
                  _history_detail_pkills_sb,
                  _history_detail_allies_sb,
                  _history_detail_achievements_sb)[idx]
            if sb is not None:
                sb.scroll_by(-1)
                if _app:
                    _app.invalidate()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            sb = (_history_detail_kills_sb,
                  _history_detail_pkills_sb,
                  _history_detail_allies_sb,
                  _history_detail_achievements_sb)[idx]
            if sb is not None:
                sb.scroll_by(1)
                if _app:
                    _app.invalidate()
            return None
        return NotImplemented
    return _handler


def _hd_scrollbar_row_cells(sb, table_idx):
    """Render `sb` and return one fragment per row (newlines stripped).
    Wraps each handler so a click also moves keyboard focus to this table.
    Wheel events scroll this table."""
    out = []
    focus_handler = _hd_make_focus_handler(table_idx)
    for f in sb.render():
        if len(f) >= 2 and f[1] == "\n":
            continue
        if len(f) == 3:
            style, text, orig = f

            def _wrapped(ev, orig=orig, idx=table_idx):
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _hd_set_focus(idx)
                    return orig(ev)
                if ev.event_type in (MouseEventType.SCROLL_UP,
                                     MouseEventType.SCROLL_DOWN):
                    return _hd_make_focus_handler(idx)(ev)
                return NotImplemented

            out.append((style, text, _wrapped))
        else:
            style, text = f[0], f[1]
            out.append((style, text, focus_handler))
    return out


def _hd_make_kill_header_handler(col):
    def _h(ev):
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return _hd_make_focus_handler(0)(ev)
        global _history_detail_kills_sort
        _hd_set_focus(0)
        _history_detail_kills_sort = _hd_toggle_sort(
            _history_detail_kills_sort, col)
        if _history_detail_kills_sb is not None:
            _history_detail_kills_sb.scroll_to(0)
        if _app:
            _app.invalidate()
    return _h


def _hd_make_pkill_header_handler(col):
    def _h(ev):
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return _hd_make_focus_handler(1)(ev)
        global _history_detail_pkills_sort
        _hd_set_focus(1)
        _history_detail_pkills_sort = _hd_toggle_sort(
            _history_detail_pkills_sort, col)
        if _history_detail_pkills_sb is not None:
            _history_detail_pkills_sb.scroll_to(0)
        if _app:
            _app.invalidate()
    return _h


def _hd_section_title_pair(frags, left_title, right_title,
                            left_w, right_w, gap, pad,
                            left_active=False, right_active=False,
                            left_focus=None, right_focus=None):
    l_style = C_ACTIVE if left_active  else C_SECTION
    r_style = C_ACTIVE if right_active else C_SECTION

    frags.append(("", pad))
    if left_focus:
        frags.append((l_style, left_title.ljust(left_w), left_focus))
    else:
        frags.append((l_style, left_title.ljust(left_w)))
    frags.append(("", " "))
    frags.append(("", gap))
    if right_focus:
        frags.append((r_style, right_title.ljust(right_w), right_focus))
    else:
        frags.append((r_style, right_title.ljust(right_w)))
    frags.append(("", " "))
    frags.append(("", "\n"))

    frags.append(("", pad))
    frags.append((C_DIVIDER, "─" * left_w))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_DIVIDER, "─" * right_w))
    frags.append(("", " "))
    frags.append(("", "\n"))


def _hd_append_allies_achievements(frags, stats, cols):
    left_w  = _HD_STAT_TABLE_LEFT_W
    right_w = _HD_STAT_TABLE_RIGHT_W
    gap     = _HD_STAT_TABLE_GAP
    total_w = left_w + 1 + len(gap) + right_w + 1
    margin  = max(0, (cols - total_w) // 2)
    pad     = " " * margin

    a_focus = _hd_make_focus_handler(2)
    h_focus = _hd_make_focus_handler(3)

    _hd_section_title_pair(
        frags, "ALLIES", "ACHIEVEMENTS", left_w, right_w, gap, pad,
        left_active=(_history_detail_focused == 2),
        right_active=(_history_detail_focused == 3),
        left_focus=a_focus, right_focus=h_focus,
    )

    ally_rows = list(stats.allies)
    ach_rows  = [a[1] for a in stats.achievements]

    a_off = _history_detail_allies_sb.scroll_offset
    h_off = _history_detail_achievements_sb.scroll_offset
    a_view = ally_rows[a_off:a_off + _HD_ALLIES_ACH_VISIBLE]
    h_view = ach_rows[h_off:h_off + _HD_ALLIES_ACH_VISIBLE]

    a_sb_cells = _hd_scrollbar_row_cells(_history_detail_allies_sb, 2)
    h_sb_cells = _hd_scrollbar_row_cells(_history_detail_achievements_sb, 3)

    a_inner_w = max(1, left_w  - 2)
    h_inner_w = max(1, right_w - 2)
    for i in range(_HD_ALLIES_ACH_VISIBLE):
        frags.append(("", pad))
        if i < len(a_view):
            a = a_view[i]
            if len(a) > a_inner_w:
                a = a[:a_inner_w - 1] + "…"
            frags.append((_S_ALLY,  "♦", a_focus))
            frags.append((_S_VALUE, " " + a.ljust(a_inner_w), a_focus))
        else:
            frags.append((_S_VALUE, " " * left_w, a_focus))
        if i < len(a_sb_cells):
            frags.append(a_sb_cells[i])
        else:
            frags.append(("", " "))
        frags.append(("", gap))
        if i < len(h_view):
            b = h_view[i]
            if len(b) > h_inner_w:
                b = b[:h_inner_w - 1] + "…"
            frags.append((_S_STAR,  "★", h_focus))
            frags.append((_S_VALUE, " " + b.ljust(h_inner_w), h_focus))
        else:
            frags.append((_S_VALUE, " " * right_w, h_focus))
        if i < len(h_sb_cells):
            frags.append(h_sb_cells[i])
        else:
            frags.append(("", " "))
        frags.append(("", "\n"))


def _hd_append_kills_pvps(frags, stats, cols, data_height):
    left_w  = _HD_STAT_TABLE_LEFT_W
    right_w = _HD_STAT_TABLE_RIGHT_W
    gap     = _HD_STAT_TABLE_GAP
    total_w = left_w + 1 + len(gap) + right_w + 1
    margin  = max(0, (cols - total_w) // 2)
    pad     = " " * margin

    k_focus = _hd_make_focus_handler(0)
    p_focus = _hd_make_focus_handler(1)

    sort_col_k,  sort_dir_k  = _history_detail_kills_sort
    sort_col_pk, sort_dir_pk = _history_detail_pkills_sort

    n_col, xp_per_col, xp_tot_col = 3, 7, 9
    k_name_col = max(1, left_w  - n_col - xp_per_col - xp_tot_col - 3)
    pk_xp_col  = 9
    p_name_col = max(1, right_w - n_col - pk_xp_col - 2)

    k_active = (_history_detail_focused == 0)
    p_active = (_history_detail_focused == 1)
    k_style  = C_ACTIVE if k_active else C_SECTION
    p_style  = C_ACTIVE if p_active else C_SECTION

    k_title = _hd_header_label("KILLS", sort_col_k  == "Mob",
                                sort_dir_k,  "left", k_name_col)
    p_title = _hd_header_label("PvPs",  sort_col_pk == "Player",
                                sort_dir_pk, "left", p_name_col)

    k_data_cols = [
        ("N",      "right", n_col),
        ("XP/N",   "right", xp_per_col),
        ("XP tot", "right", xp_tot_col),
    ]
    p_data_cols = [
        ("N",      "right", n_col),
        ("XP",     "right", pk_xp_col),
    ]

    frags.append(("", pad))
    frags.append((k_style, k_title, _hd_make_kill_header_handler("Mob")))
    for col, align, w in k_data_cols:
        h     = _hd_make_kill_header_handler(col)
        label = _hd_header_label(col, col == sort_col_k, sort_dir_k, align, w)
        frags.append((k_style, " ", h))
        frags.append((k_style, label, h))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((p_style, p_title, _hd_make_pkill_header_handler("Player")))
    for col, align, w in p_data_cols:
        h     = _hd_make_pkill_header_handler(col)
        label = _hd_header_label(col, col == sort_col_pk, sort_dir_pk, align, w)
        frags.append((p_style, " ", h))
        frags.append((p_style, label, h))
    frags.append(("", " "))
    frags.append(("", "\n"))

    frags.append(("", pad))
    frags.append((C_DIVIDER, "─" * left_w))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_DIVIDER, "─" * right_w))
    frags.append(("", " "))
    frags.append(("", "\n"))

    kills_items  = _hd_sorted_kills_items(stats.kills,   sort_col_k,  sort_dir_k)
    pkills_items = _hd_sorted_pkills_items(stats.pkills, sort_col_pk, sort_dir_pk)

    kills_count  = len(kills_items)
    pkills_count = len(pkills_items)
    needs_total  = (kills_count > 0) or (pkills_count > 0)

    k_off  = _history_detail_kills_sb.scroll_offset
    pk_off = _history_detail_pkills_sb.scroll_offset
    k_view = kills_items[k_off:k_off + data_height]
    p_view = pkills_items[pk_off:pk_off + data_height]

    k_sb_cells = _hd_scrollbar_row_cells(_history_detail_kills_sb,  0)
    p_sb_cells = _hd_scrollbar_row_cells(_history_detail_pkills_sb, 1)

    pk_n_col      = 3
    pk_xp_col_w   = 9
    pk_name_col   = max(1, right_w - pk_n_col - pk_xp_col_w - 2)
    pk_inner_name = max(1, pk_name_col - 2)

    for i in range(data_height):
        frags.append(("", pad))
        if i < len(k_view):
            name, agg = k_view[i]
            avg = agg.total_xp // agg.count if agg.count else 0
            k_line = _hd_format_kill_row(name, str(agg.count),
                                          str(avg), str(agg.total_xp), left_w)
            frags.append((_S_LABEL, k_line, k_focus))
        else:
            frags.append((_S_LABEL, " " * left_w))
        if i < len(k_sb_cells):
            frags.append(k_sb_cells[i])
        else:
            frags.append(("", " "))
        frags.append(("", gap))
        if i < len(p_view):
            name, agg = p_view[i]
            if len(name) > pk_inner_name:
                name = name[:pk_inner_name - 1] + "…"
            n_str_pk  = str(agg.count)
            xp_str_pk = str(agg.total_xp)
            p_rest    = (
                f" {name.ljust(pk_inner_name)} "
                f"{n_str_pk.rjust(pk_n_col)} "
                f"{xp_str_pk.rjust(pk_xp_col_w)}"
            )
            frags.append((_S_PVP,   "⚔", p_focus))
            frags.append((_S_LABEL, p_rest, p_focus))
        else:
            frags.append((_S_LABEL, " " * right_w))
        if i < len(p_sb_cells):
            frags.append(p_sb_cells[i])
        else:
            frags.append(("", " "))
        frags.append(("", "\n"))

    if needs_total:
        frags.append(("", pad))
        if kills_count > 0:
            k_cnt = sum(a.count for a in stats.kills.values())
            k_xp  = sum(a.total_xp for a in stats.kills.values())
            k_avg = k_xp // k_cnt if k_cnt else 0
            k_total = _hd_format_kill_row("Total", str(k_cnt), str(k_avg),
                                           str(k_xp), left_w)
            frags.append((_S_TOTAL, k_total, k_focus))
        else:
            frags.append((_S_TOTAL, " " * left_w))
        frags.append(("", " "))
        frags.append(("", gap))
        if pkills_count > 0:
            p_cnt = sum(a.count for a in stats.pkills.values())
            p_xp  = sum(a.total_xp for a in stats.pkills.values())
            pk_total = _hd_format_pkill_row("Total", str(p_cnt), str(p_xp), right_w)
            frags.append((_S_TOTAL, pk_total, p_focus))
        else:
            frags.append((_S_TOTAL, " " * right_w))
        frags.append(("", " "))
        frags.append(("", "\n"))


def _hd_append_sparklines(frags, stats, cols):
    label_w = _HD_STAT_Y_LABEL_W
    left_w  = _HD_STAT_TABLE_LEFT_W
    right_w = _HD_STAT_TABLE_RIGHT_W
    gap     = _HD_STAT_TABLE_GAP
    n_L     = max(1, left_w  - label_w - 2)
    n_R     = max(1, right_w - label_w - 2)
    total_w = left_w + 1 + len(gap) + right_w + 1
    margin  = max(0, (cols - total_w) // 2)
    pad     = " " * margin

    start    = stats.start_ts
    end      = max(stats.end_ts, start + 1)
    duration = end - start

    xp_buckets = _hd_bucket_event_sums(stats.kill_events, n_L, start, end)
    tp_buckets = _hd_bucket_event_sums(stats.tp_events,   n_R, start, end)

    xp_secs = duration / n_L if n_L > 0 else 1
    tp_secs = duration / n_R if n_R > 0 else 1
    if xp_secs <= 0:
        xp_secs = 1
    if tp_secs <= 0:
        tp_secs = 1
    xp_rates = [b * 3600.0 / xp_secs for b in xp_buckets]
    tp_rates = [b * 3600.0 / tp_secs for b in tp_buckets]

    xp_max  = max(xp_rates) if xp_rates else 0.0
    tp_max  = max(tp_rates) if tp_rates else 0.0
    xp_rows = _hd_sparkline_rows(xp_rates, xp_max, rows=3)
    tp_rows = _hd_sparkline_rows(tp_rates, tp_max, rows=3)

    frags.append(("", pad))
    frags.append((C_SECTION, "XP/h".ljust(left_w)))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_SECTION, "TP/h".ljust(right_w)))
    frags.append(("", " "))
    frags.append(("", "\n"))

    junction   = label_w + 1
    left_rule  = "─" * junction + "┬" + "─" * max(0, left_w  - junction - 1)
    right_rule = "─" * junction + "┬" + "─" * max(0, right_w - junction - 1)
    frags.append(("", pad))
    frags.append((C_DIVIDER, left_rule))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_DIVIDER, right_rule))
    frags.append(("", " "))
    frags.append(("", "\n"))

    xp_labels = [_hd_fmt_xp_short(xp_max), _hd_fmt_xp_short(xp_max / 2), "0"]
    tp_labels = [_hd_fmt_xp_short(tp_max), _hd_fmt_xp_short(tp_max / 2), "0"]

    for r in range(3):
        frags.append(("", pad))
        frags.append((_S_LABEL, xp_labels[r].rjust(label_w)))
        frags.append(("", " "))
        frags.append((C_DIVIDER, "│"))
        frags.append((_S_GAINED, xp_rows[r]))
        frags.append(("", " "))
        frags.append(("", gap))
        frags.append((_S_LABEL, tp_labels[r].rjust(label_w)))
        frags.append(("", " "))
        frags.append((C_DIVIDER, "│"))
        frags.append((_S_TP_BAR, tp_rows[r]))
        frags.append(("", " "))
        frags.append(("", "\n"))

    axis_indent = " " * (label_w + 1)
    frags.append(("", pad))
    frags.append(("", axis_indent))
    frags.append((C_DIVIDER, "└" + "─" * n_L))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append(("", axis_indent))
    frags.append((C_DIVIDER, "└" + "─" * n_R))
    frags.append(("", " "))
    frags.append(("", "\n"))

    chart_indent = " " * (label_w + 2)
    x_left  = "00:00"
    x_right = _hd_fmt_duration_hms(duration)[:5]
    fill_L  = max(1, n_L - len(x_left) - len(x_right))
    fill_R  = max(1, n_R - len(x_left) - len(x_right))
    frags.append(("", pad))
    frags.append(("", chart_indent))
    frags.append((_S_LABEL, x_left + (" " * fill_L) + x_right))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append(("", chart_indent))
    frags.append((_S_LABEL, x_left + (" " * fill_R) + x_right))
    frags.append(("", " "))
    frags.append(("", "\n"))


def _hd_append_xp_linjalen(frags, stats, cols):
    bar_w = _HD_STAT_BAR_WIDTH
    if stats.xp_at_start is None and stats.xp_current is None:
        return
    lo_xp  = min(stats.xp_at_start, stats.xp_current)
    hi_xp  = max(stats.xp_at_start, stats.xp_current)
    min_lv = max(1,   _hd_level_from_xp(lo_xp))
    hi_lv  = min(100, _hd_level_from_xp(hi_xp) + 1)
    span   = max(1, hi_lv - min_lv)

    is_loss   = stats.xp_current < stats.xp_at_start
    start_col = _hd_xp_to_bar_col(stats.xp_at_start, min_lv, hi_lv, bar_w)
    cur_col   = _hd_xp_to_bar_col(stats.xp_current,  min_lv, hi_lv, bar_w)
    lo_col    = min(start_col, cur_col)
    hi_col    = max(start_col, cur_col)
    band_w    = hi_col - lo_col
    band_style = _S_LOSS if is_loss else _S_GAINED

    margin = max(0, (cols - bar_w) // 2)
    pad    = " " * margin

    if is_loss:
        label = f"-{abs(round(stats.xp_gained / 1000))}k XP"
    else:
        label = f"{round(stats.xp_gained / 1000)}k"
    frags.append(("", pad))
    if band_w >= len(label) + 2:
        if lo_col > 0:
            frags.append(("", " " * lo_col))
        slack = band_w - len(label) - 2
        left  = (slack + 1) // 2
        right = slack // 2
        frags.append((_S_ARROW, "◄" + "─" * left))
        frags.append((band_style, label))
        frags.append((_S_ARROW, "─" * right + "►"))
    elif band_w > 0:
        centre = lo_col + band_w // 2
        before = max(0, centre - len(label) // 2)
        if before > 0:
            frags.append(("", " " * before))
        frags.append((band_style, label))
    frags.append(("", "\n"))

    frags.append(("", pad))
    if lo_col > 0:
        frags.append((_S_TRACK, "█" * lo_col))
    if band_w > 0:
        frags.append((band_style, "█" * band_w))
    if hi_col < bar_w:
        frags.append((_S_TRACK, "█" * (bar_w - hi_col)))
    frags.append(("", "\n"))

    line = [" "] * bar_w
    for lv_offset in range(span + 1):
        level   = min_lv + lv_offset
        digits  = str(level)
        is_last = (lv_offset == span)
        if is_last:
            col = bar_w - 1
            line[col] = "▐"
            text = digits + " "
            for i, ch in enumerate(text):
                pos = col - len(text) + i
                if 0 <= pos < bar_w:
                    line[pos] = ch
        else:
            col = int(round(lv_offset / span * bar_w))
            if col >= bar_w:
                col = bar_w - 1
            line[col] = "▌"
            text = " " + digits
            for i, ch in enumerate(text):
                pos = col + 1 + i
                if 0 <= pos < bar_w:
                    line[pos] = ch
    frags.append(("", pad))
    buf = ""
    cur_style = None
    for ch in line:
        if ch in ("▌", "▐"):
            style = _S_MARKER
        elif ch == " ":
            style = ""
        else:
            style = _S_LABEL
        if style != cur_style:
            if buf:
                frags.append((cur_style, buf))
            buf = ch
            cur_style = style
        else:
            buf += ch
    if buf:
        frags.append((cur_style, buf))
    frags.append(("", "\n"))


class _HDScrollControl(FormattedTextControl):
    """Body control: routes mouse-wheel events to the focused table when no
    cell-level handler consumes them. Cell handlers (KILLS/PvPs/ALLIES/
    ACHIEVEMENTS rows) already route wheel events to their own table; this
    is the safety-net path for events that land in gaps/padding."""
    def mouse_handler(self, ev):
        result = super().mouse_handler(ev)
        if result is NotImplemented:
            if ev.event_type == MouseEventType.SCROLL_UP:
                sb = _hd_focused_scrollbar()
                if sb is not None:
                    sb.scroll_by(-1)
                    if _app:
                        _app.invalidate()
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                sb = _hd_focused_scrollbar()
                if sb is not None:
                    sb.scroll_by(1)
                    if _app:
                        _app.invalidate()
                return None
        return result


def _history_detail_text():
    cols    = _term_cols()
    summary = _history_detail_summary
    stats   = _history_detail_stats
    clear   = _hover_at(None, None)
    frags   = []

    if summary is None or stats is None:
        title = "Session detail"
        frags.append(("", "\n\n", clear))
        frags.append(("", _pad_centre(title, cols), clear))
        frags.append((C_HEADER, title, clear))
        frags.append(("", "\n\n", clear))
        msg = "(no session selected)"
        frags.append(("", _pad_centre(msg, cols), clear))
        frags.append((C_BODY, msg, clear))
        frags.append(("", "\n\n", clear))
        footer = "ESC Back"
        frags.append(("", _pad_centre(footer, cols), clear))
        frags.append((C_HINT, footer, clear))
        return frags

    # --- Header row -------------------------------------------------------
    date_text     = _hd_fmt_ts(summary.start_ts, "%Y-%m-%d")
    duration_text = _history_fmt_duration(summary.duration_seconds)
    title_text    = (f"◆ Session detail  —  {summary.character}"
                     f"  ·  {date_text}  ·  {duration_text}")
    button_label  = " WATCH LOG "
    button_visible = bool(summary.has_log)

    frags.append(("", "\n", clear))

    title_pad = max(0, (cols - len(title_text)) // 2)
    frags.append(("", " " * title_pad, clear))
    frags.append((C_HEADER, title_text, clear))
    used = title_pad + len(title_text)
    if button_visible:
        # Right edge of the button matches the right edge of the centred stats block.
        left_w  = _HD_STAT_TABLE_LEFT_W
        right_w = _HD_STAT_TABLE_RIGHT_W
        total_w = left_w + 1 + len(_HD_STAT_TABLE_GAP) + right_w + 1
        block_right = max(0, (cols - total_w) // 2) + total_w
        button_start = block_right - len(button_label)
        gap = max(1, button_start - used)
        frags.append(("", " " * gap, clear))
        log_style = C_WATCH_LOG_HOVER if _history_detail_log_hover else C_WATCH_LOG
        frags.append((log_style, button_label, _hd_watch_log_handler))
    frags.append(("", "\n", clear))

    # --- Blank separator --------------------------------------------------
    frags.append(("", "\n", clear))

    # --- Statistics body --------------------------------------------------
    _hd_ensure_scrollbars()
    data_height = _hd_compute_kills_pvps_data_height(stats)
    _hd_refresh_scrollbars(stats, data_height)

    body = []
    _hd_append_allies_achievements(body, stats, cols)
    body.append(("", "\n"))

    _hd_append_kills_pvps(body, stats, cols, data_height)
    body.append(("", "\n"))

    _hd_append_sparklines(body, stats, cols)
    body.append(("", "\n"))

    _hd_append_xp_linjalen(body, stats, cols)
    body.append(("", "\n"))

    frags.extend(_hover_clear_frags(body))

    # --- Footer -----------------------------------------------------------
    footer = "ESC Back     ↑↓ Scroll     Tab/Shift+Tab Switch table"
    if button_visible:
        footer += "     L Watch log"
    frags.append(("", _pad_centre(footer, cols), clear))
    frags.append((_S_HINT, footer, clear))
    return frags


# ---------------------------------------------------------------------------
# log_view (chain log player — Phase 3 skeleton)
# ---------------------------------------------------------------------------
def _enter_log_view():
    """Push log_view for the chain currently in _history_detail_summary.

    Caller is responsible for has_log gating; this is defensive against a
    chain whose every .log file has vanished between summary build and
    button activation."""
    global _log_view_playback, _log_view_scroll, _log_view_cols, _log_view_lines
    global _log_view_event_rows
    global _log_mode, _log_play_anchor_wall, _log_play_anchor_offset_us
    global _log_paused_offset_us, _log_cursor_index, _log_last_playhead_index
    summary = _history_detail_summary
    if summary is None:
        return
    playback = log_player.LogPlayback(summary.character, summary.run_ids)
    if not playback.events:
        # Defensive — every run's .log was missing; stay on history_detail.
        return
    _log_view_playback        = playback
    _log_view_scroll          = 0
    _log_view_cols            = 0
    _log_view_lines           = None
    _log_view_event_rows      = None
    _log_mode                 = "play"
    _log_play_anchor_wall     = time.monotonic()
    _log_play_anchor_offset_us = 0
    _log_paused_offset_us     = 0
    _log_cursor_index         = 0
    _log_last_playhead_index  = -1
    _push_frame("log_view")
    _log_start_tick_task()


def _exit_log_view():
    """Pop back to history_detail and drop the playback so the chain's log
    data can be garbage-collected — chains are re-read from disk on next push."""
    global _log_view_playback, _log_view_scroll, _log_view_cols, _log_view_lines
    global _log_view_event_rows, _log_last_playhead_index
    _log_cancel_tick_task()
    _log_view_playback   = None
    _log_view_scroll     = 0
    _log_view_cols       = 0
    _log_view_lines      = None
    _log_view_event_rows = None
    _log_last_playhead_index = -1
    _pop_frame()


def _log_view_visible_rows():
    return max(1, _term_rows())


def _log_view_wrap_fragments(fragments, width):
    """Split a fragment list at terminal-column boundaries. Returns a list of
    visual lines, each a list of (style, run) tuples. Empty input produces
    a single empty line so blank events still occupy a row."""
    if width <= 0:
        return [list(fragments)]
    lines = []
    cur = []
    cur_w = 0
    for style, run in fragments:
        while run:
            avail = width - cur_w
            if avail <= 0:
                lines.append(cur)
                cur = []
                cur_w = 0
                avail = width
            if len(run) <= avail:
                if run:
                    cur.append((style, run))
                    cur_w += len(run)
                run = ""
            else:
                cur.append((style, run[:avail]))
                run = run[avail:]
                lines.append(cur)
                cur = []
                cur_w = 0
    lines.append(cur)
    return lines


def _log_view_rebuild_if_needed():
    """Rebuild the wrapped-line cache and the parallel event→row map. The map
    lets pause-mode rendering / clicking translate between event index and
    visual-row range without re-wrapping on every redraw."""
    global _log_view_lines, _log_view_cols, _log_view_event_rows
    if _log_view_playback is None:
        _log_view_lines      = []
        _log_view_event_rows = []
        return
    cols = _term_cols()
    if _log_view_lines is not None and cols == _log_view_cols:
        return
    visual = []
    ev_rows = []
    for ev in _log_view_playback.events:
        start = len(visual)
        wrapped = _log_view_wrap_fragments(ev.fragments, cols)
        visual.extend(wrapped)
        ev_rows.append((start, len(visual)))
    _log_view_lines      = visual
    _log_view_cols       = cols
    _log_view_event_rows = ev_rows


# --- Playback time / playhead --------------------------------------------
def _log_current_playback_us():
    pb = _log_view_playback
    if pb is None:
        return 0
    if _log_mode == "play":
        elapsed = int((time.monotonic() - _log_play_anchor_wall) * 1_000_000)
        cur = _log_play_anchor_offset_us + elapsed
    else:
        cur = _log_paused_offset_us
    if cur < 0:
        cur = 0
    if cur > pb.total_duration_us:
        cur = pb.total_duration_us
    return cur


def _log_playhead_index():
    pb = _log_view_playback
    if pb is None or not pb.events:
        return 0
    cur = _log_current_playback_us()
    # Largest i with playback_offset_us[i] <= cur.
    i = bisect.bisect_right(pb.playback_offset_us, cur) - 1
    if i < 0:
        i = 0
    if i >= len(pb.events):
        i = len(pb.events) - 1
    return i


# --- Mode transitions ------------------------------------------------------
def _log_pause():
    """Freeze playback on the current playhead."""
    global _log_mode, _log_paused_offset_us, _log_cursor_index
    if _log_view_playback is None:
        return
    _log_paused_offset_us = _log_current_playback_us()
    _log_cursor_index     = _log_playhead_index()
    _log_mode             = "pause"
    _log_cancel_tick_task()
    _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _log_resume():
    """Resume playing from the cursor's event timestamp. Always snaps to the
    cursor, even when the cursor hasn't moved since the pause."""
    global _log_mode, _log_play_anchor_wall, _log_play_anchor_offset_us
    global _log_last_playhead_index
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    idx = max(0, min(len(pb.events) - 1, _log_cursor_index))
    _log_play_anchor_offset_us = pb.playback_offset_us[idx]
    _log_play_anchor_wall      = time.monotonic()
    _log_mode                  = "play"
    _log_last_playhead_index   = -1
    _log_start_tick_task()
    if _app:
        _app.invalidate()


def _log_toggle_play_pause():
    if _log_view_playback is None:
        return
    if _log_mode == "play":
        _log_pause()
    else:
        _log_resume()


def _log_auto_pause_at_end():
    """End-of-log auto-pause: cursor on the final event, mode → pause."""
    global _log_mode, _log_paused_offset_us, _log_cursor_index
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    _log_cursor_index     = len(pb.events) - 1
    _log_paused_offset_us = pb.total_duration_us
    _log_mode             = "pause"
    _log_cancel_tick_task()
    _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


# --- Tick task -------------------------------------------------------------
def _log_cancel_tick_task():
    global _log_tick_task
    if _log_tick_task is not None:
        _log_tick_task.cancel()
        _log_tick_task = None


def _log_start_tick_task():
    global _log_tick_task
    _log_cancel_tick_task()
    if _app_loop is None:
        return
    _log_tick_task = _app_loop.create_task(_log_tick_loop())


async def _log_tick_loop():
    """~30 Hz redraw loop while in play mode. Stops as soon as the frame is
    popped or the mode flips to pause; invalidates only when the playhead
    crosses to a new event to avoid wasted repaints."""
    global _log_last_playhead_index
    interval = 1.0 / _LOG_TICK_HZ
    try:
        while True:
            if (_current_frame != "log_view" or _log_mode != "play"
                    or _log_view_playback is None):
                return
            pb = _log_view_playback
            if pb.events and _log_current_playback_us() >= pb.total_duration_us:
                _log_auto_pause_at_end()
                return
            idx = _log_playhead_index()
            if idx != _log_last_playhead_index:
                _log_last_playhead_index = idx
                if _app:
                    _app.invalidate()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        return


# --- Rendering -------------------------------------------------------------
def _log_apply_cursor_bg(line):
    """Compose the cursor bg over an existing wrapped line, preserving each
    fragment's existing fg/style. Style strings concatenate in prompt_toolkit;
    later attributes override earlier ones, so appending `bg:` adds the
    highlight without clobbering fg."""
    out = []
    for tup in line:
        style = tup[0]
        run   = tup[1]
        combined = (style + " " + C_LOG_CURSOR).strip() if style else C_LOG_CURSOR
        out.append((combined, run))
    return out


def _log_clamp_scroll():
    global _log_view_scroll
    visible = _log_view_visible_rows()
    mx = max(0, len(_log_view_lines) - visible)
    if _log_view_scroll > mx:
        _log_view_scroll = mx
    if _log_view_scroll < 0:
        _log_view_scroll = 0


def _log_ensure_cursor_visible():
    """Scroll so the cursor event's row range is visible. If the event is
    taller than the viewport, anchor on its first row."""
    global _log_view_scroll
    if _log_view_playback is None:
        return
    _log_view_rebuild_if_needed()
    rows = _log_view_event_rows
    if not rows:
        return
    idx = max(0, min(len(rows) - 1, _log_cursor_index))
    start, end = rows[idx]
    visible = _log_view_visible_rows()
    if end - start >= visible or start < _log_view_scroll:
        _log_view_scroll = start
    elif end > _log_view_scroll + visible:
        _log_view_scroll = end - visible
    _log_clamp_scroll()


def _log_event_row_to_index(row_abs):
    """Resolve an absolute visual row (0-based, into _log_view_lines) to an
    event index. Returns None if outside the rendered range."""
    rows = _log_view_event_rows
    if not rows:
        return None
    # bisect on starts: largest i with start <= row_abs.
    starts = [r[0] for r in rows]
    i = bisect.bisect_right(starts, row_abs) - 1
    if i < 0:
        return None
    start, end = rows[i]
    if row_abs >= end:
        return None
    return i


def _log_view_text():
    if _log_view_playback is None:
        return [(C_BODY, "(no log loaded)")]
    _log_view_rebuild_if_needed()
    visible = _log_view_visible_rows()
    if _log_mode == "play":
        return _log_view_text_play(visible)
    return _log_view_text_pause(visible)


def _log_view_text_play(visible):
    """Streaming render: only events up to the playhead, with the latest
    event sitting at the bottom of the viewport."""
    global _log_view_scroll
    pb = _log_view_playback
    rows = _log_view_event_rows
    if not rows:
        return []
    idx = _log_playhead_index()
    end_excl = rows[idx][1]  # one past the last visual row of the playhead event
    start_row = max(0, end_excl - visible)
    _log_view_scroll = start_row
    sliced = _log_view_lines[start_row:end_excl]
    return _log_lines_to_fragments(sliced, sliced_start=start_row, cursor_idx=None)


def _log_view_text_pause(visible):
    """Full-buffer render with a cursor highlight on the cursor event."""
    _log_clamp_scroll()
    start_row = _log_view_scroll
    end_row   = start_row + visible
    sliced    = _log_view_lines[start_row:end_row]
    return _log_lines_to_fragments(sliced, sliced_start=start_row,
                                   cursor_idx=_log_cursor_index)


def _log_lines_to_fragments(sliced, sliced_start, cursor_idx):
    """Flatten a slice of wrapped visual lines into a prompt_toolkit fragment
    list. When `cursor_idx` is set, rows belonging to that event get the
    C_LOG_CURSOR bg layered on top of their existing styles."""
    rows = _log_view_event_rows
    cursor_start = cursor_end = -1
    if cursor_idx is not None and rows and 0 <= cursor_idx < len(rows):
        cursor_start, cursor_end = rows[cursor_idx]
    frags = []
    for i, line in enumerate(sliced):
        abs_row = sliced_start + i
        if cursor_start <= abs_row < cursor_end:
            painted = _log_apply_cursor_bg(line)
            # Pad to terminal width so the bg highlight spans the whole row,
            # including the trailing area past the line's text.
            line_w = sum(len(r) for _, r in line)
            pad = max(0, _log_view_cols - line_w)
            if pad:
                painted.append((C_LOG_CURSOR, " " * pad))
            frags.extend(painted)
        elif line:
            frags.extend(line)
        if i < len(sliced) - 1:
            frags.append(("", "\n"))
    return frags


# --- Cursor / scroll movement (pause mode) --------------------------------
def _log_move_cursor(delta):
    """Move cursor by `delta` events; auto-pauses if currently playing.
    Clamps to [0, last_index] and keeps the cursor row in view."""
    global _log_cursor_index
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    if _log_mode == "play":
        _log_pause()
    n = len(pb.events)
    new_idx = max(0, min(n - 1, _log_cursor_index + delta))
    if new_idx == _log_cursor_index:
        return
    _log_cursor_index = new_idx
    _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _log_cursor_to(index):
    global _log_cursor_index
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    if _log_mode == "play":
        _log_pause()
    n = len(pb.events)
    new_idx = max(0, min(n - 1, index))
    if new_idx == _log_cursor_index:
        return
    _log_cursor_index = new_idx
    _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


class _LogViewControl(FormattedTextControl):
    """Mouse routing for the log_view frame.

    Pause mode:
      • Wheel up/down moves the cursor by one event (per spec: wheel moves
        the cursor, not just the viewport, so the resume point stays
        predictable).
      • Click on a rendered event row moves the cursor to that event.
        Does NOT resume playback — Space does.

    Play mode: all mouse input is a no-op here. P3 will wire mouse to the
    overlay auto-hide logic."""
    def mouse_handler(self, ev):
        result = super().mouse_handler(ev)
        if result is not NotImplemented:
            return result
        if _log_view_playback is None or _log_mode != "pause":
            return None
        t = ev.event_type
        if t == MouseEventType.SCROLL_UP:
            _log_move_cursor(-1)
            return None
        if t == MouseEventType.SCROLL_DOWN:
            _log_move_cursor(1)
            return None
        if t == MouseEventType.MOUSE_DOWN:
            row_abs = _log_view_scroll + ev.position.y
            idx = _log_event_row_to_index(row_abs)
            if idx is not None:
                _log_cursor_to(idx)
            return None
        return None


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


# History frame
@kb.add("tab", filter=_in_frame("history"))
@kb.add("s-tab", filter=_in_frame("history"))
def _kb_hist_tab(event):
    _history_toggle_focus()


@kb.add("up", filter=_in_frame("history"))
def _kb_hist_up(event):
    if _history_focused == 0:
        _history_move_sidebar(-1)
    else:
        _history_move_table(-1)


@kb.add("down", filter=_in_frame("history"))
def _kb_hist_down(event):
    if _history_focused == 0:
        _history_move_sidebar(1)
    else:
        _history_move_table(1)


@kb.add("pageup", filter=_in_frame("history"))
def _kb_hist_pgup(event):
    if _history_focused == 0:
        _history_jump_sidebar(_history_sidebar_cursor - 10)
    else:
        _history_jump_table(_history_table_cursor - 10)


@kb.add("pagedown", filter=_in_frame("history"))
def _kb_hist_pgdn(event):
    if _history_focused == 0:
        _history_jump_sidebar(_history_sidebar_cursor + 10)
    else:
        _history_jump_table(_history_table_cursor + 10)


@kb.add("home", filter=_in_frame("history"))
def _kb_hist_home(event):
    if _history_focused == 0:
        _history_jump_sidebar(0)
    else:
        _history_jump_table(0)


@kb.add("end", filter=_in_frame("history"))
def _kb_hist_end(event):
    if _history_focused == 0:
        _history_jump_sidebar(len(_history_sidebar_items) - 1)
    else:
        _history_jump_table(len(_history_sessions) - 1)


@kb.add("enter", filter=_in_frame("history"))
def _kb_hist_enter(event):
    if _history_focused == 0:
        if 0 <= _history_sidebar_cursor < len(_history_sidebar_items):
            _history_set_filter(_history_sidebar_items[_history_sidebar_cursor])
    else:
        _history_activate_table_row(_history_table_cursor)


@kb.add("escape", filter=_in_frame("history"), eager=True)
def _kb_hist_escape(event):
    _pop_frame()


# History detail
@kb.add("escape", filter=_in_frame("history_detail"), eager=True)
def _kb_hd_escape(event):
    _pop_frame()


@kb.add("tab", filter=_in_frame("history_detail"))
def _kb_hd_tab(event):
    _hd_set_focus((_history_detail_focused + 1) % 4)


@kb.add("s-tab", filter=_in_frame("history_detail"))
def _kb_hd_stab(event):
    _hd_set_focus((_history_detail_focused - 1) % 4)


@kb.add("up", filter=_in_frame("history_detail"))
def _kb_hd_up(event):
    sb = _hd_focused_scrollbar()
    if sb is None:
        return
    sb.scroll_by(-1)
    if _app:
        _app.invalidate()


@kb.add("down", filter=_in_frame("history_detail"))
def _kb_hd_down(event):
    sb = _hd_focused_scrollbar()
    if sb is None:
        return
    sb.scroll_by(1)
    if _app:
        _app.invalidate()


@kb.add("pageup", filter=_in_frame("history_detail"))
def _kb_hd_pgup(event):
    sb = _hd_focused_scrollbar()
    if sb is None:
        return
    sb.scroll_by(-10)
    if _app:
        _app.invalidate()


@kb.add("pagedown", filter=_in_frame("history_detail"))
def _kb_hd_pgdn(event):
    sb = _hd_focused_scrollbar()
    if sb is None:
        return
    sb.scroll_by(10)
    if _app:
        _app.invalidate()


@kb.add("home", filter=_in_frame("history_detail"))
def _kb_hd_home(event):
    sb = _hd_focused_scrollbar()
    if sb is None:
        return
    sb.scroll_to(0)
    if _app:
        _app.invalidate()


@kb.add("end", filter=_in_frame("history_detail"))
def _kb_hd_end(event):
    sb = _hd_focused_scrollbar()
    if sb is None:
        return
    sb.scroll_to(10**9)
    if _app:
        _app.invalidate()


# Gated on has_log: no log file → key is ignored, mirrors button visibility.
_hd_has_log = Condition(
    lambda: _history_detail_summary is not None
    and bool(_history_detail_summary.has_log))


@kb.add("l", filter=_in_frame("history_detail") & _hd_has_log)
@kb.add("L", filter=_in_frame("history_detail") & _hd_has_log)
def _kb_hd_watch_log(event):
    _enter_log_view()


# log_view (chain log player)
@kb.add("escape", filter=_in_frame("log_view"), eager=True)
def _kb_log_escape(event):
    _exit_log_view()


@kb.add("space", filter=_in_frame("log_view"))
def _kb_log_space(event):
    _log_toggle_play_pause()


@kb.add("up", filter=_in_frame("log_view"))
def _kb_log_up(event):
    _log_move_cursor(-1)


@kb.add("down", filter=_in_frame("log_view"))
def _kb_log_down(event):
    _log_move_cursor(1)


@kb.add("pageup", filter=_in_frame("log_view"))
def _kb_log_pgup(event):
    _log_move_cursor(-_LOG_PAGE_STEP)


@kb.add("pagedown", filter=_in_frame("log_view"))
def _kb_log_pgdn(event):
    _log_move_cursor(_LOG_PAGE_STEP)


@kb.add("home", filter=_in_frame("log_view"))
def _kb_log_home(event):
    _log_cursor_to(0)


@kb.add("end", filter=_in_frame("log_view"))
def _kb_log_end(event):
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    _log_cursor_to(len(pb.events) - 1)


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


def _build_history():
    """Build the History frame: title + centred (sidebar | gap | table | sb) + footer."""
    title  = Window(content=FormattedTextControl(text=_history_title_text, focusable=False),
                    height=3, wrap_lines=False, always_hide_cursor=True)
    footer = Window(content=FormattedTextControl(text=_history_footer_text, focusable=False),
                    height=2, wrap_lines=False, always_hide_cursor=True)

    sidebar_win = Window(
        content=_HistScrollControl(text=_history_sidebar_text, focusable=True, panel=0),
        wrap_lines=False, always_hide_cursor=True,
        width=lambda: Dimension.exact(_history_sidebar_panel_w()),
    )

    # Hover-clearing filler for gap and outer spacers. One " " per visible
    # body row so MOUSE_MOVE over padding fires _hover_at(None, None).
    def _make_filler_text(width):
        def _fn():
            rows = _history_body_rows()
            clear = _hover_at(None, None)
            out = []
            for i in range(rows):
                out.append(("", " " * width, clear))
                if i < rows - 1:
                    out.append(("", "\n", clear))
            return out
        return _fn

    gap_win = Window(
        content=FormattedTextControl(text=_make_filler_text(1), focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(1),
    )
    table_win = Window(
        content=_HistScrollControl(text=_history_table_text, focusable=True, panel=1),
        wrap_lines=False, always_hide_cursor=True,
        width=lambda: Dimension.exact(_history_table_panel_w()),
        height=Dimension(weight=1),
    )
    table_sb_win = Window(
        content=FormattedTextControl(text=_history_table_scrollbar_text, focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(1),
    )
    # Flex spacers on either side centre the block and clear hover when
    # the mouse drifts into the padding.
    left_spacer = Window(
        content=FormattedTextControl(text=_make_filler_text(1), focusable=False),
        wrap_lines=False, always_hide_cursor=True,
    )
    right_spacer = Window(
        content=FormattedTextControl(text=_make_filler_text(1), focusable=False),
        wrap_lines=False, always_hide_cursor=True,
    )

    body = VSplit(
        [left_spacer, sidebar_win, gap_win, table_win, table_sb_win, right_spacer],
    )
    return sidebar_win, table_win, HSplit([title, body, footer])


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
    global _history_sidebar_window, _history_table_window, _history_detail_window
    global _log_view_window

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
    _history_sidebar_window, _history_table_window, history_frame = _build_history()
    _history_detail_window = Window(
        content=_HDScrollControl(text=_history_detail_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    history_detail_frame = _centered(_history_detail_window)

    _log_view_window = Window(
        content=_LogViewControl(text=_log_view_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    log_view_frame = _log_view_window

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
        "history":                    history_frame,
        "history_detail":             history_detail_frame,
        "log_view":                   log_view_frame,
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
