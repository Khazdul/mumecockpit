#!/usr/bin/env python3
# bridge/launcher/launcher.py — pre-tmux startup menu (prompt_toolkit rewrite).
# Invoked via bridge/launcher/launcher.sh. Behavioural contract: docs/launcher.md.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import DynamicContainer, Layout, VerticalAlign
    from prompt_toolkit.layout.containers import (
        ConditionalContainer, Float, FloatContainer, HSplit, VSplit, Window,
    )
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.mouse_events import MouseButton, MouseEventType
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
import textwrap
import threading
import time

# Make sibling modules importable when run directly via the wrapper.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palette import (  # noqa: E402
    C_TITLE, C_ACTIVE, C_ITEM, C_BODY, C_HINT, C_ACCENT,
    C_YELLOW, C_ERR, C_DANGER, C_QUOTE, C_QUOTE_ATTR, C_HOVER, C_SELECTED,
    C_HEADER, C_SECTION, C_DIVIDER,
    C_BUTTON, C_BUTTON_HOVER, C_BUTTON_DISABLED,
    C_LOG_CURSOR,
    C_LOG_OVERLAY_BG, C_LOG_OVERLAY_FG, C_LOG_OVERLAY_HINT,
    C_LOG_SCRUBBER_FILLED, C_LOG_SCRUBBER_EMPTY, C_LOG_SCRUBBER_THUMB,
    C_LOG_BUTTON_IDLE, C_LOG_BUTTON_HOVER,
    C_SPOTLIGHT_BOX_BG, C_SPOTLIGHT_FRAME,
    C_SPOTLIGHT_TEXT_PRIMARY, C_SPOTLIGHT_TEXT_SECONDARY,
    _S_GAINED, _S_LOSS, _S_LABEL, _S_VALUE, _S_TP_BAR,
    _S_TRACK, _S_MARKER, _S_THUMB, _S_TOTAL, _S_ARROW,
    _S_HINT, _S_PVP, _S_ALLY, _S_STAR,
    PANE_COLORS, PANE_COLOR_ORDER,
    TTPP_COLOR_STYLES, TTPP_COLOR_NAMES,
)
import credits  # noqa: E402
import log_player  # noqa: E402
import macro_keys  # noqa: E402
import profile_io  # noqa: E402
import run_retention  # noqa: E402
import run_stats  # noqa: E402
import spotlights  # noqa: E402
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
# Per-pane list shared by the Panes submenu (top-level) and the six per-pane
# subframes. (key, label, conf_show_key, conf_color_key) — conf_show_key is
# the startup.conf flag flipped by the Enabled toggle, conf_color_key is the
# startup.conf entry written by the colour radios.
_PANE_OPTIONS = [
    ("status", "Character",     "show_status", "pane_color_status"),
    ("buffs",  "Buffs",         "show_buffs",  "pane_color_buffs"),
    ("group",  "Group",         "show_group",  "pane_color_group"),
    ("comm",   "Communication", "show_comm",   "pane_color_comm"),
    ("ui",     "UI",            "show_ui",     "pane_color_ui"),
    ("dev",    "Developer",     "show_dev",    "pane_color_dev"),
]

_CONNECTION_MODES = [
    ("mmapper", "MMapper", "(localhost:4242)"),
    ("direct",  "Direct",  "(mume.org:4242)"),
    ("custom",  "Custom",  None),   # detail filled in at render time from conf
]

_CONF_DEFAULTS = {
    "connection_mode":    "mmapper",
    "connection_host":    "localhost",
    "connection_port":    "4242",
    "show_status":        "1",
    "show_buffs":         "1",
    "show_group":         "1",
    "show_comm":          "1",
    "show_ui":            "1",
    "show_dev":           "0",
    "show_pane_dividers": "1",
    "pane_color_status":  "black",
    "pane_color_buffs":   "red",
    "pane_color_group":   "green",
    "pane_color_comm":    "blue",
    "pane_color_ui":      "black",
    "pane_color_dev":     "grey",
    "profile":            "default",
    "spotlights_show_deaths":       "1",
    "spotlights_show_levelups":     "1",
    "spotlights_show_pvp":          "1",
    "spotlights_show_achievements": "1",
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
_profiles               = []
_profile_table_cursor   = 0
_profile_table_scroll   = 0
_profile_menu_cursor    = 0
_profile_focused        = 0          # 0 = table, 1 = options
_profile_hover          = (None, None)   # (panel_idx, row_idx)
_profile_sort           = ("Name", "asc")
_profile_table_sb       = None
# Inline feedback shown directly below the Options widget after a Select /
# Edit / Rename / Export action. Same contract as the history twin.
_profile_feedback_text   = None
_profile_feedback_style  = ""
_profile_feedback_handle = None
# Profile rename
_rename_old_name     = ""
_rename_name_buf     = ""
_rename_name_err     = ""
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

# Profile editor (Phase 2: Aliases tab list + read-only detail panel + delete;
# Phase 3: editable detail panel + create flow + inline validation;
# Phase 3.5: in-buffer cursors with ←/→ movement, vertical zone nav,
# brace-balance validation, Priority field hidden — see docs/launcher.md.)
_editor_profile_path = None      # pathlib.Path | None
_editor_data         = None      # profile_io.Profile | None
_editor_active_tab   = 0         # 0..4 — Aliases / Actions / Macros / Highlights / Substitutes
_editor_hover_tab    = None      # tab idx under cursor, None when not hovering
_editor_focus        = 0         # 0 = tabs, 1 = list, 2 = detail
_editor_list_cursor  = 0         # index into the sorted display view; len(view) = "+ New entry" sentinel
_editor_list_scroll  = 0         # scroll offset for the list
_editor_sort_dir     = "asc"     # 'asc' | 'desc' — resets on each editor open
_editor_hover_row    = None      # row index in display view under cursor, or None
_editor_hover_sort   = False     # True when hovering the Pattern sort header
_editor_list_sb      = None      # Scrollbar widget for the list panel
_editor_delete_entry = None      # Entry under confirmation; cleared on confirm/cancel
# Detail-panel editing state. Phase 3.5 covers Pattern + Body text inputs;
# phase 4 adds Highlights' palette grid (sharing the detail_field == 1 slot
# with Body, dispatched on active kind).
_editor_detail_field    = 0      # 0 = Pattern, 1 = Body (text) or Palette (highlights)
_editor_pattern_cursor  = 0      # cursor offset into entry.pattern
_editor_body_line       = 0      # logical line index of the cursor inside entry.body
_editor_body_col        = 0      # column index of the cursor within the active body line
_editor_pattern_touched = False  # True once the user has left Pattern with empty buffer; gates required-error
# Shift-arrow selection anchors. None when no selection is active. The
# anchor + the current cursor define the selection range; typing,
# backspace, and forward-delete consume the selection when set. Cleared
# on any non-shift cursor move, focus change, or entry change.
_editor_pattern_anchor   = None  # int | None — anchor offset into entry.pattern
_editor_body_anchor_line = None  # int | None — anchor line in entry.body
_editor_body_anchor_col  = None  # int | None — anchor col in entry.body
# Palette state (active when _profile_editor_active_kind() == 'highlight').
_editor_palette_row     = 0      # 0..len(_EDITOR_PALETTE_GRID)-1, or _EDITOR_PALETTE_GRID len for Custom slot
_editor_palette_col     = 0      # 0 or 1; ignored when on Custom
_editor_palette_hover_row = None # (row, col) under mouse; None when not hovering
_editor_palette_hover_col = None
_editor_palette_custom_value = None  # str | None — stashed non-palette body so user can revert
# Macro key-capture overlay state (phase 5). Pushed as the
# `profile_editor_macro_keybind` frame from the macro detail's Key cell
# or auto-pushed when the user creates a new macro. The pending entry is
# stashed so an ESC during an auto-open create can remove the unfilled
# Entry from `_editor_data.items`.
_editor_keybind_error          = ""    # rendered in the overlay's error slot
_editor_keybind_just_created   = False # True when the overlay was auto-pushed by + New entry
# Inline feedback shown below the editor's footer (e.g. "Bound to F1.").
_editor_feedback_text   = None
_editor_feedback_style  = ""
_editor_feedback_handle = None

# Options — top-level (Panes / Game text-layout / Connection / Back)
_sel_options              = 0
_hover_options            = -1
# Options — Panes submenu (Character / Buffs / Group / Comm / UI / Dev / blank /
# Display pane headers / Back)
_sel_options_panes        = 0
_hover_options_panes      = -1
# Options — per-pane subframe (Enabled / blank / Pane color label / 7 colours /
# blank / Back). Single shared cursor since only one is rendered at a time.
_sel_options_pane         = 0
_hover_options_pane       = -1
_options_pane_target      = "status"   # which pane the subframe is currently editing
# Options — Connection submenu (MMapper / Direct / Custom / Back)
_sel_options_connection   = 0
_hover_options_connection = -1
# Options — Spotlights submenu (4 per-kind toggles + Back)
_sel_options_spotlights   = 0
_hover_options_spotlights = -1
# Options — Connection custom host:port input
_conn_host_buf            = ""
_conn_port_buf            = ""
_conn_field               = 0          # 0 = host, 1 = port
_conn_err                 = ""

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
_history_filter_items    = []        # ["All", "<char>", ...] — pill labels
_history_sessions        = []        # filtered + sorted SessionSummary list
_history_filter          = "All"
_history_sort            = ("Char", "asc")
_history_filter_cursor   = 0         # cursor pill index
_history_table_cursor    = 0
_history_table_scroll    = 0
_history_menu_cursor     = 0         # cursor row in Options widget
_history_focused         = 1         # 0 = filter, 1 = table, 2 = options
_history_hover           = (None, None)   # (panel_idx, row_idx)
_history_table_sb        = None
# Inline feedback shown directly below the Options widget after Export. Plain
# string (or None) and a style tuple. `_history_feedback_handle` is the
# asyncio TimerHandle scheduled to clear the line after ~3 s.
_history_feedback_text   = None
_history_feedback_style  = ""
_history_feedback_handle = None
# Rate-session frame (history surface)
_history_rate_rating     = 0         # 0..5
_history_rate_summary    = None      # SessionSummary being rated
# Delete-session confirm frame (history surface)
_history_delete_summary  = None      # SessionSummary the confirm frame targets
_history_detail_summary  = None      # SessionSummary pushed into the detail frame
_history_detail_stats    = None      # aggregated RunStats for that summary
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
_log_view_summary  = None   # SessionSummary currently being played
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
# Floating overlays (top header + bottom controls)
_log_overlays_visible       = True     # forced True in pause; auto-hidden after 3 s in play
_log_overlays_hide_at       = None     # monotonic() deadline; None disables timer
_log_overlay_hover          = None     # "rewind" | "playpause" | None
_LOG_OVERLAY_HIDE_DELAY     = 3.0
_LOG_OVERLAY_HEADER_W       = 80
_LOG_OVERLAY_CONTROLS_W     = 70
_LOG_OVERLAY_SCRUBBER_W     = 30
# Scrubber drag capture
_log_dragging_scrubber      = False    # True between MOUSE_DOWN on scrubber and release
_log_scrubber_left          = 0        # absolute column of the scrubber's first cell
_log_scrubber_width         = 0        # number of scrubber cells in the current render

# log_view mode: "chain" plays a SessionSummary's stitched chain; "spotlight"
# plays a SpotlightReel via SpotlightPlayback. The playback is set on
# `_log_view_playback` in both modes (interface-compatible); spotlight mode
# additionally stashes the playback on `_log_view_reel` so the header,
# overlay, and ←/→ seek handlers can reach spotlight-specific accessors
# without down-casting.
_log_view_mode              = "chain"
_log_view_reel              = None     # SpotlightPlayback | None

# End-of-reel scrolling credits. Pushed after the spotlight reel finishes;
# black canvas, narrative lines scroll bottom-to-top with fade bands at
# the top and bottom. See ADR 0080 and docs/launcher.md "credits frame".
_credits_lines: list             = []
_credits_start_monotonic: float  = 0.0
_credits_term_rows: int          = 0
_credits_term_cols: int          = 0
_credits_text_width: int         = 0
_credits_tick_task               = None  # asyncio.Task | None
_CREDITS_SCROLL_ROWS_PER_SEC     = 1.0
_CREDITS_FADE_BAND_FRAC          = 0.35
_CREDITS_TICK_HZ                 = 15

_history_columns = [
    # (key, base_label, width, align, type)
    ("Char",    "Char",     None, "left",  "text"),
    ("Date",    "Date",     10,   "left",  "text"),
    ("Time",    "Time",     5,    "left",  "text"),
    ("Dur.",    "Dur.",     5,    "left",  "numeric"),
    ("Expires", "Expires",  7,    "left",  "numeric"),
    ("Rating",  "Rating",   6,    "left",  "numeric"),
]

# Update flow
_update_rc           = None
_update_output       = ""

# Windows
_main_window         = None
_profile_table_window            = None
_profile_options_window          = None
_profile_rename_window           = None
_profile_create_name_window      = None
_profile_create_choose_window    = None
_profile_create_copy_window      = None
_profile_delete_window           = None
_profile_editor_window           = None
_profile_editor_delete_window    = None
_profile_editor_keybind_window   = None
_options_window                  = None
_options_panes_window            = None
_options_pane_window             = None
_options_connection_window       = None
_options_connection_custom_window = None
_options_coming_soon_window      = None
_options_spotlights_window       = None
_spotlights_empty_window         = None
_scripts_window      = None
_about_window        = None
_update_running_window = None
_update_result_window  = None
_exit_confirm_window   = None
_too_small_window      = None
_history_filter_window  = None
_history_table_window   = None
_history_options_window = None
_history_detail_window  = None
_history_rate_window    = None
_history_delete_confirm_window = None
_log_view_window        = None
_credits_window         = None

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
                "connection_mode", "connection_host", "connection_port",
                "show_status", "show_buffs", "show_group",
                "show_comm", "show_ui", "show_dev", "show_pane_dividers",
                "pane_color_status", "pane_color_buffs", "pane_color_group",
                "pane_color_comm", "pane_color_ui", "pane_color_dev",
                "profile",
                "spotlights_show_deaths", "spotlights_show_levelups",
                "spotlights_show_pvp", "spotlights_show_achievements",
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
        win = (_history_filter_window, _history_table_window,
               _history_options_window)[_history_focused]
    elif _current_frame == "profile":
        win = (_profile_table_window, _profile_options_window)[_profile_focused]
    else:
        win = {
            "main":                       _main_window,
            "profile_create_name":        _profile_create_name_window,
            "profile_create_choose":      _profile_create_choose_window,
            "profile_create_copy_picker": _profile_create_copy_window,
            "profile_delete_confirm":     _profile_delete_window,
            "profile_editor":             _profile_editor_window,
            "profile_editor_delete_confirm": _profile_editor_delete_window,
            "profile_editor_macro_keybind": _profile_editor_keybind_window,
            "profile_rename":             _profile_rename_window,
            "options":                    _options_window,
            "options_panes":              _options_panes_window,
            "options_pane":               _options_pane_window,
            "options_connection":         _options_connection_window,
            "options_connection_custom":  _options_connection_custom_window,
            "options_coming_soon":        _options_coming_soon_window,
            "options_spotlights":         _options_spotlights_window,
            "spotlights_empty":           _spotlights_empty_window,
            "scripts":                    _scripts_window,
            "about":                      _about_window,
            "update_running":             _update_running_window,
            "update_result":              _update_result_window,
            "exit_confirm":               _exit_confirm_window,
            "history_detail":             _history_detail_window,
            "history_rate":               _history_rate_window,
            "history_delete_confirm":     _history_delete_confirm_window,
            "log_view":                   _log_view_window,
            "credits":                    _credits_window,
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
    global _hover_main, _hover_options, _hover_copy
    global _hover_options_panes, _hover_options_pane, _hover_options_connection
    global _hover_options_spotlights
    changed = False
    if frame == "main" and _hover_main != idx:
        _hover_main = idx; changed = True
    elif frame == "options" and _hover_options != idx:
        _hover_options = idx; changed = True
    elif frame == "options_panes" and _hover_options_panes != idx:
        _hover_options_panes = idx; changed = True
    elif frame == "options_pane" and _hover_options_pane != idx:
        _hover_options_pane = idx; changed = True
    elif frame == "options_connection" and _hover_options_connection != idx:
        _hover_options_connection = idx; changed = True
    elif frame == "options_spotlights" and _hover_options_spotlights != idx:
        _hover_options_spotlights = idx; changed = True
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
        first = "Resume MUME" if _attached_count() == 0 else "Mirror MUME (attached elsewhere)"
    else:
        first = "Enter MUME"
    items = [first]
    if _update_available():
        items.append("Update")
    items.extend(["Profile", "Options", "History", "Spotlights", "About", "Quit"])
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
    if label in ("Enter MUME", "Resume MUME", "Mirror MUME (attached elsewhere)"):
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
    elif label == "Spotlights":
        _enter_spotlights()
    elif label == "Options":
        _enter_options_frame()
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
_PROFILE_BUTTONS = [
    ("Select", "select"),
    ("New",    "new"),
    ("Edit",   "edit"),
    ("Rename", "rename"),
    ("Delete", "delete"),
    ("Export", "export"),
    ("Back",   "back"),
]
_PROFILE_BUTTON_W   = max(len(lbl) for lbl, _ in _PROFILE_BUTTONS) + 2
_PROFILE_OPTIONS_GAP = 1


def _profile_table_panel_w():
    """Total width of the table content (column widths + per-gap separators)."""
    _, total = _profile_table_columns_layout()
    return total


def _profile_package_width():
    """Width of the centred [table | scrollbar | gap | options] package."""
    return _profile_table_panel_w() + 1 + _PROFILE_OPTIONS_GAP + _PROFILE_BUTTON_W


def _profile_left_pad():
    """Left padding (cells) that centres the package on the current terminal."""
    return max(0, (_term_cols() - _profile_package_width()) // 2)


def _enter_profile_frame():
    global _profiles, _profile_table_cursor, _profile_table_scroll
    global _profile_menu_cursor, _profile_focused, _profile_hover
    global _profile_table_sb
    _profiles = _list_profiles()
    _profile_apply_sort()
    cur = _conf.get("profile", "default")
    _profile_table_cursor = 0
    for i, name in enumerate(_profiles):
        if name == cur:
            _profile_table_cursor = i
            break
    _profile_table_scroll = 0
    _profile_focused      = 0
    _profile_hover        = (None, None)
    _profile_table_sb = Scrollbar(
        0, _profile_table_visible(), _profile_table_visible(),
    )
    _profile_clear_feedback()
    enabled = _profile_menu_enabled_indices()
    _profile_menu_cursor = enabled[0] if enabled else 0
    _push_frame("profile")


def _profile_table_visible():
    """Visible data rows in the table — data-fit, with a floor so the Options
    column never clips.

    Outer chrome (title 3 + footer 2 = 5) plus inner chrome (feedback row 1 +
    table header row 1 = 2) reserves 7 terminal rows. Options is 1 header +
    N buttons; the table window is `visible + 1` rows (header + data), so
    visible must be at least len(_PROFILE_BUTTONS) for the Options widget to
    render in full."""
    max_by_terminal = max(1, _term_rows() - 3 - 2 - 2)
    options_min = len(_PROFILE_BUTTONS)
    return min(max_by_terminal, max(options_min, len(_profiles)))


def _profile_table_window_h():
    """Table window height = data rows + 1 header row."""
    return _profile_table_visible() + 1


def _profile_apply_sort():
    """Re-sort _profiles in place per _profile_sort. Only Name is sortable
    today; default is asc."""
    global _profiles
    _col, direction = _profile_sort
    _profiles = sorted(_profiles, key=lambda n: n.lower(),
                       reverse=(direction == "desc"))


def _profile_toggle_sort(col):
    """Click handler for the Name header — flips direction. Other columns are
    not sortable."""
    global _profile_sort, _profile_table_cursor, _profile_table_scroll
    if col != "Name":
        return
    cur_name = (_profiles[_profile_table_cursor]
                if 0 <= _profile_table_cursor < len(_profiles) else None)
    _col, cur_dir = _profile_sort
    _profile_sort = ("Name", "asc" if cur_dir == "desc" else "desc")
    _profile_apply_sort()
    if cur_name is not None and cur_name in _profiles:
        _profile_table_cursor = _profiles.index(cur_name)
    _profile_table_scroll = _profile_scroll_into_view(
        _profile_table_cursor, _profile_table_scroll, _profile_table_visible()
    )
    if _app:
        _app.invalidate()


def _profile_scroll_into_view(cursor, scroll, visible):
    if cursor < scroll:
        return cursor
    if cursor >= scroll + visible:
        return cursor - visible + 1
    return scroll


def _profile_move_table(delta):
    global _profile_table_cursor, _profile_table_scroll
    n = len(_profiles)
    if not n:
        return
    new_cursor = max(0, min(n - 1, _profile_table_cursor + delta))
    _profile_table_cursor = new_cursor
    _profile_table_scroll = _profile_scroll_into_view(
        new_cursor, _profile_table_scroll, _profile_table_visible()
    )
    if _app:
        _app.invalidate()


def _profile_jump_table(target):
    global _profile_table_cursor, _profile_table_scroll
    n = len(_profiles)
    if not n:
        return
    new_cursor = max(0, min(n - 1, target))
    _profile_table_cursor = new_cursor
    _profile_table_scroll = _profile_scroll_into_view(
        new_cursor, _profile_table_scroll, _profile_table_visible()
    )
    if _app:
        _app.invalidate()


def _profile_scroll_table(delta):
    """Wheel scroll on the table — moves the viewport without moving the
    cursor."""
    global _profile_table_scroll
    mx = max(0, len(_profiles) - _profile_table_visible())
    _profile_table_scroll = max(0, min(mx, _profile_table_scroll + delta))
    if _app:
        _app.invalidate()


def _profile_set_focus(panel):
    global _profile_focused
    if _profile_focused == panel:
        return
    _profile_focused = panel
    _focus_current_frame()
    if _app:
        _app.invalidate()


def _profile_cycle_focus(delta):
    _profile_set_focus((_profile_focused + delta) % 2)


def _profile_set_hover(panel, row):
    global _profile_hover
    new_val = (panel, row)
    if _profile_hover == new_val:
        return
    _profile_hover = new_val
    if _app:
        _app.invalidate()


def _profile_hover_at(panel, idx, on_event=None):
    """Mouse handler factory for the profile frame — mirrors `_hover_at`
    but writes to `_profile_hover`."""
    def _handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _profile_set_hover(panel, idx)
            return None
        if on_event is not None:
            return on_event(ev)
        return NotImplemented
    return _handler


def _profile_hover_clear_frags(frags):
    """Wrap each fragment in `frags` so MOUSE_MOVE clears _profile_hover.
    Existing handlers are preserved."""
    out = []
    for f in frags:
        style, text = f[0], f[1]
        inner = f[2] if len(f) >= 3 else None
        out.append((style, text, _profile_hover_at(None, None, on_event=inner)))
    return out


def _profile_current_name():
    if 0 <= _profile_table_cursor < len(_profiles):
        return _profiles[_profile_table_cursor]
    return None


# --- Action menu state -----------------------------------------------------
def _profile_menu_actions():
    """Return [(label, action_id, enabled), ...] for the current selection."""
    name   = _profile_current_name()
    has    = name is not None
    active = _conf.get("profile", "default")
    is_default = (name == "default")
    return [
        ("Select", "select", has and name != active),
        ("New",    "new",    True),
        ("Edit",   "edit",   has),
        ("Rename", "rename", has and not is_default),
        ("Delete", "delete", has and not is_default),
        ("Export", "export", has),
        ("Back",   "back",   True),
    ]


def _profile_menu_enabled_indices():
    return [i for i, (_, _, en) in enumerate(_profile_menu_actions()) if en]


def _profile_menu_move(delta):
    """Move Options cursor through enabled buttons. Wraps."""
    global _profile_menu_cursor
    enabled = _profile_menu_enabled_indices()
    if not enabled:
        return
    if _profile_menu_cursor in enabled:
        idx = enabled.index(_profile_menu_cursor)
        new_idx = (idx + delta) % len(enabled)
    else:
        if delta >= 0:
            new_idx = next((j for j, ei in enumerate(enabled)
                            if ei > _profile_menu_cursor), 0)
        else:
            forward = [j for j, ei in enumerate(enabled)
                       if ei < _profile_menu_cursor]
            new_idx = forward[-1] if forward else len(enabled) - 1
    _profile_menu_cursor = enabled[new_idx]
    if _app:
        _app.invalidate()


def _profile_menu_activate(idx):
    """Run the action for Options button `idx` if enabled."""
    actions = _profile_menu_actions()
    if not (0 <= idx < len(actions)):
        return
    _label, action, enabled = actions[idx]
    if not enabled:
        return
    if action == "select":
        _profile_action_select()
    elif action == "new":
        _profile_action_new()
    elif action == "edit":
        _profile_action_edit()
    elif action == "rename":
        _profile_action_rename()
    elif action == "delete":
        _profile_action_delete()
    elif action == "export":
        _profile_action_export()
    elif action == "back":
        _pop_frame()


def _profile_action_select():
    name = _profile_current_name()
    if name is None or name == _conf.get("profile"):
        return
    _conf["profile"] = name
    _save_conf()
    if _app:
        _app.invalidate()


def _profile_action_new():
    _enter_profile_create_name()


def _profile_action_edit():
    name = _profile_current_name()
    if name is None:
        return
    path = os.path.join(PROFILES_DIR, f"{name}.tin")
    _enter_profile_editor(path)


def _profile_action_rename():
    name = _profile_current_name()
    if name is None or name == "default":
        return
    _enter_profile_rename()


def _profile_action_delete():
    name = _profile_current_name()
    if name is None or name == "default":
        return
    _enter_profile_delete_confirm()


def _profile_action_export():
    name = _profile_current_name()
    if name is None:
        return
    src = os.path.join(PROFILES_DIR, f"{name}.tin")
    dst = os.path.expanduser(f"~/{name}.tin")
    try:
        shutil.copyfile(src, dst)
    except OSError as exc:
        _profile_set_feedback(f"Export failed: {exc.strerror or exc}", C_HINT)
        return
    _profile_set_feedback(f"Exported to ~/{name}.tin.", C_ACCENT)


def _profile_set_feedback(text, style, ttl_seconds=3.0):
    """Flash an inline feedback message below the Options widget."""
    global _profile_feedback_text, _profile_feedback_style
    global _profile_feedback_handle
    _profile_feedback_text  = text
    _profile_feedback_style = style
    if _profile_feedback_handle is not None:
        try:
            _profile_feedback_handle.cancel()
        except Exception:
            pass
        _profile_feedback_handle = None
    if _app_loop is not None:
        _profile_feedback_handle = _app_loop.call_later(
            ttl_seconds, _profile_clear_feedback)
    if _app:
        _app.invalidate()


def _profile_clear_feedback():
    global _profile_feedback_text, _profile_feedback_style
    global _profile_feedback_handle
    _profile_feedback_text  = None
    _profile_feedback_style = ""
    _profile_feedback_handle = None
    if _app:
        _app.invalidate()


# --- Title / footer text ---------------------------------------------------
def _profile_title_text():
    cols = _term_cols()
    title = "─── Profile ───"
    return _profile_hover_clear_frags([
        ("", "\n"),
        ("", _pad_centre(title, cols)),
        (C_TITLE, title),
        ("", "\n"),
    ])


def _profile_footer_text():
    cols = _term_cols()
    footer = "↑↓ Cursor · Tab/←→ Cycle · Enter Activate · ESC Back"
    return _profile_hover_clear_frags([
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ])


# --- Table render ----------------------------------------------------------
def _profile_name_col_width():
    base = len("Name ▼")
    if _profiles:
        base = max(base, max(len(n) for n in _profiles))
    return base


def _profile_table_columns_layout():
    """Compute (cols_with_widths, total_width) for current state."""
    name_w = _profile_name_col_width()
    cols = [
        ("Name",     "Name",     name_w, "left",   True),
        ("Selected", "Selected", 8,      "centre", False),
    ]
    total = name_w + 1 + 8
    return cols, total


def _profile_header_label(base, is_active_sort, sort_dir, align, width):
    txt = base
    if is_active_sort:
        txt += " ▼" if sort_dir == "desc" else " ▲"
    if align == "centre":
        pad = max(0, width - len(txt))
        l = pad // 2
        r = pad - l
        return " " * l + txt[:width] + " " * r
    return txt[:width].ljust(width)


def _profile_format_row(name, cols, active_name):
    """Return list of (text, style) per column."""
    out = []
    for (key, _base, width, align, _sortable) in cols:
        if key == "Name":
            txt = name[:width].ljust(width)
            style = _S_LABEL
        elif key == "Selected":
            if name == active_name:
                glyph = "✓"
                pad = max(0, width - 1)
                l = pad // 2
                r = pad - l
                txt = " " * l + glyph + " " * r
                style = C_ACCENT
            else:
                txt = " " * width
                style = _S_LABEL
        else:
            txt = "".ljust(width)
            style = _S_LABEL
        out.append((txt, style))
    return out


def _profile_table_text():
    cols_layout, total_w = _profile_table_columns_layout()
    sort_col, sort_dir   = _profile_sort
    table_focused        = (_profile_focused == 0)
    active_name          = _conf.get("profile", "default")
    clear_hover          = _profile_hover_at(None, None)
    frags = []

    # Header row.
    header_style = C_ACTIVE if table_focused else C_SECTION
    for i, (key, base, width, align, sortable) in enumerate(cols_layout):
        is_active_sort = sortable and (key == sort_col)
        label = _profile_header_label(base, is_active_sort, sort_dir, align, width)

        if sortable:
            def _click(ev, col=key):
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _profile_set_focus(0)
                    _profile_toggle_sort(col)
                    return None
                return NotImplemented
            cell_handler = _profile_hover_at(None, None, on_event=_click)
        else:
            cell_handler = clear_hover

        if i > 0:
            frags.append((header_style, " ", cell_handler))
        frags.append((header_style, label, cell_handler))
    frags.append(("", "\n", clear_hover))

    # Data rows.
    visible = _profile_table_visible()
    total   = len(_profiles)
    mx      = max(0, total - visible)
    global _profile_table_scroll
    if _profile_table_scroll > mx:
        _profile_table_scroll = mx
    if _profile_table_sb is not None:
        _profile_table_sb.update(total, visible, height=visible)
        _profile_table_sb.scroll_to(_profile_table_scroll)

    sliced = _profiles[_profile_table_scroll:_profile_table_scroll + visible]
    hover_panel, hover_row = _profile_hover

    for vi, name in enumerate(sliced):
        row_abs   = _profile_table_scroll + vi
        is_cursor = (row_abs == _profile_table_cursor)
        is_hover  = (hover_panel == 0 and hover_row == row_abs)

        if is_cursor:
            row_bg = C_SELECTED
        elif is_hover:
            row_bg = C_HOVER
        else:
            row_bg = None

        def _click(ev, row=row_abs):
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _profile_set_focus(0)
                global _profile_table_cursor
                _profile_table_cursor = row
                if _app:
                    _app.invalidate()
                return None
            return NotImplemented
        row_handler = _profile_hover_at(0, row_abs, on_event=_click)

        row_frags = _profile_format_row(name, cols_layout, active_name)
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


def _profile_table_scrollbar_text():
    if _profile_table_sb is None or not _profiles:
        return []
    # Leave the header row's strip blank, then render scrollbar over data.
    frags = [("", " "), ("", "\n")]
    frags.extend(_profile_table_sb.render())
    return _profile_hover_clear_frags(frags)


# --- Options widget render (right side of the profile table) --------------
def _profile_options_text():
    """Render the Options column: 'Options' header + flat buttons stacked
    with no inter-button gap."""
    inner_w = _PROFILE_BUTTON_W
    actions = _profile_menu_actions()
    options_focused = (_profile_focused == 1)
    header_style = C_ACTIVE if options_focused else C_SECTION
    hover_panel, hover_row = _profile_hover
    clear_hover = _profile_hover_at(None, None)

    frags = []

    # Header — "Options" centred within the button-column width.
    header_label = "Options"
    pad_l = max(0, (inner_w - len(header_label)) // 2)
    pad_r = max(0, inner_w - len(header_label) - pad_l)
    frags.append(("", " " * pad_l, clear_hover))
    frags.append((header_style, header_label, clear_hover))
    frags.append(("", " " * pad_r, clear_hover))
    frags.append(("", "\n", clear_hover))

    for i, (label, _action, enabled) in enumerate(actions):
        is_cursor = (i == _profile_menu_cursor)
        is_hover  = (hover_panel == 1 and hover_row == i and enabled
                     and not is_cursor)
        if not enabled:
            style = C_BUTTON_DISABLED
        elif is_cursor:
            style = C_SELECTED
        elif is_hover:
            style = C_BUTTON_HOVER
        else:
            style = C_BUTTON

        pad_l = max(0, (inner_w - len(label)) // 2)
        pad_r = max(0, inner_w - len(label) - pad_l)
        cell_text = " " * pad_l + label + " " * pad_r

        if enabled:
            def _click(ev, idx=i):
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _profile_set_focus(1)
                    global _profile_menu_cursor
                    _profile_menu_cursor = idx
                    _profile_menu_activate(idx)
                    return None
                return NotImplemented
            frags.append((style, cell_text, _profile_hover_at(1, i, on_event=_click)))
        else:
            frags.append((style, cell_text, clear_hover))
        frags.append(("", "\n", clear_hover))

    # Pad trailing blank lines so the column fills the table_row height.
    used = 1 + len(actions)
    blanks = max(0, _profile_table_window_h() - used)
    for r in range(blanks):
        frags.append(("", " " * inner_w, clear_hover))
        if r < blanks - 1:
            frags.append(("", "\n", clear_hover))
    return frags


def _profile_feedback_or_blank_text():
    """Single row directly below the package; doubles as the spacing row
    above the footer. Centred on package width when a message is flashing."""
    clear_hover = _profile_hover_at(None, None)
    if not _profile_feedback_text:
        return [("", "", clear_hover)]
    text = _profile_feedback_text
    pkg_w  = _profile_package_width()
    inner  = max(0, (pkg_w - len(text)) // 2)
    pad_l  = _profile_left_pad() + inner
    return [
        ("", " " * pad_l, clear_hover),
        (_profile_feedback_style, text, clear_hover),
    ]


# --- Profile editor (Phase 2: Aliases list + read-only detail + delete) ----
# Tab strip: (label, kind in profile_io)
_PROFILE_EDITOR_TABS = [
    ("Aliases",     "alias"),
    ("Actions",     "action"),
    ("Macros",      "macro"),
    ("Highlights",  "highlight"),
    ("Substitutes", "substitute"),
]

_EDITOR_PATTERN_COL_W = 8       # Pattern column inside the list panel
_EDITOR_LIST_W        = 30      # Total list panel width (pattern + body cols)
_EDITOR_GAP           = 2       # Cells between list-scrollbar and detail
_EDITOR_DETAIL_W      = 44      # Detail panel width

# Per-kind detail-panel field labels — `(pattern_label, body_label)`. Used by
# both the detail panel (renamed `Body` slot) and the list panel header.
DETAIL_LABELS = {
    "alias":      ("Pattern", "Commands"),
    "action":     ("Pattern", "Commands"),
    "macro":      ("Key",     "Commands"),    # Key cell pushes a capture overlay
    "highlight":  ("Pattern", "Color"),       # body slot becomes the palette grid
    "substitute": ("Text",    "New text"),
}

# Per-kind detail-panel builder. The renderer dispatches on the active kind:
# text-bodied kinds reuse the Pattern + Body chain; `highlight` swaps the
# Body field for a 2-D color-palette grid; `macro` swaps Pattern for a
# "press to bind" button that pushes the key-capture overlay.
def _editor_dispatch_detail_builder(kind):
    return _EDITOR_DETAIL_BUILDERS.get(kind, _editor_build_text_detail)


# Body / Commands / etc. default values for `+ New entry` rows, keyed by kind.
# Aliases / actions / substitutes start blank; highlights default to the
# project's vintage-amber accent colour so the user sees the swatch
# pre-selected and can re-pick from the palette. Macros start blank too,
# but the overlay is auto-pushed so the user never sees the empty state.
DETAIL_NEW_DEFAULTS = {
    "alias":      ("", ""),
    "action":     ("", ""),
    "macro":      ("", ""),
    "highlight":  ("", "light yellow"),
    "substitute": ("", ""),
}


# Color-palette grid for the Highlights tab. Two columns, base name on the
# left and the `light` variant on the right (matching most users' mental
# model of the named tt++ colour set). The palette is intentionally small —
# bold / reverse / background / hex variants belong in raw mode (phase 6).
_EDITOR_PALETTE_GRID = [
    ("white",        "gray"),
    ("red",          "light red"),
    ("yellow",       "light yellow"),
    ("green",        "light green"),
    ("cyan",         "light cyan"),
    ("blue",         "light blue"),
    ("magenta",      "light magenta"),
]
_EDITOR_PALETTE_ROWS = len(_EDITOR_PALETTE_GRID)
_EDITOR_PALETTE_COLS = 2


def _editor_package_w():
    return _EDITOR_LIST_W + 1 + _EDITOR_GAP + _EDITOR_DETAIL_W


def _editor_left_pad():
    return max(0, (_term_cols() - _editor_package_w()) // 2)


def _editor_body_h():
    """Body row height — enough for the detail panel; grows with terminal.

    Phase 3.5 detail-panel minimum rows (top → bottom):
        Pattern label                            1
        Pattern box (top + content + bot)        3
        Body label                               1
        Body box (top + ≥1 content line + bot)   3
        Error slot                               1
        Blank divider                            1
        ─── Hint ─── divider                     1
        Hint lines × 2                           2
    Total minimum 13. The hint block at the bottom is truncated when
    the terminal is short, so the field chain itself stays visible."""
    return max(13, _term_rows() - 9)


def _editor_list_visible():
    """List data rows visible in the body (header sits above)."""
    return max(1, _editor_body_h() - 1)


def _enter_profile_editor(path):
    """Load `path` into the editor and push the frame. Flashes a hint on
    the profile frame and stays put if the file cannot be parsed."""
    global _editor_profile_path, _editor_data, _editor_active_tab
    global _editor_hover_tab, _editor_focus, _editor_list_cursor
    global _editor_list_scroll, _editor_sort_dir, _editor_hover_row
    global _editor_hover_sort, _editor_list_sb
    global _editor_detail_field, _editor_body_line, _editor_body_col
    global _editor_pattern_cursor, _editor_pattern_touched
    try:
        data = profile_io.load_profile(path)
    except OSError as exc:
        name = os.path.basename(path)
        _profile_set_feedback(
            f"Could not open {name}: {exc.strerror or exc}", C_HINT)
        return
    _editor_profile_path = data.path
    _editor_data         = data
    _editor_active_tab   = 0
    _editor_hover_tab    = None
    _editor_focus        = 0
    _editor_list_cursor  = 0
    _editor_list_scroll  = 0
    _editor_sort_dir     = "asc"
    _editor_hover_row    = None
    _editor_hover_sort   = False
    _editor_detail_field    = 0
    _editor_pattern_cursor  = 0
    _editor_body_line       = 0
    _editor_body_col        = 0
    _editor_pattern_touched = False
    _editor_list_sb = Scrollbar(
        0, _editor_list_visible(), _editor_list_visible(),
    )
    _push_frame("profile_editor")
    _editor_refresh_buffers()


def _profile_editor_save_and_close():
    """ESC handler: persist and pop. Flashes a hint on the profile
    frame after pop — success in `C_ACCENT`, failure in `C_HINT`."""
    err_msg = None
    saved_name = None
    if _editor_data is not None:
        try:
            profile_io.save_profile(_editor_data)
            saved_name = (
                _editor_profile_path.name
                if _editor_profile_path is not None else "")
        except OSError as exc:
            err_msg = f"Save failed: {exc.strerror or exc}"
    _pop_frame()
    if err_msg:
        _profile_set_feedback(err_msg, C_HINT)
    elif saved_name:
        _profile_set_feedback(f"Saved {saved_name}.", C_ACCENT)


def _profile_editor_set_tab(idx):
    """Switch to tab `idx`. Resets list cursor + scroll to 0 and
    refreshes detail-panel buffers from the new active kind's first
    entry, so cross-tab navigation always lands the cursor on a
    real row with valid in-buffer cursors."""
    global _editor_active_tab, _editor_list_cursor, _editor_list_scroll
    n = len(_PROFILE_EDITOR_TABS)
    new_idx = max(0, min(n - 1, idx))
    if new_idx != _editor_active_tab:
        _editor_active_tab = new_idx
        _editor_list_cursor = 0
        _editor_list_scroll = 0
        _editor_refresh_buffers()
        if _app:
            _app.invalidate()


def _profile_editor_set_hover_tab(idx):
    global _editor_hover_tab
    if _editor_hover_tab != idx:
        _editor_hover_tab = idx
        if _app:
            _app.invalidate()


def _profile_editor_set_hover_row(idx):
    global _editor_hover_row
    if _editor_hover_row != idx:
        _editor_hover_row = idx
        if _app:
            _app.invalidate()


def _profile_editor_set_hover_sort(flag):
    global _editor_hover_sort
    if _editor_hover_sort != flag:
        _editor_hover_sort = flag
        if _app:
            _app.invalidate()


def _profile_editor_clear_hover():
    global _editor_hover_tab, _editor_hover_row, _editor_hover_sort
    changed = False
    if _editor_hover_tab is not None:
        _editor_hover_tab = None
        changed = True
    if _editor_hover_row is not None:
        _editor_hover_row = None
        changed = True
    if _editor_hover_sort:
        _editor_hover_sort = False
        changed = True
    if changed and _app:
        _app.invalidate()


def _profile_editor_set_focus(panel, field=None):
    """Set the focus zone. Optional `field` selects the detail-panel
    field when entering panel=2 (0 = Pattern, 1 = Body). Switching
    panels arms the Pattern required-error when leaving an empty
    Pattern field. Any focus or field change clears live selections
    in both text fields — leaving the field invalidates the selection."""
    global _editor_focus, _editor_detail_field, _editor_pattern_touched
    prev_focus = _editor_focus
    prev_field = _editor_detail_field
    leaving_pattern = (
        prev_focus == 2 and prev_field == 0
        and (panel != 2 or (field is not None and field != 0))
    )
    leaving_body = (
        prev_focus == 2 and prev_field == 1
        and (panel != 2 or (field is not None and field != 1))
    )
    if leaving_pattern:
        entry = _editor_current_entry()
        if entry is not None and entry.pattern == "":
            _editor_pattern_touched = True
        _editor_clear_pattern_selection()
    if leaving_body:
        _editor_clear_body_selection()
    if panel != 2:
        _editor_clear_selections()
    if panel == 2:
        if field is None:
            field = _editor_detail_field if prev_focus == 2 else 0
        _editor_detail_field = max(0, min(1, field))
    if _editor_focus == panel and (panel != 2 or _editor_detail_field == prev_field):
        return
    _editor_focus = panel
    _focus_current_frame()
    if _app:
        _app.invalidate()


def _profile_editor_cycle_focus(delta):
    """Cycle the 4-stop focus chain: tabs → list → detail.Pattern →
    detail.Body → tabs."""
    if _editor_focus == 0:
        idx = 0
    elif _editor_focus == 1:
        idx = 1
    else:
        idx = 2 + _editor_detail_field
    new_idx = (idx + delta) % 4
    if new_idx == 0:
        _profile_editor_set_focus(0)
    elif new_idx == 1:
        _profile_editor_set_focus(1)
    else:
        _profile_editor_set_focus(2, field=new_idx - 2)


def _profile_editor_active_kind():
    _, kind = _PROFILE_EDITOR_TABS[_editor_active_tab]
    return kind


def _profile_editor_active_count():
    if _editor_data is None:
        return 0
    return len(_editor_data.entries_of(_profile_editor_active_kind()))


def _profile_editor_display_view():
    """Return the active tab's entries sorted by `pattern` per `_editor_sort_dir`.
    The underlying `_editor_data.items` is NOT mutated — sort is presentation
    only, so unchanged entries continue to round-trip `_raw` byte-exact.

    `macro` entries sort by their *display name* rather than the raw
    escape sequence so the list groups F-keys before numpad keys before
    Alt+letters, matching what the user sees. Unknown escapes are
    keyed on `Custom: <raw>` so they cluster together at the end of the
    ascending view."""
    if _editor_data is None:
        return []
    kind = _profile_editor_active_kind()
    entries = _editor_data.entries_of(kind)
    if kind == "macro":
        def _key(e):
            name = macro_keys.escape_to_name(e.pattern)
            return name if name is not None else f"Custom: {e.pattern}"
        return sorted(entries, key=_key,
                      reverse=(_editor_sort_dir == "desc"))
    return sorted(entries, key=lambda e: e.pattern,
                  reverse=(_editor_sort_dir == "desc"))


def _profile_editor_display_total():
    """Total displayed rows in the list: entries + 1 for the
    `+ New entry` sentinel."""
    return len(_profile_editor_display_view()) + 1


def _editor_current_entry():
    """The Entry under the list cursor in the display view, or `None`
    when the cursor sits on the `+ New entry` sentinel or the view is
    empty."""
    view = _profile_editor_display_view()
    if 0 <= _editor_list_cursor < len(view):
        return view[_editor_list_cursor]
    return None


def _editor_cursor_on_sentinel():
    return _editor_list_cursor == len(_profile_editor_display_view())


def _editor_refresh_buffers():
    """Refresh transient cursors from the current entry. Pattern and
    Body are read directly from the Entry; the in-buffer cursors land
    at end-of-buffer (and end-of-last-line for Body) so subsequent
    typing appends naturally. The pattern-touched flag resets — it
    tracks "have you ever left THIS entry's Pattern field empty" — so
    navigating away and back doesn't keep a stale error visible on a
    different row.

    On `highlight` entries the palette grid cursor + Custom-slot
    stash are also re-initialised from the entry's body. A
    palette-named body lands the cursor on the matching swatch and
    clears the Custom slot; a non-palette body stashes the original
    value and parks the cursor on Custom."""
    global _editor_pattern_cursor, _editor_body_line, _editor_body_col
    global _editor_pattern_touched
    global _editor_palette_row, _editor_palette_col
    global _editor_palette_custom_value
    global _editor_palette_hover_row, _editor_palette_hover_col
    entry = _editor_current_entry()
    if entry is None:
        _editor_pattern_cursor = 0
        _editor_body_line = 0
        _editor_body_col = 0
        _editor_palette_row = 0
        _editor_palette_col = 0
        _editor_palette_custom_value = None
    else:
        _editor_pattern_cursor = len(entry.pattern)
        body_lines = entry.body.split("\n") if entry.body else [""]
        _editor_body_line = max(0, len(body_lines) - 1)
        _editor_body_col  = len(body_lines[_editor_body_line])
        if entry.kind == "highlight":
            pos = _editor_palette_position_for_color(entry.body)
            if pos is not None:
                _editor_palette_row, _editor_palette_col = pos
                _editor_palette_custom_value = None
            else:
                # Non-palette body — stash it and park cursor on Custom.
                _editor_palette_custom_value = entry.body
                _editor_palette_row = _EDITOR_PALETTE_ROWS   # Custom slot
                _editor_palette_col = 0
        else:
            _editor_palette_row = 0
            _editor_palette_col = 0
            _editor_palette_custom_value = None
    _editor_pattern_touched = False
    _editor_palette_hover_row = None
    _editor_palette_hover_col = None
    _editor_clear_selections()


def _editor_palette_position_for_color(name):
    """Return `(row, col)` of the palette cell whose label equals `name`,
    or None when the value is not in the grid."""
    for r, (left, right) in enumerate(_EDITOR_PALETTE_GRID):
        if left == name:
            return (r, 0)
        if right == name:
            return (r, 1)
    return None


def _editor_palette_color_at(row, col):
    """Return the palette-color label at `(row, col)`, or None when
    `row` indexes the Custom slot (row == `_EDITOR_PALETTE_ROWS`)."""
    if 0 <= row < _EDITOR_PALETTE_ROWS and 0 <= col < _EDITOR_PALETTE_COLS:
        return _EDITOR_PALETTE_GRID[row][col]
    return None


def _editor_palette_apply_cursor():
    """Write the value at the current palette cursor into the active
    entry's body. Palette cells write the swatch's color name; the
    Custom slot restores the stashed pre-edit value. Routes through
    `entry.body = ...` so `__setattr__` clears `_raw` for an edited
    highlight to serialise canonically on save."""
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_palette_row == _EDITOR_PALETTE_ROWS:
        if _editor_palette_custom_value is not None:
            entry.body = _editor_palette_custom_value
        return
    color = _editor_palette_color_at(_editor_palette_row, _editor_palette_col)
    if color is not None:
        entry.body = color


def _editor_palette_set_cursor(row, col):
    """Move the palette cursor to `(row, col)` and apply the live
    binding. Clamps to the grid; `row == _EDITOR_PALETTE_ROWS` is
    only valid when the Custom slot is visible."""
    global _editor_palette_row, _editor_palette_col
    custom_visible = _editor_palette_custom_value is not None
    max_row = _EDITOR_PALETTE_ROWS if custom_visible else (_EDITOR_PALETTE_ROWS - 1)
    row = max(0, min(max_row, row))
    if row == _EDITOR_PALETTE_ROWS:
        col = 0
    else:
        col = max(0, min(_EDITOR_PALETTE_COLS - 1, col))
    if row == _editor_palette_row and col == _editor_palette_col:
        return
    _editor_palette_row = row
    _editor_palette_col = col
    _editor_palette_apply_cursor()
    if _app:
        _app.invalidate()


def _editor_palette_move(d_row, d_col):
    """Relative palette cursor move. Returns True when the cursor
    landed somewhere new (so the keybind can decide whether to fall
    through to inter-zone nav at an edge)."""
    custom_visible = _editor_palette_custom_value is not None
    cur_row = _editor_palette_row
    cur_col = _editor_palette_col
    if cur_row == _EDITOR_PALETTE_ROWS:
        # On Custom: ↑ goes back into the grid; ↓ is a no-op; ←/→ no-op.
        if d_row == -1:
            _editor_palette_set_cursor(_EDITOR_PALETTE_ROWS - 1, 0)
            return True
        return False
    new_row = cur_row + d_row
    new_col = cur_col + d_col
    if d_row > 0 and new_row >= _EDITOR_PALETTE_ROWS:
        if custom_visible:
            _editor_palette_set_cursor(_EDITOR_PALETTE_ROWS, 0)
            return True
        return False
    if d_row < 0 and new_row < 0:
        return False
    if d_col != 0 and (new_col < 0 or new_col >= _EDITOR_PALETTE_COLS):
        return False
    _editor_palette_set_cursor(new_row, new_col)
    return True


def _editor_body_lines():
    """The current entry's body split on `\\n`. `["" ]` when no entry or
    empty body, so the renderer always has at least one row to draw."""
    entry = _editor_current_entry()
    if entry is None or entry.body == "":
        return [""]
    return entry.body.split("\n")


def _editor_body_set_lines(lines):
    """Write `lines` back into the current entry's `body`. Joining with
    `\\n` round-trips the multi-line representation; `entry.body = ...`
    goes through `__setattr__` and clears `_raw`."""
    entry = _editor_current_entry()
    if entry is None:
        return
    entry.body = "\n".join(lines)


def _editor_body_clamp_cursor():
    """Defensively clamp `_editor_body_line` / `_editor_body_col` into
    the current body's shape. Called from edit and nav paths that may
    have advanced past the trailing edge."""
    global _editor_body_line, _editor_body_col
    lines = _editor_body_lines()
    _editor_body_line = max(0, min(len(lines) - 1, _editor_body_line))
    _editor_body_col  = max(0, min(len(lines[_editor_body_line]),
                                   _editor_body_col))


def _editor_body_insert_char(ch):
    """Insert `ch` at the current (line, col) cursor and advance the
    column by one. Splits and joins use `\\n` so the Entry's body
    string mirrors the visual line break exactly. Replaces the live
    selection (if any) before inserting."""
    global _editor_body_col
    entry = _editor_current_entry()
    if entry is None:
        return
    _editor_body_delete_selection()
    lines = _editor_body_lines()
    if not lines:
        lines = [""]
    line = max(0, min(len(lines) - 1, _editor_body_line))
    col  = max(0, min(len(lines[line]), _editor_body_col))
    lines[line] = lines[line][:col] + ch + lines[line][col:]
    _editor_body_set_lines(lines)
    _editor_body_col = col + 1


def _editor_body_insert_newline():
    """Split the current line at the cursor column and place the cursor
    at the start of the new line. Replaces the live selection (if any)
    before splitting."""
    global _editor_body_line, _editor_body_col
    entry = _editor_current_entry()
    if entry is None:
        return
    _editor_body_delete_selection()
    lines = _editor_body_lines()
    if not lines:
        lines = [""]
    line = max(0, min(len(lines) - 1, _editor_body_line))
    col  = max(0, min(len(lines[line]), _editor_body_col))
    head, tail = lines[line][:col], lines[line][col:]
    lines[line] = head
    lines.insert(line + 1, tail)
    _editor_body_set_lines(lines)
    _editor_body_line = line + 1
    _editor_body_col  = 0
    if _app:
        _app.invalidate()


def _editor_body_backspace():
    """Delete the character before the cursor. At the start of a line
    (col == 0) join with the previous line instead, placing the cursor
    at the join point — standard text-editor backspace semantics. With
    a live selection, delete the selection instead."""
    global _editor_body_line, _editor_body_col
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_body_delete_selection():
        if _app:
            _app.invalidate()
        return
    lines = _editor_body_lines()
    if not lines:
        return
    line = max(0, min(len(lines) - 1, _editor_body_line))
    col  = max(0, min(len(lines[line]), _editor_body_col))
    if col > 0:
        lines[line] = lines[line][:col - 1] + lines[line][col:]
        _editor_body_set_lines(lines)
        _editor_body_col = col - 1
    elif line > 0:
        prev_len = len(lines[line - 1])
        lines[line - 1] = lines[line - 1] + lines[line]
        del lines[line]
        _editor_body_set_lines(lines)
        _editor_body_line = line - 1
        _editor_body_col  = prev_len
    # else: top-left corner of an empty buffer — nothing to delete.
    if _app:
        _app.invalidate()


def _editor_body_move_left():
    """← within Body. Wraps from start-of-line to end-of-previous-line.
    No-op at the top-left corner."""
    global _editor_body_line, _editor_body_col
    lines = _editor_body_lines()
    line = max(0, min(len(lines) - 1, _editor_body_line))
    col  = max(0, min(len(lines[line]), _editor_body_col))
    if col > 0:
        _editor_body_col = col - 1
    elif line > 0:
        _editor_body_line = line - 1
        _editor_body_col  = len(lines[line - 1])
    if _app:
        _app.invalidate()


def _editor_body_move_right():
    """→ within Body. Wraps from end-of-line to start-of-next-line.
    No-op at the bottom-right corner."""
    global _editor_body_line, _editor_body_col
    lines = _editor_body_lines()
    line = max(0, min(len(lines) - 1, _editor_body_line))
    col  = max(0, min(len(lines[line]), _editor_body_col))
    if col < len(lines[line]):
        _editor_body_col = col + 1
    elif line < len(lines) - 1:
        _editor_body_line = line + 1
        _editor_body_col  = 0
    if _app:
        _app.invalidate()


def _editor_body_move_line(delta):
    """Up / Down within Body — preserve the column as far as the new
    line allows. Returns True when the cursor actually moved, so the
    `↑/↓` keybind can fall through to inter-zone nav at the edges."""
    global _editor_body_line, _editor_body_col
    lines = _editor_body_lines()
    line = max(0, min(len(lines) - 1, _editor_body_line))
    new_line = line + delta
    if new_line < 0 or new_line >= len(lines):
        return False
    _editor_body_line = new_line
    _editor_body_col  = min(_editor_body_col, len(lines[new_line]))
    if _app:
        _app.invalidate()
    return True


def _editor_set_pattern(text):
    """Update the current entry's pattern, re-sort the display view,
    and re-anchor the list cursor onto the same entry."""
    global _editor_list_cursor
    entry = _editor_current_entry()
    if entry is None:
        return
    entry.pattern = text
    # Re-sort and re-anchor.
    view_after = _profile_editor_display_view()
    try:
        _editor_list_cursor = view_after.index(entry)
    except ValueError:
        _editor_list_cursor = 0
    _profile_editor_scroll_into_view()


def _editor_clear_pattern_selection():
    global _editor_pattern_anchor
    _editor_pattern_anchor = None


def _editor_clear_body_selection():
    global _editor_body_anchor_line, _editor_body_anchor_col
    _editor_body_anchor_line = None
    _editor_body_anchor_col  = None


def _editor_clear_selections():
    """Clear both Pattern and Body selection anchors."""
    _editor_clear_pattern_selection()
    _editor_clear_body_selection()


def _editor_pattern_set_anchor_if_none():
    """Arm the Pattern selection anchor at the current cursor. Called
    from shift-arrow handlers so a fresh shift-move starts a selection
    rooted at the current cursor."""
    global _editor_pattern_anchor
    if _editor_pattern_anchor is None:
        _editor_pattern_anchor = _editor_pattern_cursor


def _editor_body_set_anchor_if_none():
    """Arm the Body selection anchor at the current cursor."""
    global _editor_body_anchor_line, _editor_body_anchor_col
    if _editor_body_anchor_line is None:
        _editor_body_anchor_line = _editor_body_line
        _editor_body_anchor_col  = _editor_body_col


def _editor_pattern_selection():
    """Return `(start, end)` in Pattern (inclusive, exclusive) or None
    when no live selection. `start == end` is treated as no selection."""
    if _editor_pattern_anchor is None:
        return None
    a = _editor_pattern_anchor
    c = _editor_pattern_cursor
    if a == c:
        return None
    return (min(a, c), max(a, c))


def _editor_body_selection():
    """Return `((s_line, s_col), (e_line, e_col))` for the Body
    selection, or None. Ordering normalised so start ≤ end in document
    order (line first, then column)."""
    if _editor_body_anchor_line is None:
        return None
    a = (_editor_body_anchor_line, _editor_body_anchor_col)
    c = (_editor_body_line, _editor_body_col)
    if a == c:
        return None
    return (min(a, c), max(a, c))


def _editor_body_line_selection_range(line_idx):
    """The per-line selection slice `(start_col, end_col)` for `line_idx`,
    or None when the selection doesn't touch this line. Used by the
    renderer to paint the C_SELECTED band per visible line."""
    sel = _editor_body_selection()
    if sel is None:
        return None
    (sl, sc), (el, ec) = sel
    if line_idx < sl or line_idx > el:
        return None
    lines = _editor_body_lines()
    line_len = len(lines[line_idx]) if 0 <= line_idx < len(lines) else 0
    start_col = sc if line_idx == sl else 0
    # End-of-line lines (anywhere except the last line of the selection)
    # paint one past the visible content so the selection reads as
    # continuous — the renderer treats `line_len + 1` as "include the
    # trailing space cell".
    end_col = ec if line_idx == el else line_len + 1
    return (start_col, end_col)


def _editor_pattern_delete_selection():
    """When a Pattern selection exists, delete it and place the cursor
    at the selection start. Returns True iff a deletion happened."""
    global _editor_pattern_cursor, _editor_pattern_anchor
    sel = _editor_pattern_selection()
    if sel is None:
        return False
    entry = _editor_current_entry()
    if entry is None:
        return False
    s, e = sel
    pat = entry.pattern
    _editor_set_pattern(pat[:s] + pat[e:])
    _editor_pattern_cursor = s
    _editor_pattern_anchor = None
    return True


def _editor_body_delete_selection():
    """When a Body selection exists, delete it and place the cursor at
    the selection start. Returns True iff a deletion happened."""
    global _editor_body_line, _editor_body_col
    global _editor_body_anchor_line, _editor_body_anchor_col
    sel = _editor_body_selection()
    if sel is None:
        return False
    (sl, sc), (el, ec) = sel
    lines = _editor_body_lines()
    if not lines:
        return False
    sl = max(0, min(len(lines) - 1, sl))
    el = max(0, min(len(lines) - 1, el))
    sc = max(0, min(len(lines[sl]), sc))
    ec = max(0, min(len(lines[el]), ec))
    head = lines[sl][:sc]
    tail = lines[el][ec:]
    new_lines = lines[:sl] + [head + tail] + lines[el + 1:]
    _editor_body_set_lines(new_lines)
    _editor_body_line = sl
    _editor_body_col  = sc
    _editor_body_anchor_line = None
    _editor_body_anchor_col  = None
    return True


def _editor_pattern_insert_char(ch):
    """Insert `ch` at the pattern cursor and advance the cursor. Replaces
    the live selection (if any) before inserting."""
    global _editor_pattern_cursor
    entry = _editor_current_entry()
    if entry is None:
        return
    _editor_pattern_delete_selection()
    pat = entry.pattern
    col = max(0, min(len(pat), _editor_pattern_cursor))
    _editor_set_pattern(pat[:col] + ch + pat[col:])
    _editor_pattern_cursor = col + 1


def _editor_pattern_backspace():
    """Delete the character before the pattern cursor. With a live
    selection, delete the selection instead."""
    global _editor_pattern_cursor
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_pattern_delete_selection():
        return
    pat = entry.pattern
    col = max(0, min(len(pat), _editor_pattern_cursor))
    if col == 0:
        return
    _editor_set_pattern(pat[:col - 1] + pat[col:])
    _editor_pattern_cursor = col - 1


def _editor_pattern_forward_delete():
    """Delete the character *at* the pattern cursor (the cell under the
    cursor). With a live selection, delete the selection instead."""
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_pattern_delete_selection():
        return
    pat = entry.pattern
    col = max(0, min(len(pat), _editor_pattern_cursor))
    if col >= len(pat):
        return
    _editor_set_pattern(pat[:col] + pat[col + 1:])


def _editor_pattern_move_left():
    global _editor_pattern_cursor
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_pattern_cursor > 0:
        _editor_pattern_cursor -= 1
        if _app:
            _app.invalidate()


def _editor_pattern_move_right():
    global _editor_pattern_cursor
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_pattern_cursor < len(entry.pattern):
        _editor_pattern_cursor += 1
        if _app:
            _app.invalidate()


def _editor_pattern_move_home():
    """Pattern is single-line — Home goes to col 0."""
    global _editor_pattern_cursor
    if _editor_current_entry() is None:
        return
    _editor_pattern_cursor = 0
    if _app:
        _app.invalidate()


def _editor_pattern_move_end():
    """Pattern is single-line — End goes to len(pattern)."""
    global _editor_pattern_cursor
    entry = _editor_current_entry()
    if entry is None:
        return
    _editor_pattern_cursor = len(entry.pattern)
    if _app:
        _app.invalidate()


def _editor_body_move_home():
    """Home in Body — start of the current logical line."""
    global _editor_body_col
    if _editor_current_entry() is None:
        return
    _editor_body_col = 0
    if _app:
        _app.invalidate()


def _editor_body_move_end():
    """End in Body — end of the current logical line."""
    global _editor_body_col
    if _editor_current_entry() is None:
        return
    lines = _editor_body_lines()
    line = max(0, min(len(lines) - 1, _editor_body_line))
    _editor_body_col = len(lines[line])
    if _app:
        _app.invalidate()


def _editor_body_forward_delete():
    """Delete the character at the cursor in Body. At end-of-line, join
    with the next line. With a live selection, delete the selection."""
    global _editor_body_col
    entry = _editor_current_entry()
    if entry is None:
        return
    if _editor_body_delete_selection():
        return
    lines = _editor_body_lines()
    if not lines:
        return
    line = max(0, min(len(lines) - 1, _editor_body_line))
    col  = max(0, min(len(lines[line]), _editor_body_col))
    if col < len(lines[line]):
        lines[line] = lines[line][:col] + lines[line][col + 1:]
        _editor_body_set_lines(lines)
    elif line < len(lines) - 1:
        lines[line] = lines[line] + lines[line + 1]
        del lines[line + 1]
        _editor_body_set_lines(lines)
    if _app:
        _app.invalidate()


def _braces_balanced(s):
    """Return True when every unescaped `{` in `s` has a matching `}`
    later and no stray `}` appears first. `\\X` for any X is treated
    as escaped (the X — including `{` and `}` — does not count toward
    depth). Used by the editor's brace-balance validation to flag
    profiles that tt++ would reject on next load."""
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _editor_validation_error():
    """Inline validation error text or None. Precedence — highest first:

      1. `Pattern is required.` — empty pattern, but only once the user
         has left the field at least once (touched flag).
      2. `Unbalanced braces in <pattern-label>.` — Pattern has mismatched
         braces; tt++ would reject the line on next load. Live, not
         gated by touched.
      3. `Unbalanced braces in <body-label>.` — same for Body.

    Save is **never** blocked by these. The user sees them while
    editing and is expected to fix them; if they ESC anyway, tt++
    will surface the error on next session load."""
    entry = _editor_current_entry()
    if entry is None:
        return None
    if _editor_pattern_touched and entry.pattern == "":
        return "Pattern is required."
    kind = entry.kind
    pat_lbl, body_lbl = DETAIL_LABELS.get(kind, ("Pattern", "Body"))
    if not _braces_balanced(entry.pattern):
        return f"Unbalanced braces in {pat_lbl}."
    if not _braces_balanced(entry.body):
        return f"Unbalanced braces in {body_lbl}."
    return None


def _editor_create_new_entry():
    """Append a blank Entry of the active kind to `Profile.items`, move
    the list cursor onto it in the sorted view, and focus the detail
    panel's Pattern field. Per-kind defaults come from
    `DETAIL_NEW_DEFAULTS`; abandoning a create is harmless because
    `save_profile` drops empty-pattern entries before write.

    Macros are special: the new entry's Key cell is left empty and the
    key-capture overlay is auto-pushed so the user never sees a
    "[ Press to bind… ]" placeholder in the wild. ESC on that overlay
    removes the unfilled Entry."""
    global _editor_list_cursor
    if _editor_data is None:
        return
    kind = _profile_editor_active_kind()
    pat_default, body_default = DETAIL_NEW_DEFAULTS.get(kind, ("", ""))
    entry = profile_io.Entry(
        kind=kind, pattern=pat_default, body=body_default,
        priority=None, _raw=None)
    _editor_data.items.append(entry)
    view_after = _profile_editor_display_view()
    try:
        _editor_list_cursor = view_after.index(entry)
    except ValueError:
        _editor_list_cursor = 0
    _profile_editor_scroll_into_view()
    _editor_refresh_buffers()
    _profile_editor_set_focus(2, field=0)
    if kind == "macro":
        _editor_push_keybind_overlay(just_created=True)


def _profile_editor_scroll_into_view():
    """Adjust `_editor_list_scroll` so the cursor row is visible."""
    global _editor_list_scroll
    visible = _editor_list_visible()
    if _editor_list_cursor < _editor_list_scroll:
        _editor_list_scroll = _editor_list_cursor
    elif _editor_list_cursor >= _editor_list_scroll + visible:
        _editor_list_scroll = _editor_list_cursor - visible + 1
    # Include the sentinel row in the scroll bounds so the cursor can
    # land on it.
    total = _profile_editor_display_total()
    max_scroll = max(0, total - visible)
    _editor_list_scroll = max(0, min(max_scroll, _editor_list_scroll))


def _profile_editor_move_cursor(delta):
    """Move the list cursor by `delta`. Includes the "+ New entry"
    sentinel in the navigable range so users can reach it with ↓ at
    the end. Refreshes detail-panel buffers when the cursor lands on
    a different entry."""
    global _editor_list_cursor
    total = _profile_editor_display_total()
    if total <= 0:
        return
    new_cursor = max(0, min(total - 1, _editor_list_cursor + delta))
    if new_cursor != _editor_list_cursor:
        _editor_list_cursor = new_cursor
        _profile_editor_scroll_into_view()
        _editor_refresh_buffers()
        if _app:
            _app.invalidate()


def _profile_editor_jump_cursor(target):
    global _editor_list_cursor
    total = _profile_editor_display_total()
    if total <= 0:
        return
    new_cursor = max(0, min(total - 1, target))
    if new_cursor != _editor_list_cursor:
        _editor_list_cursor = new_cursor
        _profile_editor_scroll_into_view()
        _editor_refresh_buffers()
        if _app:
            _app.invalidate()


def _profile_editor_scroll_list(delta):
    """Wheel scroll on the list — moves the viewport without moving the
    cursor."""
    global _editor_list_scroll
    visible = _editor_list_visible()
    total = _profile_editor_display_total()
    mx = max(0, total - visible)
    _editor_list_scroll = max(0, min(mx, _editor_list_scroll + delta))
    if _app:
        _app.invalidate()


def _profile_editor_toggle_sort():
    """Click handler for the Pattern header — flips direction and re-anchors
    the cursor onto the same Entry in the new ordering. The sentinel
    row stays at the bottom of the displayed list regardless of sort
    direction, so a cursor on it stays there too."""
    global _editor_sort_dir, _editor_list_cursor
    view_before = _profile_editor_display_view()
    on_sentinel = _editor_list_cursor == len(view_before)
    cur_entry = (view_before[_editor_list_cursor]
                 if 0 <= _editor_list_cursor < len(view_before) else None)
    _editor_sort_dir = "desc" if _editor_sort_dir == "asc" else "asc"
    view_after = _profile_editor_display_view()
    if on_sentinel:
        _editor_list_cursor = len(view_after)
    elif cur_entry is not None:
        try:
            _editor_list_cursor = view_after.index(cur_entry)
        except ValueError:
            _editor_list_cursor = 0
    _profile_editor_scroll_into_view()
    if _app:
        _app.invalidate()


def _profile_editor_request_delete():
    """`d` handler: stash the cursor Entry and push the confirm sub-frame.
    No-op when the cursor is on the `+ New entry` sentinel — there is
    nothing to delete."""
    global _editor_delete_entry
    view = _profile_editor_display_view()
    if not view or not (0 <= _editor_list_cursor < len(view)):
        return
    _editor_delete_entry = view[_editor_list_cursor]
    _push_frame("profile_editor_delete_confirm")


def _profile_editor_confirm_delete():
    """Remove the stashed Entry from items, clamp the cursor, and pop.

    After delete, prefer keeping the cursor on a real entry rather than
    falling onto the sentinel — only land on the sentinel when there
    are no entries left."""
    global _editor_delete_entry, _editor_list_cursor
    target = _editor_delete_entry
    if target is not None and _editor_data is not None:
        try:
            _editor_data.items.remove(target)
        except ValueError:
            pass
    _editor_delete_entry = None
    entries_total = _profile_editor_active_count()
    if entries_total == 0:
        _editor_list_cursor = 0   # the sentinel — only row left
    else:
        _editor_list_cursor = max(
            0, min(entries_total - 1, _editor_list_cursor))
    _profile_editor_scroll_into_view()
    _editor_refresh_buffers()
    _pop_frame()


def _profile_editor_cancel_delete():
    global _editor_delete_entry
    _editor_delete_entry = None
    _pop_frame()


# Scrollbar geometry used by the inline list/scrollbar render. Mirrors the
# math in widgets/scrollbar.py so the editor's single-window layout can
# emit one cell per body row without instantiating a separate column.
def _editor_sb_thumb_geom(total, visible, height):
    if total <= 0 or total <= visible or height <= 0:
        return 0, 0
    ratio   = visible / total
    thumb_h = max(1, round(ratio * height))
    thumb_h = min(thumb_h, height)
    max_top = height - thumb_h
    mx_scroll = max(0, total - visible)
    if max_top <= 0 or mx_scroll <= 0:
        return 0, thumb_h
    top = round(_editor_list_scroll / mx_scroll * max_top)
    top = max(0, min(max_top, top))
    return top, thumb_h


def _editor_sb_click_to_offset(cell_row, total, visible, height):
    mx_scroll = max(0, total - visible)
    if mx_scroll <= 0:
        return 0
    _top, thumb_h = _editor_sb_thumb_geom(total, visible, height)
    max_top = height - thumb_h
    if max_top <= 0:
        return 0
    target_top = max(0, min(max_top, cell_row - thumb_h // 2))
    return round(target_top / max_top * mx_scroll)


# ----- Rendering helpers --------------------------------------------------
_EDITOR_HINT_LINES = [
    "Use %1, %2, %3 as argument placeholders.",
    "Separate commands with ; for sequences.",
]

# Kind labels surfaced in user-facing hints. Singular form for in-flight
# create prompts; plural form for the empty-state message.
_EDITOR_KIND_LABELS = {
    "alias":      ("alias",      "aliases"),
    "action":     ("action",     "actions"),
    "macro":      ("macro",      "macros"),
    "highlight":  ("highlight",  "highlights"),
    "substitute": ("substitute", "substitutes"),
}


def _editor_body_lines_for_entry(entry):
    """Split an entry's body on literal `\\n` so multi-line entries render
    each physical line in the bordered body field."""
    if entry is None:
        return [""]
    return entry.body.split("\n") if entry.body else [""]


def _editor_pad_full(style, text, handler=None):
    """Build a single-fragment row of width `_EDITOR_DETAIL_W` from a
    single style + text. Pads with empty-style spaces or truncates.

    When `handler` is supplied, every fragment carries it so the whole
    row reacts to mouse clicks — used by the label, border, and gap
    rows of editable detail fields so clicking on the field's chrome
    focuses it (rather than just clicks on the content row)."""
    w = _EDITOR_DETAIL_W
    if handler is None:
        if len(text) > w:
            return [(style, text[:w])]
        if len(text) == w:
            return [(style, text)]
        return [(style, text), ("", " " * (w - len(text)))]
    if len(text) > w:
        return [(style, text[:w], handler)]
    if len(text) == w:
        return [(style, text, handler)]
    return [(style, text, handler),
            ("", " " * (w - len(text)), handler)]


def _editor_box_top(width):
    return "┌" + "─" * (width - 2) + "┐"


def _editor_box_bot(width):
    return "└" + "─" * (width - 2) + "┘"


def _editor_field_border_style(focused):
    """Subtle visual indicator for which detail field has focus.
    Unfocused: dim grey (`C_HINT`). Focused: amber (`C_ACCENT`) — a
    shift up the same warm family the launcher uses elsewhere, so it
    reads as "active" without leaving the vintage-amber palette."""
    return C_ACCENT if focused else C_HINT


def _editor_box_content_row(text, border_focused, cursor_col=None,
                            sel_range=None,
                            field_id=None, line_idx=None):
    """Render `│ <text> │` for a wide field. Splits the inner area
    into per-cell fragments so a click on any column can position the
    cursor there.

    `border_focused` controls the `│` border-character style; pass the
    field-level focus state so every row of a focused multi-line field
    draws consistent borders (the cursor line and the non-cursor lines
    look the same).

    `cursor_col`, when not None, marks the absolute column on this line
    where the in-buffer cursor sits — that cell paints `C_SELECTED`.
    Pass None on non-cursor lines.

    `sel_range`, when not None, is `(start_col, end_col)` of the live
    selection that touches this line (absolute columns, end-exclusive);
    every cell in `[start_col, end_col)` paints `C_SELECTED`.

    `field_id` is `"pattern"` or `"body"` and gates the per-cell click
    handler; `line_idx` (Body only) tells the handler which line within
    the body the click maps to.

    Returns a list of `(style, text[, handler])` fragments summing to
    `_EDITOR_DETAIL_W` cells."""
    w = _EDITOR_DETAIL_W
    inner = w - 4
    border_style = _editor_field_border_style(border_focused)
    pad_right = w - 2 - 2 - inner

    # Compute the visible view of the buffer + the cursor's visible col.
    # When the buffer fits in `inner`, show it fully. When it overflows,
    # scroll so the cursor stays visible — try to keep at least one
    # cell of context on each side.
    if cursor_col is None:
        cur_for_scroll = len(text)
    else:
        cur_for_scroll = max(0, min(len(text), cursor_col))

    if len(text) <= inner:
        view_text  = text + " " * (inner - len(text))
        start_col  = 0
    else:
        half = inner // 2
        start_col = max(0, min(len(text) - inner + 1, cur_for_scroll - half))
        view_text = text[start_col:start_col + inner]
        if len(view_text) < inner:
            view_text = view_text + " " * (inner - len(view_text))

    view_cursor = (cur_for_scroll - start_col) if cursor_col is not None else None

    frags = [(border_style, "│ ", None)]

    for i in range(inner):
        ch = view_text[i] if i < len(view_text) else " "
        abs_col = start_col + i
        in_sel = (sel_range is not None
                  and sel_range[0] <= abs_col < sel_range[1])
        is_cursor = (view_cursor is not None and i == view_cursor)
        if is_cursor or in_sel:
            style = C_SELECTED
        else:
            style = C_ITEM if ch != " " else ""
        if field_id is None:
            frags.append((style, ch, None))
        else:
            # Per-cell click handler — focuses the field and positions
            # the cursor at this visible column. Body handlers also
            # capture the line index so multi-line clicks land
            # correctly.
            frags.append((style, ch,
                          _editor_make_field_click_handler(
                              field_id, i, line_idx, start=start_col)))

    frags.append((border_style, " │", None))
    if pad_right > 0:
        frags.append(("", " " * pad_right, None))
    return frags


def _editor_make_field_click_handler(field_id, visible_col, line_idx,
                                     start=0):
    """Build a `MOUSE_DOWN` handler that focuses the named detail
    field and positions the in-buffer cursor at the clicked column.
    `start` is the scroll offset of the visible view into the buffer
    so the click maps back to the right absolute column. Clicks clear
    any live selection on that field."""
    def _handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        global _editor_pattern_cursor, _editor_body_line, _editor_body_col
        target_col = max(0, start + visible_col)
        if field_id == "pattern":
            entry = _editor_current_entry()
            if entry is None:
                return None
            _profile_editor_set_focus(2, field=0)
            _editor_pattern_cursor = max(0, min(len(entry.pattern),
                                                target_col))
            _editor_clear_pattern_selection()
        elif field_id == "body":
            entry = _editor_current_entry()
            if entry is None:
                return None
            _profile_editor_set_focus(2, field=1)
            lines = _editor_body_lines()
            line = max(0, min(len(lines) - 1,
                              line_idx if line_idx is not None else 0))
            _editor_body_line = line
            _editor_body_col  = max(0, min(len(lines[line]), target_col))
            _editor_clear_body_selection()
        if _app:
            _app.invalidate()
        return None
    return _handler


def _editor_make_field_focus_handler(field_id):
    """A MOUSE_DOWN handler that focuses the named detail field without
    repositioning the in-buffer cursor at a column. Used by the label
    row, the top/bottom border rows, and the side-padding cells so a
    click anywhere on a field's outer bounding box brings it into
    focus."""
    def _handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        entry = _editor_current_entry()
        if entry is None:
            return None
        if field_id == "pattern":
            _profile_editor_set_focus(2, field=0)
            _editor_clear_pattern_selection()
        elif field_id == "body":
            _profile_editor_set_focus(2, field=1)
            _editor_clear_body_selection()
        if _app:
            _app.invalidate()
        return None
    return _handler


def _editor_centered_row(style, text):
    """Build a row that centres `text` in the detail-panel width."""
    w = _EDITOR_DETAIL_W
    if len(text) > w:
        return [(style, text[:w])]
    pad_l = max(0, (w - len(text)) // 2)
    pad_r = max(0, w - pad_l - len(text))
    return [
        ("", " " * pad_l),
        (style, text),
        ("", " " * pad_r),
    ]


def _editor_detail_lines(entry, total_lines):
    """Build the right-side detail rows. Returns a list of length
    `total_lines`; each element is itself a list of fragments summing
    to `_EDITOR_DETAIL_W` cells. Fragments are 2-tuples `(style, text)`
    or 3-tuples `(style, text, handler)` — both forms survive the
    outer compositor.

    Dispatches the body of the panel through
    `_editor_dispatch_detail_builder`: text-bodied kinds reuse the
    Pattern + Body chain, `highlight` swaps Body for a palette grid,
    `macro` swaps Pattern for the press-to-bind Key cell.

    The wrapper handles the no-entry branch:
      • cursor on the `+ New entry` sentinel → centred prompt;
      • list empty *and* no entry under the cursor → empty-state hint.
    """
    kind = _profile_editor_active_kind()
    _kind_sing, kind_plural = _EDITOR_KIND_LABELS.get(kind, (kind, kind))

    rows = []
    view = _profile_editor_display_view()

    if entry is None:
        if len(view) == 0:
            msg = f"No {kind_plural} yet. Press n to add one."
        else:
            msg = f"Press Enter to create a new {_kind_sing}."
        top_blank = max(0, total_lines // 2 - 1)
        for _ in range(top_blank):
            rows.append(_editor_pad_full(C_HINT, ""))
        rows.append(_editor_centered_row(C_HINT, msg))
        while len(rows) < total_lines:
            rows.append(_editor_pad_full(C_HINT, ""))
        return rows[:total_lines]

    builder = _editor_dispatch_detail_builder(kind)
    return builder(entry, total_lines)


def _editor_build_text_detail(entry, total_lines):
    """Pattern + Body editor for `alias`, `action`, `substitute`. Both
    fields are text inputs with the in-buffer cursor model + focused-
    border accent shared with the alias editor."""
    detail_focused = (_editor_focus == 2)
    pat_lbl, body_lbl = DETAIL_LABELS.get(entry.kind, ("Pattern", "Body"))
    pattern_focused = detail_focused and _editor_detail_field == 0
    body_focused    = detail_focused and _editor_detail_field == 1
    pat_border  = _editor_field_border_style(pattern_focused)
    body_border = _editor_field_border_style(body_focused)
    pat_focus_h  = _editor_make_field_focus_handler("pattern")
    body_focus_h = _editor_make_field_focus_handler("body")
    pat_sel = _editor_pattern_selection() if pattern_focused else None

    rows = []

    rows.append(_editor_pad_full(C_HINT, pat_lbl, pat_focus_h))
    rows.append(_editor_pad_full(pat_border, _editor_box_top(_EDITOR_DETAIL_W),
                                 pat_focus_h))
    rows.append(_editor_box_content_row(
        entry.pattern, pattern_focused,
        cursor_col=_editor_pattern_cursor if pattern_focused else None,
        sel_range=pat_sel,
        field_id="pattern"))
    rows.append(_editor_pad_full(pat_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                 pat_focus_h))

    rows.append(_editor_pad_full(C_HINT, body_lbl, body_focus_h))
    rows.append(_editor_pad_full(body_border, _editor_box_top(_EDITOR_DETAIL_W),
                                 body_focus_h))
    body_lines = _editor_body_lines_for_entry(entry)
    cursor_line = max(0, min(len(body_lines) - 1, _editor_body_line))
    for i, line in enumerate(body_lines):
        is_cursor_line = body_focused and i == cursor_line
        col = (_editor_body_col if is_cursor_line else None)
        sel = (_editor_body_line_selection_range(i)
               if body_focused else None)
        rows.append(_editor_box_content_row(
            line, body_focused, cursor_col=col,
            sel_range=sel,
            field_id="body", line_idx=i))
    rows.append(_editor_pad_full(body_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                 body_focus_h))

    err = _editor_validation_error()
    if err:
        rows.append(_editor_pad_full(C_DANGER, err))
    else:
        rows.append(_editor_pad_full(C_HINT, ""))

    rows.append(_editor_pad_full(C_HINT, ""))
    rows.append(_editor_centered_row(C_HINT, "─── Hint ───"))
    for line in _EDITOR_HINT_LINES:
        rows.append(_editor_pad_full(C_HINT, line))

    while len(rows) < total_lines:
        rows.append(_editor_pad_full(C_HINT, ""))
    return rows[:total_lines]


def _editor_build_palette_detail(entry, total_lines):
    """Pattern + 2-D color palette grid for `highlight`. The grid sits
    where the Body box lives in the text-detail variant; the Custom
    slot appears below the grid only when the entry's body is not in
    the palette."""
    detail_focused = (_editor_focus == 2)
    pat_lbl, body_lbl = DETAIL_LABELS["highlight"]
    pattern_focused = detail_focused and _editor_detail_field == 0
    palette_focused = detail_focused and _editor_detail_field == 1
    pat_border = _editor_field_border_style(pattern_focused)
    pat_focus_h = _editor_make_field_focus_handler("pattern")
    pat_sel = _editor_pattern_selection() if pattern_focused else None

    rows = []

    rows.append(_editor_pad_full(C_HINT, pat_lbl, pat_focus_h))
    rows.append(_editor_pad_full(pat_border, _editor_box_top(_EDITOR_DETAIL_W),
                                 pat_focus_h))
    rows.append(_editor_box_content_row(
        entry.pattern, pattern_focused,
        cursor_col=_editor_pattern_cursor if pattern_focused else None,
        sel_range=pat_sel,
        field_id="pattern"))
    rows.append(_editor_pad_full(pat_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                 pat_focus_h))

    rows.append(_editor_pad_full(C_HINT, body_lbl + ":"))

    custom_visible = _editor_palette_custom_value is not None
    for r, (left, right) in enumerate(_EDITOR_PALETTE_GRID):
        is_left_cursor  = palette_focused and r == _editor_palette_row and _editor_palette_col == 0
        is_right_cursor = palette_focused and r == _editor_palette_row and _editor_palette_col == 1
        is_left_hover   = (_editor_palette_hover_row == r
                           and _editor_palette_hover_col == 0
                           and not is_left_cursor)
        is_right_hover  = (_editor_palette_hover_row == r
                           and _editor_palette_hover_col == 1
                           and not is_right_cursor)
        rows.append(_editor_palette_row_fragments(
            r, left, right,
            is_left_cursor, is_right_cursor,
            is_left_hover, is_right_hover))

    if custom_visible:
        is_custom_cursor = (palette_focused
                            and _editor_palette_row == _EDITOR_PALETTE_ROWS)
        is_custom_hover  = (_editor_palette_hover_row == _EDITOR_PALETTE_ROWS
                            and not is_custom_cursor)
        rows.append(_editor_palette_custom_row_fragments(
            is_custom_cursor, is_custom_hover))

    err = _editor_validation_error()
    if err:
        rows.append(_editor_pad_full(C_DANGER, err))
    else:
        rows.append(_editor_pad_full(C_HINT, ""))

    rows.append(_editor_pad_full(C_HINT, ""))
    rows.append(_editor_centered_row(C_HINT, "─── Hint ───"))
    rows.append(_editor_pad_full(C_HINT, "Pick a color for the highlighted text."))

    while len(rows) < total_lines:
        rows.append(_editor_pad_full(C_HINT, ""))
    return rows[:total_lines]


def _editor_build_macro_detail(entry, total_lines):
    """Key (press-to-bind cell) + Commands (text body) for `macro`.

    The Key cell is a focusable button, not a TextArea — the user can
    `Enter` or click it to push the key-capture overlay, which records
    the canonical tt++ escape into `entry.pattern`. Commands is the
    same text editor used for the other text-bodied kinds."""
    detail_focused = (_editor_focus == 2)
    pat_lbl, body_lbl = DETAIL_LABELS["macro"]
    key_focused  = detail_focused and _editor_detail_field == 0
    body_focused = detail_focused and _editor_detail_field == 1
    body_border  = _editor_field_border_style(body_focused)
    body_focus_h = _editor_make_field_focus_handler("body")

    rows = []

    rows.append(_editor_pad_full(C_HINT, pat_lbl))
    rows.append(_editor_macro_key_cell_row(entry, key_focused))
    rows.append(_editor_pad_full(C_HINT, "(Enter to rebind)"))

    rows.append(_editor_pad_full(C_HINT, body_lbl, body_focus_h))
    rows.append(_editor_pad_full(body_border, _editor_box_top(_EDITOR_DETAIL_W),
                                 body_focus_h))
    body_lines = _editor_body_lines_for_entry(entry)
    cursor_line = max(0, min(len(body_lines) - 1, _editor_body_line))
    for i, line in enumerate(body_lines):
        is_cursor_line = body_focused and i == cursor_line
        col = (_editor_body_col if is_cursor_line else None)
        sel = (_editor_body_line_selection_range(i)
               if body_focused else None)
        rows.append(_editor_box_content_row(
            line, body_focused, cursor_col=col,
            sel_range=sel,
            field_id="body", line_idx=i))
    rows.append(_editor_pad_full(body_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                 body_focus_h))

    err = _editor_validation_error()
    if err:
        rows.append(_editor_pad_full(C_DANGER, err))
    else:
        rows.append(_editor_pad_full(C_HINT, ""))

    rows.append(_editor_pad_full(C_HINT, ""))
    rows.append(_editor_centered_row(C_HINT, "─── Hint ───"))
    rows.append(_editor_pad_full(C_HINT, "Press Enter on Key to rebind."))
    rows.append(_editor_pad_full(C_HINT, "Separate commands with ; for sequences."))

    while len(rows) < total_lines:
        rows.append(_editor_pad_full(C_HINT, ""))
    return rows[:total_lines]


def _editor_macro_key_cell_text(entry):
    """The rendered text + style for the macro Key cell, given an entry.

    Three states (mirrors phase 5 spec):
      • Empty pattern (pre-capture)  → "[ Press to bind… ]" in C_HINT.
      • Known escape → "[ <display name> ]" in C_ITEM.
      • Unknown escape → "[ Custom: <raw> ]" in C_HINT (same convention as
        the highlights Custom slot).
    """
    raw = entry.pattern or ""
    if raw == "":
        return "[ Press to bind… ]", C_HINT, "placeholder"
    name = macro_keys.escape_to_name(raw)
    if name is not None:
        return f"[ {name} ]", C_ITEM, "known"
    return f"[ Custom: {raw} ]", C_HINT, "custom"


def format_entry_pattern(entry, max_len=40):
    """Readable pattern for an Entry, suitable for confirm dialogs.

    `macro` entries resolve through `escape_to_name`, falling back to
    `Custom: <raw>` for unknown escape sequences. All other kinds return
    the raw pattern, truncated with `…` when longer than `max_len`."""
    raw = entry.pattern or ""
    if entry.kind == "macro":
        name = macro_keys.escape_to_name(raw)
        return name if name is not None else f"Custom: {raw}"
    if len(raw) > max_len:
        return raw[: max(0, max_len - 1)] + "…"
    return raw


def _editor_macro_key_cell_row(entry, focused):
    """Render the macro Key cell as a single row that fills the detail
    panel width. Focused state wraps the label in `C_SELECTED`; an
    accompanying click handler pushes the capture overlay."""
    label, style, _state = _editor_macro_key_cell_text(entry)
    w = _EDITOR_DETAIL_W
    indent = 0
    text = label
    if len(text) > w - indent:
        text = text[: max(0, w - indent - 1)] + "…"
    pad = max(0, w - indent - len(text))
    if focused:
        cell_style = C_SELECTED
    else:
        cell_style = style

    def _click(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        _profile_editor_set_focus(2, field=0)
        _editor_push_keybind_overlay(just_created=False)
        return None

    frags = [(cell_style, text, _click)]
    if pad > 0:
        frags.append(("", " " * pad, _click))
    return frags


_EDITOR_DETAIL_BUILDERS = {
    "alias":      _editor_build_text_detail,
    "action":     _editor_build_text_detail,
    "substitute": _editor_build_text_detail,
    "highlight":  _editor_build_palette_detail,
    "macro":      _editor_build_macro_detail,
}


# Palette-grid row geometry: 3-cell indent + 17-cell left cell +
# 3-cell gap + 17-cell right cell. Sums to 40 (== inner detail width).
_EDITOR_PALETTE_INDENT  = 3
_EDITOR_PALETTE_CELL_W  = 17
_EDITOR_PALETTE_GAP     = 3


def _editor_palette_cell_text(name, is_cursor):
    """Compose the per-cell text for a palette swatch. The cursor cell
    wraps the name in brackets (`[ name ]`); a non-cursor cell wraps
    in spaces of equal width so the column stays aligned."""
    if is_cursor:
        text = f"[ {name} ]"
    else:
        text = f"  {name}  "
    return text.ljust(_EDITOR_PALETTE_CELL_W)[:_EDITOR_PALETTE_CELL_W]


def _editor_palette_swatch_style(name, is_cursor, is_hover):
    """Foreground style for a palette swatch. Cursor reverses the
    swatch's color into a clearly-selected band; hover renders in
    `C_HOVER` so the underlying color is dimmed but readable; normal
    cells render the name *in its own color* via `TTPP_COLOR_STYLES`."""
    if is_cursor:
        return f"{TTPP_COLOR_STYLES[name]} reverse"
    if is_hover:
        return C_HOVER
    return TTPP_COLOR_STYLES[name]


def _editor_palette_row_fragments(grid_row, left_name, right_name,
                                  left_cursor, right_cursor,
                                  left_hover, right_hover):
    """One row of the palette grid as a list of fragments summing to
    `_EDITOR_DETAIL_W` cells. Each swatch carries its own click +
    hover mouse handler keyed on its grid coordinates."""
    indent = " " * _EDITOR_PALETTE_INDENT
    gap    = " " * _EDITOR_PALETTE_GAP

    left_text  = _editor_palette_cell_text(left_name,  left_cursor)
    right_text = _editor_palette_cell_text(right_name, right_cursor)
    left_style  = _editor_palette_swatch_style(left_name,  left_cursor,
                                               left_hover)
    right_style = _editor_palette_swatch_style(right_name, right_cursor,
                                               right_hover)

    frags = [
        ("", indent),
        (left_style, left_text,
         _editor_make_palette_click_handler(grid_row, 0)),
        ("", gap),
        (right_style, right_text,
         _editor_make_palette_click_handler(grid_row, 1)),
    ]
    used = (_EDITOR_PALETTE_INDENT + _EDITOR_PALETTE_CELL_W
            + _EDITOR_PALETTE_GAP + _EDITOR_PALETTE_CELL_W)
    if used < _EDITOR_DETAIL_W:
        frags.append(("", " " * (_EDITOR_DETAIL_W - used)))
    return frags


def _editor_palette_custom_row_fragments(is_cursor, is_hover):
    """The single-row Custom slot rendered below the grid when the
    entry's body is not in the palette. Displays the stashed value so
    the user can navigate back and revert."""
    custom = _editor_palette_custom_value or ""
    label  = f"Custom: {custom}"
    if is_cursor:
        text = f"[ {label} ]"
        style = f"{C_ACCENT} reverse"
    elif is_hover:
        text = f"  {label}  "
        style = C_HOVER
    else:
        text = f"  {label}  "
        style = C_HINT
    if len(text) > _EDITOR_DETAIL_W - _EDITOR_PALETTE_INDENT:
        text = text[:max(0, _EDITOR_DETAIL_W - _EDITOR_PALETTE_INDENT - 1)] + "…"
    indent = " " * _EDITOR_PALETTE_INDENT
    pad = max(0, _EDITOR_DETAIL_W - _EDITOR_PALETTE_INDENT - len(text))
    frags = [
        ("", indent),
        (style, text,
         _editor_make_palette_click_handler(_EDITOR_PALETTE_ROWS, 0)),
    ]
    if pad > 0:
        frags.append(("", " " * pad))
    return frags


def _editor_make_palette_click_handler(row, col):
    """Build a click handler that focuses the palette grid and moves
    the cursor to `(row, col)` — applying the live binding to
    `Entry.body` via `_editor_palette_apply_cursor`."""
    def _handler(ev):
        global _editor_palette_hover_row, _editor_palette_hover_col
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            if (_editor_palette_hover_row, _editor_palette_hover_col) != (row, col):
                _editor_palette_hover_row = row
                _editor_palette_hover_col = col
                if _app:
                    _app.invalidate()
            return None
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return NotImplemented
        _profile_editor_set_focus(2, field=1)
        _editor_palette_set_cursor(row, col)
        if _app:
            _app.invalidate()
        return None
    return _handler


def _editor_list_row_text(entry, is_cursor, is_hover):
    """Render one list row as a list of `(style, text)` fragments
    summing to `_EDITOR_LIST_W` cells.

    Pattern column is fixed at `_EDITOR_PATTERN_COL_W` chars; remainder
    is the body column with `…` truncation. For `highlight` entries
    whose body resolves to a known palette colour, the body cell is
    rendered *in that colour* — so the list doubles as a colour
    preview. Custom (non-palette) values render in default text colour.

    `macro` entries show the readable key name (`Numpad 0`, `F1`,
    `Alt+a`) in place of the raw escape sequence — `escape_to_name`
    resolves the on-disk value; unknown escapes fall back to
    `Custom: <raw>` in `C_HINT`, the same convention as the
    highlights Custom slot.

    The cursor row uses a single `C_SELECTED` fragment for the whole
    row so the selection band reads as one element."""
    w = _EDITOR_LIST_W
    pat = entry.pattern
    pat_custom = False
    if entry.kind == "macro":
        name = macro_keys.escape_to_name(pat)
        if name is not None:
            pat = name
        else:
            pat = f"Custom: {pat}"
            pat_custom = True
    if len(pat) > _EDITOR_PATTERN_COL_W:
        pat = pat[:max(0, _EDITOR_PATTERN_COL_W - 1)] + "…"
    pat_cell = pat.ljust(_EDITOR_PATTERN_COL_W)
    body_col_w = w - _EDITOR_PATTERN_COL_W - 2
    body_one_line = (entry.body.split("\n", 1)[0] if entry.body else "")
    if len(body_one_line) > body_col_w:
        body_one_line = body_one_line[:max(0, body_col_w - 1)] + "…"
    body_cell = body_one_line.ljust(body_col_w)
    full_text = (pat_cell + "  " + body_cell)[:w].ljust(w)

    if is_cursor:
        return [(C_SELECTED, full_text)]
    if is_hover:
        return [(C_HOVER, full_text)]
    if entry.kind == "highlight" and body_one_line in TTPP_COLOR_NAMES:
        # Color preview: render the swatch name in its own colour. The
        # pattern + gap stay in the default list text style.
        return [
            (C_ITEM, pat_cell + "  "),
            (TTPP_COLOR_STYLES[body_one_line], body_cell),
        ]
    if entry.kind == "macro" and pat_custom:
        # Mirror the highlights Custom slot — dim the unknown-key cell so
        # it reads as "needs attention" without breaking column alignment.
        return [
            (C_HINT, pat_cell + "  "),
            (C_ITEM, body_cell),
        ]
    return [(C_ITEM, full_text)]


def _editor_list_header_frag(visible_rows):
    """Build the list header fragments — `<pattern_label> <arrow>  <body_label>`
    plus padding. Labels come from `DETAIL_LABELS[active_kind]` so the
    Highlights tab shows `Pattern + Color`, Substitutes shows
    `Text + New text`, etc.

    Returns a list of fragments that fills `_EDITOR_LIST_W` cells. The
    arrow + label are wrapped in a click handler that toggles sort."""
    w = _EDITOR_LIST_W
    arrow = "▲" if _editor_sort_dir == "asc" else "▼"
    list_focused = (_editor_focus == 1)
    base_style = C_ACTIVE if list_focused else C_SECTION
    hover_style = C_HOVER
    style = hover_style if _editor_hover_sort and not list_focused else base_style
    kind = _profile_editor_active_kind()
    pat_lbl, body_lbl = DETAIL_LABELS.get(kind, ("Pattern", "Body"))
    # Pattern-column label is truncated to fit `_EDITOR_PATTERN_COL_W - 1`
    # so it leaves room for the sort arrow. "Pattern" fits exactly; for a
    # kind like "Substitute" the source label "Text" fits comfortably.
    pat_col_w = _EDITOR_PATTERN_COL_W
    truncated_pat = pat_lbl[:max(0, pat_col_w - 1)]
    pat_label = (truncated_pat + arrow).ljust(pat_col_w)
    body_label = body_lbl[: w - pat_col_w - 2].ljust(w - pat_col_w - 2)
    gap = "  "

    def _sort_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _profile_editor_set_hover_sort(True)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _profile_editor_set_focus(1)
            _profile_editor_toggle_sort()
            return None
        return NotImplemented

    def _clear(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _profile_editor_set_hover_sort(False)
            _profile_editor_set_hover_row(None)
            return None
        return NotImplemented

    return [
        (style, pat_label, _sort_handler),
        (base_style, gap, _clear),
        (base_style, body_label, _clear),
    ]


def _editor_clear_outer_hover(ev):
    """Outer fragment hover handler — clears every hover index inside the
    editor when MOUSE_MOVE lands in chrome (padding, blanks, etc.)."""
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _profile_editor_clear_hover()
        return None
    return NotImplemented


def _profile_editor_text():
    """Render the editor frame as a single fragment list.

    Layout (top to bottom):
        ─── Profile editor: <name> ───
        <blank>
        Aliases · Actions · ... · <count> entries
        <blank>
        Pattern▲  Body          │ Pattern
        > <pattern>  <body…>    │ ┌────────────────────┐
        <pattern>  <body>       │ │ <pattern>          │
        …                       │ └────────────────────┘
                                │ Body
                                │ ┌────────────────────┐
                                │ │ <body line 1>      │
                                │ │ <body line 2>      │
                                │ └────────────────────┘
                                │ ─── Hint ───
                                │ Use %1, %2, %3 as ...
        <blank>
        ↑↓ Move · d Delete · Tab Focus tabs · ESC Save & back
    """
    cols = _term_cols()
    name = (_editor_profile_path.stem
            if _editor_profile_path is not None else "")
    title  = f"─── Profile editor: {name} ───"

    frags = []
    frags.append(("", "\n", _editor_clear_outer_hover))
    frags.append(("", _pad_centre(title, cols), _editor_clear_outer_hover))
    frags.append((C_SECTION, title, _editor_clear_outer_hover))
    frags.append(("", "\n", _editor_clear_outer_hover))
    frags.append(("", "\n", _editor_clear_outer_hover))

    # Tab strip — five labels separated by a single space. Active tab is
    # rendered bold+underline (C_ACTIVE); inactive C_ITEM; hover C_HOVER on
    # non-active labels. The active-tab count is right-aligned to `cols`.
    n_tabs = len(_PROFILE_EDITOR_TABS)
    labels = [lbl for (lbl, _k) in _PROFILE_EDITOR_TABS]
    strip_w = sum(len(s) for s in labels) + (n_tabs - 1)  # spaces between
    count_text = f"{_profile_editor_active_count()} entries"

    pad_left  = max(0, (cols - strip_w) // 2)
    pad_right = max(0, cols - pad_left - strip_w - len(count_text))

    frags.append(("", " " * pad_left, _editor_clear_outer_hover))

    for i, label in enumerate(labels):
        is_active = (i == _editor_active_tab)
        is_hover  = (_editor_hover_tab == i and not is_active)
        if is_active:
            style = C_ACTIVE + " underline"
        elif is_hover:
            style = C_HOVER
        else:
            style = C_ITEM

        def _tab_handler(ev, row=i):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                _profile_editor_set_hover_tab(row)
                return None
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _profile_editor_set_tab(row)
                return None
            return NotImplemented

        frags.append((style, label, _tab_handler))
        if i < n_tabs - 1:
            frags.append(("", " ", _editor_clear_outer_hover))

    frags.append(("", " " * pad_right, _editor_clear_outer_hover))
    frags.append((C_HINT, count_text, _editor_clear_outer_hover))
    frags.append(("", "\n", _editor_clear_outer_hover))
    frags.append(("", "\n", _editor_clear_outer_hover))

    # ----- Body region (master/detail) --------------------------------
    body_h    = _editor_body_h()
    visible   = _editor_list_visible()
    view      = _profile_editor_display_view()
    entries_total = len(view)
    sentinel_idx  = entries_total            # index of the "+ New entry" row
    total         = entries_total + 1        # entries + sentinel
    if _editor_list_sb is not None:
        _editor_list_sb.update(total, visible, height=visible)
        _editor_list_sb.scroll_to(_editor_list_scroll)

    # Clamp cursor and scroll defensively (tab switches, deletions, etc.).
    if _editor_list_cursor < 0:
        globals()["_editor_list_cursor"] = 0
    elif _editor_list_cursor >= total:
        globals()["_editor_list_cursor"] = total - 1
    _profile_editor_scroll_into_view()

    # Detail panel content (length == body_h). Sentinel cursor → no
    # entry; `_editor_detail_lines` produces the centred "press Enter"
    # prompt or the empty-state hint.
    cur_entry = (view[_editor_list_cursor]
                 if 0 <= _editor_list_cursor < entries_total else None)
    detail_rows = _editor_detail_lines(cur_entry, body_h)

    # Scrollbar geometry for the data rows (visible cells under header).
    sb_top, sb_thumb_h = _editor_sb_thumb_geom(total, visible, visible)
    sb_visible = total > visible

    left_pad  = _editor_left_pad()
    gap_str   = " " * _EDITOR_GAP
    right_pad = max(0, cols - left_pad - _editor_package_w())

    for body_row in range(body_h):
        # ----- Left column: header (row 0) or data rows (1..body_h-1) -----
        if body_row == 0:
            left_frags = _editor_list_header_frag(visible)
        else:
            data_idx = body_row - 1   # 0..body_h-2 visible data rows index
            if data_idx < visible:
                abs_idx = _editor_list_scroll + data_idx
                is_cursor = (abs_idx == _editor_list_cursor)
                if 0 <= abs_idx < entries_total:
                    is_hover  = (_editor_hover_row == abs_idx and not is_cursor)
                    row_frags = _editor_list_row_text(
                        view[abs_idx], is_cursor, is_hover)

                    def _row_handler(ev, row=abs_idx):
                        if ev.event_type == MouseEventType.MOUSE_MOVE:
                            _profile_editor_set_hover_row(row)
                            _profile_editor_set_hover_sort(False)
                            return None
                        if ev.event_type == MouseEventType.MOUSE_DOWN:
                            _profile_editor_set_focus(1)
                            global _editor_list_cursor
                            _editor_list_cursor = row
                            _profile_editor_scroll_into_view()
                            _editor_refresh_buffers()
                            if _app:
                                _app.invalidate()
                            return None
                        if ev.event_type == MouseEventType.SCROLL_UP:
                            _profile_editor_scroll_list(-1)
                            return None
                        if ev.event_type == MouseEventType.SCROLL_DOWN:
                            _profile_editor_scroll_list(1)
                            return None
                        return NotImplemented

                    left_frags = [
                        (s, t, _row_handler) for (s, t) in row_frags
                    ]
                elif abs_idx == sentinel_idx:
                    # "+ New entry" sentinel row — selectable like any
                    # row; Enter / click creates a fresh blank Entry.
                    is_hover = (_editor_hover_row == abs_idx and not is_cursor)
                    label = "+ New entry"
                    text = label.ljust(_EDITOR_LIST_W)[:_EDITOR_LIST_W]
                    if is_cursor:
                        style = C_SELECTED
                    elif is_hover:
                        style = C_HOVER
                    else:
                        style = C_HINT

                    def _sentinel_handler(ev, row=abs_idx):
                        if ev.event_type == MouseEventType.MOUSE_MOVE:
                            _profile_editor_set_hover_row(row)
                            _profile_editor_set_hover_sort(False)
                            return None
                        if ev.event_type == MouseEventType.MOUSE_DOWN:
                            _profile_editor_set_focus(1)
                            global _editor_list_cursor
                            _editor_list_cursor = row
                            _profile_editor_scroll_into_view()
                            _editor_refresh_buffers()
                            if _app:
                                _app.invalidate()
                            return None
                        if ev.event_type == MouseEventType.SCROLL_UP:
                            _profile_editor_scroll_list(-1)
                            return None
                        if ev.event_type == MouseEventType.SCROLL_DOWN:
                            _profile_editor_scroll_list(1)
                            return None
                        return NotImplemented

                    left_frags = [(style, text, _sentinel_handler)]
                else:
                    # Blank row inside the list panel — wheel still scrolls.
                    def _blank_row_handler(ev):
                        if ev.event_type == MouseEventType.MOUSE_MOVE:
                            _profile_editor_set_hover_row(None)
                            return None
                        if ev.event_type == MouseEventType.SCROLL_UP:
                            _profile_editor_scroll_list(-1)
                            return None
                        if ev.event_type == MouseEventType.SCROLL_DOWN:
                            _profile_editor_scroll_list(1)
                            return None
                        return NotImplemented
                    left_frags = [("", " " * _EDITOR_LIST_W,
                                   _blank_row_handler)]
            else:
                left_frags = [("", " " * _EDITOR_LIST_W,
                               _editor_clear_outer_hover)]

        # ----- Scrollbar cell -----
        if body_row == 0:
            sb_frag = ("", " ", _editor_clear_outer_hover)
        else:
            sb_row = body_row - 1
            if sb_visible and sb_row < visible:
                if sb_top <= sb_row < sb_top + sb_thumb_h:
                    sb_style = "bold fg:#ffffff"
                    sb_ch    = "█"
                else:
                    sb_style = "fg:#585858"
                    sb_ch    = "░"

                def _sb_handler(ev, row=sb_row):
                    if ev.event_type == MouseEventType.MOUSE_DOWN:
                        off = _editor_sb_click_to_offset(
                            row, total, visible, visible)
                        global _editor_list_scroll
                        _editor_list_scroll = off
                        if _editor_list_sb is not None:
                            _editor_list_sb.scroll_to(off)
                        if _app:
                            _app.invalidate()
                        return None
                    if ev.event_type == MouseEventType.MOUSE_MOVE:
                        _profile_editor_set_hover_row(None)
                        return None
                    return NotImplemented

                sb_frag = (sb_style, sb_ch, _sb_handler)
            else:
                sb_frag = ("", " ", _editor_clear_outer_hover)

        # ----- Detail cell -----
        detail_row = detail_rows[body_row]

        # ----- Compose the row -----
        frags.append(("", " " * left_pad, _editor_clear_outer_hover))
        for f in left_frags:
            frags.append(f)
        frags.append(sb_frag)
        frags.append(("", gap_str, _editor_clear_outer_hover))
        # Detail rows mix 2-tuples (plain text) and 3-tuples (per-cell
        # mouse handlers in the editable field areas). Both shapes
        # need to land in the FormattedText stream with a hover-clear
        # fallback for cells that don't carry their own handler.
        for f in detail_row:
            if len(f) == 3 and f[2] is not None:
                frags.append(f)
            else:
                style, text = f[0], f[1]
                frags.append((style, text, _editor_clear_outer_hover))
        if right_pad > 0:
            frags.append(("", " " * right_pad, _editor_clear_outer_hover))
        frags.append(("", "\n", _editor_clear_outer_hover))

    # ----- Footer -----
    frags.append(("", "\n", _editor_clear_outer_hover))
    if _editor_focus == 0:
        footer = ("←→ Switch tab  ·  ↓ Focus list  ·  ESC Save & back")
    elif _editor_focus == 1:
        footer = ("↑↓ Move  ·  Enter Edit  ·  n New  ·  d Delete  ·  "
                  "Tab Cycle  ·  ESC Save & back")
    else:
        footer = ("←→ Cursor  ·  Tab Field  ·  ↑ ↓ Zone  ·  "
                  "ESC Save & back")
    frags.append(("", _pad_centre(footer, cols), _editor_clear_outer_hover))
    frags.append((C_HINT, footer, _editor_clear_outer_hover))
    # Feedback flash slot — one row below the footer. Used by the
    # macro key-capture path to show "Bound to <key>." for a short
    # window after a successful capture.
    if _editor_feedback_text:
        frags.append(("", "\n", _editor_clear_outer_hover))
        frags.append((
            "", _pad_centre(_editor_feedback_text, cols),
            _editor_clear_outer_hover,
        ))
        frags.append((
            _editor_feedback_style, _editor_feedback_text,
            _editor_clear_outer_hover,
        ))
    return frags


# --- Profile editor — feedback flash --------------------------------------
def _editor_set_feedback(text, style, ttl_seconds=2.0):
    """Flash an inline feedback message below the editor footer. Used
    for "Bound to <key>." after a successful key capture."""
    global _editor_feedback_text, _editor_feedback_style
    global _editor_feedback_handle
    _editor_feedback_text  = text
    _editor_feedback_style = style
    if _editor_feedback_handle is not None:
        try:
            _editor_feedback_handle.cancel()
        except Exception:
            pass
        _editor_feedback_handle = None
    if _app_loop is not None:
        _editor_feedback_handle = _app_loop.call_later(
            ttl_seconds, _editor_clear_feedback)
    if _app:
        _app.invalidate()


def _editor_clear_feedback():
    global _editor_feedback_text, _editor_feedback_style
    global _editor_feedback_handle
    _editor_feedback_text  = None
    _editor_feedback_style = ""
    _editor_feedback_handle = None
    if _app:
        _app.invalidate()


# --- Profile editor — macro key-capture overlay ---------------------------
def _editor_push_keybind_overlay(just_created):
    """Push the `profile_editor_macro_keybind` frame. `just_created` is
    True when the overlay was auto-opened by `+ New entry`; on ESC the
    handler then removes the unfilled Entry."""
    global _editor_keybind_error, _editor_keybind_just_created
    _editor_keybind_error        = ""
    _editor_keybind_just_created = just_created
    _push_frame("profile_editor_macro_keybind")


def _editor_keybind_cancel():
    """ESC handler. When the overlay was auto-pushed by `+ New entry`,
    remove the unfilled Entry so the list stays visually consistent."""
    global _editor_keybind_just_created, _editor_list_cursor
    if _editor_keybind_just_created and _editor_data is not None:
        # The just-created entry is the most recent Entry of kind=macro
        # with an empty pattern. There is at most one such entry by
        # construction — `_editor_create_new_entry` appends it last and
        # immediately pushes the overlay before the user can edit.
        for i in range(len(_editor_data.items) - 1, -1, -1):
            it = _editor_data.items[i]
            if (isinstance(it, profile_io.Entry)
                    and it.kind == "macro" and it.pattern == ""):
                del _editor_data.items[i]
                break
        # Re-anchor the cursor — prefer falling onto the sentinel only
        # when no entries remain.
        entries_total = _profile_editor_active_count()
        if entries_total == 0:
            _editor_list_cursor = 0
        else:
            _editor_list_cursor = min(_editor_list_cursor, entries_total)
        _profile_editor_scroll_into_view()
        _editor_refresh_buffers()
    _editor_keybind_just_created = False
    _pop_frame()
    _profile_editor_set_focus(2, field=0)


def _editor_keybind_accept(match):
    """Match handler: write `match.tin_escape` into the current entry's
    pattern, flash the success line, pop the overlay, and move focus to
    Commands so the user can keep typing."""
    global _editor_keybind_just_created
    entry = _editor_current_entry()
    if entry is None:
        # Defensive — the overlay shouldn't be reachable without an
        # entry under the cursor.
        _editor_keybind_just_created = False
        _pop_frame()
        return
    entry.pattern = match.tin_escape
    # Re-sort + re-anchor so the entry's new place in the list lands
    # under the cursor.
    view_after = _profile_editor_display_view()
    try:
        global _editor_list_cursor
        _editor_list_cursor = view_after.index(entry)
        _profile_editor_scroll_into_view()
    except ValueError:
        pass
    auto_opened = _editor_keybind_just_created
    _editor_keybind_just_created = False
    _pop_frame()
    if auto_opened:
        _profile_editor_set_focus(2, field=1)
    else:
        _profile_editor_set_focus(2, field=0)
    _editor_set_feedback(f"Bound to {match.display_name}.", C_ACCENT)


def _editor_keybind_set_error(msg):
    global _editor_keybind_error
    _editor_keybind_error = msg
    if _app:
        _app.invalidate()


def _profile_editor_keybind_text():
    """Render the key-capture overlay — a centred modal panel.

    Layout:
        ─── Bind key ───
        <blank>
        Press the key to bind…
        <blank>
           <error line — only when an attempt failed>
        <blank>
           ESC  Cancel
    """
    cols = _term_cols()
    title  = "─── Bind key ───"
    prompt = "Press the key to bind…"
    footer = "ESC  Cancel"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_SECTION, title))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(prompt, cols)))
    frags.append((C_ITEM, prompt))
    frags.append(("", "\n\n"))
    if _editor_keybind_error:
        frags.append(("", _pad_centre(_editor_keybind_error, cols)))
        frags.append((C_DANGER, _editor_keybind_error))
        frags.append(("", "\n\n"))
    else:
        frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# --- Profile editor — delete-confirm sub-frame ----------------------------
def _profile_editor_delete_text():
    """Render the centred confirm-delete sub-frame. Modeled on
    `profile_delete_confirm` — title and message both use the active
    tab's kind label (alias / action / macro / highlight / substitute),
    and the pattern is routed through `format_entry_pattern` so macros
    show readable key names instead of raw escape sequences."""
    cols = _term_cols()
    if _editor_delete_entry is not None:
        kind    = _editor_delete_entry.kind
        pattern = format_entry_pattern(_editor_delete_entry)
    else:
        kind    = _profile_editor_active_kind()
        pattern = ""
    title  = f"─── Delete {kind} ───"
    msg    = f'Delete {kind} "{pattern}"?'
    footer = "Enter  Confirm · ESC  Cancel"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_SECTION, title))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(msg, cols)))
    frags.append((C_ITEM, msg))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# --- Profile rename --------------------------------------------------------
def _enter_profile_rename():
    global _rename_old_name, _rename_name_buf, _rename_name_err
    name = _profile_current_name()
    if name is None or name == "default":
        return
    _rename_old_name = name
    _rename_name_buf = ""
    _rename_name_err = ""
    _push_frame("profile_rename")


def _profile_rename_text():
    cols = _term_cols()
    title  = "─── Profile ───"
    head   = f'Rename "{_rename_old_name}" to:'
    hint   = "letters and _ only · must start with a letter · max 32"
    footer = "Enter  Confirm · ESC  Cancel"
    line   = f"> {_rename_name_buf}_"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(head, cols)))
    frags.append((C_HINT, head))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(line, cols)))
    frags.append((C_HINT, "> "))
    frags.append((C_ACTIVE, _rename_name_buf))
    frags.append((C_HINT, "_"))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(hint, cols)))
    frags.append((C_HINT, hint))
    if _rename_name_err:
        frags.append(("", "\n\n"))
        frags.append(("", _pad_centre(_rename_name_err, cols)))
        frags.append((C_YELLOW, _rename_name_err))
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


def _profile_rename_confirm():
    """Validate _rename_name_buf and perform the file rename. Pops on success,
    sets _rename_name_err and stays open on validation failure."""
    global _rename_name_err, _profiles, _profile_table_cursor
    new_name = _rename_name_buf
    if new_name == _rename_old_name:
        _pop_frame()
        return
    err = _validate_profile_name(new_name)
    if err:
        _rename_name_err = err
        if _app:
            _app.invalidate()
        return
    src = os.path.join(PROFILES_DIR, f"{_rename_old_name}.tin")
    dst = os.path.join(PROFILES_DIR, f"{new_name}.tin")
    try:
        os.rename(src, dst)
    except OSError as exc:
        _rename_name_err = f"Rename failed: {exc.strerror or exc}"
        if _app:
            _app.invalidate()
        return
    if _conf.get("profile") == _rename_old_name:
        _conf["profile"] = new_name
        _save_conf()
    _profiles = _list_profiles()
    _profile_apply_sort()
    if new_name in _profiles:
        _profile_table_cursor = _profiles.index(new_name)
    _pop_frame()
    _profile_set_feedback(f'Renamed to "{new_name}".', C_ACCENT)


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
    """Pop create frames and refresh the profile list/cursor."""
    global _profiles, _profile_table_cursor, _frame_stack, _current_frame
    while _frame_stack and _current_frame.startswith("profile_create"):
        _current_frame = _frame_stack.pop()
    if _current_frame != "profile":
        # Defensive — collapse anything stale back to main.
        _current_frame = "profile"
    _profiles = _list_profiles()
    _profile_apply_sort()
    cur = _conf.get("profile", "default")
    _profile_table_cursor = 0
    for i, name in enumerate(_profiles):
        if name == cur:
            _profile_table_cursor = i
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
    name = _profile_current_name()
    if name is None:
        return
    _delete_target = name
    _delete_locked = (name == "default")
    _push_frame("profile_delete_confirm")


def _confirm_profile_delete():
    global _profiles, _profile_table_cursor
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
    _profile_apply_sort()
    if _profile_table_cursor >= len(_profiles):
        _profile_table_cursor = max(0, len(_profiles) - 1)
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
# Options frame — top level (Panes / Scripts / Text layout / Connection / Back)
# ---------------------------------------------------------------------------
_OPTIONS_ROWS = [
    ("panes",          "Panes"),
    ("scripts",        "Scripts"),
    ("spotlights",     "Spotlights"),
    ("text_layout",    "Text layout"),
    ("connection",     "Connection"),
    ("back",           "Back"),
]


def _enter_options_frame():
    global _sel_options
    _sel_options = 0
    _push_frame("options")


def _activate_option(idx):
    global _sel_options, _sel_options_panes, _sel_options_connection
    global _sel_options_spotlights
    if idx < 0 or idx >= len(_OPTIONS_ROWS):
        return
    _sel_options = idx
    action, _label = _OPTIONS_ROWS[idx]
    if action == "panes":
        _sel_options_panes = 0
        _push_frame("options_panes")
    elif action == "scripts":
        _enter_scripts_frame()
    elif action == "spotlights":
        _sel_options_spotlights = 0
        _push_frame("options_spotlights")
    elif action == "text_layout":
        _push_frame("options_coming_soon")
    elif action == "connection":
        _sel_options_connection = _current_connection_index()
        _push_frame("options_connection")
    elif action == "back":
        _save_conf()
        _pop_frame()


def _options_text():
    cols   = _term_cols()
    title  = "─── Options ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"

    maxw = max(len(label) for _, label in _OPTIONS_ROWS)
    pad  = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    back_idx = len(_OPTIONS_ROWS) - 1

    for i, (action, label) in enumerate(_OPTIONS_ROWS):
        if i == back_idx:
            frags.append(("", "\n"))  # blank before Back

        is_active = (i == _sel_options)
        is_hover  = (i == _hover_options)
        # Text layout is a placeholder row — render its inactive state in
        # C_HINT (no bg fill) so it reads as "not ready yet" without the
        # disabled-button look. Active / hover still use the normal styles.
        inactive  = C_HINT if action == "text_layout" else C_ITEM
        style     = _row_style(is_active, is_hover, inactive)
        prefix    = "<< " if is_active else "   "
        suffix    = " >>" if is_active else "   "

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
# Options — Panes submenu
# ---------------------------------------------------------------------------
# Rows produced as (kind, payload):
#   "pane"    payload=(pane_target, label)
#   "sep"
#   "headers"
#   "back"
def _options_panes_rows():
    rows = []
    for target, label, _, _ in _PANE_OPTIONS:
        rows.append(("pane", (target, label)))
    rows.append(("sep", None))
    rows.append(("headers", None))
    rows.append(("sep", None))
    rows.append(("back", None))
    return rows


def _options_panes_selectable_indices():
    return [i for i, (k, _) in enumerate(_options_panes_rows()) if k != "sep"]


def _enter_options_pane_frame(target):
    """Push the per-pane subframe for `target` (status/buffs/...)."""
    global _options_pane_target, _sel_options_pane
    _options_pane_target = target
    _sel_options_pane = 0
    _push_frame("options_pane")


def _options_panes_activate(row_idx):
    rows = _options_panes_rows()
    if not (0 <= row_idx < len(rows)):
        return
    kind, payload = rows[row_idx]
    if kind == "pane":
        target, _ = payload
        _enter_options_pane_frame(target)
    elif kind == "headers":
        key = "show_pane_dividers"
        _conf[key] = "0" if _conf.get(key) == "1" else "1"
        if _app:
            _app.invalidate()
    elif kind == "back":
        _save_conf()
        _pop_frame()


def _options_panes_text():
    cols   = _term_cols()
    title  = "─── Panes ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"

    rows = _options_panes_rows()
    sel_indices = _options_panes_selectable_indices()
    sel_pos = (_sel_options_panes
               if 0 <= _sel_options_panes < len(sel_indices)
               else 0)
    sel_row = sel_indices[sel_pos] if sel_indices else -1

    # Pre-compute labels for width measurement.
    labels = []
    for kind, payload in rows:
        if kind == "pane":
            _, lbl = payload
            labels.append(lbl)
        elif kind == "sep":
            labels.append("")
        elif kind == "headers":
            box = "[x]" if _conf.get("show_pane_dividers") == "1" else "[ ]"
            labels.append(f"{box} Display pane headers")
        elif kind == "back":
            labels.append("Back")
    maxw = max((len(l) for l in labels), default=0)
    pad  = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    for i, (kind, payload) in enumerate(rows):
        if kind == "sep":
            frags.append(("", "\n"))
            continue

        label = labels[i]
        if kind == "back":
            label = "Back"
        is_active = (i == sel_row)
        is_hover  = (i == _hover_options_panes)
        style     = _row_style(is_active, is_hover)
        prefix    = "<< " if is_active else "   "
        suffix    = " >>" if is_active else "   "

        def _make_handler(row=i, pos=(sel_indices.index(i) if i in sel_indices else 0)):
            def _h(ev):
                global _sel_options_panes
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options_panes", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _sel_options_panes = pos
                    _options_panes_activate(row)
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
# Options — per-pane subframe (Enabled + colour radios + Back)
# ---------------------------------------------------------------------------
# Row layout:
#   0  Enabled toggle
#   1  blank
#   2  "Pane color" section label   (non-selectable)
#   3..9  colour radios (7)
#   10 blank
#   11 Back
_PANE_FRAME_ENABLED   = 0
_PANE_FRAME_SECTION   = 2
_PANE_FRAME_COLOR_LO  = 3
_PANE_FRAME_COLOR_HI  = _PANE_FRAME_COLOR_LO + len(PANE_COLOR_ORDER) - 1
_PANE_FRAME_BACK      = _PANE_FRAME_COLOR_HI + 2
_PANE_FRAME_TOTAL     = _PANE_FRAME_BACK + 1


def _options_pane_selectable_indices():
    out = [_PANE_FRAME_ENABLED]
    out.extend(range(_PANE_FRAME_COLOR_LO, _PANE_FRAME_COLOR_HI + 1))
    out.append(_PANE_FRAME_BACK)
    return out


def _current_pane_meta():
    for target, label, show_key, color_key in _PANE_OPTIONS:
        if target == _options_pane_target:
            return target, label, show_key, color_key
    # fallback — should not happen
    return _PANE_OPTIONS[0]


def _options_pane_activate(row_idx):
    target, _label, show_key, color_key = _current_pane_meta()
    if row_idx == _PANE_FRAME_ENABLED:
        _conf[show_key] = "0" if _conf.get(show_key) == "1" else "1"
        if _app:
            _app.invalidate()
        return
    if _PANE_FRAME_COLOR_LO <= row_idx <= _PANE_FRAME_COLOR_HI:
        name = PANE_COLOR_ORDER[row_idx - _PANE_FRAME_COLOR_LO]
        _conf[color_key] = name
        if _app:
            _app.invalidate()
        return
    if row_idx == _PANE_FRAME_BACK:
        _save_conf()
        _pop_frame()


def _options_pane_text():
    cols = _term_cols()
    target, label, show_key, color_key = _current_pane_meta()
    title  = f"─── {label} pane ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"

    enabled = (_conf.get(show_key) == "1")
    cur_color = _conf.get(color_key, "black")

    # Build labels and inactive styles per row index.
    rows = []  # (label_text, kind)
    enabled_label = ("[x] Enabled" if enabled else "[ ] Enabled")
    rows.append((enabled_label, "toggle"))
    rows.append(("", "sep"))
    rows.append(("Pane color", "section"))
    for name in PANE_COLOR_ORDER:
        dot = "(•)" if cur_color == name else "( )"
        rows.append((f"{dot} {name.capitalize()}", "radio"))
    rows.append(("", "sep"))
    rows.append(("Back", "back"))

    # Width of the longest left-block label (enabled / radios / Back / section).
    # Colour swatch (3 cells) plus separator are added in their own fragments.
    label_w = max(len(r[0]) for r in rows if r[1] != "sep")

    # Compute centring pad. The visible row width is:
    #   prefix(3) + label_w + suffix(3)             (toggle / section / back)
    #   prefix(3) + label_w + "  " + 3 swatches(3)  (radio)
    # Use the wider of the two so the column stays aligned.
    radio_extra = 2 + 3  # "  " gap + 3-cell swatch
    block_w = max(label_w + 6, label_w + 6 + radio_extra)
    pad = max(0, (cols - block_w) // 2)

    sel = _sel_options_pane
    sel_indices = _options_pane_selectable_indices()
    if not (0 <= sel < len(sel_indices)):
        sel = 0
    sel_row = sel_indices[sel]

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    for i, (text, kind) in enumerate(rows):
        if kind == "sep":
            frags.append(("", "\n"))
            continue

        if kind == "section":
            # Non-selectable section label, no prefix/suffix decoration.
            frags.append(("", " " * (pad + 3)))
            frags.append((C_SECTION, text))
            frags.append(("", "\n"))
            continue

        is_active = (i == sel_row)
        is_hover  = (i == _hover_options_pane)
        style     = _row_style(is_active, is_hover)
        prefix    = "<< " if is_active else "   "
        suffix    = " >>" if is_active else "   "

        # Per-row sel_pos for the click handler.
        try:
            sel_pos = sel_indices.index(i)
        except ValueError:
            sel_pos = 0

        def _make_handler(row=i, pos=sel_pos):
            def _h(ev):
                global _sel_options_pane
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options_pane", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _sel_options_pane = pos
                    _options_pane_activate(row)
            return _h

        h = _make_handler()

        # Left padding to centre the block. For radio rows, pad so the label
        # column lines up with toggle/back (which have no swatch). Both block
        # widths share the same left edge — pad is the block-centring offset.
        frags.append(("", " " * pad))
        frags.append((style, prefix, h))
        # Label, left-aligned in a fixed-width column.
        padded_label = text + " " * max(0, label_w - len(text))
        frags.append((style, padded_label, h))

        if kind == "radio":
            # Trailing colour swatch: 3 full-block glyphs. Solid fill for
            # every entry; Black is a true #000000 swatch even though the
            # actual pane keeps the terminal default bg.
            color_name = PANE_COLOR_ORDER[i - _PANE_FRAME_COLOR_LO]
            hex_color  = PANE_COLORS.get(color_name)
            frags.append((style, "  ", h))
            if hex_color is None:
                frags.append(("bg:#000000 fg:#000000", "███", h))
            else:
                frags.append((f"bg:{hex_color} fg:{hex_color}", "███", h))

        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Options — Connection submenu
# ---------------------------------------------------------------------------
def _current_connection_index():
    cur = _conf.get("connection_mode", "mmapper")
    for i, (mode, _label, _detail) in enumerate(_CONNECTION_MODES):
        if mode == cur:
            return i
    return 0


def _options_connection_activate(idx):
    global _sel_options_connection
    n = len(_CONNECTION_MODES) + 1  # + Back
    if not (0 <= idx < n):
        return
    _sel_options_connection = idx
    if idx == len(_CONNECTION_MODES):
        # Back
        _save_conf()
        _pop_frame()
        return
    mode, _label, _detail = _CONNECTION_MODES[idx]
    _conf["connection_mode"] = mode
    if _app:
        _app.invalidate()
    if mode == "custom":
        _enter_options_connection_custom_frame()


def _options_connection_text():
    cols   = _term_cols()
    title  = "─── Connection ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"

    cur = _conf.get("connection_mode", "mmapper")
    host = _conf.get("connection_host", "localhost")
    port = _conf.get("connection_port", "4242")
    custom_detail = f"<{host}>:<{port}>"

    rows = []
    for mode, lbl, detail in _CONNECTION_MODES:
        dot = "(•)" if cur == mode else "( )"
        if mode == "custom":
            rows.append((f"{dot} {lbl}", custom_detail, mode))
        else:
            rows.append((f"{dot} {lbl}", detail, mode))
    rows.append(("Back", None, None))

    # Width: left label + 2-space gap + widest detail
    label_w  = max(len(r[0]) for r in rows)
    detail_w = max((len(r[1]) for r in rows if r[1]), default=0)
    block_w  = label_w + (2 + detail_w if detail_w else 0) + 6  # +6 for << / >>
    pad      = max(0, (cols - block_w) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    back_idx = len(rows) - 1

    for i, (left, detail, mode) in enumerate(rows):
        if i == back_idx:
            frags.append(("", "\n"))

        is_active = (i == _sel_options_connection)
        is_hover  = (i == _hover_options_connection)
        style     = _row_style(is_active, is_hover)
        prefix    = "<< " if is_active else "   "
        suffix    = " >>" if is_active else "   "

        def _make_handler(row=i):
            def _h(ev):
                global _sel_options_connection
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options_connection", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _sel_options_connection = row
                    _options_connection_activate(row)
            return _h

        h = _make_handler()

        frags.append(("", " " * pad))
        frags.append((style, prefix, h))

        padded_left = left + " " * max(0, label_w - len(left))
        frags.append((style, padded_left, h))

        if detail is not None:
            frags.append((style, "  ", h))
            # Highlight Custom's host:port string in C_ACTIVE-ish when active,
            # otherwise dim C_HINT.
            if mode == "custom" and cur == "custom":
                frags.append((C_ACCENT, detail, h))
            else:
                frags.append((C_HINT, detail, h))

        frags.append((style, suffix, h))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# ---------------------------------------------------------------------------
# Options — Connection custom host:port input frame
# ---------------------------------------------------------------------------
def _enter_options_connection_custom_frame():
    global _conn_host_buf, _conn_port_buf, _conn_field, _conn_err
    _conn_host_buf = _conf.get("connection_host", "localhost") or "localhost"
    _conn_port_buf = _conf.get("connection_port", "4242") or "4242"
    _conn_field    = 0
    _conn_err      = ""
    _push_frame("options_connection_custom")


def _validate_connection_custom():
    host = _conn_host_buf.strip()
    port = _conn_port_buf.strip()
    if not host:
        return "Host cannot be empty."
    if not port.isdigit():
        return "Port must be numeric."
    p = int(port)
    if p < 1 or p > 65535:
        return "Port must be between 1 and 65535."
    return ""


def _options_connection_custom_save():
    global _conn_err
    err = _validate_connection_custom()
    if err:
        _conn_err = err
        if _app:
            _app.invalidate()
        return
    _conf["connection_host"] = _conn_host_buf.strip()
    _conf["connection_port"] = _conn_port_buf.strip()
    _conf["connection_mode"] = "custom"
    _save_conf()
    _pop_frame()


def _options_connection_custom_text():
    cols   = _term_cols()
    title  = "─── Custom Connection ───"
    hint   = "Tab to switch field · Enter to save · ESC to cancel"

    host_label = "Host: "
    port_label = "Port: "
    host_line  = f"{host_label}{_conn_host_buf}"
    port_line  = f"{port_label}{_conn_port_buf}"

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n\n"))

    # Host field
    cursor_host = "_" if _conn_field == 0 else ""
    full_host = f"{host_label}{_conn_host_buf}{cursor_host}"
    frags.append(("", _pad_centre(full_host, cols)))
    frags.append((C_HINT, host_label))
    frags.append((C_ACTIVE if _conn_field == 0 else C_ITEM, _conn_host_buf))
    if _conn_field == 0:
        frags.append((C_HINT, "_"))
    frags.append(("", "\n\n"))

    # Port field
    cursor_port = "_" if _conn_field == 1 else ""
    full_port = f"{port_label}{_conn_port_buf}{cursor_port}"
    frags.append(("", _pad_centre(full_port, cols)))
    frags.append((C_HINT, port_label))
    frags.append((C_ACTIVE if _conn_field == 1 else C_ITEM, _conn_port_buf))
    if _conn_field == 1:
        frags.append((C_HINT, "_"))
    frags.append(("", "\n"))

    if _conn_err:
        frags.append(("", "\n"))
        frags.append(("", _pad_centre(_conn_err, cols)))
        frags.append((C_ERR, _conn_err))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    frags.append(("", _pad_centre(hint, cols)))
    frags.append((C_HINT, hint))
    return frags


# ---------------------------------------------------------------------------
# Options — Spotlights submenu
# ---------------------------------------------------------------------------
# Per-kind toggles for the spotlight reel. (conf_key, label) — flipping a
# toggle writes "0" / "1" into startup.conf; the spotlight aggregator reads
# the same keys and skips disabled JSONL event kinds before building the
# reel. Missing keys default to enabled ("1").
_SPOTLIGHT_TOGGLES = [
    ("spotlights_show_deaths",       "Deaths"),
    ("spotlights_show_levelups",     "Level-ups"),
    ("spotlights_show_pvp",          "PvP kills"),
    ("spotlights_show_achievements", "Achievements"),
]


# Rows: ("toggle", conf_key, label) | ("sep", None, None) | ("back", None, None)
def _options_spotlights_rows():
    rows = [("toggle", key, label) for key, label in _SPOTLIGHT_TOGGLES]
    rows.append(("sep",  None, None))
    rows.append(("back", None, None))
    return rows


def _options_spotlights_selectable_indices():
    return [i for i, (k, _, _) in enumerate(_options_spotlights_rows()) if k != "sep"]


def _options_spotlights_activate(row_idx):
    rows = _options_spotlights_rows()
    if not (0 <= row_idx < len(rows)):
        return
    kind, key, _label = rows[row_idx]
    if kind == "toggle":
        _conf[key] = "0" if _conf.get(key) == "1" else "1"
        if _app:
            _app.invalidate()
    elif kind == "back":
        _save_conf()
        _pop_frame()


def _options_spotlights_text():
    cols   = _term_cols()
    title  = "─── Spotlights ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"

    rows = _options_spotlights_rows()
    sel_indices = _options_spotlights_selectable_indices()
    sel_pos = (_sel_options_spotlights
               if 0 <= _sel_options_spotlights < len(sel_indices)
               else 0)
    sel_row = sel_indices[sel_pos] if sel_indices else -1

    labels = []
    for kind, key, label in rows:
        if kind == "toggle":
            box = "[x]" if _conf.get(key) == "1" else "[ ]"
            labels.append(f"{box} {label}")
        elif kind == "sep":
            labels.append("")
        elif kind == "back":
            labels.append("Back")
    maxw = max((len(l) for l in labels), default=0)
    pad  = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    for i, (kind, _key, _label) in enumerate(rows):
        if kind == "sep":
            frags.append(("", "\n"))
            continue

        label = labels[i]
        is_active = (i == sel_row)
        is_hover  = (i == _hover_options_spotlights)
        style     = _row_style(is_active, is_hover)
        prefix    = "<< " if is_active else "   "
        suffix    = " >>" if is_active else "   "

        def _make_handler(row=i, pos=(sel_indices.index(i) if i in sel_indices else 0)):
            def _h(ev):
                global _sel_options_spotlights
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options_spotlights", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _sel_options_spotlights = pos
                    _options_spotlights_activate(row)
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
# Options — "Coming soon" placeholder for Game text-layout
# ---------------------------------------------------------------------------
_COMING_SOON_BODY = (
    "Text layout — coming soon. Will let you choose colour and "
    "description profiles (PK / Minimalistic / Role-play) and configure "
    "text substitutions. Font cannot be changed."
)


_SPOTLIGHTS_EMPTY_BODY = (
    "No spotlights yet. Play a session and your highlights — kills, deaths, "
    "level-ups, and achievements — will be captured here, ready to replay."
)
_SPOTLIGHTS_EMPTY_FILTERED_BODY = (
    "All matching event kinds are disabled. Enable some in Options → "
    "Spotlights to see content here."
)

# Set by _enter_spotlights to pick which empty-state copy to render.
# "no_data" — original message (no events of any kind anywhere).
# "filtered" — at least one per-kind toggle is off (cheap shortcut: the
# user may actually have no data either, but the filtered copy still
# nudges them toward Options → Spotlights, which is the useful pointer).
_spotlights_empty_reason = "no_data"


def _spotlights_empty_text():
    cols = _term_cols()
    title  = "─── Spotlights ───"
    footer = "Any key to return"
    body_w = max(20, min(72, cols - 4))
    body = (_SPOTLIGHTS_EMPTY_FILTERED_BODY
            if _spotlights_empty_reason == "filtered"
            else _SPOTLIGHTS_EMPTY_BODY)
    wrapped = _wrap_text(body, body_w)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))
    for line in wrapped:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((C_BODY, line))
        frags.append(("", "\n"))
    frags.append(("", "\n"))
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


def _options_coming_soon_text():
    cols = _term_cols()
    title  = "─── Text layout ───"
    footer = "Any key to return"
    body_w = max(20, min(72, cols - 4))
    wrapped = _wrap_text(_COMING_SOON_BODY, body_w)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))
    for line in wrapped:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((C_BODY, line))
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

# Options widget buttons. (label, action_id). Order matters: cursor moves
# top-to-bottom and ↑/↓ skips disabled rows. Back is the keyboard ESC made
# clickable; always enabled.
_HISTORY_BUTTONS = [
    ("Run log", "run_log"),
    ("Stats",   "statistics"),
    ("Rate",    "rate"),
    ("Save",    "save"),
    ("Export",  "export"),
    ("Delete",  "delete"),
    ("Back",    "back"),
]
# Button column width: longest label + 1 cell of padding on each side.
_HISTORY_BUTTON_W = max(len(lbl) for lbl, _ in _HISTORY_BUTTONS) + 2
# 1-cell gap between the table's scrollbar column and the buttons.
_HISTORY_OPTIONS_GAP = 1


def _history_table_panel_w():
    """Total width of the table content (column widths + per-gap separators)."""
    _, total = _history_table_columns_layout()
    return total


def _history_package_width():
    """Width of the centred [table | scrollbar | gap | options] package."""
    # scrollbar(1) + gap(_HISTORY_OPTIONS_GAP) + button column(_HISTORY_BUTTON_W).
    return _history_table_panel_w() + 1 + _HISTORY_OPTIONS_GAP + _HISTORY_BUTTON_W


def _history_left_pad():
    """Left padding (cells) that centres the package on the current terminal."""
    return max(0, (_term_cols() - _history_package_width()) // 2)


def _enter_history_frame():
    global _history_filter_items, _history_filter, _history_sort
    global _history_filter_cursor
    global _history_table_cursor, _history_table_scroll
    global _history_menu_cursor
    global _history_focused, _history_hover
    global _history_table_sb
    try:
        chars = run_stats.list_characters_with_runs()
    except Exception:
        chars = []
    _history_filter_items   = ["All"] + chars
    _history_filter         = "All"
    _history_sort           = ("Char", "asc")
    _history_filter_cursor  = 0
    _history_table_cursor   = 0
    _history_table_scroll   = 0
    _history_focused        = 1
    _history_hover          = (None, None)
    _history_table_sb = Scrollbar(
        0, _history_table_visible(), _history_table_visible(),
    )
    _history_refresh_sessions()
    _history_clear_feedback()
    enabled = _history_menu_enabled_indices()
    _history_menu_cursor = enabled[0] if enabled else 0
    _push_frame("history")


def _history_table_visible():
    """Visible data rows in the table — data-fit, with a floor so the Options
    column never clips.

    Outer chrome (title 3 + footer 2 = 5) plus inner chrome (filter header 1 +
    pill row 1 + blank above table 1 + feedback row 1 + table header row 1
    = 5) reserves 10 terminal rows. Options is 1 header + N buttons; the
    table window is `visible + 1` rows (header + data), so visible must be
    at least len(_HISTORY_BUTTONS) for the Options widget to render in
    full."""
    max_by_terminal = max(1, _term_rows() - 3 - 2 - 5)
    options_min = len(_HISTORY_BUTTONS)
    return min(max_by_terminal, max(options_min, len(_history_sessions)))


def _history_table_window_h():
    """Table window height = data rows + 1 header row."""
    return _history_table_visible() + 1


def _history_load_sessions_for_filter():
    if _history_filter == "All":
        out = []
        for ch in _history_filter_items[1:]:
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
    # "Saved" sorts above any "N days" value in either direction. Use a
    # 2-tuple (group, value) so the "Saved" group always pivots together
    # and numerics order normally within their group.
    return {
        "Char":    lambda s: s.character.lower(),
        "Date":    lambda s: s.start_ts,
        "Time":    lambda s: s.start_ts,
        "Dur.":    lambda s: s.duration_seconds,
        "Expires": lambda s: (0 if s.saved else 1, _history_expires_days(s) or 0),
        "Rating":  lambda s: (0 if s.saved else 1, s.rating or 0),
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
    if name not in _history_filter_items:
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


def _history_expires_days(session):
    """Days remaining before retention prunes the session's oldest run.
    Floored at 0. Returns None when the session is saved (no expiry)."""
    if session.saved:
        return None
    if not session.run_ids:
        return 0
    # The chain is sorted oldest-first by list_sessions; chain[0] = oldest.
    # _summarize_run extracts start_ts from the first row, which matches
    # the run-id timestamp used by run_retention.
    try:
        oldest_ts = int(_run_id_to_ts(session.run_ids[0]))
    except (TypeError, ValueError, OSError):
        oldest_ts = int(session.start_ts)
    now = int(time.time())
    secs_left = oldest_ts + 14 * 86400 - now
    days = -(-secs_left // 86400)   # ceil division
    return max(0, days)


def _run_id_to_ts(run_id):
    """Parse a run-id like '2026-05-13T16-13-47' to a local-time epoch."""
    return int(time.mktime(time.strptime(run_id, "%Y-%m-%dT%H-%M-%S")))


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
    chars = _history_filter_items[1:]
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


def _history_move_filter(delta):
    global _history_filter_cursor
    n = len(_history_filter_items)
    if not n:
        return
    new_cursor = (_history_filter_cursor + delta) % n
    _history_filter_cursor = new_cursor
    _history_set_filter(_history_filter_items[new_cursor])


def _history_jump_filter(target):
    global _history_filter_cursor
    n = len(_history_filter_items)
    if not n:
        return
    new_cursor = max(0, min(n - 1, target))
    _history_filter_cursor = new_cursor
    _history_set_filter(_history_filter_items[new_cursor])


def _history_apply_cursor_filter():
    """Re-apply the cursor pill's filter (no-op visually if unchanged)."""
    if 0 <= _history_filter_cursor < len(_history_filter_items):
        _history_set_filter(_history_filter_items[_history_filter_cursor])


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
    """Wheel scroll for panel under cursor. Does NOT move cursor.
    Only the table panel (1) supports scrolling — pills and menu are no-ops."""
    global _history_table_scroll
    if panel != 1:
        return
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


def _history_cycle_focus(delta):
    _history_set_focus((_history_focused + delta) % 3)


def _history_set_hover(panel, row):
    global _history_hover
    new_val = (panel, row)
    if _history_hover == new_val:
        return
    _history_hover = new_val
    if _app:
        _app.invalidate()


def _hover_at(panel, idx, on_event=None):
    """Mouse handler factory for the history frame.

    On MOUSE_MOVE, sets _history_hover to (panel, idx) — pass None for
    either arg to clear hover. Other events are delegated to on_event(ev)
    if provided. Anything we don't handle returns NotImplemented so that
    _WheelScrollControl still sees scroll-wheel events."""
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


def _history_open_detail_for(summary):
    """Aggregate the chain and push the history_detail frame for `summary`."""
    global _history_detail_summary, _history_detail_stats
    global _history_detail_kills_sort, _history_detail_pkills_sort
    global _history_detail_focused
    try:
        stats = run_stats.aggregate(summary.character, summary.run_ids)
    except Exception:
        stats = None
    _history_detail_summary    = summary
    _history_detail_stats      = stats
    _history_detail_kills_sort  = ("XP tot", "desc")
    _history_detail_pkills_sort = ("XP", "desc")
    _history_detail_focused     = 0
    _hd_ensure_scrollbars()
    for sb in (_history_detail_kills_sb, _history_detail_pkills_sb,
               _history_detail_allies_sb, _history_detail_achievements_sb):
        sb.scroll_to(0)
    _push_frame("history_detail")


def _history_activate_table_row(idx):
    """Move cursor to idx and open log_view when the row has a log.
    No-op when the row has no log — Stats has its own Options button now."""
    global _history_table_cursor
    if idx < 0 or idx >= len(_history_sessions):
        return
    _history_table_cursor = idx
    summary = _history_sessions[idx]
    if not summary.has_log:
        return
    _history_play_log(summary)


def _history_refresh_summary_meta(summary):
    """Recompute summary.saved and summary.rating from disk so a row reflects
    meta-file truth immediately after a Save / Rate write."""
    import run_meta
    saved = False
    best = None
    for run_id in summary.run_ids:
        meta = run_meta.read_meta(summary.character, run_id)
        if not meta or meta.get("saved") is not True:
            continue
        saved = True
        try:
            r = max(0, min(5, int(meta.get("rating", 0))))
        except (TypeError, ValueError):
            r = 0
        if best is None or r > best:
            best = r
    summary.saved  = saved
    summary.rating = best if saved else None


# --- Action menu state -----------------------------------------------------
def _history_current_summary():
    if 0 <= _history_table_cursor < len(_history_sessions):
        return _history_sessions[_history_table_cursor]
    return None


def _history_menu_actions():
    """Return [(label, action_id, enabled), ...] for the current selection.

    Order matches _HISTORY_BUTTONS so cursor indices line up."""
    summary = _history_current_summary()
    has = summary is not None
    return [
        ("Run log", "run_log",    has and bool(summary.has_log)),
        ("Stats",   "statistics", has),
        ("Rate",    "rate",       has),
        ("Save",    "save",       has and not summary.saved),
        ("Export",  "export",     has and bool(summary.has_log)),
        ("Delete",  "delete",     has),
        ("Back",    "back",       True),
    ]


def _history_menu_enabled_indices():
    return [i for i, (_, _, en) in enumerate(_history_menu_actions()) if en]


def _history_menu_move(delta):
    """Move Options cursor through enabled buttons. Wraps."""
    global _history_menu_cursor
    enabled = _history_menu_enabled_indices()
    if not enabled:
        return
    if _history_menu_cursor in enabled:
        idx = enabled.index(_history_menu_cursor)
        new_idx = (idx + delta) % len(enabled)
    else:
        if delta >= 0:
            new_idx = next((j for j, ei in enumerate(enabled)
                            if ei > _history_menu_cursor), 0)
        else:
            forward = [j for j, ei in enumerate(enabled)
                       if ei < _history_menu_cursor]
            new_idx = forward[-1] if forward else len(enabled) - 1
    _history_menu_cursor = enabled[new_idx]
    if _app:
        _app.invalidate()


def _history_menu_activate(idx):
    """Run the action for Options button `idx` if enabled."""
    actions = _history_menu_actions()
    if not (0 <= idx < len(actions)):
        return
    _label, action, enabled = actions[idx]
    if not enabled:
        return
    if action == "save":
        _history_action_save()
    elif action == "rate":
        _history_action_rate()
    elif action == "statistics":
        _history_action_statistics()
    elif action == "run_log":
        _history_action_run_log()
    elif action == "export":
        _history_action_export()
    elif action == "delete":
        _history_action_delete()
    elif action == "back":
        _pop_frame()


def _history_action_save():
    summary = _history_current_summary()
    if summary is None or summary.saved:
        return
    import run_meta
    run_meta.save_run_chain(summary.character, summary.run_ids, 0)
    _history_refresh_summary_meta(summary)
    if _app:
        _app.invalidate()


def _history_action_rate():
    summary = _history_current_summary()
    if summary is None:
        return
    _enter_history_rate_frame(summary)


def _history_action_statistics():
    summary = _history_current_summary()
    if summary is None:
        return
    _history_open_detail_for(summary)


def _history_action_run_log():
    summary = _history_current_summary()
    if summary is None or not summary.has_log:
        return
    _history_play_log(summary)


def _history_play_log(summary):
    """Open log_view directly for `summary` without routing through
    history_detail. has_log gating is the caller's responsibility."""
    _enter_log_view(summary)


# --- Export action ---------------------------------------------------------
_HISTORY_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
_HISTORY_LOG_LINE_RE = re.compile(r"^\d+\s")


def _history_export_clean_line(line):
    """Strip the `\\d+ ` timestamp prefix, leading `> ` outbound marker, and
    any ANSI SGR escapes. Returns the cleaned line without a trailing
    newline."""
    line = line.rstrip("\n")
    line = _HISTORY_LOG_LINE_RE.sub("", line, count=1)
    if line.startswith("> "):
        line = line[2:]
    return _HISTORY_ANSI_SGR_RE.sub("", line)


def _history_export_dest_path(character, first_run_id):
    home = os.path.expanduser("~")
    base = f"mume-{character}-{first_run_id}"
    candidate = os.path.join(home, base + ".txt")
    suffix = 2
    while os.path.exists(candidate):
        candidate = os.path.join(home, f"{base}-{suffix}.txt")
        suffix += 1
    return candidate


def _history_action_export():
    """Concatenate all .log files for the cursor session's chain, strip
    timestamp/outbound/ANSI noise, and write to ~/mume-<char>-<first>.txt."""
    summary = _history_current_summary()
    if summary is None or not summary.has_log:
        return
    if not summary.run_ids:
        return
    char_dir = os.path.join(PROJECT_DIR, "data", "runs", summary.character)
    dest = _history_export_dest_path(summary.character, summary.run_ids[0])
    try:
        with open(dest, "w", encoding="utf-8") as out:
            first_chunk = True
            for run_id in summary.run_ids:
                log_path = os.path.join(char_dir, run_id + ".log")
                if not os.path.exists(log_path):
                    continue
                if not first_chunk:
                    out.write("\n")
                first_chunk = False
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    for raw in f:
                        out.write(_history_export_clean_line(raw) + "\n")
    except OSError as exc:
        _history_set_feedback(f"Export failed: {exc.strerror or exc}", C_HINT)
        return
    home = os.path.expanduser("~")
    pretty = dest
    if dest.startswith(home + os.sep):
        pretty = "~" + dest[len(home):]
    _history_set_feedback(f"Saved to {pretty}", C_ACCENT)


# --- Delete action ---------------------------------------------------------
def _history_action_delete():
    """Push the delete-confirm frame anchored to the cursor row."""
    summary = _history_current_summary()
    if summary is None:
        return
    _enter_history_delete_confirm_frame(summary)


def _history_delete_session(summary):
    """Remove every .jsonl / .log / .meta.json for the chain's run_ids.

    Per-file OSError is swallowed — best-effort cleanup, matches the
    retention sweep's defensive style. Bypasses summary.saved (the
    confirm frame is the safety net; see ADR 0075)."""
    char_dir = os.path.join(PROJECT_DIR, "data", "runs", summary.character)
    for run_id in summary.run_ids:
        for ext in (".jsonl", ".log", ".meta.json"):
            path = os.path.join(char_dir, run_id + ext)
            try:
                os.remove(path)
            except OSError:
                pass


def _history_set_feedback(text, style, ttl_seconds=3.0):
    """Flash an inline feedback message below the Options widget."""
    global _history_feedback_text, _history_feedback_style
    global _history_feedback_handle
    _history_feedback_text  = text
    _history_feedback_style = style
    if _history_feedback_handle is not None:
        try:
            _history_feedback_handle.cancel()
        except Exception:
            pass
        _history_feedback_handle = None
    if _app_loop is not None:
        _history_feedback_handle = _app_loop.call_later(
            ttl_seconds, _history_clear_feedback)
    if _app:
        _app.invalidate()


def _history_clear_feedback():
    global _history_feedback_text, _history_feedback_style
    global _history_feedback_handle
    _history_feedback_text  = None
    _history_feedback_style = ""
    _history_feedback_handle = None
    if _app:
        _app.invalidate()


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
    footer = "↑↓ Cursor · Tab Cycle · Enter Activate · ESC Back"
    return _hover_clear_frags([
        ("", "\n"),
        ("", _pad_centre(footer, cols)),
        (C_HINT, footer),
    ])


# --- Filter row (header + pills) ------------------------------------------
def _history_filter_header_text():
    pad_left = _history_left_pad()
    label = "Filter"
    style = C_ACTIVE if _history_focused == 0 else C_SECTION
    return _hover_clear_frags([
        ("", " " * pad_left),
        (style, label),
    ])


def _history_filter_pills_text():
    items = _history_filter_items
    if not items:
        return [("", "")]
    pad_left = _history_left_pad()

    hover_panel, hover_row = _history_hover
    frags = [("", " " * pad_left, _hover_at(None, None))]

    for i, label in enumerate(items):
        is_cursor = (i == _history_filter_cursor)
        is_hover  = (hover_panel == 0 and hover_row == i and not is_cursor)
        if is_cursor:
            style = C_SELECTED
        elif is_hover:
            style = C_HOVER
        else:
            style = C_ITEM

        def _click(ev, row=i):
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                _history_set_focus(0)
                _history_jump_filter(row)
                return None
            return NotImplemented

        # Pills are adjacent — leading + trailing single space of padding.
        pill_text = " " + label + " "
        frags.append((style, pill_text, _hover_at(0, i, on_event=_click)))
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
    """Return list of (text, style) per column.

    Note: Rating cells embed the literal star glyph; their display width
    matches their character width because ★ is single-cell."""
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
        elif key == "Expires":
            if session.saved:
                txt = "Saved"[:width].ljust(width)
                style = C_ACCENT
            else:
                days = _history_expires_days(session)
                txt = f"{days} days"[:width].ljust(width)
                style = _S_LABEL
        elif key == "Rating":
            r = session.rating or 0
            stars = "★" * r
            txt = stars[:width].ljust(width)
            style = _S_STAR
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


# --- Options widget render (right side of the runs table) ------------------
def _history_options_text():
    """Render the Options column: 'Options' header + 5 flat buttons stacked
    with no inter-button gap. Trailing blanks pad the column down to the
    table_row height so the VSplit cell is opaque."""
    inner_w = _HISTORY_BUTTON_W
    actions = _history_menu_actions()
    options_focused = (_history_focused == 2)
    header_style = C_ACTIVE if options_focused else C_SECTION
    hover_panel, hover_row = _history_hover
    clear_hover = _hover_at(None, None)

    frags = []

    # Header — "Options" centred within the button-column width.
    header_label = "Options"
    pad_l = max(0, (inner_w - len(header_label)) // 2)
    pad_r = max(0, inner_w - len(header_label) - pad_l)
    frags.append(("", " " * pad_l, clear_hover))
    frags.append((header_style, header_label, clear_hover))
    frags.append(("", " " * pad_r, clear_hover))
    frags.append(("", "\n", clear_hover))

    # Buttons — fixed-width, flat backgrounds, no inter-button gap.
    for i, (label, _action, enabled) in enumerate(actions):
        is_cursor = (i == _history_menu_cursor)
        is_hover  = (hover_panel == 2 and hover_row == i and enabled
                     and not is_cursor)
        if not enabled:
            style = C_BUTTON_DISABLED
        elif is_cursor:
            style = C_SELECTED
        elif is_hover:
            style = C_BUTTON_HOVER
        else:
            style = C_BUTTON

        pad_l = max(0, (inner_w - len(label)) // 2)
        pad_r = max(0, inner_w - len(label) - pad_l)
        cell_text = " " * pad_l + label + " " * pad_r

        if enabled:
            def _click(ev, idx=i):
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _history_set_focus(2)
                    global _history_menu_cursor
                    _history_menu_cursor = idx
                    _history_menu_activate(idx)
                    return None
                return NotImplemented
            frags.append((style, cell_text, _hover_at(2, i, on_event=_click)))
        else:
            frags.append((style, cell_text, clear_hover))
        frags.append(("", "\n", clear_hover))

    # Pad trailing blank lines so the column fills the table_row height.
    # _history_table_window_h() = visible + 1 (header row). The widget body
    # already used 1 (header) + len(actions) lines.
    used = 1 + len(actions)
    blanks = max(0, _history_table_window_h() - used)
    for r in range(blanks):
        frags.append(("", " " * inner_w, clear_hover))
        if r < blanks - 1:
            frags.append(("", "\n", clear_hover))
    return frags


def _history_feedback_or_blank_text():
    """Single row directly below the package, doubling as the spacing row
    above the footer. Renders the centred feedback message when one is
    flashing, otherwise empty. Centring is over the package width (not the
    terminal width) so the message visually belongs to the package above it."""
    clear_hover = _hover_at(None, None)
    if not _history_feedback_text:
        return [("", "", clear_hover)]
    text = _history_feedback_text
    pkg_w  = _history_package_width()
    inner  = max(0, (pkg_w - len(text)) // 2)
    pad_l  = _history_left_pad() + inner
    return [
        ("", " " * pad_l, clear_hover),
        (_history_feedback_style, text, clear_hover),
    ]


# --- Wheel-scrolling control ----------------------------------------------
class _WheelScrollControl(FormattedTextControl):
    """FormattedTextControl that forwards wheel events to a supplied
    `on_scroll(delta)` callback. Used by history and profile tables alike."""
    def __init__(self, *args, on_scroll, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_scroll = on_scroll

    def mouse_handler(self, ev):
        result = super().mouse_handler(ev)
        if result is NotImplemented:
            if ev.event_type == MouseEventType.SCROLL_UP:
                self._on_scroll(-1)
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                self._on_scroll(1)
                return None
        return result


# --- history_rate frame ---------------------------------------------------
def _enter_history_rate_frame(summary):
    global _history_rate_rating, _history_rate_summary
    _history_rate_rating  = summary.rating if summary.saved and summary.rating else 0
    _history_rate_summary = summary
    _push_frame("history_rate")


def _history_rate_save():
    """Write meta for the chain at the chosen rating, refresh the row, pop."""
    global _history_rate_summary
    summary = _history_rate_summary
    if summary is None:
        _pop_frame()
        return
    import run_meta
    rating = max(0, min(5, _history_rate_rating))
    run_meta.save_run_chain(summary.character, summary.run_ids, rating)
    _history_refresh_summary_meta(summary)
    _history_rate_summary = None
    _pop_frame()


def _history_rate_cancel():
    global _history_rate_summary
    _history_rate_summary = None
    _pop_frame()


def _history_rate_text():
    cols = _term_cols()
    frags = []

    frags.append(("", "\n\n"))
    title = "─── Rate the session ───"
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_TITLE, title))
    frags.append(("", "\n\n"))

    rating = max(0, min(5, _history_rate_rating))
    frags.append(("", _pad_centre("★ ★ ★ ★ ★", cols)))
    for i in range(5):
        if i > 0:
            frags.append(("", " "))
        style = _S_STAR if i < rating else C_HINT

        def _make_star_handler(val=i + 1):
            def _h(ev):
                if ev.event_type != MouseEventType.MOUSE_DOWN:
                    return
                global _history_rate_rating
                _history_rate_rating = val
                if _app:
                    _app.invalidate()
            return _h

        frags.append((style, "★", _make_star_handler()))
    frags.append(("", "\n\n"))

    footer = "0-5 Set · ← → Adjust · Enter Save · ESC Cancel"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# --- history_delete_confirm frame -----------------------------------------
def _enter_history_delete_confirm_frame(summary):
    global _history_delete_summary
    _history_delete_summary = summary
    _push_frame("history_delete_confirm")


def _history_delete_confirm_yes():
    """Delete the chain's files, refresh the session list, pop frame."""
    global _history_delete_summary
    summary = _history_delete_summary
    _history_delete_summary = None
    if summary is None:
        _pop_frame()
        return
    _history_delete_session(summary)
    # _history_refresh_sessions() clamps _history_table_cursor when the
    # deleted row was at the end; otherwise the same index now points at
    # what was the next row, which is the desired "land on a sensible
    # neighbour" behaviour.
    _history_refresh_sessions()
    _pop_frame()


def _history_delete_confirm_cancel():
    global _history_delete_summary
    _history_delete_summary = None
    _pop_frame()


def _history_delete_confirm_text():
    cols = _term_cols()
    frags = []
    summary = _history_delete_summary
    if summary is None:
        return frags

    title = "─── Delete session ───"
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_HEADER, title))
    frags.append(("", "\n\n"))

    runs = len(summary.run_ids)
    rows = [
        ("Character:",  summary.character,                          C_ITEM),
        ("Date:",       _history_fmt_date(summary.start_ts),        C_ITEM),
        ("Time:",       _history_fmt_time(summary.start_ts),        C_ITEM),
        ("Duration:",   _history_fmt_duration(summary.duration_seconds), C_ITEM),
        ("Runs:",       str(runs),                                  C_ITEM),
    ]
    if summary.saved:
        stars = "★" * max(0, min(5, summary.rating or 0))
        saved_text = f"yes — {stars}" if stars else "yes"
        rows.append(("Saved:", saved_text, C_ACCENT))

    label_w = max(len(lbl) for lbl, _, _ in rows)
    value_w = max(len(val) for _, val, _ in rows)
    line_w  = label_w + 2 + value_w
    indent  = max(0, (cols - line_w) // 2)
    for label, value, val_style in rows:
        frags.append(("", " " * indent))
        frags.append((C_HINT, label.ljust(label_w)))
        frags.append(("", "  "))
        frags.append((val_style, value))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    warn1 = "This will permanently delete the session's logs and run data."
    warn2 = "This cannot be undone."
    for line in (warn1, warn2):
        frags.append(("", _pad_centre(line, cols)))
        frags.append((C_HINT, line))
        frags.append(("", "\n"))

    frags.append(("", "\n"))
    footer = "Y  Delete       Any other key  Cancel"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))
    return frags


# --- history_detail --------------------------------------------------------
def _hd_fmt_ts(ts, fmt):
    try:
        return time.strftime(fmt, time.localtime(int(ts)))
    except (TypeError, ValueError, OSError):
        return ""


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

    frags.append(("", "\n", clear))

    title_pad = max(0, (cols - len(title_text)) // 2)
    frags.append(("", " " * title_pad, clear))
    frags.append((C_HEADER, title_text, clear))
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
    frags.append(("", _pad_centre(footer, cols), clear))
    frags.append((_S_HINT, footer, clear))
    return frags


# ---------------------------------------------------------------------------
# Spotlights — cross-character reel of significant events
# ---------------------------------------------------------------------------
def _enter_spotlights():
    """Aggregate spotlights from every character's sealed runs and either
    push the empty-state frame or eagerly load + play the reel through
    log_view in spotlight mode."""
    global _spotlights_empty_reason
    # Cheap shortcut for the empty-state branch: if any per-kind toggle
    # is off, attribute an empty reel to the filter and nudge the user
    # toward Options → Spotlights. Otherwise it's a genuine "no data"
    # state. See docs/launcher.md "Spotlights empty-state copy".
    any_disabled = any(
        _conf.get(key) == "0"
        for key, _label in _SPOTLIGHT_TOGGLES
    )
    _spotlights_empty_reason = "filtered" if any_disabled else "no_data"

    reel = spotlights.aggregate_spotlights()
    if reel.total_count == 0:
        _push_frame("spotlights_empty")
        return

    cache: dict = {}
    playable = []
    for spot in reel.spotlights:
        spotlights.load_spotlight_log_events(spot, cache)
        if spot.log_events:
            playable.append(spot)
    if not playable:
        _push_frame("spotlights_empty")
        return

    playback = spotlights.SpotlightPlayback(playable)
    if not playback.events:
        _push_frame("spotlights_empty")
        return

    _enter_log_view_spotlight(playback)


# ---------------------------------------------------------------------------
# log_view (chain log player — Phase 3 skeleton)
# ---------------------------------------------------------------------------
def _enter_log_view(summary=None):
    """Push log_view for the chain in `summary` (or _history_detail_summary
    when called with no arg, for back-compat).

    Caller is responsible for has_log gating; this is defensive against a
    chain whose every .log file has vanished between summary build and
    button activation."""
    global _log_view_playback, _log_view_scroll, _log_view_cols, _log_view_lines
    global _log_view_event_rows
    global _log_mode, _log_play_anchor_wall, _log_play_anchor_offset_us
    global _log_paused_offset_us, _log_cursor_index, _log_last_playhead_index
    global _log_overlays_visible, _log_overlays_hide_at, _log_overlay_hover
    global _log_view_summary, _log_view_mode, _log_view_reel
    if summary is None:
        summary = _history_detail_summary
    if summary is None:
        return
    playback = log_player.LogPlayback(summary.character, summary.run_ids)
    if not playback.events:
        # Defensive — every run's .log was missing; stay on history_detail.
        return
    _log_view_mode            = "chain"
    _log_view_reel            = None
    _log_view_summary         = summary
    _log_view_playback        = playback
    _log_view_scroll          = 0
    _log_view_cols            = 0
    _log_view_lines           = None
    _log_view_event_rows      = None
    # Start paused at event 0 with overlays visible so Space, the
    # scrubber, and the buttons are discoverable on the first frame.
    # Space begins playback.
    _log_mode                 = "pause"
    _log_play_anchor_wall     = time.monotonic()
    _log_play_anchor_offset_us = 0
    _log_paused_offset_us     = 0
    _log_cursor_index         = 0
    _log_last_playhead_index  = -1
    _log_overlays_visible     = True
    _log_overlays_hide_at     = None
    _log_overlay_hover        = None
    _push_frame("log_view")


def _enter_log_view_spotlight(playback):
    """Push log_view in spotlight mode. `playback` is a SpotlightPlayback
    built by `_enter_spotlights` from a non-empty SpotlightReel.

    Unlike chain mode this enters in **play** mode: the reel starts
    rolling immediately. The playback's phantom-row block at offset 0
    provides the scroll-clear wipe — the playhead sits on the last
    phantom while the first spotlight's pre-roll counts down, so the
    viewport is blank until the first real event fires."""
    global _log_view_playback, _log_view_scroll, _log_view_cols, _log_view_lines
    global _log_view_event_rows
    global _log_mode, _log_play_anchor_wall, _log_play_anchor_offset_us
    global _log_paused_offset_us, _log_cursor_index, _log_last_playhead_index
    global _log_overlays_visible, _log_overlays_hide_at, _log_overlay_hover
    global _log_view_summary, _log_view_mode, _log_view_reel
    _log_view_mode            = "spotlight"
    _log_view_reel            = playback
    _log_view_summary         = None
    _log_view_playback        = playback
    _log_view_scroll          = 0
    _log_view_cols            = 0
    _log_view_lines           = None
    _log_view_event_rows      = None
    # Initialise in pause briefly so the resume call below sees a clean
    # state; _log_resume() flips to play and starts the 30 Hz tick task.
    _log_mode                 = "pause"
    _log_play_anchor_wall     = time.monotonic()
    _log_play_anchor_offset_us = 0
    _log_paused_offset_us     = 0
    _log_cursor_index         = 0
    _log_last_playhead_index  = -1
    _log_overlay_hover        = None
    _push_frame("log_view")
    _log_resume()
    # Spotlight mode opens cleanly — chrome reveals on mouse activity.
    # Override the visibility _log_resume() armed so the user sees the
    # info box on an empty backdrop with no header/controls.
    _log_overlays_visible = False
    _log_overlays_hide_at = None


def _exit_log_view():
    """Pop back to the previous frame and drop the playback so the chain's log
    data can be garbage-collected — chains are re-read from disk on next push."""
    global _log_view_summary, _log_view_playback
    global _log_view_scroll, _log_view_cols, _log_view_lines
    global _log_view_event_rows, _log_last_playhead_index
    global _log_overlays_visible, _log_overlays_hide_at, _log_overlay_hover
    global _log_dragging_scrubber
    global _log_view_mode, _log_view_reel
    _log_cancel_tick_task()
    _log_view_summary    = None
    _log_view_playback   = None
    _log_view_reel       = None
    _log_view_mode       = "chain"
    _log_view_scroll     = 0
    _log_view_cols       = 0
    _log_view_lines      = None
    _log_view_event_rows = None
    _log_last_playhead_index = -1
    _log_overlays_visible    = True
    _log_overlays_hide_at    = None
    _log_overlay_hover       = None
    _log_dragging_scrubber   = False
    _pop_frame()


# ---------------------------------------------------------------------------
# Credits — end-of-reel scrolling chronicle
# ---------------------------------------------------------------------------
def _credits_cancel_tick_task():
    global _credits_tick_task
    if _credits_tick_task is not None:
        _credits_tick_task.cancel()
        _credits_tick_task = None


def _credits_start_tick_task():
    global _credits_tick_task
    _credits_cancel_tick_task()
    if _app_loop is None:
        return
    _credits_tick_task = _app_loop.create_task(_credits_tick_loop())


async def _credits_tick_loop():
    """Lightweight redraw loop. The animation is row-quantised (at
    1 row/s a new offset appears once per second), so most ticks just
    confirm the current frame is still valid; we invalidate
    unconditionally at _CREDITS_TICK_HZ which is comfortably above the
    visible step rate."""
    interval = 1.0 / _CREDITS_TICK_HZ
    try:
        while True:
            if _current_frame != "credits":
                return
            if _credits_check_finished():
                return
            if _app:
                _app.invalidate()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass


def _credits_check_finished() -> bool:
    """Return True (and trigger auto-exit) when the last credit line has
    scrolled clear of the top of the viewport."""
    if not _credits_lines or _credits_term_rows <= 0:
        return False
    offset_floor = int(
        (time.monotonic() - _credits_start_monotonic) * _CREDITS_SCROLL_ROWS_PER_SEC
    )
    if offset_floor >= len(_credits_lines) + _credits_term_rows:
        _credits_finish()
        return True
    return False


def _enter_credits(spotlights_list):
    """Push the credits frame, snapshotting terminal size and generating
    the wrapped narrative content from `spotlights_list` (a list of
    Spotlight objects, typically the reel's `.spotlights`)."""
    global _credits_lines, _credits_start_monotonic
    global _credits_term_rows, _credits_term_cols, _credits_text_width
    term_rows = max(1, _term_rows())
    term_cols = max(1, _term_cols())
    text_width = min(60, max(40, term_cols - 8))
    _credits_term_rows = term_rows
    _credits_term_cols = term_cols
    _credits_text_width = text_width
    _credits_lines = credits.generate_credits_lines(spotlights_list, text_width)
    # Trailing pad: enough blank rows after the closing line so it
    # scrolls fully off the top before the auto-exit fires. The module
    # adds a small baseline buffer; we top it up with `term_rows` here
    # now that we know the viewport height.
    _credits_lines = _credits_lines + [""] * term_rows
    _credits_start_monotonic = time.monotonic()
    _push_frame("credits")
    _credits_start_tick_task()


def _credits_finish():
    """Stop the tick, clear state, and return to the launcher main menu."""
    global _credits_lines, _credits_start_monotonic
    global _credits_term_rows, _credits_term_cols, _credits_text_width
    _credits_cancel_tick_task()
    _credits_lines = []
    _credits_start_monotonic = 0.0
    _credits_term_rows = 0
    _credits_term_cols = 0
    _credits_text_width = 0
    if _current_frame == "credits":
        _reset_to_main()


def _credits_row_brightness(tr: int, n: int, fb: int) -> float:
    """Fade-band brightness for terminal row `tr` (0..n-1).
    Linear ramp up across the bottom `fb` rows, full white in the
    middle, linear ramp down across the top `fb` rows."""
    fb = max(1, fb)
    if tr < fb:
        return tr / fb
    if tr >= n - fb:
        return (n - 1 - tr) / fb
    return 1.0


def _credits_brightness_to_hex(b: float) -> str:
    v = max(0, min(255, int(round(b * 255))))
    return f"#{v:02x}{v:02x}{v:02x}"


def _credits_text():
    """Build the credits scroll as a fragment list. One fragment per
    terminal row: a centred credit line painted on a black background,
    with brightness from the fade-band formula."""
    if not _credits_lines or _credits_term_rows <= 0:
        return [("bg:#000000", " " * max(1, _term_cols()))]
    n = _credits_term_rows
    cols = max(1, _term_cols())
    fb = max(1, int(n * _CREDITS_FADE_BAND_FRAC))
    offset_floor = int(
        (time.monotonic() - _credits_start_monotonic) * _CREDITS_SCROLL_ROWS_PER_SEC
    )
    blank_row = " " * cols
    frags = []
    for tr in range(n):
        strip_row = tr + offset_floor - n
        if 0 <= strip_row < len(_credits_lines):
            line = _credits_lines[strip_row].center(cols)
        else:
            line = blank_row
        brightness = _credits_row_brightness(tr, n, fb)
        style = f"fg:{_credits_brightness_to_hex(brightness)} bg:#000000"
        frags.append((style, line))
        if tr < n - 1:
            frags.append(("", "\n"))
    return frags


def _credits_hint_text():
    """Top-right exit hint, rendered as a Float above the scroll. Dim
    grey on the same black canvas, unaffected by the fade band."""
    return [("fg:#555555 bg:#000000", "Escape to exit")]


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
    """Return the current playback offset, in microseconds."""
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
    global _log_overlays_visible, _log_overlays_hide_at
    if _log_view_playback is None:
        return
    _log_paused_offset_us = _log_current_playback_us()
    # If the playhead is sitting on a phantom row (a spotlight-boundary
    # wipe), snap forward to the next real event so pause-mode keybinds
    # operate on real content.
    _log_cursor_index     = _log_skip_phantoms(_log_playhead_index(),
                                               prefer_forward=True)
    _log_mode             = "pause"
    # Overlays become permanent while paused.
    _log_overlays_visible = True
    _log_overlays_hide_at = None
    _log_cancel_tick_task()
    _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _log_resume():
    """Resume playing from the cursor's event timestamp. Always snaps to the
    cursor, even when the cursor hasn't moved since the pause."""
    global _log_mode, _log_play_anchor_wall, _log_play_anchor_offset_us
    global _log_last_playhead_index
    global _log_overlays_visible, _log_overlays_hide_at
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    idx = max(0, min(len(pb.events) - 1, _log_cursor_index))
    _log_play_anchor_offset_us = pb.playback_offset_us[idx]
    _log_play_anchor_wall      = time.monotonic()
    _log_mode                  = "play"
    _log_last_playhead_index   = -1
    # Don't yank overlays away on pause→play. Show them and schedule a
    # 3 s hide so the controls fade out only after the user stops
    # interacting.
    _log_overlays_visible = True
    _log_overlays_hide_at = time.monotonic() + _LOG_OVERLAY_HIDE_DELAY
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


def _log_spotlight_jump_to_credits():
    """Cancel spotlight playback, pop log_view, and push the credits
    frame for the active reel. Shared by the end-of-reel auto-pause path
    and the discoverable "advance past the last spotlight" path (→ key
    / ► click at the last spotlight) so both routes use one transition."""
    reel = _log_view_reel
    spotlights_list = list(reel.spotlights) if reel is not None else []
    _log_cancel_tick_task()
    _exit_log_view()
    if spotlights_list:
        _enter_credits(spotlights_list)


def _log_auto_pause_at_end():
    """End-of-log auto-pause. In chain mode this parks on the final
    event and flips to pause. In spotlight mode the reel is finished, so
    we cancel the playback, pop log_view, and roll the credits frame —
    no hold delay (the last spotlight's content naturally fades out as
    credits scroll up)."""
    global _log_mode, _log_paused_offset_us, _log_cursor_index
    global _log_overlays_visible, _log_overlays_hide_at
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    if _log_view_mode == "spotlight":
        _log_spotlight_jump_to_credits()
        return
    _log_cursor_index     = len(pb.events) - 1
    _log_paused_offset_us = pb.total_duration_us
    _log_mode             = "pause"
    _log_overlays_visible = True
    _log_overlays_hide_at = None
    _log_cancel_tick_task()
    _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


# --- Overlay visibility ----------------------------------------------------
def _log_touch_overlays():
    """Mark overlay activity. Reveals overlays and (re)arms the 3 s hide
    timer in play mode. No-op in pause mode (overlays are permanent)."""
    global _log_overlays_visible, _log_overlays_hide_at
    if _log_view_playback is None or _log_mode != "play":
        return
    _log_overlays_hide_at = time.monotonic() + _LOG_OVERLAY_HIDE_DELAY
    if not _log_overlays_visible:
        _log_overlays_visible = True
        if _app:
            _app.invalidate()


def _log_tick_overlay_visibility():
    """Called from the play-mode tick. Hides overlays once the deadline
    expires; returns True iff visibility actually changed (caller invalidates)."""
    global _log_overlays_visible, _log_overlays_hide_at
    if _log_mode != "play":
        return False
    if not _log_overlays_visible or _log_overlays_hide_at is None:
        return False
    if time.monotonic() < _log_overlays_hide_at:
        return False
    _log_overlays_visible = False
    _log_overlays_hide_at = None
    return True


def _log_set_overlay_hover(name):
    """Update the hovered overlay control id, invalidating only on change."""
    global _log_overlay_hover
    if name == _log_overlay_hover:
        return
    _log_overlay_hover = name
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
    crosses to a new event or the overlay hide-deadline expires."""
    global _log_last_playhead_index
    interval = 1.0 / _LOG_TICK_HZ
    try:
        while True:
            if (_current_frame != "log_view" or _log_mode != "play"
                    or _log_view_playback is None):
                return
            pb = _log_view_playback
            cur_us = _log_current_playback_us()
            if pb.events and cur_us >= pb.total_duration_us:
                _log_auto_pause_at_end()
                return
            dirty = False
            idx = _log_playhead_index()
            if idx != _log_last_playhead_index:
                _log_last_playhead_index = idx
                dirty = True
            if _log_tick_overlay_visibility():
                dirty = True
            if dirty and _app:
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


# --- Phantom-event handling (spotlight mode) ------------------------------
def _log_is_phantom(event_idx):
    """True when the event at `event_idx` is a phantom blank row inserted
    at a spotlight boundary by SpotlightPlayback (zero playback duration,
    one blank visual row, skipped by pause-mode cursor navigation)."""
    pb = _log_view_playback
    if pb is None or _log_view_mode != "spotlight":
        return False
    is_p = getattr(pb, "is_phantom", None)
    if is_p is None:
        return False
    return is_p(event_idx)


def _log_skip_phantoms(idx, prefer_forward=True):
    """Snap to the nearest non-phantom event. Searches the preferred
    direction first; if it hits an end, falls back to the other direction.
    Returns the original idx if it's already a real event, or if no real
    event exists (degenerate case)."""
    pb = _log_view_playback
    if pb is None or not pb.events:
        return idx
    n = len(pb.events)
    if idx < 0:
        idx = 0
    elif idx >= n:
        idx = n - 1
    if not _log_is_phantom(idx):
        return idx
    if prefer_forward:
        for i in range(idx + 1, n):
            if not _log_is_phantom(i):
                return i
        for i in range(idx - 1, -1, -1):
            if not _log_is_phantom(i):
                return i
    else:
        for i in range(idx - 1, -1, -1):
            if not _log_is_phantom(i):
                return i
        for i in range(idx + 1, n):
            if not _log_is_phantom(i):
                return i
    return idx


# --- Cursor / scroll movement (pause mode) --------------------------------
def _log_set_cursor(new_index, prefer_forward=True):
    """Pause-mode cursor mutation. Clamps to [0, last_index], snaps over
    any phantom event in the preferred direction, then anchors
    `_log_paused_offset_us` to the cursor event's start time so the
    scrubber thumb and the MM:SS / MM:SS elapsed display follow the
    cursor on the same render pass."""
    global _log_cursor_index, _log_paused_offset_us
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    n = len(pb.events)
    clamped = max(0, min(n - 1, int(new_index)))
    clamped = _log_skip_phantoms(clamped, prefer_forward=prefer_forward)
    if clamped == _log_cursor_index:
        return
    _log_cursor_index     = clamped
    _log_paused_offset_us = pb.playback_offset_us[clamped]
    _log_ensure_cursor_visible()
    _log_touch_overlays()
    if _app:
        _app.invalidate()


def _log_move_cursor(delta):
    """Move cursor by `delta` events; auto-pauses if currently playing.
    Routes through `_log_set_cursor` for clamping + scrubber/time sync.
    Phantom blocks at spotlight boundaries are skipped in the direction
    of travel."""
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    if _log_mode == "play":
        _log_pause()
    _log_set_cursor(_log_cursor_index + delta, prefer_forward=(delta >= 0))


def _log_cursor_to(index):
    """Move cursor to an absolute event index; auto-pauses if playing."""
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    if _log_mode == "play":
        _log_pause()
    _log_set_cursor(index, prefer_forward=True)


class _LogViewControl(FormattedTextControl):
    """Mouse routing for the log_view frame.

    Pause mode:
      • Wheel up/down moves the cursor by one event (per spec: wheel moves
        the cursor, not just the viewport, so the resume point stays
        predictable).
      • Click on a rendered event row moves the cursor to that event.
        Does NOT resume playback — Space does.

    Play mode: MOUSE_MOVE, click, and wheel refresh the overlay
    visibility timer; otherwise no-op on the log content."""
    def mouse_handler(self, ev):
        result = super().mouse_handler(ev)
        if result is not NotImplemented:
            return result
        if _log_view_playback is None:
            return None
        # A scrubber drag captures all mouse events anywhere in log_view —
        # MOUSE_MOVE seeks, MOUSE_UP / button-released-during-move ends.
        if _log_maybe_handle_drag(ev):
            return None
        t = ev.event_type
        # Clear button hover whenever the mouse drifts back onto the log
        # control — the buttons reset their own hover on direct hits.
        if t == MouseEventType.MOUSE_MOVE:
            _log_set_overlay_hover(None)
            _log_touch_overlays()
            return None
        if _log_mode == "play":
            # In play, any wheel/click on the log content just refreshes
            # the overlay timer — no cursor activation.
            _log_touch_overlays()
            return None
        # Pause mode: original wheel + click-to-cursor behaviour.
        _log_touch_overlays()
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
# log_view overlays — top header + bottom controls (Phase 3, prompt 3)
# ---------------------------------------------------------------------------
def _log_format_mmss(us):
    """Format a microsecond duration as MM:SS. Allows minutes to exceed
    59 (so a 78-minute chain reads "78:34" rather than collapsing into
    hours) — matches the launcher.md spec for the overlay time fields."""
    s = max(0, int(us // 1_000_000))
    return f"{s // 60:02d}:{s % 60:02d}"


def _log_current_run_index():
    """Event index whose run we attribute to the current overlay state:
    the playhead while playing, the cursor while paused."""
    pb = _log_view_playback
    if pb is None or not pb.events:
        return 0
    if _log_mode == "play":
        return _log_playhead_index()
    return max(0, min(len(pb.events) - 1, _log_cursor_index))


def _log_overlay_inert_handler(ev):
    """MOUSE_MOVE on an overlay area not bound to a control: refresh the
    timer and clear any stale button hover so it doesn't linger. While a
    scrubber drag is in progress, route the event to the seek dispatcher
    so a drag that drifts onto overlay padding keeps tracking."""
    if _log_maybe_handle_drag(ev):
        return
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _log_set_overlay_hover(None)
    _log_touch_overlays()


def _log_pad(width, handler=None):
    """Build a horizontal padding fragment of `width` spaces using the
    overlay bg, optionally with a mouse handler."""
    if width <= 0:
        return None
    if handler is None:
        return (C_LOG_OVERLAY_BG, " " * width, _log_overlay_inert_handler)
    return (C_LOG_OVERLAY_BG, " " * width, handler)


# --- Top header ------------------------------------------------------------
def _log_header_text():
    """Build the top header overlay row. Always returns one row's worth
    of fragments, sized to the terminal width."""
    pb = _log_view_playback
    cols = max(1, _term_cols())
    if pb is None or not pb.events:
        return [(C_LOG_OVERLAY_BG, " " * cols, _log_overlay_inert_handler)]

    if _log_view_mode == "spotlight":
        return _log_spotlight_header_text(cols)

    idx = _log_current_run_index()
    run_id, run_ord, run_total = pb.run_at(idx)
    info = pb.run_info(run_id)

    name  = info.get("character") or pb.character
    level = info.get("start_level")
    char_part = f"{name} (L{level})" if isinstance(level, int) else name
    run_part  = f"Run {run_ord} of {run_total}"
    ts        = info.get("start_ts")
    when_part = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if isinstance(ts, int) else ""

    elapsed = _log_format_mmss(_log_current_playback_us())
    at_end = (_log_mode == "pause"
              and _log_current_playback_us() >= pb.total_duration_us
              and pb.total_duration_us > 0)
    if at_end:
        elapsed_part = f"{elapsed} · End of session"
    else:
        elapsed_part = elapsed

    hint = "ESC to return"

    left_pieces = [char_part, run_part]
    if when_part:
        left_pieces.append(when_part)
    left_pieces.append(elapsed_part)
    left_text = "  ·  ".join(left_pieces)

    # Inner block: ~80 cols when the terminal is wider, else full width.
    inner_w = min(_LOG_OVERLAY_HEADER_W, cols)
    gap = max(1, inner_w - len(left_text) - len(hint))
    body = left_text + (" " * gap) + hint
    if len(body) > inner_w:
        overflow = len(body) - inner_w
        trimmed_left = left_text[: max(0, len(left_text) - overflow)]
        body = trimmed_left + " " + hint
        if len(body) > inner_w:
            body = body[:inner_w]
    body_len = len(body)
    body_hint = body[body_len - len(hint):] if body_len >= len(hint) else hint
    body_left = body[: body_len - len(body_hint)] if body_len > len(body_hint) else ""

    side = max(0, (cols - inner_w) // 2)
    right_side = max(0, cols - inner_w - side)

    frags = []
    pad = _log_pad(side)
    if pad:
        frags.append(pad)
    if body_left:
        frags.append((C_LOG_OVERLAY_FG, body_left, _log_overlay_inert_handler))
    if body_hint:
        frags.append((C_LOG_OVERLAY_HINT, body_hint, _log_overlay_inert_handler))
    pad = _log_pad(right_side)
    if pad:
        frags.append(pad)
    return frags


# --- Spotlight-mode helpers (header + floating overlay + seek) ------------
def _log_spotlight_current():
    """Return (spotlight, spotlight_idx, offset_within_spotlight_us) for the
    current playback position in spotlight mode. Returns None when the
    reel is empty or we're not in spotlight mode."""
    reel = _log_view_reel
    if reel is None or not reel.spotlights:
        return None
    cur_us = _log_current_playback_us()
    spot_idx = reel.spotlight_at_offset(cur_us)
    spot = reel.spotlights[spot_idx]
    start = reel.spotlight_start_offsets_us[spot_idx]
    offset_within = max(0, cur_us - start)
    return (spot, spot_idx, offset_within)


def _log_spotlight_header_text(cols):
    """Top header for spotlight mode. Replaces the chain-mode header's
    "Run X of Y" with "SPOTLIGHT N / TOTAL" and uses the active
    spotlight's first-event date instead of the run's run_start ts.
    Trims the clock/elapsed segment that chain mode shows — the
    nav row inside the floating info box surfaces position within
    the reel, and the freed space holds the ←/→ hint."""
    info = _log_spotlight_current()
    if info is None:
        return [(C_LOG_OVERLAY_BG, " " * cols, _log_overlay_inert_handler)]
    spot, spot_idx, _ = info
    reel = _log_view_reel

    char_part = spot.character
    death_level = None
    for ev in spot.events:
        if ev.kind == "death" and isinstance(ev.extra.get("level"), int):
            death_level = ev.extra["level"]
            break
    if death_level is not None:
        char_part = f"{spot.character} (L{death_level})"

    n_part   = f"SPOTLIGHT {spot_idx + 1} / {reel.total_count}"
    first_ts = spot.events[0].ts
    when_part = time.strftime("%Y-%m-%d", time.localtime(first_ts))

    hint = "ESC Back  ·  ←/→ Prev/next"
    left_text = "  ·  ".join([char_part, n_part, when_part])

    inner_w = min(_LOG_OVERLAY_HEADER_W, cols)
    gap = max(1, inner_w - len(left_text) - len(hint))
    body = left_text + (" " * gap) + hint
    if len(body) > inner_w:
        overflow = len(body) - inner_w
        trimmed_left = left_text[: max(0, len(left_text) - overflow)]
        body = trimmed_left + " " + hint
        if len(body) > inner_w:
            body = body[:inner_w]
    body_len  = len(body)
    body_hint = body[body_len - len(hint):] if body_len >= len(hint) else hint
    body_left = body[: body_len - len(body_hint)] if body_len > len(body_hint) else ""

    side = max(0, (cols - inner_w) // 2)
    right_side = max(0, cols - inner_w - side)

    frags = []
    pad = _log_pad(side)
    if pad:
        frags.append(pad)
    if body_left:
        frags.append((C_LOG_OVERLAY_FG, body_left, _log_overlay_inert_handler))
    if body_hint:
        frags.append((C_LOG_OVERLAY_HINT, body_hint, _log_overlay_inert_handler))
    pad = _log_pad(right_side)
    if pad:
        frags.append(pad)
    return frags


# Floating spotlight info box. A 30×8 framed rectangle: top/bottom rows
# are the half-block frame (`█▀▄▌▐` in black on the cyan BG), 6 interior
# rows of `interior_width = _SPOTLIGHT_BOX_W - 2 = 28` cells flanked by
# `▌` / `▐` side glyphs. The 2-cell top/right margin lives in the Float
# positioning (top=2, right=2); the narrow-terminal suppression
# threshold is box width + 4 (margin + box + breathing room).
_SPOTLIGHT_BOX_W      = 30
_SPOTLIGHT_BOX_H      = 8
_SPOTLIGHT_BOX_MARGIN = 2


def _log_spotlight_overlay_visible():
    """The spotlight info box is always visible while in spotlight mode
    (the top header and bottom controls keep their auto-hide; the box
    does not). Hides only when the terminal is too narrow for the box
    plus its margin — playback continues without it."""
    if _log_view_mode != "spotlight":
        return False
    if _log_view_reel is None or not _log_view_reel.spotlights:
        return False
    if _term_cols() < _SPOTLIGHT_BOX_W + _SPOTLIGHT_BOX_MARGIN * 2:
        return False
    return True


def _log_spotlight_overlay_text():
    """Build the spotlight info box (top-right floating overlay).

    30×8 framed rectangle: top/bottom rows are the `█▀▄▌▐` outline in
    black on the cyan BG; 6 interior rows of `interior_width` cells
    flanked by `▌`/`▐` side glyphs.

      • Row 2: ◄ N of TOTAL ►   — centred nav row; ◄ / ► carry mouse
        handlers that seek to the adjacent spotlight (◄ at spotlight 1
        restarts current under the same 1.5 s rule as the keyboard
        path; ► at the last spotlight jumps straight into credits).
      • Row 3: <CHAR>           — centred, primary text.
      • Row 4: blank.
      • Row 5: event label l1   — centred, primary text.
      • Row 6: event label l2   — centred, primary; blank when label fits row 5.
      • Row 7: In <N> seconds.. — centred, secondary text. Collapses to
        a blank row when no next event remains in this spotlight.
    """
    box_w = _SPOTLIGHT_BOX_W
    inner = box_w - 2
    info = _log_spotlight_current()
    if info is None:
        return _log_spotlight_empty_box(box_w, inner)
    spot, spot_idx, offset_within = info
    reel = _log_view_reel

    char  = spot.character.upper()
    label = " · ".join(ev.label for ev in spot.events)

    _, seconds_to_next = reel.event_progress(spot, offset_within)
    if seconds_to_next is None:
        countdown = ""
    else:
        # Round up so "0 seconds" doesn't sit for almost a full second.
        s = (int(seconds_to_next) if seconds_to_next == int(seconds_to_next)
             else int(seconds_to_next) + 1)
        if s <= 0:
            countdown = "In 0 seconds.."
        elif s == 1:
            countdown = "In 1 second.."
        else:
            countdown = f"In {s} seconds.."

    label_l1, label_l2 = _log_spotlight_wrap_label(label, inner)

    nav_frags = _log_spotlight_nav_row(spot_idx, reel.total_count, inner)
    interior_rows = [
        ("nav",              nav_frags),
        ("centre",           char),
        ("blank",            ""),
        ("centre",           label_l1),
        ("centre",           label_l2),
        ("centre_secondary", countdown),
    ]

    frags = []
    # Top frame row: █ + ▀ × inner + █
    frags.append((C_SPOTLIGHT_FRAME, "█" + ("▀" * inner) + "█"))
    frags.append(("", "\n"))
    for kind, payload in interior_rows:
        frags.append((C_SPOTLIGHT_FRAME, "▌"))
        if kind == "nav":
            frags.extend(payload)
        else:
            frags.extend(_log_spotlight_box_row(payload, kind, inner))
        frags.append((C_SPOTLIGHT_FRAME, "▐"))
        frags.append(("", "\n"))
    # Bottom frame row: █ + ▄ × inner + █
    frags.append((C_SPOTLIGHT_FRAME, "█" + ("▄" * inner) + "█"))
    return frags


def _log_spotlight_wrap_label(label, width):
    """Wrap an event label onto up to two lines, both fitting in `width`
    cells. Returns (line1, line2) with line2 == "" when the label fits
    on one line. On 3+ wrapped lines, the second line is truncated with
    a trailing `…` so the box still ends after row 5 — rare for event
    labels (typically short phrases)."""
    if not label:
        return ("", "")
    lines = textwrap.wrap(
        label,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not lines:
        return ("", "")
    if len(lines) == 1:
        return (lines[0], "")
    if len(lines) == 2:
        return (lines[0], lines[1])
    # 3+ lines: keep line 1, ellipsise line 2.
    line2 = lines[1]
    if len(line2) >= width:
        line2 = line2[: max(0, width - 1)] + "…"
    else:
        line2 = line2 + "…"
        if len(line2) > width:
            line2 = line2[: width - 1] + "…"
    return (lines[0], line2)


def _log_spotlight_box_row(text, kind, width):
    """Render a single row of the box. Always emits exactly `width`
    cells, BG-painted.

    `kind` selects alignment and style:
      • "centre"           — primary text, centred.
      • "centre_secondary" — secondary text, centred.
      • "blank"            — pure BG fill.
    """
    if kind == "blank" or not text:
        return [(C_SPOTLIGHT_BOX_BG, " " * width)]
    t = text[:width]
    pad_l = (width - len(t)) // 2
    pad_r = width - len(t) - pad_l
    style = (C_SPOTLIGHT_TEXT_SECONDARY if kind == "centre_secondary"
             else C_SPOTLIGHT_TEXT_PRIMARY)
    frags = []
    if pad_l:
        frags.append((C_SPOTLIGHT_BOX_BG, " " * pad_l))
    frags.append((style, t))
    if pad_r:
        frags.append((C_SPOTLIGHT_BOX_BG, " " * pad_r))
    return frags


def _log_spotlight_nav_row(spot_idx, total, inner):
    """Render the clickable nav row at the top of the spotlight info box:
    `◄ <idx> of <total> ►`, centred, with each arrow carrying its own
    mouse handler. The arrows are padded with single spaces (e.g. ` ◄ `)
    so the click target is 3 cells wide rather than a single glyph.

    On the last spotlight the `►` glyph no longer seeks to a next
    spotlight — it jumps straight into credits — so we append a
    ` CREDITS` label after `►` to surface that altered destination.
    The next-click handler then covers the whole ` ► CREDITS` fragment
    so clicking the label triggers the same action."""
    if total <= 0:
        return [(C_SPOTLIGHT_BOX_BG, " " * inner)]
    idx_text     = f"{spot_idx + 1} of {total}"
    left_arrow   = " ◄ "
    is_last      = (spot_idx >= total - 1)
    right_chunk  = " ► CREDITS" if is_last else " ► "
    used = len(left_arrow) + len(idx_text) + len(right_chunk)
    if used > inner and is_last:
        # Pathologically narrow interior for the CREDITS label — drop it
        # rather than the arrow, so the row stays usable.
        right_chunk = " ► "
        used = len(left_arrow) + len(idx_text) + len(right_chunk)
    if used > inner:
        return [(C_SPOTLIGHT_BOX_BG, " " * inner)]
    pad_total = inner - used
    pad_l = pad_total // 2
    pad_r = pad_total - pad_l

    def _prev_click(ev):
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _log_spotlight_seek_relative(-1)

    def _next_click(ev):
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _log_spotlight_seek_relative(1)

    frags = []
    if pad_l:
        frags.append((C_SPOTLIGHT_BOX_BG, " " * pad_l))
    frags.append((C_SPOTLIGHT_TEXT_PRIMARY, left_arrow, _prev_click))
    frags.append((C_SPOTLIGHT_TEXT_PRIMARY, idx_text))
    frags.append((C_SPOTLIGHT_TEXT_PRIMARY, right_chunk, _next_click))
    if pad_r:
        frags.append((C_SPOTLIGHT_BOX_BG, " " * pad_r))
    return frags


def _log_spotlight_empty_box(box_w, inner):
    """Defensive fallback for the rare case where the overlay renders
    before a spotlight is selectable. Paints an empty framed box so the
    Float doesn't collapse mid-frame; should never be seen by the user
    under normal flow."""
    frags = []
    frags.append((C_SPOTLIGHT_FRAME, "█" + ("▀" * inner) + "█"))
    frags.append(("", "\n"))
    for i in range(_SPOTLIGHT_BOX_H - 2):
        frags.append((C_SPOTLIGHT_FRAME, "▌"))
        frags.append((C_SPOTLIGHT_BOX_BG, " " * inner))
        frags.append((C_SPOTLIGHT_FRAME, "▐"))
        frags.append(("", "\n"))
    frags.append((C_SPOTLIGHT_FRAME, "█" + ("▄" * inner) + "█"))
    return frags


def _log_spotlight_seek_relative(delta_spotlights):
    """← / → seek: jump to the start of an adjacent spotlight. With
    `delta_spotlights == -1` and we're more than ~1.5 s into the current
    spotlight, restart the current one first (standard media-player feel).
    Stepping past the last spotlight (`delta_spotlights >= 1` at the
    final entry) rolls straight into the end-of-reel credits — the same
    transition `_log_auto_pause_at_end` uses, so "jump to credits" is a
    discoverable action rather than a passive end behaviour."""
    reel = _log_view_reel
    if reel is None or not reel.spotlights:
        return
    info = _log_spotlight_current()
    if info is None:
        return
    _, spot_idx, offset_within = info
    target_idx = spot_idx + delta_spotlights
    if delta_spotlights < 0 and offset_within > 1_500_000 and spot_idx >= 0:
        # Less than 1.5 s elapsed → step to the previous spotlight.
        # Otherwise restart the current one.
        target_idx = spot_idx
    if target_idx < 0:
        target_idx = 0
    if target_idx >= len(reel.spotlights):
        if delta_spotlights > 0:
            _log_spotlight_jump_to_credits()
        return
    _log_scrubber_seek(reel.spotlight_start_offsets_us[target_idx])


# --- Bottom controls -------------------------------------------------------
def _log_rewind_click():
    """Jump to event 0, preserving the current mode."""
    global _log_play_anchor_offset_us, _log_play_anchor_wall
    global _log_paused_offset_us, _log_cursor_index, _log_last_playhead_index
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    if _log_mode == "play":
        _log_play_anchor_offset_us = 0
        _log_play_anchor_wall      = time.monotonic()
        _log_last_playhead_index   = -1
    else:
        _log_paused_offset_us = 0
        _log_cursor_index     = _log_skip_phantoms(0, prefer_forward=True)
        _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _log_scrubber_seek(target_us):
    """Seek to `target_us`, preserving the current mode."""
    global _log_play_anchor_offset_us, _log_play_anchor_wall
    global _log_paused_offset_us, _log_cursor_index, _log_last_playhead_index
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    target = max(0, min(pb.total_duration_us, int(target_us)))
    if _log_mode == "play":
        _log_play_anchor_offset_us = target
        _log_play_anchor_wall      = time.monotonic()
        _log_last_playhead_index   = -1
    else:
        i = bisect.bisect_right(pb.playback_offset_us, target) - 1
        if i < 0:
            i = 0
        if i >= len(pb.events):
            i = len(pb.events) - 1
        # Snap past a phantom-block landing (e.g. an ←/→ seek to a
        # spotlight boundary, or a drag that drops inside a wipe).
        i = _log_skip_phantoms(i, prefer_forward=True)
        _log_cursor_index     = i
        _log_paused_offset_us = target
        _log_ensure_cursor_visible()
    if _app:
        _app.invalidate()


def _log_make_button_handler(name, on_click):
    """Build a fragment mouse handler for a named overlay button. While a
    scrubber drag is in progress, hover is NOT updated (so buttons the
    pointer crosses mid-drag don't flicker) and the event is routed to
    the seek dispatcher instead of the button's normal handling."""
    def _h(ev):
        if _log_maybe_handle_drag(ev):
            return
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _log_set_overlay_hover(name)
            _log_touch_overlays()
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _log_set_overlay_hover(name)
            _log_touch_overlays()
            on_click()
            return
        _log_touch_overlays()
    return _h


def _log_seek_to_cell(cell, total_cells):
    """Map a scrubber cell index (0-based) to a playback offset and seek
    there. Uses c / (W - 1) so c=0 lands exactly at 0 and c=W-1 lands
    exactly at total_duration_us — the rightmost cell must be reachable
    so end-of-session click/drag can trigger auto-pause. No-op when the
    chain has no duration."""
    pb = _log_view_playback
    if pb is None or pb.total_duration_us <= 0 or total_cells <= 0:
        return
    c = max(0, min(total_cells - 1, int(cell)))
    if total_cells == 1:
        target = 0
    else:
        target = int(c / (total_cells - 1) * pb.total_duration_us)
    _log_scrubber_seek(target)


def _log_handle_drag_event(ev):
    """Route a mouse event from any log_view control to the scrubber-seek
    logic. The scrubber column is derived from the event's absolute column
    relative to the last rendered scrubber's left edge (the overlays all
    span the full width, so ev.position.x is absolute). Clamps to
    [0, W-1] so drift past either end pins to the corresponding endpoint."""
    if _log_scrubber_width <= 0:
        return
    col = ev.position.x - _log_scrubber_left
    _log_seek_to_cell(col, _log_scrubber_width)


def _log_end_drag():
    """Clear the scrubber-drag capture flag and force a redraw so any
    stale state (e.g. the playhead position at release) is rendered."""
    global _log_dragging_scrubber
    if not _log_dragging_scrubber:
        return
    _log_dragging_scrubber = False
    if _app:
        _app.invalidate()


def _log_maybe_handle_drag(ev):
    """If a scrubber drag is in progress, consume `ev` according to its
    type and return True. Returns False otherwise so the caller falls
    through to normal handling. MOUSE_DOWN always ends any stale drag
    but is not consumed — the receiving handler (which may be the
    scrubber itself, re-arming the flag) still runs."""
    if not _log_dragging_scrubber:
        return False
    t = ev.event_type
    if t == MouseEventType.MOUSE_MOVE:
        if getattr(ev, "button", MouseButton.NONE) == MouseButton.NONE:
            # Button was released somewhere we didn't observe MOUSE_UP for.
            _log_end_drag()
            return True
        _log_handle_drag_event(ev)
        return True
    if t == MouseEventType.MOUSE_UP:
        _log_end_drag()
        return True
    if t == MouseEventType.MOUSE_DOWN:
        _log_end_drag()
        return False
    return False


def _log_make_scrubber_handler(cell_index, total_cells):
    """Per-cell scrubber mouse handler. MOUSE_DOWN sets the drag-capture
    flag (so subsequent MOUSE_MOVE events on any control are routed back
    to the seek dispatcher) and performs the initial seek. In-row drag
    is normally consumed by `_log_maybe_handle_drag` before this branch
    runs; the local `is_drag` branch is a defensive fallback that uses
    the per-cell index directly, in case the absolute-column mapping is
    ever out of date. Release ends the drag through
    `_log_maybe_handle_drag` on any log_view control."""
    def _h(ev):
        if _log_maybe_handle_drag(ev):
            return
        global _log_dragging_scrubber
        t = ev.event_type
        is_drag = (t == MouseEventType.MOUSE_MOVE
                   and getattr(ev, "button", MouseButton.NONE) != MouseButton.NONE)
        if t == MouseEventType.MOUSE_DOWN:
            _log_dragging_scrubber = True
            _log_set_overlay_hover(None)
            _log_touch_overlays()
            _log_seek_to_cell(cell_index, total_cells)
            return
        if is_drag:
            _log_set_overlay_hover(None)
            _log_touch_overlays()
            _log_seek_to_cell(cell_index, total_cells)
            return
        if t == MouseEventType.MOUSE_MOVE:
            _log_set_overlay_hover(None)
            _log_touch_overlays()
            return
        _log_touch_overlays()
    return _h


def _log_controls_text():
    """Build the bottom controls overlay row (rewind / play-pause /
    scrubber / time). The whole row is filled with the overlay bg.
    Also publishes the scrubber's absolute column range into
    `_log_scrubber_left` / `_log_scrubber_width` for the drag
    dispatcher (see `_log_handle_drag_event`)."""
    global _log_scrubber_left, _log_scrubber_width
    pb = _log_view_playback
    cols = max(1, _term_cols())
    if pb is None or not pb.events:
        _log_scrubber_left  = 0
        _log_scrubber_width = 0
        return [(C_LOG_OVERLAY_BG, " " * cols, _log_overlay_inert_handler)]

    # Button glyphs. play_glyph reflects the ACTION a click would take —
    # standard video-player convention: play icon while paused, pause
    # icon while playing.
    rewind_label = " ⏮ Rewind "
    if _log_mode == "play":
        pp_label = " ⏸ Pause "
    else:
        pp_label = " ▶ Play  "

    elapsed = _log_format_mmss(_log_current_playback_us())
    total   = _log_format_mmss(pb.total_duration_us)
    time_label = f" {elapsed} / {total} "

    scrubber_w = _LOG_OVERLAY_SCRUBBER_W
    gap = "  "
    inner_w = len(rewind_label) + len(pp_label) + len(gap) + scrubber_w + len(gap) + len(time_label)
    inner_w = min(inner_w, _LOG_OVERLAY_CONTROLS_W, cols)

    overflow = (len(rewind_label) + len(pp_label) + len(gap)
                + scrubber_w + len(gap) + len(time_label)) - inner_w
    if overflow > 0:
        scrubber_w = max(4, scrubber_w - overflow)

    side = max(0, (cols - inner_w) // 2)
    right_side = max(0, cols - inner_w - side)

    frags = []
    pad = _log_pad(side)
    if pad:
        frags.append(pad)

    rewind_style = C_LOG_BUTTON_HOVER if _log_overlay_hover == "rewind" else C_LOG_BUTTON_IDLE
    frags.append((rewind_style, rewind_label,
                  _log_make_button_handler("rewind", _log_rewind_click)))

    pp_style = C_LOG_BUTTON_HOVER if _log_overlay_hover == "playpause" else C_LOG_BUTTON_IDLE
    frags.append((pp_style, pp_label,
                  _log_make_button_handler("playpause", _log_toggle_play_pause)))

    frags.append((C_LOG_OVERLAY_BG, gap, _log_overlay_inert_handler))

    # Record the scrubber's absolute left edge + width so a drag that
    # drifts off the scrubber row can still map ev.position.x → cell.
    # The bottom overlay Float spans full width with left=0, so the
    # accumulated "side + buttons + gap" column count is absolute.
    _log_scrubber_left  = side + len(rewind_label) + len(pp_label) + len(gap)
    _log_scrubber_width = scrubber_w

    if pb.total_duration_us > 0:
        thumb_cell = int(_log_current_playback_us() / pb.total_duration_us * scrubber_w)
        if thumb_cell >= scrubber_w:
            thumb_cell = scrubber_w - 1
    else:
        thumb_cell = 0
    for c in range(scrubber_w):
        if c < thumb_cell:
            style, glyph = C_LOG_SCRUBBER_FILLED, "━"
        elif c == thumb_cell:
            style, glyph = C_LOG_SCRUBBER_THUMB, "●"
        else:
            style, glyph = C_LOG_SCRUBBER_EMPTY, "─"
        frags.append((style, glyph, _log_make_scrubber_handler(c, scrubber_w)))

    frags.append((C_LOG_OVERLAY_BG, gap, _log_overlay_inert_handler))

    frags.append((C_LOG_OVERLAY_FG, time_label, _log_overlay_inert_handler))

    pad = _log_pad(right_side)
    if pad:
        frags.append(pad)
    return frags


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
@kb.add("tab", filter=_in_frame("profile"))
def _kb_profile_tab(event):
    _profile_cycle_focus(1)


@kb.add("s-tab", filter=_in_frame("profile"))
def _kb_profile_stab(event):
    _profile_cycle_focus(-1)


@kb.add("right", filter=_in_frame("profile"))
def _kb_profile_right(event):
    # Spatial Tab — table → options. No-op when already on options.
    if _profile_focused == 0:
        _profile_set_focus(1)


@kb.add("left", filter=_in_frame("profile"))
def _kb_profile_left(event):
    # Spatial Shift+Tab — options → table. No-op when already on table.
    if _profile_focused == 1:
        _profile_set_focus(0)


@kb.add("up", filter=_in_frame("profile"))
def _kb_profile_up(event):
    if _profile_focused == 0:
        _profile_move_table(-1)
    else:
        _profile_menu_move(-1)


@kb.add("down", filter=_in_frame("profile"))
def _kb_profile_down(event):
    if _profile_focused == 0:
        _profile_move_table(1)
    else:
        _profile_menu_move(1)


@kb.add("pageup", filter=_in_frame("profile"))
def _kb_profile_pgup(event):
    if _profile_focused == 0:
        _profile_jump_table(_profile_table_cursor - 10)


@kb.add("pagedown", filter=_in_frame("profile"))
def _kb_profile_pgdn(event):
    if _profile_focused == 0:
        _profile_jump_table(_profile_table_cursor + 10)


@kb.add("home", filter=_in_frame("profile"))
def _kb_profile_home(event):
    if _profile_focused == 0:
        _profile_jump_table(0)


@kb.add("end", filter=_in_frame("profile"))
def _kb_profile_end(event):
    if _profile_focused == 0:
        _profile_jump_table(len(_profiles) - 1)


@kb.add("enter", filter=_in_frame("profile"))
@kb.add(" ",     filter=_in_frame("profile"))
def _kb_profile_select(event):
    if _profile_focused == 0:
        # Enter on a table row triggers Select (no-op if disabled).
        actions = _profile_menu_actions()
        # Select is index 0.
        if actions and actions[0][2]:
            _profile_menu_activate(0)
    else:
        _profile_menu_activate(_profile_menu_cursor)


@kb.add("escape", filter=_in_frame("profile"), eager=True)
def _kb_profile_escape(event):
    _pop_frame()


# Profile editor — Tab / Shift+Tab cycle the 4-stop focus chain
# (tabs → list → detail.Pattern → detail.Body → tabs). Arrows and
# printable input route through one handler per key, gated on the
# current focus zone + active detail field.
@kb.add("tab", filter=_in_frame("profile_editor"))
def _kb_peditor_tab(event):
    _profile_editor_cycle_focus(1)


@kb.add("s-tab", filter=_in_frame("profile_editor"))
def _kb_peditor_stab(event):
    _profile_editor_cycle_focus(-1)


def _editor_in_palette_focus():
    """True when the detail panel's Body slot is showing the colour
    palette grid (Highlights tab + detail field 1)."""
    return (_editor_focus == 2
            and _editor_detail_field == 1
            and _profile_editor_active_kind() == "highlight")


def _editor_in_macro_key_focus():
    """True when the detail panel's Pattern slot is showing the macro
    Key cell (Macros tab + detail field 0)."""
    return (_editor_focus == 2
            and _editor_detail_field == 0
            and _profile_editor_active_kind() == "macro")


@kb.add("right", filter=_in_frame("profile_editor"))
def _kb_peditor_right(event):
    if _editor_focus == 0:
        _profile_editor_set_tab(_editor_active_tab + 1)
    elif _editor_focus == 1:
        _profile_editor_set_focus(2, field=0)
    elif _editor_focus == 2:
        if _editor_in_macro_key_focus():
            return   # Key cell is a button — no horizontal cursor
        if _editor_in_palette_focus():
            _editor_palette_move(0, 1)
        elif _editor_detail_field == 0:
            _editor_clear_pattern_selection()
            _editor_pattern_move_right()
        else:
            _editor_clear_body_selection()
            _editor_body_move_right()


@kb.add("left", filter=_in_frame("profile_editor"))
def _kb_peditor_left(event):
    if _editor_focus == 0:
        _profile_editor_set_tab(_editor_active_tab - 1)
    elif _editor_focus == 2:
        if _editor_in_macro_key_focus():
            return   # Key cell is a button — no horizontal cursor
        if _editor_in_palette_focus():
            _editor_palette_move(0, -1)
        elif _editor_detail_field == 0:
            _editor_clear_pattern_selection()
            _editor_pattern_move_left()
        else:
            _editor_clear_body_selection()
            _editor_body_move_left()


@kb.add("up", filter=_in_frame("profile_editor"))
def _kb_peditor_up(event):
    if _editor_focus == 0:
        return   # nothing above the tabs
    if _editor_focus == 1:
        # First list row ↑ → focus the tab strip; otherwise move within.
        if _editor_list_cursor == 0:
            _profile_editor_set_focus(0)
        else:
            _profile_editor_move_cursor(-1)
        return
    # Detail focus.
    if _editor_detail_field == 0:
        # Pattern ↑ → focus the tab strip.
        _profile_editor_set_focus(0)
        return
    if _editor_in_palette_focus():
        # Palette ↑: traverse the grid; fall through to Pattern at the
        # top edge.
        if not _editor_palette_move(-1, 0):
            _profile_editor_set_focus(2, field=0)
        return
    # Text body ↑: inter-line first; at top edge of buffer → Pattern.
    _editor_clear_body_selection()
    if not _editor_body_move_line(-1):
        _profile_editor_set_focus(2, field=0)


@kb.add("down", filter=_in_frame("profile_editor"))
def _kb_peditor_down(event):
    if _editor_focus == 0:
        _profile_editor_set_focus(1)
        _profile_editor_jump_cursor(0)
        return
    if _editor_focus == 1:
        _profile_editor_move_cursor(1)
        return
    # Detail focus.
    if _editor_detail_field == 0:
        _profile_editor_set_focus(2, field=1)
        return
    if _editor_in_palette_focus():
        _editor_palette_move(1, 0)
        return
    _editor_clear_body_selection()
    _editor_body_move_line(1)


# Shift-arrow selection. Each handler arms the anchor (if not already
# set) and reuses the regular movement primitive. The selection cell-
# range is computed at render time from (anchor, cursor).
@kb.add("s-right", filter=_in_frame("profile_editor"))
def _kb_peditor_s_right(event):
    if _editor_focus != 2:
        return
    if _editor_in_macro_key_focus() or _editor_in_palette_focus():
        return
    if _editor_detail_field == 0:
        _editor_pattern_set_anchor_if_none()
        _editor_pattern_move_right()
    else:
        _editor_body_set_anchor_if_none()
        _editor_body_move_right()


@kb.add("s-left", filter=_in_frame("profile_editor"))
def _kb_peditor_s_left(event):
    if _editor_focus != 2:
        return
    if _editor_in_macro_key_focus() or _editor_in_palette_focus():
        return
    if _editor_detail_field == 0:
        _editor_pattern_set_anchor_if_none()
        _editor_pattern_move_left()
    else:
        _editor_body_set_anchor_if_none()
        _editor_body_move_left()


@kb.add("s-up", filter=_in_frame("profile_editor"))
def _kb_peditor_s_up(event):
    if _editor_focus != 2:
        return
    if (_editor_in_macro_key_focus() or _editor_in_palette_focus()
            or _editor_detail_field == 0):
        return   # Pattern is single-line — s-up is a no-op
    _editor_body_set_anchor_if_none()
    _editor_body_move_line(-1)


@kb.add("s-down", filter=_in_frame("profile_editor"))
def _kb_peditor_s_down(event):
    if _editor_focus != 2:
        return
    if (_editor_in_macro_key_focus() or _editor_in_palette_focus()
            or _editor_detail_field == 0):
        return
    _editor_body_set_anchor_if_none()
    _editor_body_move_line(1)


@kb.add("s-home", filter=_in_frame("profile_editor"))
def _kb_peditor_s_home(event):
    if _editor_focus != 2:
        return
    if _editor_in_macro_key_focus() or _editor_in_palette_focus():
        return
    if _editor_detail_field == 0:
        _editor_pattern_set_anchor_if_none()
        _editor_pattern_move_home()
    else:
        _editor_body_set_anchor_if_none()
        _editor_body_move_home()


@kb.add("s-end", filter=_in_frame("profile_editor"))
def _kb_peditor_s_end(event):
    if _editor_focus != 2:
        return
    if _editor_in_macro_key_focus() or _editor_in_palette_focus():
        return
    if _editor_detail_field == 0:
        _editor_pattern_set_anchor_if_none()
        _editor_pattern_move_end()
    else:
        _editor_body_set_anchor_if_none()
        _editor_body_move_end()


@kb.add("pageup", filter=_in_frame("profile_editor"))
def _kb_peditor_pgup(event):
    if _editor_focus == 1:
        _profile_editor_move_cursor(-_editor_list_visible())


@kb.add("pagedown", filter=_in_frame("profile_editor"))
def _kb_peditor_pgdn(event):
    if _editor_focus == 1:
        _profile_editor_move_cursor(_editor_list_visible())


@kb.add("home", filter=_in_frame("profile_editor"))
def _kb_peditor_home(event):
    if _editor_focus == 1:
        _profile_editor_jump_cursor(0)
        return
    if _editor_focus == 2:
        if _editor_in_macro_key_focus() or _editor_in_palette_focus():
            return
        if _editor_detail_field == 0:
            _editor_clear_pattern_selection()
            _editor_pattern_move_home()
        else:
            _editor_clear_body_selection()
            _editor_body_move_home()


@kb.add("end", filter=_in_frame("profile_editor"))
def _kb_peditor_end(event):
    if _editor_focus == 1:
        # End jumps to the sentinel row — the last selectable position.
        _profile_editor_jump_cursor(_profile_editor_display_total() - 1)
        return
    if _editor_focus == 2:
        if _editor_in_macro_key_focus() or _editor_in_palette_focus():
            return
        if _editor_detail_field == 0:
            _editor_clear_pattern_selection()
            _editor_pattern_move_end()
        else:
            _editor_clear_body_selection()
            _editor_body_move_end()


@kb.add("delete", filter=_in_frame("profile_editor"))
def _kb_peditor_kdelete(event):
    """Forward-delete the character at the cursor in Pattern/Body. On
    list focus, this binding is a no-op for now — Section B swaps `d`
    out for `Delete` to delete the list entry."""
    if _editor_focus != 2:
        return
    if _editor_in_macro_key_focus() or _editor_in_palette_focus():
        return
    if _editor_detail_field == 0:
        _editor_pattern_forward_delete()
        if _app:
            _app.invalidate()
    else:
        _editor_body_forward_delete()


@kb.add("d", filter=_in_frame("profile_editor"))
@kb.add("D", filter=_in_frame("profile_editor"))
def _kb_peditor_delete(event):
    if _editor_focus == 1:
        _profile_editor_request_delete()
    elif _editor_focus == 2:
        # In a detail field, `d` is a regular character — fall through
        # to the printable-input handler (the palette field swallows it).
        _kb_peditor_any(event)


@kb.add("n", filter=_in_frame("profile_editor"))
@kb.add("N", filter=_in_frame("profile_editor"))
def _kb_peditor_n(event):
    if _editor_focus == 1:
        _editor_create_new_entry()
    elif _editor_focus == 2:
        _kb_peditor_any(event)


@kb.add("enter", filter=_in_frame("profile_editor"))
def _kb_peditor_enter(event):
    if _editor_focus == 1:
        if _editor_cursor_on_sentinel():
            _editor_create_new_entry()
            return
        entry = _editor_current_entry()
        if entry is None:
            return
        _profile_editor_set_focus(2, field=0)
        return
    if _editor_focus == 2:
        if _editor_in_macro_key_focus():
            # Key cell is a button — Enter pushes the capture overlay.
            _editor_push_keybind_overlay(just_created=False)
            return
        if _editor_in_palette_focus():
            return   # palette is selection-only; Enter is a no-op
        if _editor_detail_field == 1:
            _editor_body_insert_newline()
        # Pattern: Enter is a no-op (use Tab / ↓ to advance).


@kb.add("backspace", filter=_in_frame("profile_editor"))
def _kb_peditor_backspace(event):
    if _editor_focus != 2:
        return
    if _editor_in_macro_key_focus():
        return   # Key cell is a button — backspace is a no-op
    if _editor_detail_field == 0:
        _editor_pattern_backspace()
        if _app:
            _app.invalidate()
    elif _editor_in_palette_focus():
        return   # palette is selection-only
    else:
        _editor_body_backspace()


@kb.add("<any>", filter=_in_frame("profile_editor"))
def _kb_peditor_any(event):
    """Printable-char input on the detail panel. Pattern and Body
    accept any printable character; insertion happens at the in-buffer
    cursor. The palette field and the macro Key cell are
    selection-only and swallow everything."""
    if _editor_focus != 2:
        return
    if _editor_in_palette_focus():
        return
    if _editor_in_macro_key_focus():
        return
    data = event.data or ""
    if len(data) != 1 or not data.isprintable():
        return
    if _editor_detail_field == 0:
        _editor_pattern_insert_char(data)
        if _app:
            _app.invalidate()
    elif _editor_detail_field == 1:
        _editor_body_insert_char(data)
        if _app:
            _app.invalidate()


@kb.add("escape", filter=_in_frame("profile_editor"), eager=True)
def _kb_peditor_escape(event):
    _profile_editor_save_and_close()


# Profile editor — delete-confirm sub-frame
@kb.add("enter", filter=_in_frame("profile_editor_delete_confirm"))
def _kb_peditor_del_enter(event):
    _profile_editor_confirm_delete()


@kb.add("escape", filter=_in_frame("profile_editor_delete_confirm"),
        eager=True)
def _kb_peditor_del_escape(event):
    _profile_editor_cancel_delete()


# Profile editor — macro key-capture overlay
# `eager=True` is intentionally omitted on the ESC binding so
# prompt_toolkit waits briefly for a follower key — without that
# disambiguation, Alt+letter (delivered as `escape`, then letter)
# fires Cancel before the letter arrives.
@kb.add("escape", filter=_in_frame("profile_editor_macro_keybind"))
def _kb_peditor_keybind_escape(event):
    _editor_keybind_cancel()


# Explicit binding per KNOWN_KEYS entry. Required so prompt_toolkit
# matches chord forms (("escape", "a") for Alt+a, ("escape", "O", "p")
# for Numpad 0) before the bare `escape` Cancel — and so the chord
# doesn't fall through to the wildcard `<any>` on the parent list.
def _register_overlay_keybinds():
    for mk in macro_keys.KNOWN_KEYS:
        keys = mk.pk_keys if isinstance(mk.pk_keys, tuple) else (mk.pk_keys,)
        def _handler(event, _mk=mk):
            _editor_keybind_accept(_mk)
        kb.add(*keys,
               filter=_in_frame("profile_editor_macro_keybind"))(_handler)
_register_overlay_keybinds()


@kb.add("<any>", filter=_in_frame("profile_editor_macro_keybind"))
def _kb_peditor_keybind_any(event):
    """Wildcard fallback for keys outside KNOWN_KEYS — show the standard
    rejection message. (Known keys are handled by the explicit bindings
    registered above, which take precedence over this wildcard.)"""
    match = macro_keys.match_pressed(event)
    if match is not None:
        # Defensive — explicit bindings above should have caught this.
        _editor_keybind_accept(match)
    else:
        _editor_keybind_set_error(macro_keys.rejection_reason(event))


# Profile rename
@kb.add("escape", filter=_in_frame("profile_rename"), eager=True)
def _kb_pren_escape(event):
    _pop_frame()


@kb.add("enter", filter=_in_frame("profile_rename"))
def _kb_pren_enter(event):
    _profile_rename_confirm()


@kb.add("backspace", filter=_in_frame("profile_rename"))
def _kb_pren_backspace(event):
    global _rename_name_buf, _rename_name_err
    if _rename_name_buf:
        _rename_name_buf = _rename_name_buf[:-1]
        _rename_name_err = ""


@kb.add("<any>", filter=_in_frame("profile_rename"))
def _kb_pren_any(event):
    global _rename_name_buf, _rename_name_err
    data = event.data or ""
    if len(data) != 1 or not data.isprintable():
        return
    if len(_rename_name_buf) >= 32:
        return
    _rename_name_buf += data
    _rename_name_err = ""


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


# Options — top level
@kb.add("up", filter=_in_frame("options"))
def _kb_opt_up(event):
    global _sel_options
    n = len(_OPTIONS_ROWS)
    if n:
        _sel_options = (_sel_options - 1) % n


@kb.add("down", filter=_in_frame("options"))
def _kb_opt_down(event):
    global _sel_options
    n = len(_OPTIONS_ROWS)
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


# Options — Panes submenu
@kb.add("up", filter=_in_frame("options_panes"))
def _kb_optp_up(event):
    global _sel_options_panes
    n = len(_options_panes_selectable_indices())
    if n:
        _sel_options_panes = (_sel_options_panes - 1) % n


@kb.add("down", filter=_in_frame("options_panes"))
def _kb_optp_down(event):
    global _sel_options_panes
    n = len(_options_panes_selectable_indices())
    if n:
        _sel_options_panes = (_sel_options_panes + 1) % n


@kb.add("enter", filter=_in_frame("options_panes"))
@kb.add(" ",     filter=_in_frame("options_panes"))
def _kb_optp_select(event):
    sel = _options_panes_selectable_indices()
    if not sel:
        return
    idx = _sel_options_panes if _sel_options_panes < len(sel) else len(sel) - 1
    _options_panes_activate(sel[idx])


@kb.add("escape", filter=_in_frame("options_panes"), eager=True)
def _kb_optp_escape(event):
    _save_conf()
    _pop_frame()


# Options — per-pane subframe
@kb.add("up", filter=_in_frame("options_pane"))
def _kb_optpp_up(event):
    global _sel_options_pane
    n = len(_options_pane_selectable_indices())
    if n:
        _sel_options_pane = (_sel_options_pane - 1) % n


@kb.add("down", filter=_in_frame("options_pane"))
def _kb_optpp_down(event):
    global _sel_options_pane
    n = len(_options_pane_selectable_indices())
    if n:
        _sel_options_pane = (_sel_options_pane + 1) % n


@kb.add("enter", filter=_in_frame("options_pane"))
@kb.add(" ",     filter=_in_frame("options_pane"))
def _kb_optpp_select(event):
    sel = _options_pane_selectable_indices()
    if not sel:
        return
    idx = _sel_options_pane if _sel_options_pane < len(sel) else len(sel) - 1
    _options_pane_activate(sel[idx])


@kb.add("escape", filter=_in_frame("options_pane"), eager=True)
def _kb_optpp_escape(event):
    _save_conf()
    _pop_frame()


# Options — Spotlights submenu
@kb.add("up", filter=_in_frame("options_spotlights"))
def _kb_opts_up(event):
    global _sel_options_spotlights
    n = len(_options_spotlights_selectable_indices())
    if n:
        _sel_options_spotlights = (_sel_options_spotlights - 1) % n


@kb.add("down", filter=_in_frame("options_spotlights"))
def _kb_opts_down(event):
    global _sel_options_spotlights
    n = len(_options_spotlights_selectable_indices())
    if n:
        _sel_options_spotlights = (_sel_options_spotlights + 1) % n


@kb.add("enter", filter=_in_frame("options_spotlights"))
@kb.add(" ",     filter=_in_frame("options_spotlights"))
def _kb_opts_select(event):
    sel = _options_spotlights_selectable_indices()
    if not sel:
        return
    idx = _sel_options_spotlights if _sel_options_spotlights < len(sel) else len(sel) - 1
    _options_spotlights_activate(sel[idx])


@kb.add("escape", filter=_in_frame("options_spotlights"), eager=True)
def _kb_opts_escape(event):
    _save_conf()
    _pop_frame()


# Options — Connection submenu
@kb.add("up", filter=_in_frame("options_connection"))
def _kb_optc_up(event):
    global _sel_options_connection
    n = len(_CONNECTION_MODES) + 1
    if n:
        _sel_options_connection = (_sel_options_connection - 1) % n


@kb.add("down", filter=_in_frame("options_connection"))
def _kb_optc_down(event):
    global _sel_options_connection
    n = len(_CONNECTION_MODES) + 1
    if n:
        _sel_options_connection = (_sel_options_connection + 1) % n


@kb.add("enter", filter=_in_frame("options_connection"))
@kb.add(" ",     filter=_in_frame("options_connection"))
def _kb_optc_select(event):
    _options_connection_activate(_sel_options_connection)


@kb.add("escape", filter=_in_frame("options_connection"), eager=True)
def _kb_optc_escape(event):
    _save_conf()
    _pop_frame()


# Options — Connection custom host:port input
@kb.add("escape", filter=_in_frame("options_connection_custom"), eager=True)
def _kb_optcc_escape(event):
    _pop_frame()


@kb.add("tab", filter=_in_frame("options_connection_custom"))
@kb.add("s-tab", filter=_in_frame("options_connection_custom"))
def _kb_optcc_tab(event):
    global _conn_field, _conn_err
    _conn_field = 1 - _conn_field
    _conn_err = ""


@kb.add("enter", filter=_in_frame("options_connection_custom"))
def _kb_optcc_enter(event):
    _options_connection_custom_save()


@kb.add("backspace", filter=_in_frame("options_connection_custom"))
def _kb_optcc_backspace(event):
    global _conn_host_buf, _conn_port_buf, _conn_err
    if _conn_field == 0:
        if _conn_host_buf:
            _conn_host_buf = _conn_host_buf[:-1]
    else:
        if _conn_port_buf:
            _conn_port_buf = _conn_port_buf[:-1]
    _conn_err = ""


@kb.add("<any>", filter=_in_frame("options_connection_custom"))
def _kb_optcc_any(event):
    global _conn_host_buf, _conn_port_buf, _conn_err
    data = event.data or ""
    if len(data) != 1 or not data.isprintable():
        return
    if _conn_field == 0:
        if len(_conn_host_buf) >= 64:
            return
        _conn_host_buf += data
    else:
        if not data.isdigit():
            return
        if len(_conn_port_buf) >= 5:
            return
        _conn_port_buf += data
    _conn_err = ""


# Options — Coming-soon placeholder (any key returns)
@kb.add("escape", filter=_in_frame("options_coming_soon"), eager=True)
def _kb_optcs_escape(event):
    _pop_frame()


@kb.add("<any>", filter=_in_frame("options_coming_soon"))
def _kb_optcs_any(event):
    _pop_frame()


# Spotlights — empty-state placeholder (any key returns)
@kb.add("escape", filter=_in_frame("spotlights_empty"), eager=True)
def _kb_spemp_escape(event):
    _pop_frame()


@kb.add("<any>", filter=_in_frame("spotlights_empty"))
def _kb_spemp_any(event):
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
def _kb_hist_tab(event):
    _history_cycle_focus(1)


@kb.add("s-tab", filter=_in_frame("history"))
def _kb_hist_stab(event):
    _history_cycle_focus(-1)


@kb.add("left", filter=_in_frame("history"))
def _kb_hist_left(event):
    if _history_focused == 0:
        _history_move_filter(-1)


@kb.add("right", filter=_in_frame("history"))
def _kb_hist_right(event):
    if _history_focused == 0:
        _history_move_filter(1)


@kb.add("up", filter=_in_frame("history"))
def _kb_hist_up(event):
    if _history_focused == 1:
        _history_move_table(-1)
    elif _history_focused == 2:
        _history_menu_move(-1)


@kb.add("down", filter=_in_frame("history"))
def _kb_hist_down(event):
    if _history_focused == 1:
        _history_move_table(1)
    elif _history_focused == 2:
        _history_menu_move(1)


@kb.add("pageup", filter=_in_frame("history"))
def _kb_hist_pgup(event):
    if _history_focused == 1:
        _history_jump_table(_history_table_cursor - 10)


@kb.add("pagedown", filter=_in_frame("history"))
def _kb_hist_pgdn(event):
    if _history_focused == 1:
        _history_jump_table(_history_table_cursor + 10)


@kb.add("home", filter=_in_frame("history"))
def _kb_hist_home(event):
    if _history_focused == 1:
        _history_jump_table(0)


@kb.add("end", filter=_in_frame("history"))
def _kb_hist_end(event):
    if _history_focused == 1:
        _history_jump_table(len(_history_sessions) - 1)


@kb.add("enter", filter=_in_frame("history"))
@kb.add(" ",     filter=_in_frame("history"))
def _kb_hist_enter(event):
    if _history_focused == 0:
        _history_apply_cursor_filter()
    elif _history_focused == 1:
        _history_activate_table_row(_history_table_cursor)
    else:
        _history_menu_activate(_history_menu_cursor)


@kb.add("escape", filter=_in_frame("history"), eager=True)
def _kb_hist_escape(event):
    _pop_frame()


# History rate-session frame (launcher surface)
for _n in range(6):
    def _make_hr_digit(val=_n):
        def _h(event):
            global _history_rate_rating
            _history_rate_rating = val
            if _app:
                _app.invalidate()
        return _h
    kb.add(str(_n), filter=_in_frame("history_rate"))(_make_hr_digit())
del _n


@kb.add("left", filter=_in_frame("history_rate"))
def _kb_hr_left(event):
    global _history_rate_rating
    _history_rate_rating = max(0, _history_rate_rating - 1)
    if _app:
        _app.invalidate()


@kb.add("right", filter=_in_frame("history_rate"))
def _kb_hr_right(event):
    global _history_rate_rating
    _history_rate_rating = min(5, _history_rate_rating + 1)
    if _app:
        _app.invalidate()


@kb.add("enter", filter=_in_frame("history_rate"))
@kb.add(" ",     filter=_in_frame("history_rate"))
def _kb_hr_save(event):
    _history_rate_save()


@kb.add("escape", filter=_in_frame("history_rate"), eager=True)
def _kb_hr_escape(event):
    _history_rate_cancel()


# History delete confirm
@kb.add("y", filter=_in_frame("history_delete_confirm"))
@kb.add("Y", filter=_in_frame("history_delete_confirm"))
def _kb_hdc_yes(event):
    _history_delete_confirm_yes()


@kb.add("escape", filter=_in_frame("history_delete_confirm"), eager=True)
def _kb_hdc_escape(event):
    _history_delete_confirm_cancel()


@kb.add("<any>", filter=_in_frame("history_delete_confirm"))
def _kb_hdc_any(event):
    _history_delete_confirm_cancel()


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


# log_view (chain log player)
@kb.add("escape", filter=_in_frame("log_view"), eager=True)
def _kb_log_escape(event):
    _exit_log_view()


@kb.add("space", filter=_in_frame("log_view"))
def _kb_log_space(event):
    _log_touch_overlays()
    _log_toggle_play_pause()


@kb.add("up", filter=_in_frame("log_view"))
def _kb_log_up(event):
    _log_touch_overlays()
    _log_move_cursor(-1)


@kb.add("down", filter=_in_frame("log_view"))
def _kb_log_down(event):
    _log_touch_overlays()
    _log_move_cursor(1)


@kb.add("pageup", filter=_in_frame("log_view"))
def _kb_log_pgup(event):
    _log_touch_overlays()
    _log_move_cursor(-_LOG_PAGE_STEP)


@kb.add("pagedown", filter=_in_frame("log_view"))
def _kb_log_pgdn(event):
    _log_touch_overlays()
    _log_move_cursor(_LOG_PAGE_STEP)


@kb.add("home", filter=_in_frame("log_view"))
def _kb_log_home(event):
    _log_touch_overlays()
    _log_cursor_to(0)


@kb.add("end", filter=_in_frame("log_view"))
def _kb_log_end(event):
    _log_touch_overlays()
    pb = _log_view_playback
    if pb is None or not pb.events:
        return
    _log_cursor_to(len(pb.events) - 1)


# Credits (end-of-reel scrolling chronicle). ESC exits immediately;
# all other input is ignored (mouse + keys).
@kb.add("escape", filter=_in_frame("credits"), eager=True)
def _kb_credits_escape(event):
    _credits_finish()


# Spotlight-mode ← / → seek between spotlights. The bindings are added
# unconditionally; a `_log_view_mode != "spotlight"` guard inside the
# handler makes them no-ops in chain mode.
@kb.add("right", filter=_in_frame("log_view"))
def _kb_log_next_spotlight(event):
    if _log_view_mode != "spotlight":
        return
    _log_touch_overlays()
    _log_spotlight_seek_relative(1)


@kb.add("left", filter=_in_frame("log_view"))
def _kb_log_prev_spotlight(event):
    if _log_view_mode != "spotlight":
        return
    _log_touch_overlays()
    _log_spotlight_seek_relative(-1)


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
    """Build the History frame:
        title · filter header · pill row · blank · [table + options] · feedback · footer.
    Returns the three focusable windows (filter / table / options) plus the frame."""
    title  = Window(content=FormattedTextControl(text=_history_title_text, focusable=False),
                    height=3, wrap_lines=False, always_hide_cursor=True)
    footer = Window(content=FormattedTextControl(text=_history_footer_text, focusable=False),
                    height=2, wrap_lines=False, always_hide_cursor=True)

    filter_header_win = Window(
        content=FormattedTextControl(text=_history_filter_header_text, focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )
    filter_pills_win = Window(
        content=FormattedTextControl(text=_history_filter_pills_text, focusable=True),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )

    # Hover-clearing filler used by spacers and blanks. One " " per body
    # row so MOUSE_MOVE over padding fires _hover_at(None, None).
    def _make_filler_text(width, rows_fn=None):
        def _fn():
            rows = rows_fn() if rows_fn else 1
            clear = _hover_at(None, None)
            out = []
            for i in range(rows):
                out.append(("", " " * width, clear))
                if i < rows - 1:
                    out.append(("", "\n", clear))
            return out
        return _fn

    blank_above_table = Window(
        content=FormattedTextControl(text=_make_filler_text(1), focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )

    # Centred package: [left_spacer | table | scrollbar | gap | options | right_spacer]
    # Width contract:
    #   table_left_spacer = _history_left_pad()
    #   table_win         = _history_table_panel_w()
    #   table_sb_win      = 1
    #   gap_win           = _HISTORY_OPTIONS_GAP
    #   options_win       = _HISTORY_BUTTON_W
    #   table_right_spacer = remainder (flex)
    table_win = Window(
        content=_WheelScrollControl(text=_history_table_text, focusable=True,
                                    on_scroll=lambda d: _history_scroll_panel(1, d)),
        wrap_lines=False, always_hide_cursor=True,
        width=lambda: Dimension.exact(_history_table_panel_w()),
    )
    table_sb_win = Window(
        content=FormattedTextControl(text=_history_table_scrollbar_text, focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(1),
    )
    table_left_spacer = Window(
        content=FormattedTextControl(
            text=_make_filler_text(1, rows_fn=_history_table_window_h),
            focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=lambda: Dimension.exact(_history_left_pad()),
    )
    gap_win = Window(
        content=FormattedTextControl(
            text=_make_filler_text(1, rows_fn=_history_table_window_h),
            focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(_HISTORY_OPTIONS_GAP),
    )
    options_win = Window(
        content=FormattedTextControl(text=_history_options_text, focusable=True),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(_HISTORY_BUTTON_W),
    )
    table_right_spacer = Window(
        content=FormattedTextControl(
            text=_make_filler_text(1, rows_fn=_history_table_window_h),
            focusable=False),
        wrap_lines=False, always_hide_cursor=True,
    )
    table_row = VSplit(
        [table_left_spacer, table_win, table_sb_win, gap_win, options_win,
         table_right_spacer],
        height=lambda: Dimension.exact(_history_table_window_h()),
    )

    # Single-row feedback slot — doubles as the spacing row between the
    # table package and the footer. Renders empty when no message is
    # flashing.
    feedback_win = Window(
        content=FormattedTextControl(text=_history_feedback_or_blank_text,
                                     focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )

    body = HSplit([
        filter_header_win,
        filter_pills_win,
        blank_above_table,
        table_row,
        feedback_win,
    ])
    # flex_spacer sits below the footer and absorbs leftover terminal rows
    # so the footer hint sits one row below the table package instead of
    # pinning to the terminal's last row.
    flex_spacer = Window()
    return (filter_pills_win, table_win, options_win,
            HSplit([title, body, footer, flex_spacer]))


def _build_profile():
    """Build the Profile frame:
        title · [table + options] · feedback · footer.
    Returns the two focusable windows (table / options) plus the frame."""
    title  = Window(content=FormattedTextControl(text=_profile_title_text, focusable=False),
                    height=3, wrap_lines=False, always_hide_cursor=True)
    footer = Window(content=FormattedTextControl(text=_profile_footer_text, focusable=False),
                    height=2, wrap_lines=False, always_hide_cursor=True)

    def _make_filler_text(width, rows_fn=None):
        def _fn():
            rows = rows_fn() if rows_fn else 1
            clear = _profile_hover_at(None, None)
            out = []
            for i in range(rows):
                out.append(("", " " * width, clear))
                if i < rows - 1:
                    out.append(("", "\n", clear))
            return out
        return _fn

    table_win = Window(
        content=_WheelScrollControl(text=_profile_table_text, focusable=True,
                                    on_scroll=_profile_scroll_table),
        wrap_lines=False, always_hide_cursor=True,
        width=lambda: Dimension.exact(_profile_table_panel_w()),
    )
    table_sb_win = Window(
        content=FormattedTextControl(text=_profile_table_scrollbar_text, focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(1),
    )
    table_left_spacer = Window(
        content=FormattedTextControl(
            text=_make_filler_text(1, rows_fn=_profile_table_window_h),
            focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=lambda: Dimension.exact(_profile_left_pad()),
    )
    gap_win = Window(
        content=FormattedTextControl(
            text=_make_filler_text(1, rows_fn=_profile_table_window_h),
            focusable=False),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(_PROFILE_OPTIONS_GAP),
    )
    options_win = Window(
        content=FormattedTextControl(text=_profile_options_text, focusable=True),
        wrap_lines=False, always_hide_cursor=True,
        width=Dimension.exact(_PROFILE_BUTTON_W),
    )
    table_right_spacer = Window(
        content=FormattedTextControl(
            text=_make_filler_text(1, rows_fn=_profile_table_window_h),
            focusable=False),
        wrap_lines=False, always_hide_cursor=True,
    )
    table_row = VSplit(
        [table_left_spacer, table_win, table_sb_win, gap_win, options_win,
         table_right_spacer],
        height=lambda: Dimension.exact(_profile_table_window_h()),
    )

    feedback_win = Window(
        content=FormattedTextControl(text=_profile_feedback_or_blank_text,
                                     focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )

    body = HSplit([
        table_row,
        feedback_win,
    ])
    flex_spacer = Window()
    return (table_win, options_win,
            HSplit([title, body, footer, flex_spacer]))


def _build_history_rate():
    """Build the History rate-session frame — single centred Window with the
    star widget and footer hint. Mirrors the popup's rate_session shape."""
    win = Window(
        content=FormattedTextControl(text=_history_rate_text, focusable=True),
        wrap_lines=False, always_hide_cursor=True,
    )
    return win, _centered(win)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _app, _app_loop, _cockpit_version, _cache_mtime
    global _main_window
    global _profile_table_window, _profile_options_window, _profile_rename_window
    global _profile_create_name_window, _profile_create_choose_window
    global _profile_create_copy_window, _profile_delete_window
    global _profile_editor_window, _profile_editor_delete_window
    global _profile_editor_keybind_window
    global _options_window, _options_panes_window, _options_pane_window
    global _options_connection_window, _options_connection_custom_window
    global _options_coming_soon_window, _options_spotlights_window
    global _spotlights_empty_window
    global _scripts_window, _about_window
    global _update_running_window, _update_result_window
    global _exit_confirm_window, _too_small_window
    global _history_filter_window, _history_table_window, _history_options_window
    global _history_detail_window, _history_rate_window
    global _history_delete_confirm_window
    global _log_view_window
    global _credits_window

    os.chdir(PROJECT_DIR)
    _one_shot_migrations()
    _load_conf()
    try:
        run_retention.prune_expired_runs()
    except Exception:
        pass
    _cockpit_version = _read_version_file()
    _spawn_version_check()
    _load_random_quote()
    _cache_mtime = _cache_mtime_now()
    _rebuild_main_items(preserve_label=False)

    _main_window,                  main_frame                = _build_simple(_main_text)
    (_profile_table_window, _profile_options_window,
     profile_frame)                                          = _build_profile()
    _profile_rename_window,        profile_rename_frame      = _build_simple(_profile_rename_text)
    _profile_create_name_window,   pcn_frame                 = _build_simple(_profile_create_name_text)
    _profile_create_choose_window, pcc_frame                 = _build_simple(_profile_create_choose_text)
    _profile_create_copy_window,   pcp_frame                 = _build_simple(_profile_create_copy_text)
    _profile_delete_window,        pd_frame                  = _build_simple(_profile_delete_text)
    _profile_editor_window,        profile_editor_frame      = _build_simple(_profile_editor_text)
    _profile_editor_delete_window, peditor_delete_frame      = _build_simple(_profile_editor_delete_text)
    _profile_editor_keybind_window, peditor_keybind_frame    = _build_simple(_profile_editor_keybind_text)
    _options_window,                    options_frame                  = _build_simple(_options_text)
    _options_panes_window,              options_panes_frame            = _build_simple(_options_panes_text)
    _options_pane_window,               options_pane_frame             = _build_simple(_options_pane_text)
    _options_connection_window,         options_connection_frame       = _build_simple(_options_connection_text)
    _options_connection_custom_window,  options_connection_custom_frame = _build_simple(_options_connection_custom_text)
    _options_coming_soon_window,        options_coming_soon_frame      = _build_simple(_options_coming_soon_text)
    _options_spotlights_window,         options_spotlights_frame       = _build_simple(_options_spotlights_text)
    _spotlights_empty_window,           spotlights_empty_frame         = _build_simple(_spotlights_empty_text)
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
    (_history_filter_window, _history_table_window, _history_options_window,
     history_frame) = _build_history()
    _history_detail_window = Window(
        content=_HDScrollControl(text=_history_detail_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    history_detail_frame = _centered(_history_detail_window)
    _history_rate_window, history_rate_frame = _build_history_rate()
    _history_delete_confirm_window = Window(
        content=FormattedTextControl(text=_history_delete_confirm_text,
                                     focusable=True),
        wrap_lines=False, always_hide_cursor=True,
    )
    history_delete_confirm_frame = _centered(_history_delete_confirm_window)

    _log_view_window = Window(
        content=_LogViewControl(text=_log_view_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
    )
    log_header_win = Window(
        content=FormattedTextControl(text=_log_header_text, focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )
    log_controls_win = Window(
        content=FormattedTextControl(text=_log_controls_text, focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )
    log_spotlight_win = Window(
        content=FormattedTextControl(text=_log_spotlight_overlay_text,
                                     focusable=False),
        width=_SPOTLIGHT_BOX_W,
        height=_SPOTLIGHT_BOX_H,
        wrap_lines=False, always_hide_cursor=True,
    )
    _log_overlays_filter = Condition(lambda: _log_overlays_visible)
    _log_spotlight_overlay_filter = Condition(_log_spotlight_overlay_visible)
    log_view_frame = FloatContainer(
        content=_log_view_window,
        floats=[
            Float(
                top=0, left=0, right=0, height=1,
                content=ConditionalContainer(content=log_header_win,
                                             filter=_log_overlays_filter),
            ),
            # Top-right floating spotlight info box (spotlight mode only).
            # Pinned with a 2-cell margin from both the top and right edges
            # of the log_view frame; framed in half-block glyphs with
            # full-block █ corners on a bright banner-hue fill. Visibility
            # is *not* gated by the bottom controls' auto-hide — only by
            # the spotlight-mode predicate and a narrow-terminal fallback.
            Float(
                top=_SPOTLIGHT_BOX_MARGIN, right=_SPOTLIGHT_BOX_MARGIN,
                width=_SPOTLIGHT_BOX_W, height=_SPOTLIGHT_BOX_H,
                content=ConditionalContainer(content=log_spotlight_win,
                                             filter=_log_spotlight_overlay_filter),
            ),
            Float(
                bottom=0, left=0, right=0, height=1,
                content=ConditionalContainer(content=log_controls_win,
                                             filter=_log_overlays_filter),
            ),
        ],
    )

    # Credits frame — scrolling end-of-reel chronicle on a black canvas.
    # Mouse is intentionally not bound (no handler on the control); only
    # ESC exits early. The dim "Escape to exit" hint floats top-right.
    _credits_window = Window(
        content=FormattedTextControl(text=_credits_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
        style="bg:#000000",
    )
    credits_hint_win = Window(
        content=FormattedTextControl(text=_credits_hint_text, focusable=False),
        width=len("Escape to exit"),
        height=1,
        wrap_lines=False,
        always_hide_cursor=True,
    )
    credits_frame = FloatContainer(
        content=_credits_window,
        floats=[
            Float(
                top=1, right=2,
                width=len("Escape to exit"), height=1,
                content=credits_hint_win,
            ),
        ],
    )

    frames = {
        "main":                       main_frame,
        "profile":                    profile_frame,
        "profile_rename":             profile_rename_frame,
        "profile_create_name":        pcn_frame,
        "profile_create_choose":      pcc_frame,
        "profile_create_copy_picker": pcp_frame,
        "profile_delete_confirm":     pd_frame,
        "profile_editor":             profile_editor_frame,
        "profile_editor_delete_confirm": peditor_delete_frame,
        "profile_editor_macro_keybind": peditor_keybind_frame,
        "options":                    options_frame,
        "options_panes":              options_panes_frame,
        "options_pane":               options_pane_frame,
        "options_connection":         options_connection_frame,
        "options_connection_custom":  options_connection_custom_frame,
        "options_coming_soon":        options_coming_soon_frame,
        "options_spotlights":         options_spotlights_frame,
        "spotlights_empty":           spotlights_empty_frame,
        "scripts":                    scripts_frame,
        "about":                      about_frame,
        "history":                    history_frame,
        "history_detail":             history_detail_frame,
        "history_rate":               history_rate_frame,
        "history_delete_confirm":     history_delete_confirm_frame,
        "log_view":                   log_view_frame,
        "credits":                    credits_frame,
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
