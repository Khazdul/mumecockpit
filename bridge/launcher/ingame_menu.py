#!/usr/bin/env python3
# bridge/launcher/ingame_menu.py — in-game popup menu (prompt_toolkit rewrite).
# Launched via tmux display-popup. Do not invoke directly outside that context.
# Behavioural contract: docs/popup-menu.md.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import DynamicKeyBindings, KeyBindings, merge_key_bindings
    from prompt_toolkit.layout import DynamicContainer, Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import asyncio
import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import time

from pathlib import Path
import threading

import run_meta
import run_stats
from menu_chrome import (
    footer_block, menu_row, title_block, title_block_height,
)
from panes_grid import apply_cell_toggle, panes_grid_fragments
import comm_channels
from timers_layout_grid import (
    TIMERS_LAYOUT_TYPES, TIMERS_LAYOUT_LABELS, TIMERS_LAYOUT_DEFAULTS,
    TIMERS_HEADERS_DEFAULT, TIMERS_COMPACT_DEFAULT,
    max_cols_for, clamp_cols, step_cols, timers_grid_fragments,
)
import core_aliases
import profile_editor
import profile_io
import readability_view
import scripts_view
from widgets.scrollbar import Scrollbar

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BRIDGE_DIR            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR           = os.path.dirname(BRIDGE_DIR)
RUNTIME_DIR           = os.path.join(BRIDGE_DIR, "runtime")
DATA_RUNS_DIR         = os.path.join(PROJECT_DIR, "data", "runs")
POPUP_SENTINEL        = os.path.join(RUNTIME_DIR, ".popup_open")
RETURN_TO_MENU_SENT   = os.path.join(RUNTIME_DIR, ".return_to_menu")
CONNECTION_STATE_PATH = os.path.join(RUNTIME_DIR, "connection.state")
PING_CACHE_PATH       = os.path.join(RUNTIME_DIR, "ping.cache")
STARTUP_CONF_PATH     = os.path.join(RUNTIME_DIR, "startup.conf")
TIMERS_LAYOUT_CONF_PATH = os.path.join(RUNTIME_DIR, "timers_layout.conf")
STATUS_STATE_PATH     = os.path.join(RUNTIME_DIR, "status.state")
SCRIPTS_CACHE_PATH    = os.path.join(RUNTIME_DIR, "scripts.cache")
TOGGLE_PANE_SCRIPT    = os.path.join(BRIDGE_DIR, "layout", "toggle_pane.sh")

READABILITY_MODULES_DIR = os.path.join(PROJECT_DIR, "ttpp", "readability", "modules")
PROFILES_DIR           = os.path.join(PROJECT_DIR, "ttpp", "profiles")
SANITIZE_SCRIPT        = os.path.join(BRIDGE_DIR, "release", "sanitize_profile.sh")
LAYOUT_CONF_PATH       = os.path.join(RUNTIME_DIR, "layout.conf")
PROFILE_SNAPSHOT_PATH  = os.path.join(RUNTIME_DIR, "profile_snapshot.tin")
PROFILE_EDIT_PATH      = os.path.join(RUNTIME_DIR, "profile_edit.tin")
PROFILE_SNAP_RESULT    = os.path.join(RUNTIME_DIR, ".profile_snapshot_result")
PROFILE_APPLY_RESULT   = os.path.join(RUNTIME_DIR, ".profile_apply_result")

TMUX_TARGET  = "mume:cockpit.0"
TMUX_SESSION = "mume:cockpit"
TMUX_OPTROOT = "mume"

# Banner twinkle redraw rate. The main frame's banner is animated; submenus
# are static, so the loop skips the invalidate when `_current_frame` is not
# "main". Mirrors launcher.py's `_banner_tick_loop` precedent.
_BANNER_TICK_HZ = 6

# ---------------------------------------------------------------------------
# Colour palette — definitions live in bridge/launcher/palette.py so the
# launcher rewrite can import the same constants. See docs/launcher.md.
# ---------------------------------------------------------------------------
from palette import *  # noqa: F401,F403
import launcher_banner

# ---------------------------------------------------------------------------
# Panes submenu: pane target -> (display label, conf colour key). Order
# matches the launcher's Panes submenu. The launcher is the source of truth
# for the colour names list; we mirror the order here.
# ---------------------------------------------------------------------------
_PANE_TARGETS = [
    ("status", "Character",     "pane_color_status"),
    ("timers", "Timers",        "pane_color_timers"),
    ("group",  "Group",         "pane_color_group"),
    ("comm",   "Communication", "pane_color_comm"),
    ("ui",     "UI",            "pane_color_ui"),
    ("dev",    "Developer",     "pane_color_dev"),
]

# ---------------------------------------------------------------------------
# Mutable application state
# ---------------------------------------------------------------------------
_current_frame    = "main"
_frame_stack      = []          # navigation stack: [(frame, ...) for ancestor frames]
_sel_main         = 0
_sel_options      = 0           # cursor within the popup Options grouping (Panes / Scripts / Back)
# Panes hub (thin index: General / Timers / Back). Mirrors the `options`
# grouping; per-pane layout pages hang under it.
_sel_panes        = 0
_hover_panes      = -1
# Panes → General submenu (colour grid). Eight navigable rows:
#   0..5 — pane rows × 7 colour columns (←/→ moves the column; the column
#          persists across grid rows).
#   6    — Display pane headers toggle.
#   7    — Back.
_panes_general_row        = 0
_panes_general_col        = 0
# Timers-layout submenu (group × colour grid + per-row column stepper).
# Seven navigable rows: 0..5 — group rows; 6 — Back. Colour cells are
# cols 0..N-1 (N = len(TIMERS_COLOR_ORDER)); ◄ at col N; ► at col N+1.
_timers_row       = 0
_timers_col       = 0
# Panes → Communication submenu (per-channel on/off list). Twelve navigable
# rows: 0..9 channel rows, row 10 the [X] Show channel header toggle, row 11
# Back. Cursor-only (no hover). Persistence is immediate: each toggle reads,
# flips, and writes the relevant conf via comm_channels; the render re-reads
# every frame. Logic lives in comm_channels — none duplicated here.
_panes_comm_row   = 0
# Scripts (read-only popup view) — frozen snapshot of scripts.cache,
# loaded on every push of the frame. The cursor browses the list and
# updates the detail panel; PageUp/PageDown scrolls the detail. No
# toggling, no live re-scan: the popup must never disagree with the
# brain's currently-running set, which the cache represents.
_scripts_catalog       = []
_scripts_cursor        = 0         # latched script-row index (drives detail)
_scripts_on_back       = False     # True when the cursor sits on the in-column Back row
_scripts_list_scroll   = 0
_scripts_detail_scroll = 0
_scripts_hover         = None      # list row under the mouse, or None
_scripts_hover_back    = False     # True when the mouse is over the Back row
# Readability (interactive popup view) — live filesystem scan of
# ttpp/readability/modules/, toggling in place. Save-and-pop writes
# startup.conf and fires hot reload via _send_to_game.
_readability_catalog       = []
_readability_dirty         = False
_readability_cursor        = 0
_readability_on_back       = False
_readability_list_scroll   = 0
_readability_detail_scroll = 0
_readability_hover         = None
_readability_hover_back    = False
_rate_session_rating = 0        # 0..5; reset on every push of the rate_session frame
_app                 = None
_main_window         = None     # set in main(); referenced for focus
_options_window      = None     # set in main(); referenced for focus
_panes_window        = None     # set in main(); referenced for focus
_panes_general_window        = None     # set in main(); referenced for focus
_panes_communication_window  = None     # set in main(); referenced for focus
_timers_window       = None     # set in main(); referenced for focus
_scripts_window      = None     # set in main(); referenced for focus
_readability_window  = None     # set in main(); referenced for focus
_statistics_window   = None     # set in main(); referenced for focus
_exit_confirm_window = None     # set in main(); referenced for focus
_rate_session_window = None     # set in main(); referenced for focus
_stats_data       = None        # cached run_stats.RunStats for statistics frame
_stats_status     = None        # cached status.state dict (xp_progress source)
_stats_char       = None        # character name driving the statistics view
_stats_kills_sort  = ("XP tot", "desc")
_stats_pkills_sort = ("XP", "desc")
_stats_focused     = 0          # 0=Kills, 1=PKills, 2=Allies, 3=Achievements
_stats_run_ended   = False
_stats_tick_task   = None       # asyncio.Task for the 60 s refresh loop
_banner_tick_task  = None       # asyncio.Task for the main-frame banner twinkle
_profile_editor_instance       = None
_profile_editor_original_text  = None
_profile_editor_pending_profile = None
_profile_editor_disk_path      = None
_profile_editor_name           = None
_profile_apply_confirm_window  = None
_profile_apply_status          = None   # None | "applying" | "ok" | "fail:<msg>"
_kills_sb          = None       # Scrollbar instances, created on first push
_pkills_sb         = None
_allies_sb         = None
_achievements_sb   = None

# Mouse-hover state. Sticky-on-last-cell matches the launcher; mouse motion on
# a new frame updates it immediately so the stale value is invisible.
_hover_main        = -1
_hover_options     = -1


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


def _read_status_state():
    try:
        with open(STATUS_STATE_PATH) as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _statistics_character():
    """Return character name if status.state names one AND its current.jsonl
    exists; otherwise None. Used to gate the Statistics row on the main frame."""
    status = _read_status_state()
    char = status.get("character") if status else None
    if not isinstance(char, str) or not char:
        return None
    if not os.path.exists(os.path.join(DATA_RUNS_DIR, char, "current.jsonl")):
        return None
    return char


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
def _focus_current_frame():
    if not _app:
        return
    if _current_frame == "profile_editor" and _profile_editor_instance:
        win = _profile_editor_instance.main_window()
    elif _current_frame == "profile_editor_macro_keybind" and _profile_editor_instance:
        win = _profile_editor_instance.overlay_window()
    else:
        win = {
            "main":                  _main_window,
            "options":               _options_window,
            "panes":                 _panes_window,
            "panes_general":         _panes_general_window,
            "panes_communication":   _panes_communication_window,
            "timers":                _timers_window,
            "scripts":               _scripts_window,
            "readability":           _readability_window,
            "statistics":            _statistics_window,
            "exit_confirm":          _exit_confirm_window,
            "rate_session":          _rate_session_window,
            "profile_apply_confirm": _profile_apply_confirm_window,
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
    if _frame_stack:
        _current_frame = _frame_stack.pop()
    else:
        _current_frame = "main"
    _focus_current_frame()
    if _app:
        _app.invalidate()


# ---------------------------------------------------------------------------
# Hover handling (mirrors launcher.py — see docs/launcher.md)
# ---------------------------------------------------------------------------
def _set_hover(frame, idx):
    """Update hover index for the named frame; invalidate if changed."""
    global _hover_main, _hover_options, _hover_panes
    changed = False
    if frame == "main" and _hover_main != idx:
        _hover_main = idx
        changed = True
    elif frame == "options" and _hover_options != idx:
        _hover_options = idx
        changed = True
    elif frame == "panes" and _hover_panes != idx:
        _hover_panes = idx
        changed = True
    if changed and _app:
        _app.invalidate()


def _menu_row_state(is_active, is_hover):
    """Map (active, hover) to a `menu_chrome.menu_row` state name.
    Selection (keyboard cursor) wins over hover."""
    if is_active:
        return "selected"
    if is_hover:
        return "hover"
    return "inactive"


def _main_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("main", -1)


def _options_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("options", -1)


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
def _save_session_state():
    """Return (rating, character, run_id) when the active run is already
    saved, else (None, character, run_id_or_None). character is None when
    no active run is being tracked — i.e. the row should not appear."""
    char = _statistics_character()
    if char is None:
        return None, None, None
    run_id = run_stats.current_run_id_for(char)
    if run_id is None:
        return None, char, None
    if not run_meta.is_saved(char, run_id):
        return None, char, run_id
    meta   = run_meta.read_meta(char, run_id) or {}
    rating = meta.get("rating", 0)
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = 0
    return max(0, min(5, rating)), char, run_id


def _main_items():
    """Rows on the main frame.

    Each entry is (label, action, kind, payload). Every row is `"normal"`
    (selectable, handlers attached); run rating/save now lives in the
    exit_confirm frame rather than a dedicated main-menu row.
    """
    items = []
    if _is_connected():
        items.append(("Continue", "continue", "normal", None))
    items.append(("Reconnect", "reconnect", "normal", None))

    if _statistics_character() is not None:
        items.append(("Statistics", "statistics", "normal", None))

    items.append(("Profile",      "profile",  "normal", None))
    items.append(("Options",      "options",  "normal", None))
    items.append(("Exit session", "exit",     "normal", None))
    return items


def _main_selectable_indices():
    return list(range(len(_main_items())))


def _activate_main_item(action):
    global _sel_options, _rate_session_rating
    if action == "continue":
        _app.exit()
    elif action == "reconnect":
        _send_to_game("reconnect")
        _app.exit()
    elif action == "profile":
        _enter_profile_editor()
    elif action == "options":
        _sel_options = 0
        _push_frame("options")
    elif action == "scripts":
        _enter_scripts_frame()
    elif action == "statistics":
        char = _statistics_character()
        if char:
            _load_statistics(char)
            _push_frame("statistics")
            _start_stats_tick()
    elif action == "exit":
        # Pre-fill the rating widget from disk: the saved rating if this
        # run was already saved this session, else 0. Mirrors how the old
        # save_session action reset the rating before pushing rate_session.
        rating, _, _ = _save_session_state()
        _rate_session_rating = rating if rating is not None else 0
        _push_frame("exit_confirm")


def _append_status_header(frags, cols, clear_hover=None):
    """Centred Profile · Mode · Link line. Same form on main and rate_session.
    When `clear_hover` is given, every emitted fragment carries it so
    MOUSE_MOVE over the status header clears the frame's hover index."""
    conf = _parse_keyval(STARTUP_CONF_PATH)
    profile    = conf.get("profile") or "default"
    conn_mode  = conf.get("connection_mode") or "mmapper"
    mode_label = {
        "direct": "Direct",
        "custom": "Custom",
    }.get(conn_mode, "MMapper")

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

    def _push(style, text):
        if clear_hover is None:
            frags.append((style, text))
        else:
            frags.append((style, text, clear_hover))

    _push("", _pad_centre(plain, cols))
    _push(C_HINT, base)
    if latest:
        _push(C_HINT, "  ·  Link: ")
        if latest == "TIMEOUT":
            _push(C_ERR, "timeout")
        else:
            _push(C_HINT, f"{latest}ms")
        if quality:
            if quality in ("stable", "ok"):
                q_style = C_HINT
            elif quality in ("jittery", "spiking"):
                q_style = C_YELLOW
            else:
                q_style = C_ERR
            _push(C_HINT, " (")
            _push(q_style, quality)
            _push(C_HINT, ")")


def _main_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    frags  = []
    clear_hover = _main_clear_hover

    items   = _main_items()
    sel_idx = _sel_main
    if sel_idx >= len(items):
        sel_idx = len(items) - 1

    flash_active = bool(_profile_flash_text
                        and time.monotonic() < _profile_flash_until)
    flash_row = 1 if flash_active else 0

    # `reserved_rows` is the exact row count the surface emits *without*
    # the banner block: status header + the single separator blank +
    # every menu row + optional flash row + the anchored footer. The
    # shared `launcher_banner.banner_fits` helper checks whether the
    # banner block (its own leading + trailing blank + BANNER_HEIGHT
    # logo rows) fits on top — when it doesn't, we drop the banner so
    # the menu always wins on a short terminal.
    status_rows   = 1
    spacer_rows   = 1
    footer_rows   = 1
    reserved_rows = (status_rows + spacer_rows
                     + len(items) + flash_row + footer_rows)
    show_banner   = launcher_banner.banner_fits(rows_h, reserved_rows)

    # Status header on the topmost row of the frame (Profile · Mode · Link),
    # followed by a newline that terminates that row.
    _append_status_header(frags, cols, clear_hover=clear_hover)
    frags.append(("", "\n", clear_hover))

    # Starfield + wordmark banner — the logo is the popup's signature,
    # not a section title, and does not go through `menu_chrome.title_block`.
    # Art lives in launcher_banner.py and is shared with the launcher main
    # page; both surfaces drop the banner at the same threshold via the
    # shared `banner_fits` helper so the layout decision is one place.
    if show_banner:
        banner_pad = _pad_centre(" " * launcher_banner.BANNER_WIDTH, cols)
        frags.append(("", "\n", clear_hover))
        for line_frags in launcher_banner.banner_lines():
            frags.append(("", banner_pad, clear_hover))
            for style, text in line_frags:
                frags.append((style, text, clear_hover))
            frags.append(("", "\n", clear_hover))
        frags.append(("", "\n", clear_hover))
        banner_rows = 1 + launcher_banner.BANNER_HEIGHT + 1
    else:
        banner_rows = 0

    # Single blank between the top section (status / banner) and the
    # menu — when the banner is shown this stacks with its trailing
    # blank for breathing room; when the banner is hidden it's the
    # sole separator so the menu doesn't crowd the status header.
    frags.append(("", "\n", clear_hover))

    for i, (label, action, kind, payload) in enumerate(items):
        row_w     = len(label) + 6
        left_pad  = max(0, (cols - row_w) // 2)
        right_pad = max(0, cols - left_pad - row_w)

        state = _menu_row_state(i == sel_idx, i == _hover_main)

        def _make_handler(idx=i, act=action):
            def _handler(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("main", idx)
                    return
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _sel_main
                _sel_main = idx
                _activate_main_item(act)
                if _app:
                    _app.invalidate()
            return _handler

        h = _make_handler()
        frags.append(("", " " * left_pad, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * right_pad, clear_hover))
        frags.append(("", "\n", clear_hover))

    if flash_active:
        frags.append(("", "\n", clear_hover))
        frags.append(("", _pad_centre(_profile_flash_text, cols), clear_hover))
        frags.append((_profile_flash_style, _profile_flash_text, clear_hover))

    footer = "↑↓ Navigate · Enter Select · ESC Dismiss"
    content_rows = status_rows + banner_rows + spacer_rows + len(items) + flash_row
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


# ---------------------------------------------------------------------------
# Options grouping (popup-only): a thin index frame that holds Panes and
# Scripts. See docs/popup-menu.md. Mirrors the popup's behaviour from before
# the per-pane-colour PR — the only thing under it now is the launcher-shape
# Panes submenu.
# ---------------------------------------------------------------------------
_OPTIONS_ROWS = [
    ("panes",       "Panes"),
    ("readability", "Readability"),
    ("scripts",     "Scripts"),
    ("sep",         ""),
    ("back",        "Back"),
]


def _options_selectable_indices():
    return [i for i, (k, _) in enumerate(_OPTIONS_ROWS) if k != "sep"]


def _options_activate(row_idx):
    if not (0 <= row_idx < len(_OPTIONS_ROWS)):
        return
    action, _label = _OPTIONS_ROWS[row_idx]
    if action == "panes":
        _enter_panes_frame()
    elif action == "readability":
        _enter_readability_frame()
    elif action == "scripts":
        _enter_scripts_frame()
    elif action == "back":
        _pop_frame()


def _options_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Options ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"
    clear_hover = _options_clear_hover

    sel_indices = _options_selectable_indices()
    sel = _sel_options
    if sel >= len(sel_indices):
        sel = len(sel_indices) - 1
    sel_row = sel_indices[sel] if sel_indices else -1

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=1, mouse_handler=clear_hover,
    ))

    body_rows = 0
    for i, (kind, label) in enumerate(_OPTIONS_ROWS):
        if kind == "sep":
            frags.append(("", "\n", clear_hover))
            body_rows += 1
            continue

        is_active = (i == sel_row)
        is_hover  = (i == _hover_options)
        state     = _menu_row_state(is_active, is_hover)

        def _make_handler(row_idx=i, sel_pos=sel_indices.index(i) if i in sel_indices else 0):
            def _handler(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options", row_idx)
                    return
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _sel_options
                _sel_options = sel_pos
                _options_activate(row_idx)
                if _app:
                    _app.invalidate()
            return _handler

        h         = _make_handler()
        row_w     = len(label) + 6
        left_pad  = max(0, (cols - row_w) // 2)
        right_pad = max(0, cols - left_pad - row_w)
        frags.append(("", " " * left_pad, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * right_pad, clear_hover))
        frags.append(("", "\n", clear_hover))
        body_rows += 1

    content_rows = title_block_height(1) + body_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


# ---------------------------------------------------------------------------
# Panes hub (Options → Panes): thin index over the per-pane layout pages.
# Mirrors the Options grouping — a `<< label >>` menu listing General (the
# pane × colour grid) and Timers (the timers-layout grid), with a Back row.
# Future per-pane pages (Status / Communication / Group) slot in here.
# ---------------------------------------------------------------------------
_OPTIONS_PANES_ROWS = [
    ("general",       "General"),
    ("timers",        "Timers"),
    ("communication", "Communication"),
    ("sep",           ""),
    ("back",          "Back"),
]


def _panes_selectable_indices():
    return [i for i, (k, _) in enumerate(_OPTIONS_PANES_ROWS) if k != "sep"]


def _enter_panes_frame():
    global _sel_panes
    _sel_panes = 0
    _push_frame("panes")


def _panes_activate(row_idx):
    global _panes_general_row, _panes_general_col, _timers_row, _timers_col
    global _panes_comm_row
    if not (0 <= row_idx < len(_OPTIONS_PANES_ROWS)):
        return
    action, _label = _OPTIONS_PANES_ROWS[row_idx]
    if action == "general":
        _panes_general_row = 0
        _panes_general_col = 0
        _push_frame("panes_general")
    elif action == "timers":
        _timers_row = 0
        _timers_col = 0
        _push_frame("timers")
    elif action == "communication":
        _panes_comm_row = 0
        _push_frame("panes_communication")
    elif action == "back":
        _pop_frame()


def _panes_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("panes", -1)


def _panes_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Panes ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"
    clear_hover = _panes_clear_hover

    sel_indices = _panes_selectable_indices()
    sel = _sel_panes
    if sel >= len(sel_indices):
        sel = len(sel_indices) - 1
    sel_row = sel_indices[sel] if sel_indices else -1

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=1, mouse_handler=clear_hover,
    ))

    body_rows = 0
    for i, (kind, label) in enumerate(_OPTIONS_PANES_ROWS):
        if kind == "sep":
            frags.append(("", "\n", clear_hover))
            body_rows += 1
            continue

        is_active = (i == sel_row)
        is_hover  = (i == _hover_panes)
        state     = _menu_row_state(is_active, is_hover)

        def _make_handler(row_idx=i, sel_pos=sel_indices.index(i) if i in sel_indices else 0):
            def _handler(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("panes", row_idx)
                    return
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _sel_panes
                _sel_panes = sel_pos
                _panes_activate(row_idx)
                if _app:
                    _app.invalidate()
            return _handler

        h         = _make_handler()
        row_w     = len(label) + 6
        left_pad  = max(0, (cols - row_w) // 2)
        right_pad = max(0, cols - left_pad - row_w)
        frags.append(("", " " * left_pad, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * right_pad, clear_hover))
        frags.append(("", "\n", clear_hover))
        body_rows += 1

    content_rows = title_block_height(1) + body_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


def _build_panes_container():
    global _panes_window
    _panes_window = Window(
        content=FormattedTextControl(text=_panes_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _panes_window


# ---------------------------------------------------------------------------
# Panes → General submenu (Options → Panes → General): pane × colour grid.
# ---------------------------------------------------------------------------
# Six pane rows × seven colour columns: each (pane, colour) cell is either
# checked or unchecked. A row with no checked cell is off; exactly one
# checked cell is on with that colour. apply_cell_toggle handles on/off /
# switch-colour; rendering goes through panes_grid_fragments. Three extra
# navigable rows hang below the grid: a blank, a [X] Display pane headers
# toggle, a blank, and Back.
#
# Persistence is immediate and live: clicking a cell writes the new state
# to startup.conf in-place AND drives tmux directly. Opening / closing a
# pane goes through toggle_pane.sh; recolouring an open pane goes through
# tmux select-pane -P bg=…. Pane open-state is re-probed from tmux on
# every render, matching the previous popup behaviour.

_PANES_GRID_ROWS   = len(_PANE_TARGETS)            # 6
_PANES_HEADERS_ROW = _PANES_GRID_ROWS              # 6
_PANES_BACK_ROW    = _PANES_GRID_ROWS + 1          # 7
_PANES_LAST_ROW    = _PANES_BACK_ROW
_PANES_LAST_COL    = len(PANE_COLOR_ORDER) - 1     # 6

# Timers-layout grid geometry. One row per group, then a [X] Display headers
# toggle, a [X] Compact layout toggle, and a Back row. The column stepper
# occupies two cursor columns (◄ at N, ► at N+1) after the N colour cells. See
# timers_layout_grid.py and docs/timers-pane.md.
_TIMERS_GRID_ROWS    = len(TIMERS_LAYOUT_TYPES)    # 6
_TIMERS_HEADERS_ROW  = _TIMERS_GRID_ROWS           # 6
_TIMERS_COMPACT_ROW  = _TIMERS_GRID_ROWS + 1       # 7
_TIMERS_BACK_ROW     = _TIMERS_GRID_ROWS + 2       # Back is the 9th row
_TIMERS_LAST_ROW     = _TIMERS_BACK_ROW
_TIMERS_LAST_COL     = len(TIMERS_COLOR_ORDER) + 1 # colour cols + ◄ + ►


def _set_panes_cursor(row, col=None):
    """Update the popup panes cursor; invalidate on change."""
    global _panes_general_row, _panes_general_col
    changed = False
    if row != _panes_general_row:
        _panes_general_row = row
        changed = True
    if col is not None and col != _panes_general_col:
        _panes_general_col = col
        changed = True
    if changed and _app:
        _app.invalidate()


def _persist_conf_key(key, val):
    """Append-or-replace a single key=val line in bridge/runtime/startup.conf.
    The launcher writes the file fresh on save; the popup edits it in-place
    via toggle_pane.sh for show_* keys, and here for pane_color_* keys."""
    try:
        existing = ""
        if os.path.exists(STARTUP_CONF_PATH):
            with open(STARTUP_CONF_PATH) as fh:
                existing = fh.read()
        lines = existing.splitlines()
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={val}")
        with open(STARTUP_CONF_PATH, "w") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def _retint_pane(target, color_name):
    """Apply the new colour live to the open pane (no-op if pane is closed)."""
    titles = _tmux_pane_titles()
    if target not in titles:
        return
    hex_color = PANE_COLORS.get(color_name)
    bg = "bg=default" if hex_color is None else f"bg={hex_color}"
    # Resolve the target's pane index.
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-t", TMUX_SESSION,
             "-F", "#{pane_index} #{pane_title}"],
            capture_output=True, text=True, timeout=1.0,
        )
    except (subprocess.SubprocessError, OSError):
        return
    idx = None
    for line in out.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1] == target:
            idx = parts[0]
            break
    if idx is None:
        return
    try:
        subprocess.run(
            ["tmux", "select-pane", "-t", f"{TMUX_SESSION}.{idx}", "-P", bg],
            timeout=1.0,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def _apply_panes_grid_toggle(row, col):
    """Apply a click on grid cell (row, col): open/close and/or re-tint.

    The new (enabled, colour) state comes from apply_cell_toggle; the
    delta from the current tmux state drives toggle_pane.sh and a live
    re-tint when the pane is (or just became) open.
    """
    target, _label, color_key = _PANE_TARGETS[row]
    titles = set(_tmux_pane_titles())
    enabled = (target in titles)
    conf = _parse_keyval(STARTUP_CONF_PATH)
    cur_color = conf.get(color_key, "")
    try:
        cur_idx = PANE_COLOR_ORDER.index(cur_color)
    except ValueError:
        cur_idx = 0

    new_enabled, new_idx = apply_cell_toggle(enabled, cur_idx, col)
    new_color = PANE_COLOR_ORDER[new_idx]

    if new_enabled != enabled:
        _toggle_pane(target)
    if new_enabled:
        if new_color != cur_color:
            _persist_conf_key(color_key, new_color)
        _retint_pane(target, new_color)
    if _app:
        _app.invalidate()


def _toggle_pane_headers():
    """Flip the pane-divider headers (live tmux + persisted)."""
    _toggle_pane("headers")
    if _app:
        _app.invalidate()


# ---------------------------------------------------------------------------
# Timers-layout submenu (group colours, columns, visibility).
#
# Mirrors the Panes submenu but edits per-group timer settings instead of
# tmux panes. Persistence is immediate and live: clicking a cell writes the
# changed key(s) to bridge/runtime/timers_layout.conf in-place; the running
# timers pane polls that file (~100 ms) and re-renders. No tmux interaction.
# See timers_layout_grid.py and docs/timers-pane.md.
# ---------------------------------------------------------------------------
def _read_timers_layout():
    """Merge timers_layout.conf over the defaults into a per-type dict.

    Returns {type: {"enabled": bool, "color": "#rrggbb", "cols": int}} so the
    render path can re-probe live state every frame, matching the panes
    submenu's per-render re-read."""
    conf = _parse_keyval(TIMERS_LAYOUT_CONF_PATH)
    layout = {
        typ: dict(TIMERS_LAYOUT_DEFAULTS[typ]) for typ in TIMERS_LAYOUT_TYPES
    }
    layout["headers"] = TIMERS_HEADERS_DEFAULT
    layout["compact"] = TIMERS_COMPACT_DEFAULT
    for key, val in conf.items():
        # timers_headers / timers_compact are global toggles with no second
        # underscore, so they must branch before the type-split below
        # (rpartition would drop them).
        if key == "timers_headers":
            if val in ("0", "1"):
                layout["headers"] = (val == "1")
            continue
        if key == "timers_compact":
            if val in ("0", "1"):
                layout["compact"] = (val == "1")
            continue
        if not key.startswith("timers_"):
            continue
        typ, _sep, attr = key[len("timers_"):].rpartition("_")
        if typ not in layout:
            continue
        if attr == "enabled":
            layout[typ]["enabled"] = (val != "0")
        elif attr == "color":
            v = val.strip()
            if len(v) == 7 and v.startswith("#"):
                layout[typ]["color"] = v
        elif attr == "cols":
            n = clamp_cols(typ, val)
            if n is not None:
                layout[typ]["cols"] = n
    return layout


def _persist_timers_layout_key(key, val):
    """Append-or-replace a single key=val line in timers_layout.conf.
    Byte-for-byte mirror of _persist_conf_key, targeting the timers file."""
    try:
        existing = ""
        if os.path.exists(TIMERS_LAYOUT_CONF_PATH):
            with open(TIMERS_LAYOUT_CONF_PATH) as fh:
                existing = fh.read()
        lines = existing.splitlines()
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={val}")
        with open(TIMERS_LAYOUT_CONF_PATH, "w") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def _set_timers_cursor(row, col=None):
    """Update the popup timers cursor; invalidate on change."""
    global _timers_row, _timers_col
    changed = False
    if row != _timers_row:
        _timers_row = row
        changed = True
    if col is not None and col != _timers_col:
        _timers_col = col
        changed = True
    if changed and _app:
        _app.invalidate()


def _apply_timers_grid_toggle(row, col):
    """Apply a click on a colour cell: flip enabled / pick colour, persist."""
    typ = TIMERS_LAYOUT_TYPES[row]
    cur = _read_timers_layout()[typ]
    enabled = cur["enabled"]
    idx = timers_color_index(cur["color"])
    new_en, new_idx = apply_cell_toggle(enabled, idx, col)
    _persist_timers_layout_key(f"timers_{typ}_enabled", "1" if new_en else "0")
    _persist_timers_layout_key(f"timers_{typ}_color", timers_color_hex(new_idx))
    if _app:
        _app.invalidate()


def _apply_timers_step(row, delta):
    """Step a group's column count by delta (clamped), persist."""
    typ = TIMERS_LAYOUT_TYPES[row]
    cur = _read_timers_layout()[typ]
    new = step_cols(cur["cols"], max_cols_for(typ), delta)
    _persist_timers_layout_key(f"timers_{typ}_cols", str(new))
    if _app:
        _app.invalidate()


def _toggle_timers_headers():
    """Flip timers_headers and persist immediately. The running timers pane
    polls timers_layout.conf (~100 ms) and re-renders — no tmux interaction."""
    headers = _read_timers_layout()["headers"]
    _persist_timers_layout_key("timers_headers", "0" if headers else "1")
    if _app:
        _app.invalidate()


def _toggle_timers_compact():
    """Flip timers_compact and persist immediately. The running timers pane
    polls timers_layout.conf (~100 ms) and re-renders — no tmux interaction."""
    compact = _read_timers_layout()["compact"]
    _persist_timers_layout_key("timers_compact", "0" if compact else "1")
    if _app:
        _app.invalidate()


def _panes_general_text():
    cols   = _term_cols()
    rows_h = _term_rows()

    # Live grid state: pane-open from tmux, current colour from startup.conf.
    titles_set = set(_tmux_pane_titles())
    conf       = _parse_keyval(STARTUP_CONF_PATH)
    grid_rows = []
    for target, label, color_key in _PANE_TARGETS:
        enabled = (target in titles_set)
        cur_color = conf.get(color_key, "")
        try:
            colour_index = PANE_COLOR_ORDER.index(cur_color)
        except ValueError:
            colour_index = 0
        grid_rows.append((label, enabled, colour_index))

    cur_row = _panes_general_row
    cur_col = _panes_general_col
    grid_cursor = (cur_row, cur_col) if cur_row < _PANES_GRID_ROWS else None

    headers_on    = (_tmux_border_status() != "off")
    headers_label = f"[{'X' if headers_on else ' '}] Display pane headers"
    back_label    = "Back"

    frags = []
    frags.extend(title_block("─── Panes ───", cols, blank_above=1))

    def _make_cell_handler(ri, ci):
        def _h(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                _set_panes_cursor(ri, ci)
                return
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _set_panes_cursor(ri, ci)
                _apply_panes_grid_toggle(ri, ci)
        return _h

    frags.extend(panes_grid_fragments(
        grid_rows, cols, grid_cursor, cell_handler=_make_cell_handler,
    ))

    frags.append(("", "\n"))

    # Display pane headers — single << label >> toggle, centred per row.
    # Cursor row → gold-arrow `selected`; otherwise `inactive` (cursor-only
    # frame, no separate mouse-hover index).
    state_h = "selected" if cur_row == _PANES_HEADERS_ROW else "inactive"

    def _headers_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_panes_cursor(_PANES_HEADERS_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _set_panes_cursor(_PANES_HEADERS_ROW)
            _toggle_pane_headers()

    pad_h = max(0, (cols - (len(headers_label) + 6)) // 2)
    frags.append(("", " " * pad_h))
    frags.extend(menu_row(headers_label, state_h, mouse_handler=_headers_handler))
    frags.append(("", "\n"))

    frags.append(("", "\n"))

    # Back — plain << label >> row, centred per row.
    state_b = "selected" if cur_row == _PANES_BACK_ROW else "inactive"

    def _back_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_panes_cursor(_PANES_BACK_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _pop_frame()

    pad_b = max(0, (cols - (len(back_label) + 6)) // 2)
    frags.append(("", " " * pad_b))
    frags.extend(menu_row(back_label, state_b, mouse_handler=_back_handler))
    frags.append(("", "\n"))

    # title block (3 rows for popup) + grid header (1) + 6 pane rows
    # + blank + headers + blank + Back (4 rows).
    content_rows = title_block_height(1) + 1 + _PANES_GRID_ROWS + 4
    footer = "↑↓←→ Move · Enter Toggle · ESC Back"
    frags.extend(footer_block(footer, cols, rows_h, content_rows))

    return frags


# ---------------------------------------------------------------------------
# Scripts frame — read-only two-column [ list | detail ] view.
#
# Sourced from `bridge/runtime/scripts.cache` (the brain-written snapshot)
# rather than a live filesystem scan, so the popup always reflects the
# enabled set that's currently loaded into the brain — including disabled
# scripts and their metadata. Toggling is intentionally absent: enabled
# scripts may have registered aliases / triggers / event subscriptions
# without a universal teardown contract, so toggling mid-session would
# leave phantom registrations. See ADR 0093 and docs/scripts.md.
# ---------------------------------------------------------------------------
def _enter_scripts_frame():
    """Load the cache, seat the cursor at row 0, push the frame."""
    global _scripts_catalog, _scripts_cursor, _scripts_on_back
    global _scripts_list_scroll, _scripts_detail_scroll
    global _scripts_hover, _scripts_hover_back
    _scripts_catalog       = scripts_view.parse_scripts_cache(
        SCRIPTS_CACHE_PATH,
    )
    _scripts_cursor        = 0
    # When the cache is empty there is no script row to highlight, so
    # the cursor lands on Back (the only navigable row).
    _scripts_on_back       = (len(_scripts_catalog) == 0)
    _scripts_list_scroll   = 0
    _scripts_detail_scroll = 0
    _scripts_hover         = None
    _scripts_hover_back    = False
    _push_frame("scripts")


def _scripts_visible_rows():
    """Visible body rows = popup rows minus the title block (3 for the
    popup's `blank_above=1`) and the single footer row anchored at the
    bottom by `footer_block`."""
    return max(1, _term_rows() - title_block_height(1) - 1)


def _scripts_list_rows():
    """Rows available to the script list — body minus the 2 trailing
    rows the left column reserves for the blank spacer + Back."""
    return max(1, _scripts_visible_rows() - 2)


def _scripts_detail_total():
    """Number of detail-panel rows for the latched script, used to
    clamp detail-pane scroll bounds. Mirrors the launcher's helper."""
    if not _scripts_catalog:
        return _scripts_visible_rows()
    cur = _scripts_catalog[max(0, min(_scripts_cursor,
                                      len(_scripts_catalog) - 1))]
    list_w   = scripts_view.list_panel_width(_scripts_catalog)
    detail_w = scripts_view.detail_panel_width(_term_cols(), list_w)
    return len(scripts_view.render_detail_lines(cur, detail_w))


def _scripts_move_up():
    """Step the cursor one row up: Back → last script; first script
    → no-op. Resets the detail scroll on a script change."""
    global _scripts_cursor, _scripts_on_back
    global _scripts_detail_scroll, _scripts_list_scroll
    n = len(_scripts_catalog)
    if _scripts_on_back:
        if n == 0:
            return
        _scripts_on_back = False
        _scripts_cursor  = n - 1
        _scripts_detail_scroll = 0
    elif _scripts_cursor > 0:
        _scripts_cursor -= 1
        _scripts_detail_scroll = 0
    else:
        return
    _scripts_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _scripts_move_down():
    """Step the cursor one row down: last script → Back; Back → no-op.
    Resets the detail scroll on a script change."""
    global _scripts_cursor, _scripts_on_back
    global _scripts_detail_scroll, _scripts_list_scroll
    n = len(_scripts_catalog)
    if _scripts_on_back or n == 0:
        return
    if _scripts_cursor < n - 1:
        _scripts_cursor += 1
        _scripts_detail_scroll = 0
    else:
        _scripts_on_back = True
    _scripts_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _scripts_ensure_cursor_visible():
    """Pull `_scripts_list_scroll` so the cursor stays inside the
    visible list window. No-op when the cursor sits on Back — Back
    lives below the spacer, outside the list scroll viewport."""
    global _scripts_list_scroll
    if _scripts_on_back:
        return
    body = _scripts_list_rows()
    if _scripts_cursor < _scripts_list_scroll:
        _scripts_list_scroll = _scripts_cursor
    elif _scripts_cursor >= _scripts_list_scroll + body:
        _scripts_list_scroll = _scripts_cursor - body + 1


def _scripts_scroll_detail(delta):
    """Page the detail viewport by `delta` rows, clamped to the detail
    content total. PageUp/PageDown is the keyboard scroll path; the
    detail scrollbar click handler reuses it. The popup intentionally
    has no mouse-wheel binding."""
    global _scripts_detail_scroll
    total = _scripts_detail_total()
    body  = _scripts_visible_rows()
    mx    = max(0, total - body)
    new   = max(0, min(mx, _scripts_detail_scroll + delta))
    if new != _scripts_detail_scroll:
        _scripts_detail_scroll = new
        if _app:
            _app.invalidate()


def _scripts_set_hover(row):
    """Update the row under the mouse pointer (or None when over
    chrome). Also clears the Back hover — only one row can be hovered
    at a time. Only repaints when something actually changes."""
    global _scripts_hover, _scripts_hover_back
    changed = False
    if _scripts_hover != row:
        _scripts_hover = row
        changed = True
    if _scripts_hover_back:
        _scripts_hover_back = False
        changed = True
    if changed and _app:
        _app.invalidate()


def _scripts_set_hover_back(on):
    """Mark the Back row as hovered. Clears the list hover too."""
    global _scripts_hover, _scripts_hover_back
    changed = False
    if _scripts_hover_back != on:
        _scripts_hover_back = on
        changed = True
    if _scripts_hover is not None:
        _scripts_hover = None
        changed = True
    if changed and _app:
        _app.invalidate()


def _scripts_clear_hover(ev):
    """MOUSE_MOVE handler attached to title/footer chrome so the hover
    highlight clears the moment the pointer leaves a selectable row —
    the hover-clear invariant from docs/popup-menu.md. Title/footer
    span both columns; wheel here forwards to the detail panel (the
    primary content surface) so the chrome doesn't absorb the event
    (ADR 0062)."""
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _scripts_set_hover(None)
        return None
    if ev.event_type == MouseEventType.SCROLL_UP:
        _scripts_scroll_detail(-3)
        return None
    if ev.event_type == MouseEventType.SCROLL_DOWN:
        _scripts_scroll_detail(3)
        return None
    return NotImplemented


def _scripts_list_chrome_wheel_handler(ev):
    """MOUSE_MOVE + wheel handler for cells living in the list column
    (the blank spacer above Back). Wheel moves the list cursor by 1
    row per notch, matching the row handler above it."""
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _scripts_set_hover(None)
        return None
    if ev.event_type == MouseEventType.SCROLL_UP:
        _scripts_move_up()
        return None
    if ev.event_type == MouseEventType.SCROLL_DOWN:
        _scripts_move_down()
        return None
    return NotImplemented


def _scripts_select_row(row_idx):
    """Move the browse cursor to `row_idx` without toggling — the
    popup's read-only equivalent of clicking a script row in the
    launcher. Resets the detail scroll and keeps the row visible."""
    global _scripts_cursor, _scripts_on_back, _scripts_detail_scroll
    n = len(_scripts_catalog)
    if not (0 <= row_idx < n):
        return
    if row_idx != _scripts_cursor or _scripts_on_back:
        _scripts_cursor = row_idx
        _scripts_on_back = False
        _scripts_detail_scroll = 0
        _scripts_ensure_cursor_visible()
        if _app:
            _app.invalidate()


def _scripts_row_handler(row_idx):
    """Mouse handler for one list row — click moves the cursor (no
    toggle: the popup is read-only); MOUSE_MOVE updates hover; wheel
    moves the cursor by 1 row per notch (mirrors the launcher)."""
    def _h(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _scripts_set_hover(row_idx)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _scripts_select_row(row_idx)
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _scripts_move_up()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _scripts_move_down()
            return None
        return NotImplemented
    return _h


def _scripts_list_sb_handler(local_row):
    """Click on the list scrollbar — page-step toward the click row.
    Wheel forwarded to the cursor-movement handlers so the list and
    its scrollbar feel like one surface."""
    def _h(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            _scripts_move_up()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _scripts_move_down()
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        body = _scripts_list_rows()
        if local_row < body // 2:
            for _ in range(body):
                _scripts_move_up()
        else:
            for _ in range(body):
                _scripts_move_down()
        return None
    return _h


def _scripts_back_handler():
    """Mouse handler for the in-column Back row — click pops the
    frame; MOUSE_MOVE highlights Back; wheel moves the list cursor
    (Back sits in the list column)."""
    def _h(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _scripts_set_hover_back(True)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _pop_frame()
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _scripts_move_up()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _scripts_move_down()
            return None
        return NotImplemented
    return _h


def _scripts_detail_handler(body_row):
    """Mouse handler over a detail-panel cell — clears the list/Back
    hover so previously-glowing rows stop glowing on MOUSE_MOVE; wheel
    scrolls the detail panel 3 rows per notch (mirrors the launcher).
    Click is a no-op (the detail panel is read-only)."""
    def _h(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _scripts_set_hover(None)
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _scripts_scroll_detail(-3)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _scripts_scroll_detail(3)
            return None
        return NotImplemented
    return _h


def _scripts_detail_sb_handler(local_row):
    """Click on the detail scrollbar — page-step toward the click row.
    Wheel scrolls the detail panel (so the scrollbar cell behaves like
    the panel it serves)."""
    def _h(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            _scripts_scroll_detail(-3)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _scripts_scroll_detail(3)
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        body = _scripts_visible_rows()
        if local_row < body // 2:
            _scripts_scroll_detail(-body)
        else:
            _scripts_scroll_detail(body)
        return None
    return _h


def _scripts_back_row_frags(list_w):
    """Pre-rendered fragments for the in-column Back row — same
    `menu_chrome.menu_row` grammar as the launcher's Scripts Back:
      cursor on Back        → gold `<< Back >>` (selected)
      mouse hover on Back   → light label (`C_HOVER`)
      otherwise             → inactive label (`C_ITEM`)
    Outer padding carries the Back handler so MOUSE_MOVE anywhere on
    the row sets the Back hover."""
    label = "Back"
    row_w = len(label) + 6       # `<< ` + label + ` >>`
    pad   = max(0, list_w - row_w)
    left  = pad // 2
    right = pad - left

    if _scripts_on_back:
        state = "selected"
    elif _scripts_hover_back:
        state = "hover"
    else:
        state = "inactive"
    h = _scripts_back_handler()
    return [
        ("", " " * left,  h),
        *menu_row(label, state, mouse_handler=h),
        ("", " " * right, h),
    ]


def _scripts_blank_row_frags(list_w):
    """Blank spacer row in the left column. Carries a clear-hover +
    wheel-forwarding handler so the highlight does not stick when the
    pointer crosses the spacer and wheel events don't get absorbed
    (ADR 0062)."""
    return [("", " " * list_w, _scripts_list_chrome_wheel_handler)]


def _scripts_text():
    """Renderer for the popup's Scripts page. Uses the shared body
    renderer with the same in-column Back / extras layout as the
    launcher, minus toggling and mouse-wheel (the popup is read-only
    and tmux popup mode does not forward wheel events anyway). The
    footer omits the Toggle key — its absence is the read-only signal."""
    cols   = _term_cols()
    rows_h = _term_rows()
    body_h = _scripts_visible_rows()
    clear  = _scripts_clear_hover

    frags = []
    frags.extend(title_block(
        "─── Scripts ───", cols, blank_above=1, mouse_handler=clear,
    ))

    list_w = (scripts_view.list_panel_width(_scripts_catalog)
              if _scripts_catalog else scripts_view.MIN_LIST_W)
    extra_left = [
        _scripts_blank_row_frags(list_w),
        _scripts_back_row_frags(list_w),
    ]

    if _scripts_catalog:
        row_h  = _scripts_row_handler
        sb_h   = _scripts_list_sb_handler
        hover  = _scripts_hover
    else:
        row_h = sb_h = None
        hover  = None
    det_h  = _scripts_detail_handler
    det_sb = _scripts_detail_sb_handler

    # When the cursor sits on Back, suppress the list-row highlight
    # (`cursor_idx=-1`) but keep the detail panel showing the latched
    # script via `detail_idx=_scripts_cursor`.
    cursor_idx = -1 if _scripts_on_back else _scripts_cursor

    frags.extend(scripts_view.render_body(
        _scripts_catalog,
        cursor_idx=cursor_idx,
        list_scroll=_scripts_list_scroll,
        detail_scroll=_scripts_detail_scroll,
        term_cols=cols,
        body_h=body_h,
        focus="list",
        mode="readonly",
        row_handler=row_h,
        sb_handler=sb_h,
        detail_handler=det_h,
        detail_sb_handler=det_sb,
        hover_row=hover,
        detail_idx=_scripts_cursor,
        extra_left_rows=extra_left,
    ))

    if _scripts_catalog:
        footer = "↑↓ Move · PgUp/PgDn Scroll · ESC Back"
    else:
        footer = "ESC Back"
    content_rows = title_block_height(1) + body_h
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear,
    ))
    return frags


# ---------------------------------------------------------------------------
# Readability frame — interactive two-column [ list | detail ] view.
#
# Live filesystem scan of ttpp/readability/modules/; toggling updates the
# glyph in place and marks dirty. Save-and-pop writes startup.conf, fires
# hot reload via _send_to_game, and flashes on main. Mirrors the launcher's
# slice-2a implementation with the addition of the reload dispatch +
# pop-two-frames-to-main pattern from the profile-apply flow (ADR 0110).
#
# The snapshot/canary/result-poll/worker-thread machinery from ADR 0110 is
# deliberately omitted: readability .tin files are static developer-authored
# content, not user-edited text, so there is no "user corrupts the class
# with a parse error" failure mode to guard against.
# ---------------------------------------------------------------------------
def _enter_readability_frame():
    global _readability_catalog, _readability_dirty
    global _readability_cursor, _readability_on_back
    global _readability_list_scroll, _readability_detail_scroll
    global _readability_hover, _readability_hover_back
    enabled = readability_view.read_enabled(STARTUP_CONF_PATH)
    _readability_catalog       = readability_view.scan_modules_dir(
        READABILITY_MODULES_DIR, enabled,
    )
    _readability_dirty         = False
    _readability_cursor        = 0
    _readability_on_back       = (len(_readability_catalog) == 0)
    _readability_list_scroll   = 0
    _readability_detail_scroll = 0
    _readability_hover         = None
    _readability_hover_back    = False
    _push_frame("readability")


def _readability_visible_rows():
    return max(1, _term_rows() - title_block_height(1) - 1)


def _readability_list_rows():
    return max(1, _readability_visible_rows() - 2)


def _readability_save_and_pop():
    global _readability_dirty
    if _readability_dirty and _readability_catalog:
        enabled = {m.name for m in _readability_catalog if m.enabled}
        readability_view.write_enabled(STARTUP_CONF_PATH, enabled)
        _send_to_game("cp -readability-apply")
        _flash_main("Readability updated.", C_ACCENT)
        _readability_dirty = False
    _pop_frame()
    _pop_frame()


def _readability_detail_total():
    if not _readability_catalog:
        return _readability_visible_rows()
    cur = _readability_catalog[max(0, min(_readability_cursor,
                                          len(_readability_catalog) - 1))]
    list_w   = readability_view.list_panel_width(_readability_catalog)
    detail_w = readability_view.detail_panel_width(_term_cols(), list_w)
    return len(readability_view.render_detail_lines(cur, detail_w))


def _readability_move_up():
    global _readability_cursor, _readability_on_back
    global _readability_detail_scroll, _readability_list_scroll
    n = len(_readability_catalog)
    if _readability_on_back:
        if n == 0:
            return
        _readability_on_back = False
        _readability_cursor  = n - 1
        _readability_detail_scroll = 0
    elif _readability_cursor > 0:
        _readability_cursor -= 1
        _readability_detail_scroll = 0
    else:
        return
    _readability_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _readability_move_down():
    global _readability_cursor, _readability_on_back
    global _readability_detail_scroll, _readability_list_scroll
    n = len(_readability_catalog)
    if _readability_on_back or n == 0:
        return
    if _readability_cursor < n - 1:
        _readability_cursor += 1
        _readability_detail_scroll = 0
    else:
        _readability_on_back = True
    _readability_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _readability_ensure_cursor_visible():
    global _readability_list_scroll
    if _readability_on_back:
        return
    body = _readability_list_rows()
    if _readability_cursor < _readability_list_scroll:
        _readability_list_scroll = _readability_cursor
    elif _readability_cursor >= _readability_list_scroll + body:
        _readability_list_scroll = _readability_cursor - body + 1


def _readability_scroll_detail(delta):
    global _readability_detail_scroll
    total = _readability_detail_total()
    body  = _readability_visible_rows()
    mx    = max(0, total - body)
    new   = max(0, min(mx, _readability_detail_scroll + delta))
    if new != _readability_detail_scroll:
        _readability_detail_scroll = new
        if _app:
            _app.invalidate()


def _readability_toggle_cursor():
    global _readability_dirty
    n = len(_readability_catalog)
    if n == 0 or _readability_on_back:
        return
    idx = max(0, min(n - 1, _readability_cursor))
    _readability_catalog[idx].enabled = not _readability_catalog[idx].enabled
    _readability_dirty = True
    if _app:
        _app.invalidate()


def _readability_activate_cursor():
    if _readability_on_back:
        _readability_save_and_pop()
    else:
        _readability_toggle_cursor()


def _readability_set_hover(row):
    global _readability_hover, _readability_hover_back
    changed = False
    if _readability_hover != row:
        _readability_hover = row
        changed = True
    if _readability_hover_back:
        _readability_hover_back = False
        changed = True
    if changed and _app:
        _app.invalidate()


def _readability_set_hover_back(on):
    global _readability_hover, _readability_hover_back
    changed = False
    if _readability_hover_back != on:
        _readability_hover_back = on
        changed = True
    if _readability_hover is not None:
        _readability_hover = None
        changed = True
    if changed and _app:
        _app.invalidate()


def _readability_clear_hover(ev):
    """Title/footer chrome handler. Wheel forwards to the detail panel
    so the chrome doesn't absorb the event (ADR 0062)."""
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _readability_set_hover(None)
        return None
    if ev.event_type == MouseEventType.SCROLL_UP:
        _readability_scroll_detail(-3)
        return None
    if ev.event_type == MouseEventType.SCROLL_DOWN:
        _readability_scroll_detail(3)
        return None
    return NotImplemented


def _readability_list_chrome_wheel_handler(ev):
    """Clear-hover + wheel-forwarding handler for cells in the list
    column (the blank spacer above Back). Wheel moves the list cursor
    by 1 row per notch, matching the row handler above it."""
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _readability_set_hover(None)
        return None
    if ev.event_type == MouseEventType.SCROLL_UP:
        _readability_move_up()
        return None
    if ev.event_type == MouseEventType.SCROLL_DOWN:
        _readability_move_down()
        return None
    return NotImplemented


def _readability_row_handler(row_idx):
    def _h(ev):
        global _readability_cursor, _readability_on_back, _readability_detail_scroll
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _readability_set_hover(row_idx)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            if row_idx != _readability_cursor or _readability_on_back:
                _readability_cursor = row_idx
                _readability_on_back = False
                _readability_detail_scroll = 0
                _readability_ensure_cursor_visible()
            _readability_toggle_cursor()
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _readability_move_up()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _readability_move_down()
            return None
        return NotImplemented
    return _h


def _readability_list_sb_handler(local_row):
    def _h(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            _readability_move_up()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _readability_move_down()
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        body = _readability_list_rows()
        if local_row < body // 2:
            for _ in range(body):
                _readability_move_up()
        else:
            for _ in range(body):
                _readability_move_down()
        return None
    return _h


def _readability_back_handler():
    def _h(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _readability_set_hover_back(True)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _readability_save_and_pop()
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _readability_move_up()
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _readability_move_down()
            return None
        return NotImplemented
    return _h


def _readability_detail_handler(body_row):
    def _h(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _readability_set_hover(None)
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _readability_scroll_detail(-3)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _readability_scroll_detail(3)
            return None
        return NotImplemented
    return _h


def _readability_detail_sb_handler(local_row):
    def _h(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            _readability_scroll_detail(-3)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _readability_scroll_detail(3)
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        body = _readability_visible_rows()
        if local_row < body // 2:
            _readability_scroll_detail(-body)
        else:
            _readability_scroll_detail(body)
        return None
    return _h


def _readability_back_row_frags(list_w):
    label = "Back"
    row_w = len(label) + 6
    pad   = max(0, list_w - row_w)
    left  = pad // 2
    right = pad - left

    if _readability_on_back:
        state = "selected"
    elif _readability_hover_back:
        state = "hover"
    else:
        state = "inactive"
    h = _readability_back_handler()
    return [
        ("", " " * left,  h),
        *menu_row(label, state, mouse_handler=h),
        ("", " " * right, h),
    ]


def _readability_blank_row_frags(list_w):
    return [("", " " * list_w, _readability_list_chrome_wheel_handler)]


def _readability_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    body_h = _readability_visible_rows()
    clear  = _readability_clear_hover

    frags = []
    frags.extend(title_block(
        "─── Readability ───", cols, blank_above=1, mouse_handler=clear,
    ))

    list_w = (readability_view.list_panel_width(_readability_catalog)
              if _readability_catalog else readability_view.MIN_LIST_W)
    extra_left = [
        _readability_blank_row_frags(list_w),
        _readability_back_row_frags(list_w),
    ]

    if _readability_catalog:
        row_h  = _readability_row_handler
        sb_h   = _readability_list_sb_handler
        hover  = _readability_hover
    else:
        row_h = sb_h = None
        hover  = None
    det_h  = _readability_detail_handler
    det_sb = _readability_detail_sb_handler

    cursor_idx = -1 if _readability_on_back else _readability_cursor

    frags.extend(readability_view.render_body(
        _readability_catalog,
        cursor_idx=cursor_idx,
        list_scroll=_readability_list_scroll,
        detail_scroll=_readability_detail_scroll,
        term_cols=cols,
        body_h=body_h,
        focus="list",
        mode="interactive",
        row_handler=row_h,
        sb_handler=sb_h,
        detail_handler=det_h,
        detail_sb_handler=det_sb,
        hover_row=hover,
        detail_idx=_readability_cursor,
        extra_left_rows=extra_left,
    ))

    if _readability_catalog:
        footer = "↑↓ Move · Space Toggle · PgUp/PgDn Scroll · ESC Back"
    else:
        footer = "ESC Back"
    content_rows = title_block_height(1) + body_h
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear,
    ))
    return frags


# ---------------------------------------------------------------------------
# Profile editor — EditorHost, entry flow, on_exit, apply-confirm
# ---------------------------------------------------------------------------
def _read_terminal_bg():
    """Read terminal_bg from bridge/runtime/layout.conf (persisted by
    the launcher's background-detect probe). Returns hex string or None."""
    try:
        with open(LAYOUT_CONF_PATH) as fh:
            for line in fh:
                if line.startswith("terminal_bg="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val
    except OSError:
        pass
    return None


class _PopupEditorHost:
    """Bridges ProfileEditor back to ingame_menu globals."""

    @property
    def app(self):
        return _app

    @property
    def app_loop(self):
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    @property
    def terminal_bg(self):
        return _read_terminal_bg()

    def term_cols(self):
        return _term_cols()

    def term_rows(self):
        return _term_rows()

    def push_overlay_frame(self):
        _push_frame("profile_editor_macro_keybind")

    def pop_overlay_frame(self):
        _pop_frame()

    def focus_current_frame(self):
        _focus_current_frame()

    def is_active(self):
        return _current_frame == "profile_editor"

    def is_overlay_active(self):
        return _current_frame == "profile_editor_macro_keybind"


_popup_editor_host = _PopupEditorHost()


def _profile_editor_cleanup():
    """Clear the editor instance and remove runtime tempfiles."""
    global _profile_editor_instance, _profile_editor_original_text
    global _profile_editor_pending_profile, _profile_editor_disk_path
    global _profile_editor_name, _profile_apply_status
    _profile_editor_instance = None
    _profile_editor_original_text = None
    _profile_editor_pending_profile = None
    _profile_editor_disk_path = None
    _profile_editor_name = None
    _profile_apply_status = None
    for p in (PROFILE_SNAPSHOT_PATH, PROFILE_EDIT_PATH,
              PROFILE_SNAP_RESULT, PROFILE_APPLY_RESULT):
        _remove_sentinel(p)


def _flash_main(msg, style, duration=3.0):
    """Show a temporary message on the main frame. The popup's 1 Hz tick
    invalidates often enough for the message to disappear after `duration`."""
    global _profile_flash_text, _profile_flash_style, _profile_flash_until
    _profile_flash_text  = msg
    _profile_flash_style = style
    _profile_flash_until = time.monotonic() + duration
    if _app:
        _app.invalidate()


_profile_flash_text  = None
_profile_flash_style = ""
_profile_flash_until = 0.0


def _poll_file(path, timeout=2.0, tick=0.05):
    """Block until `path` exists and is non-empty, or timeout. Returns
    content string or None. Runs in a worker thread — never on the
    event loop."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(path) as fh:
                content = fh.read().strip()
            if content:
                return content
        except OSError:
            pass
        time.sleep(tick)
    return None


def _enter_profile_editor():
    """Entry point from the main frame's Profile row."""
    if _is_connected():
        _enter_profile_editor_connected()
    else:
        _enter_profile_editor_disconnected()


def _enter_profile_editor_connected():
    """Connected path: snapshot the live class, parse it, open the editor."""
    global _profile_editor_instance, _profile_editor_original_text
    global _profile_editor_disk_path, _profile_editor_name

    for p in (PROFILE_SNAPSHOT_PATH, PROFILE_EDIT_PATH,
              PROFILE_SNAP_RESULT, PROFILE_APPLY_RESULT):
        _remove_sentinel(p)

    _send_to_game("cp -profile-snapshot")

    loop = asyncio.get_running_loop()

    def _finish_snapshot():
        global _profile_editor_instance, _profile_editor_original_text
        global _profile_editor_disk_path, _profile_editor_name
        result = _poll_file(PROFILE_SNAP_RESULT)
        if result != "ok":
            reason = "no active profile" if result == "fail" else "timeout"
            loop.call_soon_threadsafe(
                _flash_main, f"Could not open profile: {reason}.", C_HINT)
            if _app:
                loop.call_soon_threadsafe(_app.invalidate)
            return

        try:
            prof = profile_io.load_profile(PROFILE_SNAPSHOT_PATH)
        except (OSError, Exception) as exc:
            loop.call_soon_threadsafe(
                _flash_main, f"Could not open profile: {exc}.", C_HINT)
            if _app:
                loop.call_soon_threadsafe(_app.invalidate)
            return

        conf = _parse_keyval(STARTUP_CONF_PATH)
        _profile_editor_name = conf.get("profile", "default")
        _profile_editor_disk_path = Path(
            os.path.join(PROFILES_DIR, f"{_profile_editor_name}.tin"))
        prof.path = _profile_editor_disk_path
        _profile_editor_original_text = profile_io.serialize_profile(prof)

        _profile_editor_instance = profile_editor.ProfileEditor(
            path=_profile_editor_disk_path,
            profile=prof,
            on_exit=_on_profile_editor_exit,
            host=_popup_editor_host,
        )

        loop.call_soon_threadsafe(_push_frame, "profile_editor")

    threading.Thread(target=_finish_snapshot, daemon=True).start()


def _enter_profile_editor_disconnected():
    """Disconnected path: read the profile .tin from disk directly."""
    global _profile_editor_instance, _profile_editor_original_text
    global _profile_editor_disk_path, _profile_editor_name

    conf = _parse_keyval(STARTUP_CONF_PATH)
    name = conf.get("profile", "default")
    path = Path(os.path.join(PROFILES_DIR, f"{name}.tin"))
    if not path.exists():
        _flash_main(f"Profile not found: {path.name}.", C_HINT)
        return

    try:
        prof = profile_io.load_profile(path)
    except (OSError, Exception) as exc:
        _flash_main(f"Could not open profile: {exc}.", C_HINT)
        return

    _profile_editor_name = name
    _profile_editor_disk_path = path
    _profile_editor_original_text = profile_io.serialize_profile(prof)

    _profile_editor_instance = profile_editor.ProfileEditor(
        path=path,
        profile=prof,
        on_exit=_on_profile_editor_exit,
        host=_popup_editor_host,
    )
    _push_frame("profile_editor")


def _on_profile_editor_exit(profile):
    """Called by the editor's ESC binding. Dirty-check and branch."""
    global _profile_editor_pending_profile
    final_text = profile_io.serialize_profile(profile)
    dirty = (final_text != _profile_editor_original_text)

    # Even when the user made no edits, a pre-existing hand-edit may have
    # left a core-shadowing #alias in the file. save_profile() strips it;
    # force a save so the file is cleaned and the user sees the message.
    if not dirty and profile_io.profile_has_core_collisions(profile):
        dirty = True

    if not dirty:
        _profile_editor_cleanup()
        _pop_frame()
        return

    if _is_connected():
        _profile_editor_pending_profile = profile
        _push_frame("profile_apply_confirm")
    else:
        try:
            profile.path = _profile_editor_disk_path
            profile_io.save_profile(profile)
            subprocess.run(
                ["bash", str(SANITIZE_SCRIPT), str(_profile_editor_disk_path)],
                check=False, timeout=5.0,
            )
            dropped = getattr(profile, "dropped_collisions", [])
            if dropped:
                _flash_main(
                    core_aliases.format_dropped_message(dropped), C_YELLOW)
            else:
                _flash_main(f"Saved {_profile_editor_name}.tin.", C_ACCENT)
        except OSError as exc:
            _flash_main(f"Save failed: {exc}.", C_HINT)
        _profile_editor_cleanup()
        _pop_frame()


def _apply_profile_connected():
    """Y on the apply-confirm modal: serialize, append canary, send alias,
    poll for result. Runs the poll in a worker thread."""
    global _profile_apply_status
    prof = _profile_editor_pending_profile
    if prof is None:
        _profile_editor_cleanup()
        _pop_frame()
        _pop_frame()
        return

    saved_path = prof.path
    try:
        prof.path = Path(PROFILE_EDIT_PATH)
        profile_io.save_profile(prof)
    except OSError as exc:
        prof.path = saved_path
        _flash_main(f"Save failed: {exc}.", C_HINT)
        _profile_editor_cleanup()
        _pop_frame()
        _pop_frame()
        return
    finally:
        prof.path = saved_path

    try:
        with open(PROFILE_EDIT_PATH, "a") as fh:
            fh.write("\n#var {_profile_load_canary} {ok}\n")
    except OSError:
        pass

    _profile_apply_status = "applying"
    if _app:
        _app.invalidate()

    _remove_sentinel(PROFILE_APPLY_RESULT)
    _send_to_game("cp -profile-apply")

    loop = asyncio.get_running_loop()

    def _finish_apply():
        result = _poll_file(PROFILE_APPLY_RESULT)
        if result == "ok":
            dropped = getattr(prof, "dropped_collisions", [])
            if dropped:
                loop.call_soon_threadsafe(
                    _flash_main,
                    core_aliases.format_dropped_message(dropped),
                    C_YELLOW)
            else:
                loop.call_soon_threadsafe(
                    _flash_main, "Profile updated.", C_ACCENT)
        else:
            msg = "Apply failed — rolled back." if result == "fail" else \
                  "Apply timed out — rolled back."
            loop.call_soon_threadsafe(_flash_main, msg, C_HINT)

        def _finish_on_main():
            _profile_editor_cleanup()
            _pop_frame()
            _pop_frame()
        loop.call_soon_threadsafe(_finish_on_main)

    threading.Thread(target=_finish_apply, daemon=True).start()


def _profile_apply_confirm_text():
    cols = _term_cols()
    if _profile_apply_status == "applying":
        msg = "Applying…"
        return [
            ("", "\n\n"),
            ("", _pad_centre(msg, cols)),
            (C_HINT, msg),
        ]
    msg  = "Apply changes to your profile?"
    hint = "Y to apply · N to discard · ESC to keep editing"
    return [
        ("", "\n\n"),
        ("", _pad_centre(msg, cols)),
        (C_SECTION, msg),
        ("", "\n\n"),
        ("", _pad_centre(hint, cols)),
        (C_HINT, hint),
    ]


# ---------------------------------------------------------------------------
# Exit-confirm frame
# ---------------------------------------------------------------------------
def _append_star_row(frags, cols):
    """Append the centred five-star rating widget to `frags`.

    First `_rate_session_rating` stars paint in gold (`_S_STAR`), the rest
    in dim grey (`C_HINT`); single-space separated, visual width 9 cells.
    Each star carries a click handler that sets the rating to its
    1-indexed position. Shared by `rate_session` and `exit_confirm`."""
    rating = max(0, min(5, _rate_session_rating))
    frags.append(("", _pad_centre("★ ★ ★ ★ ★", cols)))
    for i in range(5):
        if i > 0:
            frags.append(("", " "))
        style = _S_STAR if i < rating else C_HINT

        def _make_star_handler(val=i + 1):
            def _h(ev):
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _rate_session_rating
                _rate_session_rating = val
                if _app:
                    _app.invalidate()
            return _h

        frags.append((style, "★", _make_star_handler()))
    frags.append(("", "\n"))


def _exit_confirm_text():
    """Combined exit confirmation + optional run rating. Top to bottom:
    title, label, star row, the exit warning, footer."""
    cols   = _term_cols()
    rows_h = _term_rows()
    frags  = []

    frags.extend(title_block("─── Exit session ───", cols, blank_above=1))

    # Blank spacer, then the centred opt-in label above the star row.
    frags.append(("", "\n"))
    spacer_above_rows = 1
    label = "Rate & save this run (optional)"
    frags.append(("", _pad_centre(label, cols)))
    frags.append((C_HINT, label))
    frags.append(("", "\n"))
    label_rows = 1

    _append_star_row(frags, cols)
    star_rows = 1

    # Blank spacer, then the terminate-session warning.
    frags.append(("", "\n"))
    spacer_below_rows = 1
    warn = "Attention! This terminates the current session."
    frags.append(("", _pad_centre(warn, cols)))
    frags.append((C_ERR, warn))
    frags.append(("", "\n"))
    warn_rows = 1

    footer = "0-5 Rate · ←→ Adjust · Y Exit · ESC Cancel"
    content_rows = (title_block_height(1) + spacer_above_rows
                    + label_rows + star_rows + spacer_below_rows + warn_rows)
    frags.extend(footer_block(footer, cols, rows_h, content_rows))
    return frags


# ---------------------------------------------------------------------------
# Rate-session frame (popup "Save run" → 0..5 star rating + save)
# ---------------------------------------------------------------------------
def _rate_session_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    frags  = []

    # Title row at the top, then the Profile · Mode · Link status header
    # below it (mirrors the main frame's chrome stack).
    title = "─── Rate the run ───"
    frags.extend(title_block(title, cols, blank_above=1))

    _append_status_header(frags, cols)
    frags.append(("", "\n"))
    status_rows = 1

    # Blank above the star row for breathing space.
    frags.append(("", "\n"))
    spacer_rows = 1

    # Star row — shared widget with the exit_confirm frame.
    _append_star_row(frags, cols)
    star_rows = 1

    footer = "0-5 Set · ←→ Adjust · Enter Save · ESC Cancel"
    content_rows = title_block_height(1) + status_rows + spacer_rows + star_rows
    frags.extend(footer_block(footer, cols, rows_h, content_rows))

    return frags


def _save_run_with_rating(rating):
    """Chain-save the active run and its stitched predecessors with the
    given 0..5 `rating`. No-op when no run is being tracked. Shared by the
    rate_session Save action and the exit_confirm commit; does not touch
    frames or cursor state."""
    char = _statistics_character()
    if char is None:
        return
    run_id = run_stats.current_run_id_for(char)
    if run_id is None:
        return
    chain = run_stats.previous_run_chain(char, run_id)
    run_meta.save_run_chain(char, chain, rating)


def _rate_session_save():
    global _sel_main
    char = _statistics_character()
    if char is None:
        _pop_frame()
        return
    run_id = run_stats.current_run_id_for(char)
    if run_id is None:
        _pop_frame()
        return
    _save_run_with_rating(_rate_session_rating)
    # The row at _sel_main just turned into the dead "saved" row. Move
    # the cursor to the next selectable index so the <<>> decoration
    # doesn't vanish silently on the post-pop main frame.
    sel = _main_selectable_indices()
    if _sel_main not in sel:
        forward = [i for i in sel if i > _sel_main]
        _sel_main = forward[0] if forward else (sel[0] if sel else 0)
    _pop_frame()


# ---------------------------------------------------------------------------
# Statistics frame
# ---------------------------------------------------------------------------
_STAT_BAR_WIDTH       = 84
_STAT_Y_LABEL_W       = 5       # right-aligned y-axis label width
_STAT_TABLE_LEFT_W    = 40
_STAT_TABLE_RIGHT_W   = 40
_STAT_TABLE_GAP       = "  "
_STAT_BLOCKS          = "▁▂▃▄▅▆▇█"

# ALLIES + ACHIEVEMENTS show a fixed 3 rows each. KILLS + PvPs auto-fit the
# popup height (see _compute_kills_pvps_visible) with a 2-row minimum.
_ALLIES_ACH_VISIBLE        = 3
_KILLS_PVPS_MIN_VISIBLE    = 2
# Fixed lines around the kills/pvps data rows in _statistics_text. Counted to
# match the actual render output so the footer pins to the bottom of the popup.
# Merging the KILLS/PvPs column-header row into the title row (-1) is offset
# by the new ──┬── divider under XP/h and TP/h (+1), so the total is unchanged.
_STATS_FIXED_LINES         = 27

_stats_kills_pvps_visible  = _KILLS_PVPS_MIN_VISIBLE


def _compute_kills_pvps_visible():
    available = _term_rows() - _STATS_FIXED_LINES
    return max(_KILLS_PVPS_MIN_VISIBLE, available)


def _ensure_stats_scrollbars():
    global _kills_sb, _pkills_sb, _allies_sb, _achievements_sb
    if _kills_sb is None:
        _kills_sb        = Scrollbar(0, _KILLS_PVPS_MIN_VISIBLE, _KILLS_PVPS_MIN_VISIBLE,
                                     thumb_style=_S_THUMB, track_style=_S_TRACK)
        _pkills_sb       = Scrollbar(0, _KILLS_PVPS_MIN_VISIBLE, _KILLS_PVPS_MIN_VISIBLE,
                                     thumb_style=_S_THUMB, track_style=_S_TRACK)
        _allies_sb       = Scrollbar(0, _ALLIES_ACH_VISIBLE,     _ALLIES_ACH_VISIBLE,
                                     thumb_style=_S_THUMB, track_style=_S_TRACK)
        _achievements_sb = Scrollbar(0, _ALLIES_ACH_VISIBLE,     _ALLIES_ACH_VISIBLE,
                                     thumb_style=_S_THUMB, track_style=_S_TRACK)


def _refresh_stats_scrollbars(visible):
    global _stats_kills_pvps_visible
    if _stats_data is None or _kills_sb is None:
        return
    _stats_kills_pvps_visible = visible
    _kills_sb.update(len(_stats_data.kills),  visible, height=visible)
    _pkills_sb.update(len(_stats_data.pkills), visible, height=visible)
    _allies_sb.update(len(_stats_data.allies), _ALLIES_ACH_VISIBLE,
                      height=_ALLIES_ACH_VISIBLE)
    _achievements_sb.update(len(_stats_data.achievements), _ALLIES_ACH_VISIBLE,
                            height=_ALLIES_ACH_VISIBLE)


def _load_statistics(character):
    global _stats_data, _stats_status, _stats_char
    global _stats_kills_sort, _stats_pkills_sort, _stats_focused, _stats_run_ended
    _stats_char   = character
    _stats_status = _read_status_state()
    try:
        _stats_data = run_stats.load_current_run_stats(character)
    except Exception:
        _stats_data = None
    _stats_kills_sort  = ("XP tot", "desc")
    _stats_pkills_sort = ("XP", "desc")
    _stats_focused     = 0
    _stats_run_ended   = False
    _ensure_stats_scrollbars()
    for sb in (_kills_sb, _pkills_sb, _allies_sb, _achievements_sb):
        sb.scroll_to(0)
    _refresh_stats_scrollbars(_compute_kills_pvps_visible())


async def _stats_tick():
    """1 s refresh loop. Detects run-end-mid-view and stops itself."""
    global _stats_data, _stats_status, _stats_run_ended
    try:
        while True:
            await asyncio.sleep(1)
            if _current_frame != "statistics" or not _stats_char:
                return
            old_active = bool(_stats_data and _stats_data.is_active)
            try:
                new_stats = run_stats.load_current_run_stats(_stats_char)
            except Exception:
                new_stats = None
            if new_stats is None:
                continue
            _stats_data   = new_stats
            _stats_status = _read_status_state()
            _refresh_stats_scrollbars(_stats_kills_pvps_visible)
            if old_active and not new_stats.is_active:
                _stats_run_ended = True
                if _app:
                    _app.invalidate()
                return
            if _app:
                _app.invalidate()
    except asyncio.CancelledError:
        pass


def _start_stats_tick():
    global _stats_tick_task
    _stop_stats_tick()
    try:
        loop = asyncio.get_running_loop()
        _stats_tick_task = loop.create_task(_stats_tick())
    except RuntimeError:
        pass


def _stop_stats_tick():
    global _stats_tick_task
    if _stats_tick_task is not None:
        _stats_tick_task.cancel()
        _stats_tick_task = None


def _focused_scrollbar():
    return (_kills_sb, _pkills_sb, _allies_sb, _achievements_sb)[_stats_focused]


def _focused_visible_count():
    if _stats_focused < 2:
        return _stats_kills_pvps_visible
    return _ALLIES_ACH_VISIBLE


def _fmt_xp_short(n):
    """Mirror of fmt_xp in lua/core/run_state.lua: 1234 → '1.2k', 12345 → '12k'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k"
    return f"{n // 1000}k"


def _fmt_duration(secs):
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _bucket_event_sums(events, n_buckets, start_ts, end_ts):
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


def _sparkline_rows(values, max_val, rows=3, levels_per_row=8):
    """Render `values` as `rows` row strings, bottom-up. Each cell contributes
    up to `levels_per_row` sub-levels per row via the partial block chars."""
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
                line.append(_STAT_BLOCKS[sub - 1])
        out.append("".join(line))
    return out


def _format_kill_row(name, n, xp_per, xp_tot, width):
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


def _format_pkill_row(name, n, xp, width):
    n_col    = 3
    xp_col   = 9
    name_col = max(1, width - n_col - xp_col - 2)
    if len(name) > name_col:
        name = name[:name_col - 1] + "…"
    return f"{name.ljust(name_col)} {n.rjust(n_col)} {xp.rjust(xp_col)}"


# Cumulative career-XP thresholds, indexed by level - 1 (level 1 → index 0).
# Mirror of TABLE_XP in lua/core/level_progress.lua; keep in sync.
# stylua: ignore
_TABLE_XP = [
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


def _level_threshold(level):
    if level <= 1:
        return _TABLE_XP[0]
    if level >= 100:
        return _TABLE_XP[99]
    return _TABLE_XP[level - 1]


def _level_from_xp(xp):
    """Return the level corresponding to an absolute career-XP value.

    Level L is defined as the highest L in [1, 100] such that
    xp >= _TABLE_XP[L-1]. Clamped to [1, 100]. Non-positive xp
    returns 1."""
    if xp <= 0:
        return 1
    L = 1
    while L < 100 and xp >= _TABLE_XP[L]:
        L += 1
    return L


def _xp_to_bar_col(xp, min_lv, hi_lv, bar_w):
    """Map an absolute career-XP value to a column index in [0, bar_w].

    The bar maps level → column linearly across [min_lv, hi_lv], with XP
    interpolated linearly within each level interval (matching the
    level-marker placement)."""
    span = max(1, hi_lv - min_lv)
    if xp <= _level_threshold(min_lv):
        return 0
    if xp >= _level_threshold(hi_lv):
        return bar_w
    L = min_lv
    while L < hi_lv - 1 and xp >= _level_threshold(L + 1):
        L += 1
    lo = _level_threshold(L)
    hi = _level_threshold(L + 1)
    frac = (xp - lo) / (hi - lo) if hi > lo else 0.0
    frac = max(0.0, min(1.0, frac))
    level_pos = (L - min_lv) + frac
    return max(0, min(bar_w, int(round(level_pos / span * bar_w))))


def _append_xp_linjalen(frags, stats, cols):
    """XP-linjalen: 4 rows — gain bracket, gain bar, level markers, blank."""
    bar_w = _STAT_BAR_WIDTH
    if stats.xp_at_start is None and stats.xp_current is None:
        return
    lo_xp  = min(stats.xp_at_start, stats.xp_current)
    hi_xp  = max(stats.xp_at_start, stats.xp_current)
    min_lv = max(1,   _level_from_xp(lo_xp))
    hi_lv  = min(100, _level_from_xp(hi_xp) + 1)
    span   = max(1, hi_lv - min_lv)

    is_loss   = stats.xp_current < stats.xp_at_start
    start_col = _xp_to_bar_col(stats.xp_at_start, min_lv, hi_lv, bar_w)
    cur_col   = _xp_to_bar_col(stats.xp_current,  min_lv, hi_lv, bar_w)
    lo_col    = min(start_col, cur_col)
    hi_col    = max(start_col, cur_col)
    band_w    = hi_col - lo_col
    band_style = _S_LOSS if is_loss else _S_GAINED

    margin = max(0, (cols - bar_w) // 2)
    pad    = " " * margin

    # Row 1: ◄──<label>──► spanning the band when wide enough, else the label
    # alone, centred above the band. Arrowheads sit on the band's boundary
    # columns (▌ on lo_col, ▐ on hi_col); minimum arrow form is ◄label►. On
    # a net loss the label flips to "-N XP" and renders in _S_LOSS; brackets,
    # arrowheads, and ▬ filler keep _S_ARROW.
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

    # Row 2: the bar. Untraversed cells use █ (full-block) in track grey so
    # they fill the cell entirely — this is what the ▌/▐ markers on row 3
    # must visually merge with. The band (between lo_col and hi_col) renders
    # in _S_GAINED on net positive sessions, _S_LOSS on net negative.
    frags.append(("", pad))
    if lo_col > 0:
        frags.append((_S_TRACK, "█" * lo_col))
    if band_w > 0:
        frags.append((band_style, "█" * band_w))
    if hi_col < bar_w:
        frags.append((_S_TRACK, "█" * (bar_w - hi_col)))
    frags.append(("", "\n"))

    # Row 3: ▌ N at each boundary except the last, N ▐ on the last.
    # Half-block glyphs sit on the boundary column itself; the label flows off
    # the block. The space adjacent to the tick lives in the label fragment
    # (style _S_LABEL or empty), so the marker's dark bg stays one cell wide.
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
    # Row 3 colouring: ▌ / ▐ are half-block glyphs — setting only fg paints
    # half the cell and leaves the other half on the terminal default bg,
    # which reads visibly lighter than the row-2 full-block track cells. We
    # set both fg AND bg to the track hex (_S_MARKER) so the half-block
    # cell is filled edge-to-edge in the same grey as the row above. The
    # digit labels render in label-gray; spaces are uncoloured (so the
    # marker's dark bg does not bleed into the adjacent label cell). Group
    # consecutive same-style cells into single fragments to keep the
    # output compact.
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

    # Row 4: trailing blank line for breathing space below the linjal.
    frags.append(("", "\n"))


def _append_sparklines(frags, stats, cols):
    # Each chart fills its column above: XP/h matches KILLS, TP/h matches PvPs.
    # Chart cells: label_w (rjust) + " " + "│" + bucket_w → chart_w.
    label_w     = _STAT_Y_LABEL_W
    left_w      = _STAT_TABLE_LEFT_W
    right_w     = _STAT_TABLE_RIGHT_W
    gap         = _STAT_TABLE_GAP
    n_L         = max(1, left_w  - label_w - 2)
    n_R         = max(1, right_w - label_w - 2)
    total_w     = left_w + 1 + len(gap) + right_w + 1
    margin      = max(0, (cols - total_w) // 2)
    pad         = " " * margin

    start       = stats.start_ts
    end         = max(stats.end_ts, start + 1)
    duration    = end - start

    xp_buckets  = _bucket_event_sums(stats.kill_events, n_L, start, end)
    tp_buckets  = _bucket_event_sums(stats.tp_events,   n_R, start, end)

    xp_secs     = duration / n_L if n_L > 0 else 1
    tp_secs     = duration / n_R if n_R > 0 else 1
    if xp_secs <= 0:
        xp_secs = 1
    if tp_secs <= 0:
        tp_secs = 1
    xp_rates    = [b * 3600.0 / xp_secs for b in xp_buckets]
    tp_rates    = [b * 3600.0 / tp_secs for b in tp_buckets]

    xp_max      = max(xp_rates) if xp_rates else 0.0
    tp_max      = max(tp_rates) if tp_rates else 0.0
    xp_rows     = _sparkline_rows(xp_rates, xp_max, rows=3)
    tp_rows     = _sparkline_rows(tp_rates, tp_max, rows=3)

    # Title row.
    frags.append(("", pad))
    frags.append((C_SECTION, "XP/h".ljust(left_w)))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_SECTION, "TP/h".ljust(right_w)))
    frags.append(("", " "))
    frags.append(("", "\n"))

    # Divider rule with ┬ at the column where the chart's │ axis sits (and
    # where the └ on the bottom rule lands), so the chart frame closes
    # cleanly: ──┬── above, │ down the middle, └── below.
    junction = label_w + 1
    left_rule  = "─" * junction + "┬" + "─" * max(0, left_w  - junction - 1)
    right_rule = "─" * junction + "┬" + "─" * max(0, right_w - junction - 1)
    frags.append(("", pad))
    frags.append((C_DIVIDER, left_rule))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_DIVIDER, right_rule))
    frags.append(("", " "))
    frags.append(("", "\n"))

    xp_labels = [_fmt_xp_short(xp_max), _fmt_xp_short(xp_max / 2), "0"]
    tp_labels = [_fmt_xp_short(tp_max), _fmt_xp_short(tp_max / 2), "0"]

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

    # Bottom rule: └────
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

    # X-axis labels (00:00 … duration), each sitting under its bucket row.
    chart_indent = " " * (label_w + 2)
    x_left       = "00:00"
    x_right      = _fmt_duration(duration)[:5]
    fill_L       = max(1, n_L - len(x_left) - len(x_right))
    fill_R       = max(1, n_R - len(x_left) - len(x_right))
    frags.append(("", pad))
    frags.append(("", chart_indent))
    frags.append((_S_LABEL, x_left + (" " * fill_L) + x_right))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append(("", chart_indent))
    frags.append((_S_LABEL, x_left + (" " * fill_R) + x_right))
    frags.append(("", " "))
    frags.append(("", "\n"))


def _stats_wheel_scroll(table_idx, delta):
    """Scroll the table at `table_idx` by `delta` rows (the keyboard step)
    and move keyboard focus to it. Mirrors the click-sets-focus behaviour
    on the wheel surface so wheel scrolling always tracks the table the
    user is interacting with."""
    global _stats_focused
    sbs = (_kills_sb, _pkills_sb, _allies_sb, _achievements_sb)
    sb = sbs[table_idx]
    if sb is None:
        return
    _stats_focused = table_idx
    sb.scroll_by(delta)
    if _app:
        _app.invalidate()


def _make_focus_handler(idx):
    def _handler(ev):
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            global _stats_focused
            _stats_focused = idx
            if _app:
                _app.invalidate()
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            _stats_wheel_scroll(idx, -1)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _stats_wheel_scroll(idx, 1)
            return None
        return NotImplemented
    return _handler


def _scrollbar_row_cells(sb, table_idx):
    """Render `sb` and return one fragment per row (newlines stripped).

    Wraps each cell handler so a click also moves keyboard focus to this
    table, and so the wheel scrolls this table (matching the click-sets-
    focus behaviour on the table proper).
    """
    out = []
    for f in sb.render():
        if len(f) >= 2 and f[1] == "\n":
            continue
        if len(f) == 3:
            style, text, orig = f

            def _wrapped(ev, orig=orig, idx=table_idx):
                if ev.event_type == MouseEventType.SCROLL_UP:
                    _stats_wheel_scroll(idx, -1)
                    return None
                if ev.event_type == MouseEventType.SCROLL_DOWN:
                    _stats_wheel_scroll(idx, 1)
                    return None
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    global _stats_focused
                    _stats_focused = idx
                return orig(ev)

            out.append((style, text, _wrapped))
        else:
            style, text = f[0], f[1]
            out.append((style, text, _make_focus_handler(table_idx)))
    return out


def _default_sort_dir(col):
    return "asc" if col in ("Mob", "Player") else "desc"


def _toggle_sort(state_tuple, col):
    cur_col, cur_dir = state_tuple
    if col == cur_col:
        return (col, "asc" if cur_dir == "desc" else "desc")
    return (col, _default_sort_dir(col))


def _make_kill_header_handler(col):
    def _h(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            _stats_wheel_scroll(0, -1)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _stats_wheel_scroll(0, 1)
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        global _stats_kills_sort, _stats_focused
        _stats_focused = 0
        _stats_kills_sort = _toggle_sort(_stats_kills_sort, col)
        _kills_sb.scroll_to(0)
        if _app:
            _app.invalidate()
        return None
    return _h


def _make_pkill_header_handler(col):
    def _h(ev):
        if ev.event_type == MouseEventType.SCROLL_UP:
            _stats_wheel_scroll(1, -1)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            _stats_wheel_scroll(1, 1)
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        global _stats_pkills_sort, _stats_focused
        _stats_focused = 1
        _stats_pkills_sort = _toggle_sort(_stats_pkills_sort, col)
        _pkills_sb.scroll_to(0)
        if _app:
            _app.invalidate()
        return None
    return _h


def _sorted_kills_items(kills_dict, sort_col, sort_dir):
    keys = {
        "Mob":    lambda kv: kv[0].lower(),
        "N":      lambda kv: kv[1].count,
        "XP/N":   lambda kv: (kv[1].total_xp // kv[1].count) if kv[1].count else 0,
        "XP tot": lambda kv: kv[1].total_xp,
    }
    items = list(kills_dict.items())
    items.sort(key=keys.get(sort_col, keys["XP tot"]), reverse=(sort_dir == "desc"))
    return items


def _sorted_pkills_items(pkills_dict, sort_col, sort_dir):
    keys = {
        "Player": lambda kv: kv[0].lower(),
        "N":      lambda kv: kv[1].count,
        "XP":     lambda kv: kv[1].total_xp,
    }
    items = list(pkills_dict.items())
    items.sort(key=keys.get(sort_col, keys["XP"]), reverse=(sort_dir == "desc"))
    return items


def _header_label(base, is_active, sort_dir, align, width):
    txt = base
    if is_active:
        txt += " ▼" if sort_dir == "desc" else " ▲"
    if align == "left":
        return txt[:width].ljust(width)
    return txt[:width].rjust(width)


def _section_title_pair(frags, left_title, right_title, left_w, right_w, gap, pad,
                         left_active=False, right_active=False,
                         left_focus=None, right_focus=None):
    """Two side-by-side section titles, each with a divider rule under it."""
    l_style = C_CURSOR_CELL if left_active else C_SECTION
    r_style = C_CURSOR_CELL if right_active else C_SECTION

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


def _append_kills_pvps(frags, stats, cols, visible):
    left_w  = _STAT_TABLE_LEFT_W
    right_w = _STAT_TABLE_RIGHT_W
    gap     = _STAT_TABLE_GAP
    # +2 reserves one column on each side for the per-table scrollbar strip.
    total_w = left_w + 1 + len(gap) + right_w + 1
    margin  = max(0, (cols - total_w) // 2)
    pad     = " " * margin

    k_focus = _make_focus_handler(0)
    p_focus = _make_focus_handler(1)

    sort_col_k, sort_dir_k   = _stats_kills_sort
    sort_col_pk, sort_dir_pk = _stats_pkills_sort

    # Column geometry matches _format_kill_row / _format_pkill_row exactly so
    # title-row labels sit above their data columns.
    n_col, xp_per_col, xp_tot_col = 3, 7, 9
    k_name_col = max(1, left_w  - n_col - xp_per_col - xp_tot_col - 3)
    pk_xp_col  = 9
    p_name_col = max(1, right_w - n_col - pk_xp_col - 2)

    k_active = (_stats_focused == 0)
    p_active = (_stats_focused == 1)
    k_style  = C_CURSOR_CELL if k_active else C_SECTION
    p_style  = C_CURSOR_CELL if p_active else C_SECTION

    # Merged title row: section name in the name-column slot (clickable to
    # sort by name), then N / XP/N / XP tot (or N / XP) in their data-column
    # positions. The entire row paints en bloc in k_style / p_style; the
    # active sort indicator just changes the glyph after the label.
    k_title = _header_label("KILLS", sort_col_k  == "Mob",    sort_dir_k,  "left", k_name_col)
    p_title = _header_label("PvPs",  sort_col_pk == "Player", sort_dir_pk, "left", p_name_col)

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
    frags.append((k_style, k_title, _make_kill_header_handler("Mob")))
    for col, align, w in k_data_cols:
        h     = _make_kill_header_handler(col)
        label = _header_label(col, col == sort_col_k, sort_dir_k, align, w)
        frags.append((k_style, " ", h))
        frags.append((k_style, label, h))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((p_style, p_title, _make_pkill_header_handler("Player")))
    for col, align, w in p_data_cols:
        h     = _make_pkill_header_handler(col)
        label = _header_label(col, col == sort_col_pk, sort_dir_pk, align, w)
        frags.append((p_style, " ", h))
        frags.append((p_style, label, h))
    frags.append(("", " "))
    frags.append(("", "\n"))

    # Divider rule beneath the title row, full column width.
    frags.append(("", pad))
    frags.append((C_DIVIDER, "─" * left_w))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((C_DIVIDER, "─" * right_w))
    frags.append(("", " "))
    frags.append(("", "\n"))

    kills_items  = _sorted_kills_items(stats.kills,  sort_col_k,  sort_dir_k)
    pkills_items = _sorted_pkills_items(stats.pkills, sort_col_pk, sort_dir_pk)

    k_off  = _kills_sb.scroll_offset
    pk_off = _pkills_sb.scroll_offset
    k_view = kills_items[k_off:k_off + visible]
    p_view = pkills_items[pk_off:pk_off + visible]

    k_sb_cells = _scrollbar_row_cells(_kills_sb,  0)
    p_sb_cells = _scrollbar_row_cells(_pkills_sb, 1)

    # PvPs row geometry: ⚔ + space are absorbed into the name column's left
    # padding so the N / XP columns and the right edge stay put.
    pk_n_col      = 3
    pk_xp_col_w   = 9
    pk_name_col   = max(1, right_w - pk_n_col - pk_xp_col_w - 2)
    pk_inner_name = max(1, pk_name_col - 2)

    for i in range(visible):
        if i < len(k_view):
            name, agg = k_view[i]
            avg = agg.total_xp // agg.count if agg.count else 0
            k_line = _format_kill_row(name, str(agg.count), str(avg), str(agg.total_xp), left_w)
        else:
            k_line = " " * left_w

        frags.append(("", pad))
        frags.append((_S_LABEL, k_line, k_focus))
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
            frags.append((_S_LABEL, " " * right_w, p_focus))
        if i < len(p_sb_cells):
            frags.append(p_sb_cells[i])
        else:
            frags.append(("", " "))
        frags.append(("", "\n"))

    # Sticky total row.
    k_cnt = sum(a.count for a in stats.kills.values())
    k_xp  = sum(a.total_xp for a in stats.kills.values())
    k_avg = k_xp // k_cnt if k_cnt else 0
    p_cnt = sum(a.count for a in stats.pkills.values())
    p_xp  = sum(a.total_xp for a in stats.pkills.values())

    k_total  = _format_kill_row("Total",  str(k_cnt), str(k_avg), str(k_xp), left_w)
    pk_total = _format_pkill_row("Total", str(p_cnt), str(p_xp), right_w)
    frags.append(("", pad))
    frags.append((_S_TOTAL, k_total, k_focus))
    frags.append(("", " "))
    frags.append(("", gap))
    frags.append((_S_TOTAL, pk_total, p_focus))
    frags.append(("", " "))
    frags.append(("", "\n"))


def _append_allies_achievements(frags, stats, cols):
    left_w  = _STAT_TABLE_LEFT_W
    right_w = _STAT_TABLE_RIGHT_W
    gap     = _STAT_TABLE_GAP
    total_w = left_w + 1 + len(gap) + right_w + 1
    margin  = max(0, (cols - total_w) // 2)
    pad     = " " * margin

    a_focus = _make_focus_handler(2)
    h_focus = _make_focus_handler(3)

    _section_title_pair(
        frags, "ALLIES", "ACHIEVEMENTS", left_w, right_w, gap, pad,
        left_active=(_stats_focused == 2),
        right_active=(_stats_focused == 3),
        left_focus=a_focus, right_focus=h_focus,
    )

    ally_rows = list(stats.allies)
    ach_rows  = [a[1] for a in stats.achievements]

    a_off  = _allies_sb.scroll_offset
    h_off  = _achievements_sb.scroll_offset
    a_view = ally_rows[a_off:a_off + _ALLIES_ACH_VISIBLE]
    h_view = ach_rows[h_off:h_off + _ALLIES_ACH_VISIBLE]

    a_sb_cells = _scrollbar_row_cells(_allies_sb,       2)
    h_sb_cells = _scrollbar_row_cells(_achievements_sb, 3)

    # ♦ / ★ glyphs + space are absorbed into the name column's left padding so
    # the right edges of both tables stay put.
    a_inner_w = max(1, left_w  - 2)
    h_inner_w = max(1, right_w - 2)
    for i in range(_ALLIES_ACH_VISIBLE):
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


def _statistics_text():
    cols   = _term_cols()
    stats  = _stats_data
    status = _stats_status or {}

    if stats is None or not _stats_char:
        msg  = "No run data available."
        hint = "ESC Back"
        return [
            ("", "\n\n"),
            ("", _pad_centre(msg, cols)),
            (C_ERR, msg),
            ("", "\n\n"),
            ("", _pad_centre(hint, cols)),
            (_S_HINT, hint),
        ]

    # Auto-fit KILLS/PvPs to the popup height; update both scrollbars so the
    # thumb geometry matches the rendered row count.
    visible = _compute_kills_pvps_visible()
    _refresh_stats_scrollbars(visible)

    frags = []

    if stats.xp_current and stats.xp_current > 0:
        cur_lv = _level_from_xp(stats.xp_current)
    else:
        cur_lv = status.get("level", "?")
    base_header = (
        f"◆ STATISTICS  —  {_stats_char}  "
        f"·  Lvl {cur_lv}  ·  Run {_fmt_duration(stats.duration_seconds)}"
    )
    suffix = " · Run ended" if _stats_run_ended else ""

    stars = ""
    if stats.saved and stats.rating is not None:
        r = max(0, min(5, stats.rating))
        if r > 0:
            stars = "★" * r

    rating_sep  = " · " if stars else ""
    title_for_centering = base_header + suffix + rating_sep + stars

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(title_for_centering, cols)))
    frags.append((_S_HINT, base_header))
    if suffix:
        frags.append((_S_HINT, suffix))
    if stars:
        frags.append((_S_HINT, rating_sep + stars))
    frags.append(("", "\n\n"))

    _append_allies_achievements(frags, stats, cols)
    frags.append(("", "\n"))

    _append_kills_pvps(frags, stats, cols, visible)
    frags.append(("", "\n"))

    _append_sparklines(frags, stats, cols)
    frags.append(("", "\n"))

    _append_xp_linjalen(frags, stats, cols)

    footer = "ESC Back · ↑↓ Scroll · Tab/Shift+Tab Switch table"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((_S_HINT, footer))

    return frags




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
    sel = _main_selectable_indices()
    if not sel:
        return
    pos = sel.index(_sel_main) if _sel_main in sel else 0
    _sel_main = sel[(pos - 1) % len(sel)]


@kb.add("down", filter=_in_frame("main"))
def _main_down(event):
    global _sel_main
    sel = _main_selectable_indices()
    if not sel:
        return
    pos = sel.index(_sel_main) if _sel_main in sel else 0
    _sel_main = sel[(pos + 1) % len(sel)]


@kb.add("enter", filter=_in_frame("main"))
@kb.add(" ",     filter=_in_frame("main"))
def _main_select(event):
    items = _main_items()
    sel   = _main_selectable_indices()
    if not sel:
        return
    idx = _sel_main if _sel_main in sel else sel[0]
    if 0 <= idx < len(items):
        _activate_main_item(items[idx][1])


@kb.add("escape", filter=_in_frame("main"), eager=True)
def _main_escape(event):
    event.app.exit()


# Options frame (Panes / Scripts / Back)
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


# Panes hub (thin index: General / Timers / Back).
@kb.add("up", filter=_in_frame("panes"))
def _panes_hub_up(event):
    global _sel_panes
    n = len(_panes_selectable_indices())
    if n:
        _sel_panes = (_sel_panes - 1) % n


@kb.add("down", filter=_in_frame("panes"))
def _panes_hub_down(event):
    global _sel_panes
    n = len(_panes_selectable_indices())
    if n:
        _sel_panes = (_sel_panes + 1) % n


@kb.add("enter", filter=_in_frame("panes"))
@kb.add(" ",     filter=_in_frame("panes"))
def _panes_hub_select(event):
    sel_indices = _panes_selectable_indices()
    if not sel_indices:
        return
    idx = _sel_panes if _sel_panes < len(sel_indices) else len(sel_indices) - 1
    _panes_activate(sel_indices[idx])


@kb.add("escape", filter=_in_frame("panes"), eager=True)
def _panes_hub_escape(event):
    _pop_frame()


# Panes → General frame (colour grid). Eight navigable rows; ←/→ moves the
# column only on grid rows, persisting across grid rows.
@kb.add("up", filter=_in_frame("panes_general"))
def _panes_up(event):
    if _panes_general_row > 0:
        _set_panes_cursor(_panes_general_row - 1)


@kb.add("down", filter=_in_frame("panes_general"))
def _panes_down(event):
    if _panes_general_row < _PANES_LAST_ROW:
        _set_panes_cursor(_panes_general_row + 1)


@kb.add("left", filter=_in_frame("panes_general"))
def _panes_left(event):
    if _panes_general_row < _PANES_GRID_ROWS and _panes_general_col > 0:
        _set_panes_cursor(_panes_general_row, _panes_general_col - 1)


@kb.add("right", filter=_in_frame("panes_general"))
def _panes_right(event):
    if _panes_general_row < _PANES_GRID_ROWS and _panes_general_col < _PANES_LAST_COL:
        _set_panes_cursor(_panes_general_row, _panes_general_col + 1)


@kb.add("enter", filter=_in_frame("panes_general"))
@kb.add(" ",     filter=_in_frame("panes_general"))
def _panes_select(event):
    r = _panes_general_row
    if r < _PANES_GRID_ROWS:
        _apply_panes_grid_toggle(r, _panes_general_col)
    elif r == _PANES_HEADERS_ROW:
        _toggle_pane_headers()
    elif r == _PANES_BACK_ROW:
        _pop_frame()


@kb.add("escape", filter=_in_frame("panes_general"), eager=True)
def _panes_escape(event):
    _pop_frame()


# Panes → Communication frame (per-channel on/off list). Twelve navigable
# rows: 0..9 channels, row 10 the header toggle, row 11 Back.
@kb.add("up", filter=_in_frame("panes_communication"))
def _panes_comm_up(event):
    if _panes_comm_row > 0:
        _set_comm_cursor(_panes_comm_row - 1)


@kb.add("down", filter=_in_frame("panes_communication"))
def _panes_comm_down(event):
    if _panes_comm_row < _COMM_LAST_ROW:
        _set_comm_cursor(_panes_comm_row + 1)


@kb.add("enter", filter=_in_frame("panes_communication"))
@kb.add(" ",     filter=_in_frame("panes_communication"))
def _panes_comm_select(event):
    r = _panes_comm_row
    if r < _COMM_CHANNEL_ROWS:
        _toggle_comm_channel(r)
    elif r == _COMM_HEADER_ROW:
        _toggle_comm_header()
    elif r == _COMM_BACK_ROW:
        _pop_frame()


@kb.add("escape", filter=_in_frame("panes_communication"), eager=True)
def _panes_comm_escape(event):
    _pop_frame()


# Timers-layout frame (group × colour grid + per-row column stepper).
# Seven navigable rows; ←/→ moves the column only on grid rows, persisting
# across grid rows. Colour cols 0..N-1; ◄ at N; ► at N+1.
@kb.add("up", filter=_in_frame("timers"))
def _timers_up(event):
    if _timers_row > 0:
        _set_timers_cursor(_timers_row - 1)


@kb.add("down", filter=_in_frame("timers"))
def _timers_down(event):
    if _timers_row < _TIMERS_LAST_ROW:
        _set_timers_cursor(_timers_row + 1)


@kb.add("left", filter=_in_frame("timers"))
def _timers_left(event):
    if _timers_row < _TIMERS_GRID_ROWS and _timers_col > 0:
        _set_timers_cursor(_timers_row, _timers_col - 1)


@kb.add("right", filter=_in_frame("timers"))
def _timers_right(event):
    if _timers_row < _TIMERS_GRID_ROWS and _timers_col < _TIMERS_LAST_COL:
        _set_timers_cursor(_timers_row, _timers_col + 1)


@kb.add("enter", filter=_in_frame("timers"))
@kb.add(" ",     filter=_in_frame("timers"))
def _timers_select(event):
    r = _timers_row
    if r < _TIMERS_GRID_ROWS:
        n = len(TIMERS_COLOR_ORDER)
        if _timers_col < n:
            _apply_timers_grid_toggle(r, _timers_col)
        elif _timers_col == n:
            _apply_timers_step(r, -1)
        elif _timers_col == n + 1:
            _apply_timers_step(r, +1)
    elif r == _TIMERS_HEADERS_ROW:
        _toggle_timers_headers()
    elif r == _TIMERS_COMPACT_ROW:
        _toggle_timers_compact()
    elif r == _TIMERS_BACK_ROW:
        _pop_frame()


@kb.add("escape", filter=_in_frame("timers"), eager=True)
def _timers_escape(event):
    _pop_frame()


# Scripts frame — two-column view with browse cursor + in-column Back.
# Up/Down steps through script rows and Back (mirrors the launcher);
# PageUp/PageDown scrolls the detail panel (keyboard-only — the popup
# intentionally has no mouse-wheel binding). Enter on Back pops; on a
# script row it is a no-op (the popup is read-only).
@kb.add("up", filter=_in_frame("scripts"))
def _scr_up(event):
    _scripts_move_up()


@kb.add("down", filter=_in_frame("scripts"))
def _scr_down(event):
    _scripts_move_down()


@kb.add("pageup", filter=_in_frame("scripts"))
def _scr_pageup(event):
    _scripts_scroll_detail(-_scripts_visible_rows())


@kb.add("pagedown", filter=_in_frame("scripts"))
def _scr_pagedown(event):
    _scripts_scroll_detail(_scripts_visible_rows())


@kb.add("home", filter=_in_frame("scripts"))
def _scr_home(event):
    if _scripts_catalog:
        _scripts_select_row(0)


@kb.add("end", filter=_in_frame("scripts"))
def _scr_end(event):
    n = len(_scripts_catalog)
    if n:
        _scripts_select_row(n - 1)


@kb.add("enter", filter=_in_frame("scripts"))
def _scr_enter(event):
    if _scripts_on_back:
        _pop_frame()


@kb.add("escape", filter=_in_frame("scripts"), eager=True)
def _scr_escape(event):
    _pop_frame()


# Readability frame — interactive two-column view. Up/Down steps through
# module rows and Back; PageUp/PageDown scrolls the detail panel; Space
# and Enter toggle or activate Back (save-and-pop). ESC always routes
# through save-and-pop so dirty state is never silently discarded.
@kb.add("up", filter=_in_frame("readability"))
def _rdbl_up(event):
    _readability_move_up()


@kb.add("down", filter=_in_frame("readability"))
def _rdbl_down(event):
    _readability_move_down()


@kb.add("pageup", filter=_in_frame("readability"))
def _rdbl_pageup(event):
    _readability_scroll_detail(-_readability_visible_rows())


@kb.add("pagedown", filter=_in_frame("readability"))
def _rdbl_pagedown(event):
    _readability_scroll_detail(_readability_visible_rows())


@kb.add("enter", filter=_in_frame("readability"))
@kb.add(" ",     filter=_in_frame("readability"))
def _rdbl_activate(event):
    _readability_activate_cursor()


@kb.add("escape", filter=_in_frame("readability"), eager=True)
def _rdbl_escape(event):
    _readability_save_and_pop()


# Statistics frame
@kb.add("escape", filter=_in_frame("statistics"), eager=True)
def _stat_escape(event):
    _stop_stats_tick()
    _pop_frame()


@kb.add("up", filter=_in_frame("statistics"))
def _stat_up(event):
    if _kills_sb is None:
        return
    _focused_scrollbar().scroll_by(-1)
    if _app:
        _app.invalidate()


@kb.add("down", filter=_in_frame("statistics"))
def _stat_down(event):
    if _kills_sb is None:
        return
    _focused_scrollbar().scroll_by(1)
    if _app:
        _app.invalidate()


@kb.add("pageup", filter=_in_frame("statistics"))
def _stat_pgup(event):
    if _kills_sb is None:
        return
    _focused_scrollbar().scroll_by(-_focused_visible_count())
    if _app:
        _app.invalidate()


@kb.add("pagedown", filter=_in_frame("statistics"))
def _stat_pgdn(event):
    if _kills_sb is None:
        return
    _focused_scrollbar().scroll_by(_focused_visible_count())
    if _app:
        _app.invalidate()


@kb.add("tab", filter=_in_frame("statistics"))
def _stat_tab(event):
    global _stats_focused
    _stats_focused = (_stats_focused + 1) % 4
    if _app:
        _app.invalidate()


@kb.add("s-tab", filter=_in_frame("statistics"))
def _stat_stab(event):
    global _stats_focused
    _stats_focused = (_stats_focused - 1) % 4
    if _app:
        _app.invalidate()


# Rate-session frame
for _n in range(6):
    def _make_rs_digit(val=_n):
        def _h(event):
            global _rate_session_rating
            _rate_session_rating = val
            if _app:
                _app.invalidate()
        return _h
    kb.add(str(_n), filter=_in_frame("rate_session"))(_make_rs_digit())
del _n


@kb.add("left", filter=_in_frame("rate_session"))
def _rs_left(event):
    global _rate_session_rating
    _rate_session_rating = max(0, _rate_session_rating - 1)
    if _app:
        _app.invalidate()


@kb.add("right", filter=_in_frame("rate_session"))
def _rs_right(event):
    global _rate_session_rating
    _rate_session_rating = min(5, _rate_session_rating + 1)
    if _app:
        _app.invalidate()


@kb.add("enter", filter=_in_frame("rate_session"))
@kb.add(" ",     filter=_in_frame("rate_session"))
def _rs_save(event):
    _rate_session_save()


@kb.add("escape", filter=_in_frame("rate_session"), eager=True)
def _rs_escape(event):
    _pop_frame()


# Exit-confirm frame — combined exit + optional rating. No `<any>`
# catch-all cancel: 0..5 are now rating keys, so only ESC cancels.
for _n in range(6):
    def _make_ec_digit(val=_n):
        def _h(event):
            global _rate_session_rating
            _rate_session_rating = val
            if _app:
                _app.invalidate()
        return _h
    kb.add(str(_n), filter=_in_frame("exit_confirm"))(_make_ec_digit())
del _n


@kb.add("left", filter=_in_frame("exit_confirm"))
def _ec_left(event):
    global _rate_session_rating
    _rate_session_rating = max(0, _rate_session_rating - 1)
    if _app:
        _app.invalidate()


@kb.add("right", filter=_in_frame("exit_confirm"))
def _ec_right(event):
    global _rate_session_rating
    _rate_session_rating = min(5, _rate_session_rating + 1)
    if _app:
        _app.invalidate()


@kb.add("y", filter=_in_frame("exit_confirm"))
@kb.add("Y", filter=_in_frame("exit_confirm"))
def _ec_confirm(event):
    # Save first (synchronous sidecar writes), then exit. A 0-star rating
    # never saves — exit never un-saves a previously-saved run.
    if _rate_session_rating > 0:
        _save_run_with_rating(_rate_session_rating)
    _write_sentinel(RETURN_TO_MENU_SENT)
    _send_to_game("cp -e")
    event.app.exit()


@kb.add("escape", filter=_in_frame("exit_confirm"), eager=True)
def _ec_escape(event):
    _pop_frame()


# Profile apply-confirm frame (Y / N / ESC)
@kb.add("y", filter=_in_frame("profile_apply_confirm"))
@kb.add("Y", filter=_in_frame("profile_apply_confirm"))
def _pac_confirm(event):
    if _profile_apply_status == "applying":
        return
    _apply_profile_connected()


@kb.add("n", filter=_in_frame("profile_apply_confirm"))
@kb.add("N", filter=_in_frame("profile_apply_confirm"))
def _pac_discard(event):
    if _profile_apply_status == "applying":
        return
    _profile_editor_cleanup()
    _pop_frame()
    _pop_frame()


@kb.add("escape", filter=_in_frame("profile_apply_confirm"), eager=True)
def _pac_escape(event):
    if _profile_apply_status == "applying":
        return
    _pop_frame()


@kb.add("<any>", filter=_in_frame("profile_apply_confirm"))
def _pac_any(event):
    pass


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
    for p in (PROFILE_SNAPSHOT_PATH, PROFILE_EDIT_PATH,
              PROFILE_SNAP_RESULT, PROFILE_APPLY_RESULT):
        _remove_sentinel(p)


def _signal_exit(signum, frame):
    _cleanup()
    sys.exit(0)


# ---------------------------------------------------------------------------
# Layout / main
# ---------------------------------------------------------------------------
def _build_main_container():
    global _main_window
    # focusable=False + always_hide_cursor so the terminal cursor doesn't
    # blink on the main frame (submenus already use focusable=False FTCs).
    _main_window = Window(
        content=FormattedTextControl(text=_main_text, focusable=False),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _main_window


def _build_options_container():
    global _options_window
    # Single FormattedTextControl Window — the frame emits the title
    # block, menu rows, and footer as one fragment list; footer_block
    # pads the trailing rows so the footer lands at the bottom of the
    # popup. Mirrors the launcher's `_build_simple` for Options.
    _options_window = Window(
        content=FormattedTextControl(text=_options_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _options_window


def _build_panes_general_container():
    global _panes_general_window
    # Single FormattedTextControl Window — the grid frame emits the title
    # block, grid, controls and footer as one fragment list and footer_block
    # pads the trailing rows so the footer lands at the bottom of the popup.
    _panes_general_window = Window(
        content=FormattedTextControl(text=_panes_general_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _panes_general_window


# ---------------------------------------------------------------------------
# Panes → Communication frame (Options → Panes → Communication): channel list.
# ---------------------------------------------------------------------------
# One row per comm channel, each with its colour swatch and a [X]/[ ]
# reflecting comm_filters.conf (sparse; missing key = enabled). Below the
# list hang a blank, a [X] Show channel header toggle (writes comm_prefs.conf),
# a blank, and Back. Cursor-only frame (no separate hover index).
#
# Persistence is immediate: each toggle reads the relevant conf, flips, and
# writes it back via comm_channels, and the render re-reads every frame — so
# the popup never clobbers a concurrent comm-pane header click. There is no
# live re-read in the comm pane yet (Phase 2); changes land on the next pane
# start. Render / toggle / persistence all go through comm_channels.
_COMM_CHANNEL_ROWS = len(comm_channels.CHANNEL_ORDER)   # 10
_COMM_HEADER_ROW   = _COMM_CHANNEL_ROWS                 # 10
_COMM_BACK_ROW     = _COMM_CHANNEL_ROWS + 1             # 11
_COMM_LAST_ROW     = _COMM_BACK_ROW


def _set_comm_cursor(row):
    """Update the popup communication-list cursor; invalidate on change."""
    global _panes_comm_row
    if row != _panes_comm_row:
        _panes_comm_row = row
        if _app:
            _app.invalidate()


def _toggle_comm_channel(row):
    """Flip the channel at list row `row`: read, flip, write comm_filters.conf."""
    name = comm_channels.CHANNEL_ORDER[row]
    filters = comm_channels.read_filters()
    comm_channels.toggle_channel(filters, name)
    comm_channels.write_filters(filters)
    if _app:
        _app.invalidate()


def _toggle_comm_header():
    """Flip show_header and persist comm_prefs.conf immediately."""
    comm_channels.write_show_header(
        comm_channels.toggle_header(comm_channels.read_show_header()),
    )
    if _app:
        _app.invalidate()


def _panes_communication_text():
    cols   = _term_cols()
    rows_h = _term_rows()

    # Live state: re-read both conf files every render so external edits show.
    rows         = comm_channels.channel_rows(comm_channels.read_filters())
    show_header  = comm_channels.read_show_header()

    cur_row = _panes_comm_row
    list_cursor = cur_row if cur_row < _COMM_CHANNEL_ROWS else None

    header_label = f"[{'X' if show_header else ' '}] Show channel header"
    back_label   = "Back"

    frags = []
    frags.extend(title_block("─── Communication ───", cols, blank_above=1))

    def _make_row_handler(ri):
        def _h(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                _set_comm_cursor(ri)
                return
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _set_comm_cursor(ri)
                _toggle_comm_channel(ri)
        return _h

    frags.extend(comm_channels.comm_channels_fragments(
        rows, cols, list_cursor, row_handler=_make_row_handler,
    ))

    frags.append(("", "\n"))

    # Show channel header — single << label >> toggle, centred per row.
    state_h = "selected" if cur_row == _COMM_HEADER_ROW else "inactive"

    def _header_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_comm_cursor(_COMM_HEADER_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _set_comm_cursor(_COMM_HEADER_ROW)
            _toggle_comm_header()

    pad_h = max(0, (cols - (len(header_label) + 6)) // 2)
    frags.append(("", " " * pad_h))
    frags.extend(menu_row(header_label, state_h, mouse_handler=_header_handler))
    frags.append(("", "\n"))

    frags.append(("", "\n"))

    # Back — plain << label >> row, centred per row.
    state_b = "selected" if cur_row == _COMM_BACK_ROW else "inactive"

    def _back_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_comm_cursor(_COMM_BACK_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _pop_frame()

    pad_b = max(0, (cols - (len(back_label) + 6)) // 2)
    frags.append(("", " " * pad_b))
    frags.extend(menu_row(back_label, state_b, mouse_handler=_back_handler))
    frags.append(("", "\n"))

    # title block (3 rows for popup) + 10 channel rows + blank + header
    # + blank + Back (4 rows).
    content_rows = title_block_height(1) + _COMM_CHANNEL_ROWS + 4
    footer = "↑↓ Move · Enter Toggle · ESC Back"
    frags.extend(footer_block(footer, cols, rows_h, content_rows))

    return frags


def _build_panes_communication_container():
    global _panes_communication_window
    _panes_communication_window = Window(
        content=FormattedTextControl(text=_panes_communication_text,
                                     focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _panes_communication_window


def _timers_text():
    cols   = _term_cols()
    rows_h = _term_rows()

    # Live grid state: re-read timers_layout.conf every render so external
    # edits (or this menu's own writes) show up immediately.
    layout = _read_timers_layout()
    grid_rows = []
    for typ in TIMERS_LAYOUT_TYPES:
        cur = layout[typ]
        grid_rows.append((
            TIMERS_LAYOUT_LABELS[typ],
            cur["enabled"],
            timers_color_index(cur["color"]),
            cur["cols"],
            max_cols_for(typ),
        ))

    cur_row = _timers_row
    cur_col = _timers_col
    grid_cursor = (cur_row, cur_col) if cur_row < _TIMERS_GRID_ROWS else None

    back_label = "Back"

    frags = []
    frags.extend(title_block("─── Timers layout ───", cols, blank_above=1))

    def _make_cell_handler(ri, ci):
        def _h(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                _set_timers_cursor(ri, ci)
                return
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _set_timers_cursor(ri, ci)
                _apply_timers_grid_toggle(ri, ci)
        return _h

    def _make_stepper_handler(ri, delta):
        col = (len(TIMERS_COLOR_ORDER) if delta < 0
               else len(TIMERS_COLOR_ORDER) + 1)

        def _h(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                _set_timers_cursor(ri, col)
                return
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _set_timers_cursor(ri, col)
                _apply_timers_step(ri, delta)
        return _h

    frags.extend(timers_grid_fragments(
        grid_rows, cols, grid_cursor,
        cell_handler=_make_cell_handler,
        stepper_handler=_make_stepper_handler,
    ))

    frags.append(("", "\n"))

    # Display headers + Compact layout — two << label >> toggles that form
    # one centred block. Both composed labels are left-padded to a shared
    # label_col_w and the block (label_col_w + 6) is centred as a unit, so
    # the leading `[X]` glyphs stack vertically. Checked headers = group
    # headers shown; checked compact = no blank lines between groups.
    headers_on    = layout["headers"]
    compact_on    = layout["compact"]
    headers_label = f"[{'X' if headers_on else ' '}] Display headers"
    compact_label = f"[{'X' if compact_on else ' '}] Compact layout"
    label_col_w   = max(len(headers_label), len(compact_label))
    block_left    = max(0, (cols - (label_col_w + 6)) // 2)

    state_c = "selected" if cur_row == _TIMERS_HEADERS_ROW else "inactive"

    def _headers_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_timers_cursor(_TIMERS_HEADERS_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _set_timers_cursor(_TIMERS_HEADERS_ROW)
            _toggle_timers_headers()

    frags.append(("", " " * block_left))
    frags.extend(menu_row(
        headers_label.ljust(label_col_w), state_c,
        mouse_handler=_headers_handler,
    ))
    frags.append(("", "\n"))

    state_cp = "selected" if cur_row == _TIMERS_COMPACT_ROW else "inactive"

    def _compact_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_timers_cursor(_TIMERS_COMPACT_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _set_timers_cursor(_TIMERS_COMPACT_ROW)
            _toggle_timers_compact()

    frags.append(("", " " * block_left))
    frags.extend(menu_row(
        compact_label.ljust(label_col_w), state_cp,
        mouse_handler=_compact_handler,
    ))
    frags.append(("", "\n"))

    frags.append(("", "\n"))

    # Back — plain << label >> row, centred per row.
    state_b = "selected" if cur_row == _TIMERS_BACK_ROW else "inactive"

    def _back_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_timers_cursor(_TIMERS_BACK_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _pop_frame()

    pad_b = max(0, (cols - (len(back_label) + 6)) // 2)
    frags.append(("", " " * pad_b))
    frags.extend(menu_row(back_label, state_b, mouse_handler=_back_handler))
    frags.append(("", "\n"))

    # title block (3 rows for popup) + header row + 6 group rows + blank
    # + headers + compact + blank + Back (5 rows).
    content_rows = title_block_height(1) + 1 + _TIMERS_GRID_ROWS + 5
    footer = "↑↓←→ Move · Enter Toggle · ESC Back"
    frags.extend(footer_block(footer, cols, rows_h, content_rows))

    return frags


def _build_timers_container():
    global _timers_window
    # Single FormattedTextControl Window — the grid frame emits the title
    # block, grid, controls and footer as one fragment list and footer_block
    # pads the trailing rows so the footer lands at the bottom of the popup.
    _timers_window = Window(
        content=FormattedTextControl(text=_timers_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _timers_window


def _build_scripts_container():
    global _scripts_window
    # Single FormattedTextControl Window — `_scripts_text` emits the
    # title block, two-column body (shared `scripts_view.render_body`),
    # and footer in one fragment list. Mirrors the launcher's Scripts
    # frame; mode="readonly" suppresses hover treatment in the body.
    _scripts_window = Window(
        content=FormattedTextControl(text=_scripts_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _scripts_window


def _build_readability_container():
    global _readability_window
    _readability_window = Window(
        content=FormattedTextControl(text=_readability_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _readability_window


def _build_exit_confirm_container():
    global _exit_confirm_window
    _exit_confirm_window = Window(
        content=FormattedTextControl(text=_exit_confirm_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _exit_confirm_window


def _build_statistics_container():
    global _statistics_window
    _statistics_window = Window(
        content=FormattedTextControl(text=_statistics_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _statistics_window


def _build_rate_session_container():
    global _rate_session_window
    _rate_session_window = Window(
        content=FormattedTextControl(text=_rate_session_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _rate_session_window


def _build_profile_apply_confirm_container():
    global _profile_apply_confirm_window
    _profile_apply_confirm_window = Window(
        content=FormattedTextControl(
            text=_profile_apply_confirm_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    return _profile_apply_confirm_window


async def _tick(app):
    try:
        while True:
            await asyncio.sleep(1.0)
            app.invalidate()
    except asyncio.CancelledError:
        pass


async def _banner_tick_loop():
    """Persistent redraw loop for the main-frame starfield. Invalidates only
    while `_current_frame == "main"` so submenus stay still; sleeps at
    `_BANNER_TICK_HZ`. Mirrors the launcher's `_banner_tick_loop`."""
    interval = 1.0 / _BANNER_TICK_HZ
    try:
        while True:
            if _app is None:
                return
            if _current_frame == "main":
                _app.invalidate()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


def _banner_start_tick_task():
    """Kick off the banner twinkle loop. Idempotent: a second call is a
    no-op once the task is running."""
    global _banner_tick_task
    if _banner_tick_task is not None:
        return
    try:
        loop = asyncio.get_running_loop()
        _banner_tick_task = loop.create_task(_banner_tick_loop())
    except RuntimeError:
        pass


def main():
    global _app

    _write_sentinel(POPUP_SENTINEL)
    atexit.register(_cleanup)
    signal.signal(signal.SIGTERM, _signal_exit)
    signal.signal(signal.SIGHUP,  _signal_exit)
    signal.signal(signal.SIGINT,  _signal_exit)

    profile_editor_frame = DynamicContainer(
        lambda: _profile_editor_instance.container()
        if _profile_editor_instance is not None else Window())
    peditor_keybind_frame = DynamicContainer(
        lambda: _profile_editor_instance.overlay_container()
        if _profile_editor_instance is not None else Window())

    frames = {
        "main":                          _build_main_container(),
        "options":                       _build_options_container(),
        "panes":                         _build_panes_container(),
        "panes_general":                 _build_panes_general_container(),
        "panes_communication":           _build_panes_communication_container(),
        "timers":                        _build_timers_container(),
        "scripts":                       _build_scripts_container(),
        "readability":                   _build_readability_container(),
        "statistics":                    _build_statistics_container(),
        "exit_confirm":                  _build_exit_confirm_container(),
        "rate_session":                  _build_rate_session_container(),
        "profile_editor":                profile_editor_frame,
        "profile_editor_macro_keybind":  peditor_keybind_frame,
        "profile_apply_confirm":         _build_profile_apply_confirm_container(),
    }

    root   = DynamicContainer(lambda: frames.get(_current_frame, frames["main"]))
    layout = Layout(root)

    merged_kb = merge_key_bindings([
        kb,
        DynamicKeyBindings(
            lambda: (_profile_editor_instance.key_bindings()
                     if _profile_editor_instance is not None
                     else KeyBindings()),
        ),
    ])

    app = Application(
        layout=layout,
        key_bindings=merged_kb,
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

    async def _run():
        global _banner_tick_task
        tick_task = asyncio.ensure_future(_tick(app))
        _banner_start_tick_task()
        try:
            await app.run_async()
        finally:
            tick_task.cancel()
            if _banner_tick_task is not None:
                _banner_tick_task.cancel()
            for t in (tick_task, _banner_tick_task):
                if t is None:
                    continue
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            _banner_tick_task = None

    try:
        asyncio.run(_run())
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
