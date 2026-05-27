#!/usr/bin/env python3
# bridge/launcher/launcher.py — pre-tmux startup menu (prompt_toolkit rewrite).
# Invoked via bridge/launcher/launcher.sh. Behavioural contract: docs/launcher.md.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import (
        DynamicKeyBindings, KeyBindings, merge_key_bindings,
    )
    from prompt_toolkit.keys import Keys
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
import base64
import bisect
import dataclasses
import glob
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time

# Make sibling modules importable when run directly via the wrapper.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palette import (  # noqa: E402
    C_TITLE, C_ACTIVE, C_ITEM, C_BODY, C_HINT, C_ACCENT,
    C_YELLOW, C_ERR, C_DANGER, C_QUOTE, C_QUOTE_ATTR, C_HOVER, C_SELECTED,
    C_SECTION, C_DIVIDER,
    C_BUTTON, C_BUTTON_HOVER, C_BUTTON_DISABLED,
    C_BUTTON_INACTIVE, C_BUTTON_ACTIVE_UNFOCUSED, C_BUTTON_ACTIVE_FOCUSED,
    C_OK, C_CURSOR_CELL,
    C_LOG_CURSOR,
    C_LOG_OVERLAY_BG, C_LOG_OVERLAY_FG, C_LOG_OVERLAY_HINT,
    C_LOG_SCRUBBER_FILLED, C_LOG_SCRUBBER_EMPTY, C_LOG_SCRUBBER_THUMB,
    C_LOG_BUTTON_IDLE, C_LOG_BUTTON_HOVER,
    C_SPOTLIGHT_BOX_BG, C_SPOTLIGHT_FRAME, spotlight_frame_style,
    C_SPOTLIGHT_TEXT_PRIMARY, C_SPOTLIGHT_TEXT_SECONDARY,
    _S_GAINED, _S_LOSS, _S_LABEL, _S_VALUE, _S_TP_BAR,
    _S_TRACK, _S_MARKER, _S_THUMB, _S_TOTAL, _S_ARROW,
    _S_HINT, _S_PVP, _S_ALLY, _S_STAR,
    PANE_COLOR_ORDER, pane_color_hex,
    TTPP_COLOR_STYLES, TTPP_COLOR_NAMES,
    C_SYN_COMMAND, C_SYN_BRACE, C_SYN_DELIM, C_SYN_VAR, C_SYN_CODE,
    C_SYN_BRACE_MATCH,
)
import ttpp_syntax  # noqa: E402
import launcher_banner  # noqa: E402
import credits  # noqa: E402
import foot_config  # noqa: E402
import history_filter  # noqa: E402
import log_player  # noqa: E402
import macro_keys  # noqa: E402
import profile_io  # noqa: E402
import profile_editor  # noqa: E402
import run_retention  # noqa: E402
import run_stats  # noqa: E402
import spotlights  # noqa: E402
from menu_chrome import (  # noqa: E402
    button_fragment, footer_block, menu_row, title_block, title_block_height,
)
from panes_grid import apply_cell_toggle, panes_grid_fragments  # noqa: E402
import scripts_view  # noqa: E402
from widgets.scrollbar import Scrollbar  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR         = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR         = os.path.dirname(SCRIPT_DIR)
PROJECT_DIR        = os.path.dirname(BRIDGE_DIR)
RUNTIME_DIR        = os.path.join(BRIDGE_DIR, "runtime")
CONF_PATH          = os.path.join(RUNTIME_DIR, "startup.conf")
LAYOUT_CONF_PATH   = os.path.join(RUNTIME_DIR, "layout.conf")
VERSION_CACHE_PATH = os.path.join(RUNTIME_DIR, "version.cache")
SCRIPTS_CACHE_PATH = os.path.join(RUNTIME_DIR, "scripts.cache")
SCRIPTS_CONF_PATH      = os.path.join(RUNTIME_DIR, "scripts.conf")
SCRIPTS_CONF_TEMPLATE  = os.path.join(SCRIPT_DIR, "templates", "scripts.conf")
LUA_SCRIPTS_DIR        = os.path.join(PROJECT_DIR, "lua", "scripts")
VERSION_FILE       = os.path.join(PROJECT_DIR, "VERSION")
PROFILES_DIR       = os.path.join(PROJECT_DIR, "ttpp", "profiles")
QUOTES_PATH        = os.path.join(SCRIPT_DIR, "quotes.txt")
ABOUT_PATH         = os.path.join(SCRIPT_DIR, "about.txt")
TEMPLATE_BLANK     = os.path.join(SCRIPT_DIR, "templates", "blank_profile.tin")
STARTUP_CONF_TEMPLATE = os.path.join(SCRIPT_DIR, "templates", "startup.conf")
UPDATE_SH          = os.path.join(BRIDGE_DIR, "release", "update.sh")
VERSION_CHECK_SH   = os.path.join(BRIDGE_DIR, "services", "version_check.sh")
PING_MONITOR_SH    = os.path.join(BRIDGE_DIR, "services", "ping_monitor.sh")
# Foot/WSLg supervisor handshake. The sentinel name MUST match the
# `SENTINEL` path in bridge/supervisor.sh — touching it asks the
# supervisor to relaunch foot once the cockpit exits (ADR 0104). The
# resume-hint is a separate one-shot consumed by the fresh launcher
# post-relaunch to restore the frame stack (see _consume_launcher_resume).
FOOT_RELAUNCH_SENTINEL = os.path.join(RUNTIME_DIR, ".relaunch_terminal")
LAUNCHER_RESUME_PATH   = os.path.join(RUNTIME_DIR, ".launcher_resume")

MIN_COLS = 60
MIN_ROWS = 18

PROFILE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")

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

# MUME_TERMINAL contract (ADR 0104). The Windows foot/WSLg deployment's
# supervisor sets `MUME_TERMINAL=foot-managed` when it launches foot so
# downstream code can tell it owns the host terminal and the launcher
# can safely surface foot-specific affordances (the Terminal Settings
# submenu under Options). Fail-closed: any other value, or the
# variable absent, means we are not running under the managed-foot
# deployment and the submenu stays hidden.
_FOOT_MANAGED = os.environ.get("MUME_TERMINAL") == "foot-managed"

# Fresh-install defaults are sourced from the shipped
# templates/startup.conf — single source of truth for both the launcher
# and tmux_start.sh's first-run seeding (ADR 0101). The hardcoded dict
# below is only a defensive backstop used if the template file is
# missing at import time, so the launcher can still start.
_CONF_DEFAULTS_FALLBACK = {
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
    "terminal_bg_fallback":         "#000000",
}


def _load_startup_conf_defaults():
    # Parse the shipped template via the same _parse_conf used at
    # runtime. Defined inline so the load runs at module import; the
    # fallback dict above covers the (should-not-happen) missing-template case.
    out = {}
    try:
        with open(STARTUP_CONF_TEMPLATE) as fh:
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
    return out or dict(_CONF_DEFAULTS_FALLBACK)


_CONF_DEFAULTS = _load_startup_conf_defaults()

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

# Profile editor instance (None when the editor is not open).
# Constructed by _profile_action_edit(); lives in profile_editor.py.
_profile_editor_instance = None

# Options — top-level (Panes / Game text-layout / Connection / Back)
_sel_options              = 0
_hover_options            = -1
# Options — Panes submenu (pane × colour grid). Eight navigable rows:
#   0..5 — pane rows (Character / Buffs / Group / Comm / UI / Developer).
#   6    — Display pane headers toggle.
#   7    — Back.
# _options_panes_col is the persistent column (0..6) for grid rows; it is
# preserved while the cursor sits on the headers / Back rows so returning
# to a grid row re-enters the same column.
_options_panes_row        = 0
_options_panes_col        = 0
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

# Options — Terminal submenu (foot/WSLg managed only). Pending tracks
# the user's in-flight edits; disk is re-read from foot.ini at every
# frame push so it reflects external edits. Both are `TerminalConfig`
# dataclass instances (or None before first entry); Apply is active iff
# `pending != disk` (dataclass equality across every managed field).
_options_terminal_cursor       = 0
_options_terminal_hover        = -1
_options_terminal_disk          = None   # type: TerminalConfig | None
_options_terminal_pending       = None   # type: TerminalConfig | None
# Font picker subframe (pushed from the Font row). Scrollable list of
# installed monospace families, scanned on entry via foot_config.
_terminal_font_picker_cursor   = 0
_terminal_font_picker_scroll   = 0
_terminal_font_picker_hover    = -1
_terminal_font_picker_fonts    = []
# Bounds on the pending font size; foot itself accepts a broad range
# but the launcher clamps to a sensible stepper window.
_TERMINAL_SIZE_MIN = 6
_TERMINAL_SIZE_MAX = 32
# Padding stepper bounds (in pixels) and step granularity. The pad is
# always written symmetrically — `pad_y` mirrors `pad_x` on Apply.
_TERMINAL_PAD_MIN  = 0
_TERMINAL_PAD_MAX  = 40
_TERMINAL_PAD_STEP = 2
# Window size stepper bounds (pixels) and granularity. The 800×600 floor
# keeps the cockpit above its MIN_COLS / MIN_ROWS at common font sizes;
# the upper bound is 8K (7680×4320) so high-DPI users can address their
# full panel through the stepper without scrolling forever.
_TERMINAL_WIN_W_MIN  = 800
_TERMINAL_WIN_W_MAX  = 7680
_TERMINAL_WIN_H_MIN  = 600
_TERMINAL_WIN_H_MAX  = 4320
_TERMINAL_WIN_STEP   = 100

# Scripts — live-scanned catalog of `lua/scripts/<name>.lua` with their
# resolved enable state (from runtime/scripts.conf, falling back to the
# template). Toggles mutate the catalog in memory; the write to
# scripts.conf is deferred to Back/ESC. Mirrors the Panes/Spotlights
# pattern. See docs/launcher.md → Scripts page.
#
# Single-column navigation model: the cursor moves through script rows
# (0..n-1) and the in-column Back row (`_scripts_on_back == True`)
# below a blank spacer. There is no list/detail focus split — Up/Down
# moves the cursor, PageUp/PageDown scrolls the detail panel
# unconditionally. When the cursor sits on Back the detail still shows
# the last-cursored script (`_scripts_cursor` is latched and not
# moved), so navigating down toward Back doesn't lose the preview.
_scripts_catalog       = []        # list[scripts_view.Script]
_scripts_dirty         = False     # True after a toggle; drives the write on pop
_scripts_cursor        = 0         # latched script-row index (drives the detail)
_scripts_on_back       = False     # True when the cursor visually sits on Back
_scripts_list_scroll   = 0         # first visible list row
_scripts_detail_scroll = 0         # first visible detail row
_scripts_hover         = None      # list row under the mouse, or None
_scripts_hover_back    = False     # True when the mouse is over the Back row

# About
_about_lines         = []
_about_scroll        = 0
_about_cols          = 0
_about_sb            = None

# History
_history_filter_items    = []        # ["All", "<char>", ...] — pill labels
_history_sessions        = []        # filtered + sorted SessionSummary list
_history_filter          = "All"
_history_sort            = ("Date", "desc")
_history_filter_cursor   = 0         # cursor pill index
_history_filter_offset   = 0         # leftmost visible pill index (P4.2 scroll)
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

# Main-page starfield twinkle — persistent redraw loop while the main
# frame is visible. The animation itself lives in launcher_banner; this
# tick just nudges prompt_toolkit to repaint at a steady rate.
_banner_tick_task                = None  # asyncio.Task | None
_BANNER_TICK_HZ                  = 12

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
_options_window                  = None
_options_panes_window            = None
_options_connection_window       = None
_options_connection_custom_window = None
_options_spotlights_window       = None
_options_terminal_window         = None
_terminal_font_picker_window     = None
_spotlights_empty_window         = None
_scripts_window      = None
_about_window        = None
_update_running_window = None
_update_result_window  = None
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
# Host-terminal background detection (OSC 11)
# ---------------------------------------------------------------------------
# Probed once at launcher startup, while the tty is still in cooked mode and
# the launcher owns it (before prompt_toolkit's Application takes over).
# Three consumers, all chrome that bakes in a black backdrop and reads wrong
# on light or tinted themes:
#   • the credits canvas + fade ramp,
#   • the spotlight info box outline,
#   • the tmux pane separator (apply_border_style.sh, via layout.conf).
# None when stdin isn't a tty or the terminal doesn't reply within the
# bounded probe window; callers fall back to #000000.
_terminal_bg = None
# Pre-computed spotlight info-box outline style derived from _terminal_bg.
# Re-set once at startup by _probe_and_persist_terminal_bg(); the spotlight
# overlay renderer reads it on every tick.
_spotlight_frame_style = C_SPOTLIGHT_FRAME

_OSC11_REPLY_RE = re.compile(rb"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)")


def _parse_osc11_reply(reply: bytes):
    """Parse an OSC 11 reply `\\x1b]11;rgb:RRRR/GGGG/BBBB\\x07` (or the
    8-bit-per-channel `rgb:RR/GG/BB` form) into `#rrggbb`. Channels may
    be 1, 2, 3, or 4 hex digits on different terminals — normalise to
    two digits per channel (top two)."""
    if not reply:
        return None
    m = _OSC11_REPLY_RE.search(reply)
    if not m:
        return None
    parts = []
    for raw in (m.group(1), m.group(2), m.group(3)):
        s = raw.decode("ascii")
        if len(s) == 1:
            s = s + s
        parts.append(s[:2])
    return "#" + "".join(parts).lower()


def _detect_terminal_bg():
    """Query the host terminal background colour via OSC 11.

    Writes the query to /dev/tty, reads the reply with a bounded
    ~0.25 s timeout via `select`, and restores the saved termios state
    unconditionally. Returns `#rrggbb` on success, `None` when there is
    no controlling terminal, when the terminal doesn't reply, or when
    any step fails — failure must never wedge the tty or block startup."""
    try:
        import termios
        import tty
        import select
    except ImportError:
        return None
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None
    try:
        try:
            if not os.isatty(fd):
                return None
        except OSError:
            return None
        try:
            old = termios.tcgetattr(fd)
        except (termios.error, OSError):
            return None
        reply = b""
        try:
            try:
                tty.setraw(fd)
            except (termios.error, OSError):
                return None
            try:
                os.write(fd, b"\x1b]11;?\x07")
            except OSError:
                return None
            deadline = time.monotonic() + 0.25
            while len(reply) < 64:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    r, _, _ = select.select([fd], [], [], remaining)
                except (OSError, ValueError):
                    break
                if not r:
                    break
                try:
                    chunk = os.read(fd, 64 - len(reply))
                except OSError:
                    break
                if not chunk:
                    break
                reply += chunk
                if reply.endswith(b"\x07") or reply.endswith(b"\x1b\\"):
                    break
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except (termios.error, OSError):
                pass
        return _parse_osc11_reply(reply)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _write_terminal_bg_to_layout_conf(bg):
    """Persist `terminal_bg=<hex>` into bridge/runtime/layout.conf using an
    in-place append-or-replace pattern. Writes the key with an empty value
    when `bg` is None so `apply_border_style.sh` reads it as "no detection"
    and falls back to `fg=default bg=default`. The remaining layout.conf
    keys are populated later by build_initial_layout.sh; that script only
    seeds missing keys, so it does not clobber this write."""
    val = bg if bg else ""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
    except OSError:
        return
    try:
        with open(LAYOUT_CONF_PATH) as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        lines = []
    except OSError:
        return
    new_line = f"terminal_bg={val}\n"
    replaced = False
    out = []
    for line in lines:
        if line.startswith("terminal_bg="):
            if not replaced:
                out.append(new_line)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(new_line)
    try:
        with open(LAYOUT_CONF_PATH, "w") as fh:
            fh.writelines(out)
    except OSError:
        pass


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _probe_and_persist_terminal_bg():
    """One-shot wrapper: detect, stash on the module-level _terminal_bg,
    pre-compute the spotlight frame style and editor focused current-line
    band derived from it, and write the value to layout.conf. Called once
    from main() before the prompt_toolkit Application starts.

    When OSC 11 detection fails (e.g. WSL2 + Alacritty, which routes
    through ConPTY and never relays the reply), falls back to the
    user-configurable `terminal_bg_fallback` from startup.conf — default
    `#000000` to match the bundled Alacritty background. Detection wins
    when it succeeds, so a user who alternates between a detecting and
    a non-detecting terminal stays correct on both."""
    global _terminal_bg, _spotlight_frame_style
    detected = _detect_terminal_bg()
    fallback = _conf.get("terminal_bg_fallback", "#000000")
    if not _HEX_COLOR_RE.match(fallback or ""):
        fallback = "#000000"
    _terminal_bg = detected or fallback
    if detected:
        msg = f"terminal-bg: detected {detected}\n"
    else:
        msg = f"terminal-bg: detection failed, using fallback {fallback}\n"
    try:
        log_path = os.path.join(PROJECT_DIR, "logs", "debug.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as fh:
            fh.write(msg)
    except OSError:
        pass
    _spotlight_frame_style = spotlight_frame_style(_terminal_bg)
    _write_terminal_bg_to_layout_conf(_terminal_bg)


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
                "terminal_bg_fallback",
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
            "profile_editor":             _profile_editor_instance.main_window() if _profile_editor_instance else None,
            "profile_editor_macro_keybind": _profile_editor_instance.overlay_window() if _profile_editor_instance else None,
            "profile_rename":             _profile_rename_window,
            "options":                    _options_window,
            "options_panes":              _options_panes_window,
            "options_connection":         _options_connection_window,
            "options_connection_custom":  _options_connection_custom_window,
            "options_spotlights":         _options_spotlights_window,
            "options_terminal":           _options_terminal_window,
            "terminal_font_picker":       _terminal_font_picker_window,
            "spotlights_empty":           _spotlights_empty_window,
            "scripts":                    _scripts_window,
            "about":                      _about_window,
            "update_running":             _update_running_window,
            "update_result":              _update_result_window,
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


# ---------------------------------------------------------------------------
# EditorHost implementation for the launcher
# ---------------------------------------------------------------------------
class _LauncherEditorHost:
    """Bridges ProfileEditor back to launcher globals."""

    @property
    def app(self):
        return _app

    @property
    def app_loop(self):
        return _app_loop

    @property
    def terminal_bg(self):
        return _terminal_bg

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


_editor_host = _LauncherEditorHost()


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
    global _hover_options_connection
    global _hover_options_spotlights
    global _options_terminal_hover, _terminal_font_picker_hover
    changed = False
    if frame == "main" and _hover_main != idx:
        _hover_main = idx; changed = True
    elif frame == "options" and _hover_options != idx:
        _hover_options = idx; changed = True
    elif frame == "options_connection" and _hover_options_connection != idx:
        _hover_options_connection = idx; changed = True
    elif frame == "options_spotlights" and _hover_options_spotlights != idx:
        _hover_options_spotlights = idx; changed = True
    elif frame == "options_terminal" and _options_terminal_hover != idx:
        _options_terminal_hover = idx; changed = True
    elif frame == "terminal_font_picker" and _terminal_font_picker_hover != idx:
        _terminal_font_picker_hover = idx; changed = True
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


def _menu_row_state(is_active, is_hover):
    """Map (active, hover) to a `menu_chrome.menu_row` state name.

    Selection (keyboard cursor) wins over hover — a row that is both
    selected and hovered renders as `selected`."""
    if is_active:
        return "selected"
    if is_hover:
        return "hover"
    return "inactive"


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
        _app.exit()


def _main_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("main", -1)


def _main_text():
    _check_cache_change()
    cols = _term_cols()
    rows_h = _term_rows()
    frags = []
    clear_hover = _main_clear_hover

    # Starfield + wordmark banner — the logo is the launcher's signature,
    # not a section title, and does not go through `menu_chrome.title_block`.
    # Art lives in launcher_banner.py (decoupled from the popup's banner.py
    # so the launcher banner can evolve independently).
    banner_pad = _pad_centre(" " * launcher_banner.BANNER_WIDTH, cols)
    frags.append(("", "\n", clear_hover))
    for line_frags in launcher_banner.banner_lines():
        frags.append(("", banner_pad, clear_hover))
        for style, text in line_frags:
            frags.append((style, text, clear_hover))
        frags.append(("", "\n", clear_hover))
    frags.append(("", "\n", clear_hover))
    banner_rows = 1 + launcher_banner.BANNER_HEIGHT + 1

    items = _main_items
    sel_idx = _sel_main if 0 <= _sel_main < len(items) else 0

    # Plain `<< label >>` menu: centre each row independently
    # (ragged-centred). The row width is `len(label) + 6` (3-cell
    # prefix + label + 3-cell suffix); centring on that width keeps
    # the label fixed between states because the prefix and suffix
    # are the same width in every state.
    for i, label in enumerate(items):
        state = _menu_row_state(i == sel_idx, i == _hover_main)

        def _make_handler(row=i):
            def _h(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("main", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _activate_main(row)
            return _h

        h = _make_handler()
        row_w     = len(label) + 6
        left_pad  = max(0, (cols - row_w) // 2)
        right_pad = max(0, cols - left_pad - row_w)
        frags.append(("", " " * left_pad, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * right_pad, clear_hover))
        frags.append(("", "\n", clear_hover))

    frags.append(("", "\n", clear_hover))

    quote_rows = 0
    if _quote_text:
        quoted = f'"{_quote_text}"'
        frags.append(("", _pad_centre(quoted, cols), clear_hover))
        frags.append((C_QUOTE, quoted, clear_hover))
        frags.append(("", "\n", clear_hover))
        quote_rows += 1
        if _quote_attr:
            attr = f"— {_quote_attr}"
            frags.append(("", _pad_centre(attr, cols), clear_hover))
            frags.append((C_QUOTE_ATTR, attr, clear_hover))
            frags.append(("", "\n", clear_hover))
            quote_rows += 1
        frags.append(("", "\n", clear_hover))
        quote_rows += 1

    footer = "↑↓ Navigate · Enter/Space Select"
    content_rows = banner_rows + len(items) + 1 + quote_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


# ---------------------------------------------------------------------------
# Profile frame
# ---------------------------------------------------------------------------
_PROFILE_BUTTONS = [
    ("SELECT", "select"),
    ("NEW",    "new"),
    ("EDIT",   "edit"),
    ("RENAME", "rename"),
    ("DELETE", "delete"),
    ("EXPORT", "export"),
    ("BACK",   "back"),
]
_PROFILE_BUTTON_W   = max(len(lbl) for lbl, _ in _PROFILE_BUTTONS) + 2
_PROFILE_OPTIONS_GAP = 2


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
    """Visible data rows in the table — data-fit, with a floor so the button
    column never clips.

    P4 chrome budget: title (4 rows, `title_block_height(2)`) + feedback
    (1) + footer (1) + table header (1) = 7 reserved rows; flex_spacer
    absorbs anything left over. The button column has no header in P4 —
    its first button aligns with the table header row — so visible must be
    at least `len(_PROFILE_BUTTONS)` for the button column to render in
    full."""
    max_by_terminal = max(1, _term_rows() - 7)
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
        ("SELECT", "select", has and name != active),
        ("NEW",    "new",    True),
        ("EDIT",   "edit",   has),
        ("RENAME", "rename", has and not is_default),
        ("DELETE", "delete", has and not is_default),
        ("EXPORT", "export", has),
        ("BACK",   "back",   True),
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
    global _profile_editor_instance
    name = _profile_current_name()
    if name is None:
        return
    from pathlib import Path
    path = Path(os.path.join(PROFILES_DIR, f"{name}.tin"))
    try:
        prof = profile_io.load_profile(path)
    except OSError as exc:
        _profile_set_feedback(
            f"Could not open {path.name}: {exc.strerror or exc}", C_HINT)
        return

    def _on_exit(p):
        global _profile_editor_instance
        err_msg = None
        saved_name = None
        try:
            profile_io.save_profile(p)
            saved_name = p.path.name if p.path is not None else ""
        except OSError as exc:
            err_msg = f"Save failed: {exc.strerror or exc}"
        _pop_frame()
        _profile_editor_instance = None
        if err_msg:
            _profile_set_feedback(err_msg, C_HINT)
        elif saved_name:
            _profile_set_feedback(f"Saved {saved_name}.", C_ACCENT)

    _profile_editor_instance = profile_editor.ProfileEditor(
        path=path, profile=prof, on_exit=_on_exit, host=_editor_host)
    _push_frame("profile_editor")


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
    clear_hover = _profile_hover_at(None, None)
    return list(title_block(
        "─── Profile ───", cols, blank_above=2, mouse_handler=clear_hover,
    ))


def _profile_footer_text():
    cols = _term_cols()
    clear_hover = _profile_hover_at(None, None)
    footer = "↑↓ Navigate · Tab/←→ Cycle · Enter Select · ESC Back"
    pad = " " * max(0, (cols - len(footer)) // 2)
    return [("", pad, clear_hover), (C_HINT, footer, clear_hover)]


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
                style = C_OK
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

    # Header row — always muted grey (C_HINT), regardless of focus.
    # The sort indicator glyph carries the active-column signal.
    header_style = C_HINT
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

        if is_cursor and table_focused:
            row_bg = C_BUTTON_ACTIVE_FOCUSED
        elif is_cursor:
            row_bg = C_BUTTON_ACTIVE_UNFOCUSED
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


# --- Options widget render (left side of the profile table) --------------
def _profile_options_text():
    """Render the button column: stacked `button_fragment` cells, no header.

    The first button row sits at row 0 of the VSplit so it top-aligns with
    the table's header row. State mapping per ADR 0085's button-cell
    grammar: cursor + options focused → `selected_focused` (gold bg);
    cursor + options unfocused → `selected_unfocused` (grey bg); hover on
    a non-cursor enabled button → `hover`; disabled → `disabled`; else
    `inactive`. Trailing blank rows pad the column down to the
    table_row VSplit height."""
    inner_w = _PROFILE_BUTTON_W
    actions = _profile_menu_actions()
    options_focused = (_profile_focused == 1)
    hover_panel, hover_row = _profile_hover
    clear_hover = _profile_hover_at(None, None)

    frags = []

    for i, (label, _action, enabled) in enumerate(actions):
        is_cursor = (i == _profile_menu_cursor)
        is_hover  = (hover_panel == 1 and hover_row == i and enabled
                     and not is_cursor)
        if not enabled:
            state = "disabled"
        elif is_cursor and options_focused:
            state = "selected_focused"
        elif is_cursor:
            state = "selected_unfocused"
        elif is_hover:
            state = "hover"
        else:
            state = "inactive"
        style, cell_text = button_fragment(label, inner_w, state)

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

    # Pad trailing blank lines so the column fills the table_row height
    # (table_window_h = visible + 1 = header row + data rows).
    used = len(actions)
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
    footer = "Enter Confirm · ESC Cancel"
    line   = f"> {_rename_name_buf}_"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_SECTION, title))
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
    footer = "Enter Confirm · ESC Cancel"
    line   = f"> {_create_name_buf}_"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_SECTION, title))
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
    footer  = "B Blank profile · C Copy from existing · ESC Cancel"
    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_SECTION, title))
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
        frags.append((C_SECTION, title))
        frags.append(("", "\n\n\n"))
        frags.append(("", _pad_centre(msg, cols)))
        frags.append((C_YELLOW, msg))
        frags.append(("", "\n\n\n"))
        frags.append(("", _pad_centre(hint, cols)))
        frags.append((C_HINT, hint))
        return frags

    footer = "↑↓ Navigate · Enter Select · ESC Cancel"
    head   = "Copy from:"
    labels = list(_create_src_profiles)
    maxw   = max(len(l) for l in labels)
    pad    = max(0, (cols - (maxw + 6)) // 2)

    frags = []
    frags.append(("", "\n\n"))
    frags.append(("", _pad_centre(title, cols)))
    frags.append((C_SECTION, title))
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
    frags.append((C_SECTION, title))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(msg, cols)))
    frags.append((msg_style, msg))
    frags.append(("", "\n\n\n"))
    frags.append(("", _pad_centre(hint, cols)))
    frags.append((C_HINT, hint))
    return frags


# ---------------------------------------------------------------------------
# Options frame — top level (Connection / Panes / Scripts / Spotlights / Back)
# ---------------------------------------------------------------------------
# The "Terminal" row appears only when the cockpit was launched under
# the foot/WSLg managed-terminal deployment (`MUME_TERMINAL=foot-managed`).
# Built at module import time — the env var is fixed for the launcher's
# lifetime — so the row's presence is deterministic across frame pushes.
def _build_options_rows():
    rows = [
        ("connection", "Connection"),
    ]
    if _FOOT_MANAGED:
        rows.append(("terminal", "Terminal"))
    rows.extend([
        ("panes",      "Panes"),
        ("scripts",    "Scripts"),
        ("spotlights", "Spotlights"),
        ("back",       "Back"),
    ])
    return rows


_OPTIONS_ROWS = _build_options_rows()


def _enter_options_frame():
    global _sel_options
    _sel_options = 0
    _push_frame("options")


def _activate_option(idx):
    global _sel_options, _sel_options_connection
    global _sel_options_spotlights
    global _options_panes_row, _options_panes_col
    if idx < 0 or idx >= len(_OPTIONS_ROWS):
        return
    _sel_options = idx
    action, _label = _OPTIONS_ROWS[idx]
    if action == "panes":
        _options_panes_row = 0
        _options_panes_col = 0
        _push_frame("options_panes")
    elif action == "scripts":
        _enter_scripts_frame()
    elif action == "spotlights":
        _sel_options_spotlights = 0
        _push_frame("options_spotlights")
    elif action == "connection":
        _sel_options_connection = _current_connection_index()
        _push_frame("options_connection")
    elif action == "terminal":
        _enter_options_terminal_frame()
    elif action == "back":
        _save_conf()
        _pop_frame()


def _options_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("options", -1)


def _options_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Options ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"
    clear_hover = _options_clear_hover

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=2, mouse_handler=clear_hover,
    ))

    back_idx = len(_OPTIONS_ROWS) - 1
    blank_rows = 0

    # Plain `<< label >>` menu: centre each row independently
    # (ragged-centred). Same per-row width as the main frame.
    for i, (action, label) in enumerate(_OPTIONS_ROWS):
        if i == back_idx:
            frags.append(("", "\n", clear_hover))   # blank before Back
            blank_rows += 1

        is_active = (i == _sel_options)
        is_hover  = (i == _hover_options)
        state     = _menu_row_state(is_active, is_hover)

        def _make_handler(row=i):
            def _h(ev):
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _activate_option(row)
            return _h

        h = _make_handler()
        row_w     = len(label) + 6
        left_pad  = max(0, (cols - row_w) // 2)
        right_pad = max(0, cols - left_pad - row_w)
        frags.append(("", " " * left_pad, clear_hover))
        frags.extend(menu_row(
            label, state,
            mouse_handler=h,
        ))
        frags.append(("", " " * right_pad, clear_hover))
        frags.append(("", "\n", clear_hover))

    content_rows = title_block_height(2) + len(_OPTIONS_ROWS) + blank_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


# ---------------------------------------------------------------------------
# Options — Panes submenu (pane × colour grid)
# ---------------------------------------------------------------------------
# One frame replaces the previous Panes index + six per-pane subframes.
# Rows of the grid are panes, columns are the seven colours. A pane row
# with zero checked cells is off; exactly one checked cell is on with
# that colour. apply_cell_toggle handles the on/off/switch-colour logic;
# rendering goes through panes_grid_fragments. See ADR 0086 and
# docs/launcher.md "Panes submenu".
#
# Eight navigable rows: rows 0..5 are pane rows (←/→ moves between the
# seven colour columns; the column persists across grid rows). Row 6 is
# the [X] Display pane headers toggle; row 7 is Back. ↑/↓ moves between
# all eight rows. Enter activates: a grid cell toggles via the model
# above, the headers row flips show_pane_dividers, Back saves and pops.
# ESC = Back. All writes are deferred — _save_conf fires on the exit path.

_PANES_GRID_ROWS   = len(_PANE_OPTIONS)            # 6
_PANES_HEADERS_ROW = _PANES_GRID_ROWS              # 6
_PANES_BACK_ROW    = _PANES_GRID_ROWS + 1          # 7
_PANES_LAST_ROW    = _PANES_BACK_ROW
_PANES_LAST_COL    = len(PANE_COLOR_ORDER) - 1     # 6


def _set_panes_cursor(row, col=None):
    """Update the panes-grid cursor; invalidate on change."""
    global _options_panes_row, _options_panes_col
    changed = False
    if row != _options_panes_row:
        _options_panes_row = row
        changed = True
    if col is not None and col != _options_panes_col:
        _options_panes_col = col
        changed = True
    if changed and _app:
        _app.invalidate()


def _options_panes_back():
    _save_conf()
    _pop_frame()


def _apply_panes_grid_toggle(row, col):
    """Apply a click on grid cell (row, col): on/off or switch-colour."""
    _target, _label, show_key, color_key = _PANE_OPTIONS[row]
    enabled = (_conf.get(show_key) == "1")
    cur_color = _conf.get(color_key, "")
    try:
        cur_idx = PANE_COLOR_ORDER.index(cur_color)
    except ValueError:
        cur_idx = 0
    new_enabled, new_idx = apply_cell_toggle(enabled, cur_idx, col)
    _conf[show_key] = "1" if new_enabled else "0"
    if new_enabled:
        _conf[color_key] = PANE_COLOR_ORDER[new_idx]
    if _app:
        _app.invalidate()


def _toggle_pane_headers():
    key = "show_pane_dividers"
    _conf[key] = "0" if _conf.get(key) == "1" else "1"
    if _app:
        _app.invalidate()


def _options_panes_clear_hover(ev):
    """MOUSE_MOVE handler for the panes-frame chrome. Sets the cursor row
    to the no-hover sentinel (_PANES_LAST_ROW + 1) so chrome events drop
    the hover; the keyboard cursor stays where it was via the persisted
    `_options_panes_row` (only changed by `_set_panes_cursor` calls)."""
    # Panes frame is unique: the keyboard cursor and the mouse hover
    # share `_options_panes_row`. Clearing hover here would also move
    # the cursor, so we deliberately do nothing — the headers / Back
    # rows' own MOUSE_MOVE handlers already overwrite the cursor when
    # the mouse moves onto them, and the grid cells do the same. The
    # function still exists so the title_block / footer_block / blank
    # rows can carry a handler (the invariant) even though it is a
    # no-op on MOUSE_MOVE.
    return


def _options_panes_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    clear_hover = _options_panes_clear_hover

    # Grid rows from _conf. Empty / unknown colour names fall back to
    # Black (column 0) per the grid model.
    grid_rows = []
    for _target, label, show_key, color_key in _PANE_OPTIONS:
        enabled = (_conf.get(show_key) == "1")
        cur_color = _conf.get(color_key, "")
        try:
            colour_index = PANE_COLOR_ORDER.index(cur_color)
        except ValueError:
            colour_index = 0
        grid_rows.append((label, enabled, colour_index))

    cur_row = _options_panes_row
    cur_col = _options_panes_col
    grid_cursor = (cur_row, cur_col) if cur_row < _PANES_GRID_ROWS else None

    headers_on    = (_conf.get("show_pane_dividers") == "1")
    headers_label = f"[{'X' if headers_on else ' '}] Display pane headers"
    back_label    = "Back"
    # Headers is a glyph row, so it gets the centred-block left
    # margin. Back is a plain `<< label >>` row and centres per row
    # (computed below). The block here is degenerate — one row — but
    # the structure mirrors the multi-row glyph blocks elsewhere.
    label_col_w   = len(headers_label)
    block_w       = label_col_w + 6
    left_pad      = max(0, (cols - block_w) // 2)

    frags = []
    frags.extend(title_block(
        "─── Panes ───", cols, blank_above=2, mouse_handler=clear_hover,
    ))

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

    # Blank row between grid and the headers toggle.
    frags.append(("", "\n", clear_hover))

    # Display pane headers — << label >> menu-row grammar.
    state_h = "selected" if cur_row == _PANES_HEADERS_ROW else "inactive"

    def _headers_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_panes_cursor(_PANES_HEADERS_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _set_panes_cursor(_PANES_HEADERS_ROW)
            _toggle_pane_headers()

    headers_right_pad = max(0, cols - left_pad - len(headers_label) - 6)
    frags.append(("", " " * left_pad, clear_hover))
    frags.extend(menu_row(
        headers_label, state_h, mouse_handler=_headers_handler,
    ))
    frags.append(("", " " * headers_right_pad, clear_hover))
    frags.append(("", "\n", clear_hover))

    # Blank row between headers and Back.
    frags.append(("", "\n", clear_hover))

    # Back — plain << label >> row, centred per row (no leading glyph
    # to stack with the headers toggle above).
    state_b = "selected" if cur_row == _PANES_BACK_ROW else "inactive"

    def _back_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_panes_cursor(_PANES_BACK_ROW)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _options_panes_back()

    back_row_w     = len(back_label) + 6
    back_left_pad  = max(0, (cols - back_row_w) // 2)
    back_right_pad = max(0, cols - back_left_pad - back_row_w)
    frags.append(("", " " * back_left_pad, clear_hover))
    frags.extend(menu_row(
        back_label, state_b, mouse_handler=_back_handler,
    ))
    frags.append(("", " " * back_right_pad, clear_hover))
    frags.append(("", "\n", clear_hover))

    # Footer block anchored to the final terminal row. Content rows
    # above the footer = title block + header row + 6 pane rows + 4
    # rows of bottom chrome (blank · headers · blank · Back).
    content_rows = title_block_height(2) + 1 + _PANES_GRID_ROWS + 4
    footer = "↑↓←→ Move · Enter Toggle · ESC Back"
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))

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


def _options_connection_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("options_connection", -1)


def _options_connection_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Connection ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"
    clear_hover = _options_connection_clear_hover

    cur = _conf.get("connection_mode", "mmapper")
    host = _conf.get("connection_host", "localhost")
    port = _conf.get("connection_port", "4242")
    custom_detail = f"<{host}>:<{port}>"

    # Each row's full label includes the radio glyph and (for the three
    # modes) the host:port detail; the leading (•) / ( ) glyph carries
    # the persistent on / active state — colour is reserved for the
    # transient cursor and hover. The block is left-aligned on a shared
    # column inside a centred block so the radio glyphs stack vertically.
    rows = _CONNECTION_MODES_ROWS(cur, custom_detail)
    back_label = "Back"
    # Glyph menu: the mode rows left-align at the same column inside
    # a centred block so the (•) / ( ) glyphs stack. `Back` is a
    # plain `<< label >>` row and centres per row (below the block).
    label_col_w = max(len(l) for l in rows)
    block_w     = label_col_w + 6
    left_pad    = max(0, (cols - block_w) // 2)

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=2, mouse_handler=clear_hover,
    ))

    back_idx = len(rows)   # Back is rendered below the mode rows
    n_rows = len(rows) + 1

    for i, label in enumerate(rows):
        is_active = (i == _sel_options_connection)
        is_hover  = (i == _hover_options_connection)
        state     = _menu_row_state(is_active, is_hover)

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
        right_pad = max(0, cols - left_pad - len(label) - 6)
        frags.append(("", " " * left_pad, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * right_pad, clear_hover))
        frags.append(("", "\n", clear_hover))

    # Blank row before Back, then the per-row-centred Back row.
    frags.append(("", "\n", clear_hover))

    is_active = (back_idx == _sel_options_connection)
    is_hover  = (back_idx == _hover_options_connection)
    state     = _menu_row_state(is_active, is_hover)

    def _back_handler(ev):
        global _sel_options_connection
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _set_hover("options_connection", back_idx)
            return
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _sel_options_connection = back_idx
            _options_connection_activate(back_idx)

    back_row_w     = len(back_label) + 6
    back_left_pad  = max(0, (cols - back_row_w) // 2)
    back_right_pad = max(0, cols - back_left_pad - back_row_w)
    frags.append(("", " " * back_left_pad, clear_hover))
    frags.extend(menu_row(back_label, state, mouse_handler=_back_handler))
    frags.append(("", " " * back_right_pad, clear_hover))
    frags.append(("", "\n", clear_hover))

    content_rows = title_block_height(2) + n_rows + 1
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


def _CONNECTION_MODES_ROWS(cur, custom_detail):
    """Mode-row labels for the Connection submenu. The leading (•) / ( )
    glyph is part of the menu-row label so the cursor / hover grammar
    rendered by `menu_chrome.menu_row` does not need to overlay a
    separate persistent-active style."""
    rows = []
    for mode, lbl, detail in _CONNECTION_MODES:
        dot = "(•)" if cur == mode else "( )"
        suffix = custom_detail if mode == "custom" else detail
        rows.append(f"{dot} {lbl}  {suffix}")
    return rows


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
    rows_h = _term_rows()
    title  = "─── Custom Connection ───"
    hint   = "Tab Cycle · Enter Save · ESC Cancel"

    host_label = "Host: "
    port_label = "Port: "

    frags = []
    frags.extend(title_block(title, cols, blank_above=2))
    frags.append(("", "\n"))

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

    body_rows = 1 + 1 + 1 + 1  # blank · host · blank · port

    if _conn_err:
        frags.append(("", "\n"))
        frags.append(("", _pad_centre(_conn_err, cols)))
        frags.append((C_ERR, _conn_err))
        frags.append(("", "\n"))
        body_rows += 2

    content_rows = title_block_height(2) + body_rows
    frags.extend(footer_block(hint, cols, rows_h, content_rows))
    return frags


# ---------------------------------------------------------------------------
# Options — Spotlights submenu
# ---------------------------------------------------------------------------
# Per-kind toggles for the spotlight reel. (conf_key, label) — flipping a
# toggle writes "0" / "1" into startup.conf; the spotlight aggregator reads
# the same keys and skips disabled JSONL event kinds before building the
# reel. Missing keys default to enabled ("1").
_SPOTLIGHT_TOGGLES = [
    ("spotlights_show_achievements", "Achievements"),
    ("spotlights_show_deaths",       "Deaths"),
    ("spotlights_show_levelups",     "Level-ups"),
    ("spotlights_show_pvp",          "PvP kills"),
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


def _options_spotlights_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("options_spotlights", -1)


def _options_spotlights_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Spotlights ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"
    clear_hover = _options_spotlights_clear_hover

    rows = _options_spotlights_rows()
    sel_indices = _options_spotlights_selectable_indices()
    sel_pos = (_sel_options_spotlights
               if 0 <= _sel_options_spotlights < len(sel_indices)
               else 0)
    sel_row = sel_indices[sel_pos] if sel_indices else -1

    labels = []
    for kind, key, label in rows:
        if kind == "toggle":
            # The leading [X] / [ ] glyph carries the persistent on /
            # active state, so the row's transient cursor / hover colour
            # can ride on the shared menu-row grammar without overloading.
            box = "[X]" if _conf.get(key) == "1" else "[ ]"
            labels.append(f"{box} {label}")
        elif kind == "sep":
            labels.append("")
        elif kind == "back":
            labels.append("Back")
    # Glyph menu: the toggle rows left-align at the same column inside
    # a centred block so the [X] / [ ] glyphs stack. `Back` is a plain
    # `<< label >>` row and centres per row (handled inline below).
    toggle_labels = [labels[i] for i, (kind, _, _) in enumerate(rows)
                     if kind == "toggle"]
    label_col_w = max((len(l) for l in toggle_labels), default=0)
    block_w     = label_col_w + 6
    left_pad    = max(0, (cols - block_w) // 2)

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=2, mouse_handler=clear_hover,
    ))

    body_rows = 0
    for i, (kind, _key, _label) in enumerate(rows):
        if kind == "sep":
            frags.append(("", "\n", clear_hover))
            body_rows += 1
            continue

        label = labels[i]
        is_active = (i == sel_row)
        is_hover  = (i == _hover_options_spotlights)
        state     = _menu_row_state(is_active, is_hover)

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
        if kind == "back":
            # Per-row centring — Back is a plain << label >> row.
            row_w     = len(label) + 6
            row_left  = max(0, (cols - row_w) // 2)
            row_right = max(0, cols - row_left - row_w)
        else:
            row_left  = left_pad
            row_right = max(0, cols - left_pad - len(label) - 6)
        frags.append(("", " " * row_left, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * row_right, clear_hover))
        frags.append(("", "\n", clear_hover))
        body_rows += 1

    content_rows = title_block_height(2) + body_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


# ---------------------------------------------------------------------------
# Options — Terminal submenu (interactive foot.ini appearance editor)
# ---------------------------------------------------------------------------
# Only reachable when the cockpit was launched by the foot/WSLg
# managed-terminal supervisor (`MUME_TERMINAL=foot-managed`). The row
# that opens this frame is conditionally added by `_build_options_rows`
# and the activation router in `_activate_option`. The Font row pushes
# the `terminal_font_picker` subframe; every other row is an inline ←/→
# control (numeric stepper or fixed-value cycle). Apply writes the
# pending TerminalConfig through `foot_config.write_settings`, writes
# the relaunch sentinel, and exits — the supervisor then relaunches
# foot with the new config (ADR 0104). The fresh launcher consumes
# `.launcher_resume` to return straight here. Back / ESC discard
# pending edits.
_TERMINAL_DEFAULT_SIZE = 12   # used when foot.ini has no `size=` attribute


def _terminal_size_clamp(n):
    return max(_TERMINAL_SIZE_MIN, min(_TERMINAL_SIZE_MAX, int(n)))


def _normalise_hex(value):
    """Strip the leading `#` and uppercase a hex colour string. An empty
    or missing value becomes `""` — the caller decides what to do."""
    return (value or "").strip().lstrip("#").upper()


def _background_cycle_entries(disk_hex):
    """Return the ordered `[(hex, label), …]` cycle for Background.

    The seven palette entries (PANE_COLOR_ORDER), plus a leading entry
    for the on-disk hex when it falls outside the palette — mirroring
    the font picker's off-list-family handling so a hand-rolled
    background survives a no-op Apply. The off-list entry is labelled
    by its hex.
    """
    palette = []
    for name in PANE_COLOR_ORDER:
        hex_str = pane_color_hex(name)
        hex_norm = _normalise_hex(hex_str) if hex_str else "000000"
        palette.append((hex_norm, name))
    palette_values = {v for v, _ in palette}
    disk_norm = _normalise_hex(disk_hex)
    if disk_norm and disk_norm not in palette_values:
        return [(disk_norm, disk_norm)] + palette
    return palette


def _cycle_pick(values, current, delta):
    """Step through `values` from `current` by `delta`, wrapping at both
    ends. Falls back to `values[0]` when `current` is not in `values`."""
    if not values:
        return current
    try:
        idx = values.index(current)
    except ValueError:
        idx = 0
    return values[(idx + delta) % len(values)]


def _options_terminal_rows():
    """Row catalog for the Terminal Settings frame.

    `(action, label)` tuples in render order, rebuilt per render so the
    labels reflect the current pending-vs-disk delta. Each row's label
    uses the `Label: <disk> → <pending>` notation when the field
    differs from disk, else `Label: <value>`. Apply is the active row
    when `pending != disk`, else the dead-grey `apply_disabled` row.
    """
    disk = _options_terminal_disk
    pend = _options_terminal_pending

    def _delta(label, disk_text, pend_text, differs):
        if differs:
            return f"{label}: {disk_text} → {pend_text}"
        return f"{label}: {disk_text}"

    if disk is None or disk.family is None:
        font_label = "Font: (unreadable)"
    else:
        font_label = _delta(
            "Font", disk.family, pend.family, pend.family != disk.family,
        )

    def _size_text(s):
        return "default" if s is None else str(s)
    size_label = _delta(
        "Size", _size_text(disk.size), _size_text(pend.size),
        pend.size != disk.size,
    )

    window_mode_label = _delta(
        "Window mode", disk.window_mode, pend.window_mode,
        pend.window_mode != disk.window_mode,
    )

    width_label = _delta(
        "Width", str(disk.window_width), str(pend.window_width),
        pend.window_width != disk.window_width,
    )
    height_label = _delta(
        "Height", str(disk.window_height), str(pend.window_height),
        pend.window_height != disk.window_height,
    )

    padding_label = _delta(
        "Padding", str(disk.pad_x), str(pend.pad_x),
        pend.pad_x != disk.pad_x,
    )

    bg_entries = _background_cycle_entries(disk.background)
    bg_label_map = dict(bg_entries)
    def _bg_disp(v):
        return bg_label_map.get(v, v or "—")
    background_label = _delta(
        "Background", _bg_disp(disk.background), _bg_disp(pend.background),
        pend.background != disk.background,
    )

    cursor_style_label = _delta(
        "Cursor style", disk.cursor_style, pend.cursor_style,
        pend.cursor_style != disk.cursor_style,
    )

    def _blink_text(b):
        return "On" if b else "Off"
    cursor_blink_label = _delta(
        "Cursor blink", _blink_text(disk.cursor_blink),
        _blink_text(pend.cursor_blink),
        pend.cursor_blink != disk.cursor_blink,
    )

    has_delta = (pend != disk)
    apply_row = ("apply", "Apply") if has_delta else ("apply_disabled", "Apply")

    rows = [
        ("font",         font_label),
        ("size",         size_label),
        ("window_mode",  window_mode_label),
    ]
    # Width / Height only make sense for the windowed mode; maximized
    # and fullscreen ignore them entirely. The pending config keeps
    # carrying the values, so a round-trip back to "windowed" restores
    # the user's last edits without resetting them.
    if pend.window_mode == "windowed":
        rows.append(("width",  width_label))
        rows.append(("height", height_label))
    rows.extend([
        ("padding",      padding_label),
        ("background",   background_label),
        ("cursor_style", cursor_style_label),
        ("cursor_blink", cursor_blink_label),
        apply_row,
        ("back",         "Back"),
    ])
    return rows


def _enter_options_terminal_frame(restore_cursor=None):
    """Seed pending state from disk and push the frame.

    `restore_cursor` lets the post-relaunch resume hook drop the cursor
    on the row it was on before Apply exited the launcher; absent, the
    cursor lands on the Font row.
    """
    global _options_terminal_disk, _options_terminal_pending
    global _options_terminal_cursor, _options_terminal_hover
    disk = foot_config.read_settings()
    # Normalise the background hex so equality compares case-insensitively
    # and the cycle lookup hits the palette entries even when foot.ini
    # uses lowercase.
    disk.background = _normalise_hex(disk.background) or "000000"
    _options_terminal_disk    = disk
    _options_terminal_pending = dataclasses.replace(disk)
    _options_terminal_hover   = -1
    if restore_cursor is not None:
        # Snap the saved index to the nearest selectable row. Post-Apply
        # pending equals disk so Apply is dead-grey — fall back to the
        # nearest selectable neighbour rather than stranding the cursor.
        selectable = _options_terminal_selectable_indices()
        target = max(0, int(restore_cursor))
        if selectable:
            # Closest selectable index, ties prefer the preceding one.
            _options_terminal_cursor = min(
                selectable, key=lambda i: (abs(i - target), i > target),
            )
        else:
            _options_terminal_cursor = 0
    else:
        _options_terminal_cursor = 0
    _push_frame("options_terminal")


def _options_terminal_back():
    """Discard pending edits and pop. Pending is re-seeded from disk
    on the next entry, so an explicit reset here is redundant."""
    _pop_frame()


def _options_terminal_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("options_terminal", -1)


def _options_terminal_selectable_indices():
    """Indices of keyboard-selectable rows. The dead-grey Apply row
    (action `apply_disabled`) is skipped by ↑/↓ navigation, mirroring
    the ingame_menu Save-run pattern."""
    return [i for i, (action, _label) in enumerate(_options_terminal_rows())
            if action != "apply_disabled"]


def _options_terminal_move(delta):
    """Step the cursor by `delta` rows over the selectable subset, with
    wrap-around. Off-list cursors snap onto the nearest selectable row
    before stepping (defensive — happens when the row list changes
    under the cursor, e.g. Apply transitioning into the dead state)."""
    global _options_terminal_cursor
    selectable = _options_terminal_selectable_indices()
    if not selectable:
        return
    if _options_terminal_cursor in selectable:
        pos = selectable.index(_options_terminal_cursor)
    else:
        # Cursor sits on a row that just lost selectability — fall back
        # to the nearest preceding selectable row, or the first one.
        pos = 0
        for i, idx in enumerate(selectable):
            if idx <= _options_terminal_cursor:
                pos = i
            else:
                break
    pos = (pos + delta) % len(selectable)
    _options_terminal_cursor = selectable[pos]
    if _app:
        _app.invalidate()


def _options_terminal_size_step(delta):
    """Adjust pending size by `delta` (clamped). Only valid on the Size
    row — callers gate this on the current cursor row."""
    global _options_terminal_pending
    cur = _options_terminal_pending.size
    if cur is None:
        # No size on disk: snap to the default before applying the step
        # so the first nudge produces a deterministic concrete value.
        cur = _TERMINAL_DEFAULT_SIZE
    new = _terminal_size_clamp(cur + delta)
    if new != _options_terminal_pending.size:
        _options_terminal_pending.size = new
        if _app:
            _app.invalidate()


def _options_terminal_padding_step(delta):
    """Step pending padding by `delta * _TERMINAL_PAD_STEP`, clamped to
    `[_TERMINAL_PAD_MIN, _TERMINAL_PAD_MAX]`. Writes symmetrically:
    `pad_x` and `pad_y` are kept equal, so an asymmetric hand-edit on
    disk is collapsed by the next Apply (acceptable per the spec)."""
    global _options_terminal_pending
    cur = _options_terminal_pending.pad_x
    new = max(_TERMINAL_PAD_MIN,
              min(_TERMINAL_PAD_MAX, cur + delta * _TERMINAL_PAD_STEP))
    if new != _options_terminal_pending.pad_x or new != _options_terminal_pending.pad_y:
        _options_terminal_pending.pad_x = new
        _options_terminal_pending.pad_y = new
        if _app:
            _app.invalidate()


def _options_terminal_background_step(delta):
    """Cycle pending background hex through the palette (plus any
    leading off-list disk entry) by `delta`, wrapping."""
    global _options_terminal_pending
    entries = _background_cycle_entries(_options_terminal_disk.background)
    values = [v for v, _ in entries]
    new = _cycle_pick(values, _options_terminal_pending.background, delta)
    if new != _options_terminal_pending.background:
        _options_terminal_pending.background = new
        if _app:
            _app.invalidate()


def _options_terminal_cursor_style_step(delta):
    """Cycle pending cursor style through block / beam / underline."""
    global _options_terminal_pending
    values = ["block", "beam", "underline"]
    new = _cycle_pick(values, _options_terminal_pending.cursor_style, delta)
    if new != _options_terminal_pending.cursor_style:
        _options_terminal_pending.cursor_style = new
        if _app:
            _app.invalidate()


def _options_terminal_window_mode_step(delta):
    """Cycle pending window mode through windowed / maximized / fullscreen.

    The pending config always carries `window_width` / `window_height`;
    cycling away from "windowed" only hides the conditional Width / Height
    rows, so a round-trip back to "windowed" finds the user's last edits
    intact.
    """
    global _options_terminal_pending
    values = ["windowed", "maximized", "fullscreen"]
    new = _cycle_pick(values, _options_terminal_pending.window_mode, delta)
    if new != _options_terminal_pending.window_mode:
        _options_terminal_pending.window_mode = new
        if _app:
            _app.invalidate()


def _options_terminal_width_step(delta):
    """Step pending window width by `delta * _TERMINAL_WIN_STEP`, clamped
    to `[_TERMINAL_WIN_W_MIN, _TERMINAL_WIN_W_MAX]`."""
    global _options_terminal_pending
    cur = _options_terminal_pending.window_width
    new = max(_TERMINAL_WIN_W_MIN,
              min(_TERMINAL_WIN_W_MAX, cur + delta * _TERMINAL_WIN_STEP))
    if new != _options_terminal_pending.window_width:
        _options_terminal_pending.window_width = new
        if _app:
            _app.invalidate()


def _options_terminal_height_step(delta):
    """Step pending window height by `delta * _TERMINAL_WIN_STEP`, clamped
    to `[_TERMINAL_WIN_H_MIN, _TERMINAL_WIN_H_MAX]`."""
    global _options_terminal_pending
    cur = _options_terminal_pending.window_height
    new = max(_TERMINAL_WIN_H_MIN,
              min(_TERMINAL_WIN_H_MAX, cur + delta * _TERMINAL_WIN_STEP))
    if new != _options_terminal_pending.window_height:
        _options_terminal_pending.window_height = new
        if _app:
            _app.invalidate()


def _options_terminal_cursor_blink_step(delta):
    """Toggle pending cursor blink (Off ↔ On). `delta` direction is
    irrelevant for a two-value cycle but kept for symmetry with the
    other steppers."""
    global _options_terminal_pending
    values = [False, True]
    new = _cycle_pick(values, _options_terminal_pending.cursor_blink, delta)
    if new != _options_terminal_pending.cursor_blink:
        _options_terminal_pending.cursor_blink = new
        if _app:
            _app.invalidate()


_OPTIONS_TERMINAL_ARROW_STEPPERS = {
    "size":         _options_terminal_size_step,
    "window_mode":  _options_terminal_window_mode_step,
    "width":        _options_terminal_width_step,
    "height":       _options_terminal_height_step,
    "padding":      _options_terminal_padding_step,
    "background":   _options_terminal_background_step,
    "cursor_style": _options_terminal_cursor_style_step,
    "cursor_blink": _options_terminal_cursor_blink_step,
}


def _options_terminal_arrow_step(delta):
    """Dispatch a ←/→ on the current cursor row to the right field's
    stepper. No-op on non-stepper rows (Font / Apply / Back)."""
    rows = _options_terminal_rows()
    if not (0 <= _options_terminal_cursor < len(rows)):
        return
    action = rows[_options_terminal_cursor][0]
    stepper = _OPTIONS_TERMINAL_ARROW_STEPPERS.get(action)
    if stepper is not None:
        stepper(delta)


def _options_terminal_activate(row_idx=None):
    """Activate the row at `row_idx` (or the cursor row if omitted)."""
    rows = _options_terminal_rows()
    idx = _options_terminal_cursor if row_idx is None else row_idx
    if not (0 <= idx < len(rows)):
        return
    action, _label = rows[idx]
    if action == "font":
        _enter_terminal_font_picker_frame()
    elif action in _OPTIONS_TERMINAL_ARROW_STEPPERS:
        # Stepper / cycle rows are driven by ← / → — Enter is a no-op.
        pass
    elif action == "apply":
        _options_terminal_apply()
    elif action == "apply_disabled":
        # Dead row; nothing to do (keyboard nav still steps onto it so
        # the user can see it).
        pass
    elif action == "back":
        _options_terminal_back()


def _options_terminal_apply():
    """Write the pending foot.ini, drop the relaunch sentinel + resume
    hint, exit.

    Order matters: write the foot.ini first so a crash before the
    sentinel still produces a useful config on the next manual launch;
    write the sentinel before the resume hint so a crash between them
    falls back to "relaunch but start on main menu" (the resume hint
    is a one-shot consumed by the fresh launcher); call `app.exit()`
    last so the supervisor's loop sees both files when foot returns.
    """
    if _options_terminal_pending is None:
        # Defensive — Apply is gated on a pending != disk delta.
        return
    try:
        foot_config.write_settings(_options_terminal_pending)
    except OSError:
        # The write failed (permissions, disk full, …). Bail out
        # without exiting — the user keeps their pending values.
        return
    _write_relaunch_sentinel()
    _write_launcher_resume(
        frame="options_terminal", cursor=_options_terminal_cursor,
    )
    if _app:
        _app.exit()


def _write_relaunch_sentinel():
    """Touch the foot relaunch sentinel. The supervisor checks for this
    file when foot exits — when present, it removes it and relaunches
    foot. Empty file is fine; existence is the signal."""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        with open(FOOT_RELAUNCH_SENTINEL, "w", encoding="utf-8") as fh:
            fh.write("")
    except OSError:
        pass


def _write_launcher_resume(frame, cursor):
    """Write `bridge/runtime/.launcher_resume` (atomic temp + rename).

    Consumed once by the fresh launcher in `_consume_launcher_resume`
    to restore the frame stack post-relaunch. Format is a plain
    key=value file; unknown frame names are ignored on read."""
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".launcher_resume.", suffix=".tmp", dir=RUNTIME_DIR,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"frame={frame}\n")
                fh.write(f"cursor={int(cursor)}\n")
            os.replace(tmp_path, LAUNCHER_RESUME_PATH)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError:
        pass


def _consume_launcher_resume():
    """Read and delete `.launcher_resume`; return a `(frame, cursor)`
    tuple or `None`. One-shot semantics: the delete happens before the
    caller acts on the value so a crash mid-restoration cannot
    re-trigger the same restore on the next start. Returns `None` when
    the file is absent or unparseable."""
    try:
        with open(LAUNCHER_RESUME_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        os.unlink(LAUNCHER_RESUME_PATH)
    except OSError:
        pass
    frame = None
    cursor = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key == "frame":
            frame = value
        elif key == "cursor":
            try:
                cursor = int(value)
            except ValueError:
                cursor = 0
    if frame is None:
        return None
    return (frame, cursor)


def _options_terminal_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Terminal Settings ───"
    has_delta = (
        _options_terminal_pending is not None
        and _options_terminal_pending != _options_terminal_disk
    )
    if has_delta:
        footer = "↑↓ Navigate · ←→ Adjust · Enter Select · Apply restarts the terminal · ESC Back"
    else:
        footer = "↑↓ Navigate · ←→ Adjust · Enter Select · ESC Back"
    clear_hover = _options_terminal_clear_hover

    rows = _options_terminal_rows()
    cur  = _options_terminal_cursor
    if not (0 <= cur < len(rows)):
        cur = 0

    # Glyph-menu block grammar: every stepper row carries its value
    # inline so row labels vary in width. The block left-margin is
    # computed from the widest row so the labels stack on the same
    # column; the chunkier "Apply restarts the terminal" hint lives in
    # the footer, not in a row.
    label_widths = [len(label) for _action, label in rows]
    block_w  = max(label_widths) + 6
    left_pad = max(0, (cols - block_w) // 2)

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=2, mouse_handler=clear_hover,
    ))

    body_rows = 0
    for i, (action, label) in enumerate(rows):
        # Blank spacer before Back, matching the Panes / Scripts frames.
        # Rendered inline rather than as a catalog entry so the row list
        # stays navigable-only and ↑/↓ navigation is unaffected.
        if action == "back":
            frags.append(("", "\n", clear_hover))
            body_rows += 1
        is_cursor = (i == cur)
        is_hover  = (i == _options_terminal_hover)
        # Apply renders as dead-grey (inactive_style=C_HINT) when there
        # is no delta to write; cursor and hover land on it but do not
        # change its colour — that's the "inactive" state from the
        # ingame_menu Save-run row pattern.
        if action == "apply_disabled":
            row_left  = left_pad
            row_right = max(0, cols - left_pad - len(label) - 6)
            frags.append(("", " " * row_left, clear_hover))
            # Pass the menu_row's hover slot for the cursor too: the
            # row is non-actionable, so we suppress the gold << >>
            # arrows even when the cursor sits on it.
            frags.extend(menu_row(
                label, "inactive",
                mouse_handler=clear_hover, inactive_style=C_HINT,
            ))
            frags.append(("", " " * row_right, clear_hover))
            frags.append(("", "\n", clear_hover))
            body_rows += 1
            continue

        state = _menu_row_state(is_cursor, is_hover)

        def _make_handler(row=i, act=action):
            def _h(ev):
                global _options_terminal_cursor
                if ev.event_type == MouseEventType.MOUSE_MOVE:
                    _set_hover("options_terminal", row)
                    return
                if ev.event_type == MouseEventType.MOUSE_DOWN:
                    _options_terminal_cursor = row
                    _options_terminal_activate(row)
            return _h

        h = _make_handler()
        row_left  = left_pad
        row_right = max(0, cols - left_pad - len(label) - 6)
        frags.append(("", " " * row_left, clear_hover))
        frags.extend(menu_row(label, state, mouse_handler=h))
        frags.append(("", " " * row_right, clear_hover))
        frags.append(("", "\n", clear_hover))
        body_rows += 1

    content_rows = title_block_height(2) + body_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


# ---------------------------------------------------------------------------
# Terminal — font picker subframe (pushed from Options → Terminal → Font)
# ---------------------------------------------------------------------------
# Scrollable list of installed monospace families, scanned on entry via
# `foot_config.list_monospace_fonts`. Selection grammar parallels
# options_connection's radio rows: the pending family carries a
# persistent grey-background marker even when the cursor is elsewhere,
# the cursor row paints with the gold-background focus style, and the
# pending row under the cursor renders gold (the cursor wins). Enter /
# click sets the pending font on the parent frame and pops back;
# ESC pops without changing the pending family.
_NO_MONO_FONTS_MESSAGE = "No monospace fonts found"


def _enter_terminal_font_picker_frame():
    """Scan the installed monospace fonts and push the picker frame.

    If the current pending family is not among the scan results (e.g.
    foot.ini names an uninstalled family), we still surface it as the
    first entry so it's visible and re-pickable — the spec calls this
    out explicitly so the user is not silently stranded.
    """
    global _terminal_font_picker_fonts
    global _terminal_font_picker_cursor, _terminal_font_picker_scroll
    global _terminal_font_picker_hover
    fonts = foot_config.list_monospace_fonts()
    pending = (_options_terminal_pending.family
               if _options_terminal_pending is not None else None)
    if pending and pending not in fonts:
        fonts = [pending] + fonts
    _terminal_font_picker_fonts  = fonts
    _terminal_font_picker_hover  = -1
    _terminal_font_picker_scroll = 0
    if fonts:
        try:
            _terminal_font_picker_cursor = fonts.index(pending) if pending else 0
        except ValueError:
            _terminal_font_picker_cursor = 0
        _terminal_font_picker_ensure_visible()
    else:
        _terminal_font_picker_cursor = 0
    _push_frame("terminal_font_picker")


def _terminal_font_picker_back():
    _pop_frame()


def _terminal_font_picker_clear_hover(ev):
    if ev.event_type == MouseEventType.MOUSE_MOVE:
        _set_hover("terminal_font_picker", -1)


def _terminal_font_picker_visible_rows():
    """List body = terminal rows minus title block, footer, and the
    trailing Back row + its spacer."""
    return max(1, _term_rows() - title_block_height(2) - 1 - 2)


def _terminal_font_picker_ensure_visible():
    """Pull the scroll so the cursor stays inside the body window.

    The Back row (cursor index `n`) sits in the reserved non-scrolling
    row below the list — when the cursor is there, clamp scroll so the
    tail of the font list is visible instead of running the font-range
    scroll math on the out-of-range index.
    """
    global _terminal_font_picker_scroll
    body = _terminal_font_picker_visible_rows()
    n = len(_terminal_font_picker_fonts)
    if n == 0:
        _terminal_font_picker_scroll = 0
        return
    if _terminal_font_picker_cursor >= n:
        _terminal_font_picker_scroll = max(0, n - body)
        return
    if _terminal_font_picker_cursor < _terminal_font_picker_scroll:
        _terminal_font_picker_scroll = _terminal_font_picker_cursor
    elif _terminal_font_picker_cursor >= _terminal_font_picker_scroll + body:
        _terminal_font_picker_scroll = _terminal_font_picker_cursor - body + 1
    _terminal_font_picker_scroll = max(
        0, min(_terminal_font_picker_scroll, max(0, n - body)),
    )


def _terminal_font_picker_move(delta):
    """Step cursor by `delta` over the `n + 1` position space (n font
    rows plus the trailing Back row at index `n`), with wrap-around."""
    global _terminal_font_picker_cursor
    n = len(_terminal_font_picker_fonts)
    _terminal_font_picker_cursor = (_terminal_font_picker_cursor + delta) % (n + 1)
    _terminal_font_picker_ensure_visible()
    if _app:
        _app.invalidate()


def _terminal_font_picker_select(idx=None):
    """Commit the row at `idx` (or the cursor row). Index `n` is the
    Back row — selecting it pops the frame instead of committing a
    font family."""
    n = len(_terminal_font_picker_fonts)
    row = _terminal_font_picker_cursor if idx is None else idx
    if row == n:
        _terminal_font_picker_back()
        return
    if not (0 <= row < n):
        return
    if _options_terminal_pending is not None:
        _options_terminal_pending.family = _terminal_font_picker_fonts[row]
    _terminal_font_picker_back()


def _terminal_font_picker_text():
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Choose Font ───"
    footer = "↑↓ Navigate · Enter Select · ESC Back"
    clear_hover = _terminal_font_picker_clear_hover

    frags = []
    frags.extend(title_block(
        title, cols, blank_above=2, mouse_handler=clear_hover,
    ))

    fonts   = _terminal_font_picker_fonts
    cur     = _terminal_font_picker_cursor
    pending = (_options_terminal_pending.family
               if _options_terminal_pending is not None else None)
    body_rows = 0

    if not fonts:
        # Empty-state pane: a single explanatory line, then Back. The
        # picker is still escapable, so the user is never trapped.
        msg = _NO_MONO_FONTS_MESSAGE
        pad = max(0, (cols - len(msg)) // 2)
        frags.append(("", " " * pad, clear_hover))
        frags.append((C_BODY, msg, clear_hover))
        frags.append(("", "\n", clear_hover))
        body_rows += 1
    else:
        scroll = _terminal_font_picker_scroll
        visible = _terminal_font_picker_visible_rows()
        # Widest visible name drives a centred block so the rows align
        # on the same column even when names vary in length. Long
        # names truncate at the right edge with an ellipsis to keep the
        # background fill rectangular.
        end     = min(len(fonts), scroll + visible)
        widest  = max((len(f) for f in fonts[scroll:end]), default=0)
        # Background fill width — clamped to leave 4 cells of side
        # margin so the row backgrounds don't touch the terminal edges.
        bg_w    = max(8, min(cols - 4, widest + 4))
        left_pad = max(0, (cols - bg_w) // 2)

        for visible_idx in range(scroll, end):
            family    = fonts[visible_idx]
            is_cursor  = (visible_idx == cur)
            is_pending = (family == pending)
            is_hover   = (visible_idx == _terminal_font_picker_hover)
            # Style mapping mirrors the palette's three-state button
            # grammar: cursor (focused) → gold bg; pending (selected
            # but unfocused) → grey bg; hover → grey bg; otherwise the
            # plain item colour. Cursor wins over pending — the
            # pending family under the cursor renders gold.
            if is_cursor:
                style = C_BUTTON_ACTIVE_FOCUSED
            elif is_pending:
                style = C_BUTTON_ACTIVE_UNFOCUSED
            elif is_hover:
                style = C_BUTTON_HOVER
            else:
                style = C_ITEM
            # Centre the family inside the background fill, truncate
            # with an ellipsis when the name overflows bg_w-2.
            text_w = bg_w - 2
            if len(family) > text_w:
                shown = family[: max(0, text_w - 1)] + "…"
            else:
                shown = family
            inner_pad = text_w - len(shown)
            inner_l = inner_pad // 2
            inner_r = inner_pad - inner_l
            cell = " " + " " * inner_l + shown + " " * inner_r + " "

            def _make_handler(row=visible_idx):
                def _h(ev):
                    global _terminal_font_picker_cursor
                    if ev.event_type == MouseEventType.MOUSE_MOVE:
                        _set_hover("terminal_font_picker", row)
                        return
                    if ev.event_type == MouseEventType.MOUSE_DOWN:
                        _terminal_font_picker_cursor = row
                        _terminal_font_picker_select(row)
                return _h

            h = _make_handler()
            right_pad = max(0, cols - left_pad - len(cell))
            frags.append(("", " " * left_pad, clear_hover))
            frags.append((style, cell, h))
            frags.append(("", " " * right_pad, clear_hover))
            frags.append(("", "\n", clear_hover))
            body_rows += 1

    # Blank row + `<< Back >>` row below the list. Back is the final
    # cursor index (`n`); when cursored it renders in the focused style,
    # matching every other launcher frame's Back row.
    frags.append(("", "\n", clear_hover))
    body_rows += 1

    back_label = "Back"
    back_state = "selected" if cur == len(fonts) else "inactive"

    def _back_handler(ev):
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _terminal_font_picker_back()

    row_w     = len(back_label) + 6
    row_left  = max(0, (cols - row_w) // 2)
    row_right = max(0, cols - row_left - row_w)
    frags.append(("", " " * row_left, clear_hover))
    frags.extend(menu_row(back_label, back_state, mouse_handler=_back_handler))
    frags.append(("", " " * row_right, clear_hover))
    frags.append(("", "\n", clear_hover))
    body_rows += 1

    content_rows = title_block_height(2) + body_rows
    frags.extend(footer_block(
        footer, cols, rows_h, content_rows, mouse_handler=clear_hover,
    ))
    return frags


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
    cols   = _term_cols()
    rows_h = _term_rows()
    title  = "─── Spotlights ───"
    footer = "Any key to return"
    body_w = max(20, min(72, cols - 4))
    body = (_SPOTLIGHTS_EMPTY_FILTERED_BODY
            if _spotlights_empty_reason == "filtered"
            else _SPOTLIGHTS_EMPTY_BODY)
    wrapped = _wrap_text(body, body_w)

    frags = []
    frags.extend(title_block(title, cols, blank_above=2))
    for line in wrapped:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((C_BODY, line))
        frags.append(("", "\n"))

    content_rows = title_block_height(2) + len(wrapped)
    frags.extend(footer_block(footer, cols, rows_h, content_rows))
    return frags


# ---------------------------------------------------------------------------
# Scripts frame — centred two-column [ list | detail ] manager.
#
# The launcher does a live scan of `lua/scripts/*.lua` on every frame
# entry and resolves enable state from `runtime/scripts.conf` (falling
# back to the shipped template). The brain-written `scripts.cache` is
# the popup's source — the launcher must never read it here, since it
# runs pre-tmux and must reflect the folder as it is right now.
#
# Toggles mutate the catalog in memory; the deferred write on Back/ESC
# follows the Panes / Spotlights pattern. Changes take effect at the
# next cockpit start — there is no live effect.
#
# Navigation is single-column (no focus zones): the cursor steps
# through script rows and a centred Back row beneath a blank spacer,
# mirroring `options_spotlights` (toggle rows + blank + Back).
# PageUp/PageDown scrolls the detail panel unconditionally — no focus
# state to consult.
# ---------------------------------------------------------------------------
def _enter_scripts_frame():
    """Live-scan lua/scripts/ on push and seat the cursor at row 0.
    `_scripts_dirty` is reset so the previous session's toggles don't
    bleed into this push."""
    global _scripts_catalog, _scripts_dirty
    global _scripts_cursor, _scripts_on_back
    global _scripts_list_scroll, _scripts_detail_scroll
    global _scripts_hover, _scripts_hover_back
    conf = scripts_view.resolve_scripts_conf(
        SCRIPTS_CONF_PATH, SCRIPTS_CONF_TEMPLATE,
    )
    _scripts_catalog       = scripts_view.scan_scripts_dir(
        LUA_SCRIPTS_DIR, conf,
    )
    _scripts_dirty         = False
    _scripts_cursor        = 0
    # When the catalog is empty there is no script row to highlight,
    # so the cursor lands on Back.
    _scripts_on_back       = (len(_scripts_catalog) == 0)
    _scripts_list_scroll   = 0
    _scripts_detail_scroll = 0
    _scripts_hover         = None
    _scripts_hover_back    = False
    _push_frame("scripts")


def _scripts_visible_rows():
    """Visible body rows = terminal rows minus the title block (4) and
    the single footer row anchored at the bottom by `footer_block`."""
    return max(1, _term_rows() - title_block_height(2) - 1)


def _scripts_list_rows():
    """Rows available to the script list — body minus the 2 trailing
    rows the left column reserves for the blank spacer + Back."""
    return max(1, _scripts_visible_rows() - 2)


def _scripts_save_and_pop():
    """Write the in-memory catalog to bridge/runtime/scripts.conf when
    a toggle has happened, then pop. Mirrors the Panes/Spotlights
    deferred-persistence contract — changes take effect next start."""
    global _scripts_dirty
    if _scripts_dirty and _scripts_catalog:
        scripts_view.write_scripts_conf(SCRIPTS_CONF_PATH, _scripts_catalog)
        _scripts_dirty = False
    _pop_frame()


def _scripts_detail_total():
    """Number of detail-panel rows for the latched script (or the
    empty-state pane when the catalog is empty). Used by the page-step
    handler to clamp the detail scroll."""
    if not _scripts_catalog:
        return _scripts_visible_rows()
    cur = _scripts_catalog[max(0, min(_scripts_cursor,
                                      len(_scripts_catalog) - 1))]
    list_w = scripts_view.list_panel_width(_scripts_catalog)
    detail_w = scripts_view.detail_panel_width(_term_cols(), list_w)
    return len(scripts_view.render_detail_lines(cur, detail_w))


def _scripts_move_up():
    """Step the cursor one row up: Back → last script; first script
    → no-op (clamp). Resets the detail scroll on a script change."""
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
    """Step the cursor one row down: last script → Back; Back → no-op
    (clamp). Resets the detail scroll on a script change."""
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
    visible list window. No-op when the cursor sits on Back — the
    list scroll doesn't follow Back, which lives below the spacer."""
    global _scripts_list_scroll
    if _scripts_on_back:
        return
    body = _scripts_list_rows()
    if _scripts_cursor < _scripts_list_scroll:
        _scripts_list_scroll = _scripts_cursor
    elif _scripts_cursor >= _scripts_list_scroll + body:
        _scripts_list_scroll = _scripts_cursor - body + 1


def _scripts_scroll_detail(delta):
    """Shift the detail-panel viewport by `delta` rows, clamping to
    the detail-row total. No-op when content fits in the body."""
    global _scripts_detail_scroll
    total = _scripts_detail_total()
    body  = _scripts_visible_rows()
    mx    = max(0, total - body)
    new   = max(0, min(mx, _scripts_detail_scroll + delta))
    if new != _scripts_detail_scroll:
        _scripts_detail_scroll = new
        if _app:
            _app.invalidate()


def _scripts_toggle_cursor():
    """Flip the latched script's enabled state. Sets `_scripts_dirty`
    so the conf gets written on the next Back/ESC. No-op when the
    cursor is on Back or the catalog is empty."""
    global _scripts_dirty
    n = len(_scripts_catalog)
    if n == 0 or _scripts_on_back:
        return
    idx = max(0, min(n - 1, _scripts_cursor))
    _scripts_catalog[idx].enabled = not _scripts_catalog[idx].enabled
    _scripts_dirty = True
    if _app:
        _app.invalidate()


def _scripts_activate_cursor():
    """Enter/Space dispatch: toggle the latched script, or pop the
    frame when the cursor is on Back."""
    if _scripts_on_back:
        _scripts_save_and_pop()
    else:
        _scripts_toggle_cursor()


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


def _scripts_row_handler(row_idx):
    """Mouse handler for one list row — click jumps the cursor and
    toggles; wheel moves the cursor one row per notch; MOUSE_MOVE
    updates hover."""
    def _h(ev):
        global _scripts_cursor, _scripts_on_back, _scripts_detail_scroll
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _scripts_set_hover(row_idx)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            if row_idx != _scripts_cursor or _scripts_on_back:
                _scripts_cursor = row_idx
                _scripts_on_back = False
                _scripts_detail_scroll = 0
                _scripts_ensure_cursor_visible()
            _scripts_toggle_cursor()
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
    """Mouse handler for the in-column Back row — click pops (saving
    any pending toggles); MOUSE_MOVE highlights Back; wheel is a
    no-op (the detail panel is the wheel-active surface)."""
    def _h(ev):
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            _scripts_set_hover_back(True)
            return None
        if ev.event_type == MouseEventType.MOUSE_DOWN:
            _scripts_save_and_pop()
            return None
        return NotImplemented
    return _h


def _scripts_detail_handler(body_row):
    """Mouse handler over a detail-panel cell — wheel scrolls the
    detail; MOUSE_MOVE clears the list/Back hover state so previously-
    glowing rows stop glowing. Click is a no-op; the detail panel is
    read-only."""
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
    """Pre-rendered fragments for the in-column Back row.

    Layout: `list_w` cells total — outer blank padding + a centred
    `<< Back >>` row (`menu_chrome.menu_row`) + outer blank padding.
    Grammatically identical to the `options_spotlights` Back row:
      cursor on Back        → gold `<< Back >>` (selected)
      mouse hover on Back   → light label (`C_HOVER`)
      otherwise             → inactive label (`C_ITEM`)
    Outer padding carries the same handler so MOUSE_MOVE anywhere on
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
    """Blank spacer row in the left column. Carries no hover handler
    — the row above (last script or scrollbar gutter) and the row
    below (Back) own the hover state on either side."""
    return [("", " " * list_w)]


def _scripts_text():
    """Renderer for the centred two-column Scripts page.

    Title block, body region (shared `scripts_view.render_body`),
    footer hint anchored to the final terminal row by
    `menu_chrome.footer_block`."""
    cols   = _term_cols()
    rows_h = _term_rows()
    body_h = _scripts_visible_rows()

    frags = []
    frags.extend(title_block("─── Scripts ───", cols, blank_above=2))

    list_w = (scripts_view.list_panel_width(_scripts_catalog)
              if _scripts_catalog else scripts_view.MIN_LIST_W)
    extra_left = [
        _scripts_blank_row_frags(list_w),
        _scripts_back_row_frags(list_w),
    ]

    if _scripts_catalog:
        row_h  = _scripts_row_handler
        sb_h   = _scripts_list_sb_handler
        det_h  = _scripts_detail_handler
        det_sb = _scripts_detail_sb_handler
        hover  = _scripts_hover
    else:
        row_h = sb_h = None
        det_h  = _scripts_detail_handler
        det_sb = _scripts_detail_sb_handler
        hover  = None

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
        mode="interactive",
        row_handler=row_h,
        sb_handler=sb_h,
        detail_handler=det_h,
        detail_sb_handler=det_sb,
        hover_row=hover,
        detail_idx=_scripts_cursor,
        extra_left_rows=extra_left,
    ))

    if _scripts_catalog:
        footer = "↑↓ Move · Space Toggle · PgUp/PgDn Scroll · ESC Back"
    else:
        footer = "↑↓ Move · PgUp/PgDn Scroll · ESC Back"
    content_rows = title_block_height(2) + body_h
    frags.extend(footer_block(footer, cols, rows_h, content_rows))
    return frags


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
    """Visible body rows = terminal rows minus the title block (4) and
    the single footer row anchored at the bottom by `footer_block`."""
    return max(1, _term_rows() - title_block_height(2) - 1)


def _about_title_fragments(cols):
    """Title-block fragments for the About frame.

    Matches `menu_chrome.title_block(..., blank_above=2)` in layout (2
    blank rows, title row, trailing blank row) but right-aligns the
    current version (and any "Update available" suffix) on the title
    row, which the generic helper does not support."""
    title = "─── About ───"
    cur   = _cockpit_version
    latest = _latest_release_tag()
    has_update = bool(latest) and _strip_v(latest) != _strip_v(cur)

    if has_update:
        right = f"{cur}  ·  Update available: {latest}"
    else:
        right = cur

    tlen = len(title)
    rlen = len(right)
    tpad = max(0, (cols - tlen) // 2)
    vstart = max(0, cols - 2 - rlen)
    gap = max(1, vstart - tpad - tlen)

    frags = [
        ("", "\n"),                   # blank row 1
        ("", "\n"),                   # blank row 2
        ("", " " * tpad),
        (C_SECTION, title),
        ("", " " * gap),
    ]
    if has_update:
        frags.append((C_BODY, cur))
        frags.append((C_BODY, "  ·  "))
        frags.append((C_ACCENT, f"Update available: {latest}"))
    else:
        frags.append((C_BODY, cur))
    frags.append(("", "\n"))          # end of title row
    frags.append(("", "\n"))          # trailing blank
    return frags


def _about_text():
    """Single-frame renderer for the About page. See `_scripts_text` for
    the title-block / viewport / footer-block contract."""
    global _about_scroll
    _wrap_about_if_needed()
    cols   = _term_cols()
    rows_h = _term_rows()
    width = max(20, min(76, cols - 4))
    pad = max(0, (cols - width) // 2)
    p = " " * pad

    viewport = _about_visible_rows()
    total = len(_about_lines)
    mx = max(0, total - viewport)
    if _about_scroll > mx:
        _about_scroll = mx
    if _about_sb is not None:
        _about_sb.update(total, viewport, height=viewport)
        _about_sb.scroll_to(_about_scroll)

    frags = []
    frags.extend(_about_title_fragments(cols))

    sliced = _about_lines[_about_scroll:_about_scroll + viewport]
    for i in range(viewport):
        if i < len(sliced):
            line = sliced[i]
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
        frags.append(("", "\n"))

    overflow = _about_sb is not None and _about_sb.visible
    footer = "↑↓ Scroll · ESC Back" if overflow else "ESC Back"
    content_rows = title_block_height(2) + viewport
    frags.extend(footer_block(footer, cols, rows_h, content_rows))
    return frags


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
    ("RUN LOG", "run_log"),
    ("STATS",   "statistics"),
    ("RATE",    "rate"),
    ("SAVE",    "save"),
    ("EXPORT",  "export"),
    ("DELETE",  "delete"),
    ("BACK",    "back"),
]
# Button column width: longest label + 1 cell of padding on each side.
_HISTORY_BUTTON_W = max(len(lbl) for lbl, _ in _HISTORY_BUTTONS) + 2
# 2-cell gap between the options column and the runs table (P4.1).
_HISTORY_OPTIONS_GAP = 2


def _history_table_panel_w():
    """Total width of the table content (column widths + per-gap separators)."""
    _, total = _history_table_columns_layout()
    return total


def _history_package_width():
    """Width of the centred package
    `[options | gap | table | scrollbar]` (P4.1 layout).
    The horizontal filter pill row centres on the terminal independently."""
    return (_HISTORY_BUTTON_W
            + _HISTORY_OPTIONS_GAP
            + _history_table_panel_w()
            + 1)


def _history_left_pad():
    """Left padding (cells) that centres the package on the current terminal."""
    return max(0, (_term_cols() - _history_package_width()) // 2)


def _enter_history_frame():
    global _history_filter_items, _history_filter, _history_sort
    global _history_filter_cursor, _history_filter_offset
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
    _history_sort           = ("Date", "desc")
    _history_filter_cursor  = 0
    _history_filter_offset  = 0
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
    """Visible data rows in the table — data-fit, with a floor so the button
    column never clips.

    P4.1 chrome budget: title (4 rows, `title_block_height(2)`) + filter
    pill row (1) + blank (1) + table header (1) + feedback (1) +
    footer (1) = 9 reserved rows; flex_spacer absorbs anything left
    over. The button column has no header in P4.1 — its first row
    aligns with the table header row — so visible must be at least
    `len(_HISTORY_BUTTONS)` for the column to render in full."""
    max_by_terminal = max(1, _term_rows() - 9)
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


def _history_filter_pill_widths():
    return [len(it) + 4 for it in _history_filter_items]


def _history_scroll_filter_to_cursor():
    """Pan _history_filter_offset minimally so the cursor pill is visible."""
    global _history_filter_offset
    _history_filter_offset = history_filter.scroll_to_cursor(
        _history_filter_pill_widths(),
        _term_cols(),
        _history_filter_cursor,
        _history_filter_offset,
    )


def _history_move_filter(delta):
    """Move the filter pill cursor one step left/right in the horizontal
    pill row (P4.1). Clamps at both ends — no wrap. P4.2: scrolls the
    overflow window minimally to keep the cursor pill visible."""
    global _history_filter_cursor
    n = len(_history_filter_items)
    if not n:
        return
    new_cursor = max(0, min(n - 1, _history_filter_cursor + delta))
    if new_cursor == _history_filter_cursor:
        return
    _history_filter_cursor = new_cursor
    _history_scroll_filter_to_cursor()
    _history_set_filter(_history_filter_items[new_cursor])


def _history_jump_filter(target):
    global _history_filter_cursor
    n = len(_history_filter_items)
    if not n:
        return
    new_cursor = max(0, min(n - 1, target))
    _history_filter_cursor = new_cursor
    _history_scroll_filter_to_cursor()
    _history_set_filter(_history_filter_items[new_cursor])


def _history_pan_filter(delta):
    """Pan the filter window by `delta` whole pills without moving the
    cursor (mouse-arrow browsing). Clamps to the valid pan range."""
    global _history_filter_offset
    _history_filter_offset = history_filter.pan(
        _history_filter_pill_widths(),
        _term_cols(),
        _history_filter_offset,
        delta,
    )
    if _app:
        _app.invalidate()


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
        ("RUN LOG", "run_log",    has and bool(summary.has_log)),
        ("STATS",   "statistics", has),
        ("RATE",    "rate",       has),
        ("SAVE",    "save",       has and not summary.saved),
        ("EXPORT",  "export",     has and bool(summary.has_log)),
        ("DELETE",  "delete",     has),
        ("BACK",    "back",       True),
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
    clear_hover = _hover_at(None, None)
    return list(title_block(
        "─── History ───", cols, blank_above=2, mouse_handler=clear_hover,
    ))


def _history_footer_text():
    cols = _term_cols()
    clear_hover = _hover_at(None, None)
    footer = "↑↓ Navigate · Tab/←→ Cycle · Enter Select · ESC Back"
    pad = " " * max(0, (cols - len(footer)) // 2)
    return [("", pad, clear_hover), (C_HINT, footer, clear_hover)]


# --- Filter pill row render (horizontal, centred under the title) ---------
def _history_filter_pills_text():
    """Render the horizontal filter pill row.

    One pill per filter item (`All` first, then characters alphabetically).
    Visual grammar matches the table cursor row and the button columns:
    cursor + filter row focused → `C_BUTTON_ACTIVE_FOCUSED` (gold);
    cursor + focus elsewhere → `C_BUTTON_ACTIVE_UNFOCUSED` (grey,
    ≡ `C_SELECTED`); hover → `C_HOVER`; otherwise `C_ITEM`. Selecting a
    pill applies its filter immediately.

    P4.2 horizontal scroll: when the pills' total width exceeds the
    terminal width, a window of whole pills is rendered with 2-cell edge
    slots reserved for `‹` / `›` arrows (painted in C_BODY). The
    arrow glyphs appear only on the side with hidden pills; the slot
    stays reserved either way so pill positions don't jump. Clicking an
    arrow pans the window one pill without moving the cursor; the
    cursor's keyboard moves pan the window minimally."""
    cols  = _term_cols()
    items = _history_filter_items
    clear_hover = _hover_at(None, None)
    if not items:
        return [("", "", clear_hover)]

    pill_widths = _history_filter_pill_widths()
    start, end, left_arrow, right_arrow, overflows = history_filter.compute_window(
        pill_widths, cols, _history_filter_offset,
    )

    filter_focused = (_history_focused == 0)
    hover_panel, hover_row = _history_hover
    frags = []

    if overflows:
        # Edge slot (2 cells): "‹ " when there are hidden pills to the
        # left, "  " otherwise. Click on the arrow pans one pill left.
        def _click_left(ev):
            if ev.event_type == MouseEventType.MOUSE_DOWN and left_arrow:
                _history_set_focus(0)
                _history_pan_filter(-1)
                return None
            return NotImplemented
        left_glyph = "‹ " if left_arrow else "  "
        frags.append((C_BODY, left_glyph,
                      _hover_at(None, None, on_event=_click_left)))
    else:
        total_w = history_filter.total_row_width(pill_widths)
        pad_left = max(0, (cols - total_w) // 2)
        if pad_left:
            frags.append(("", " " * pad_left, clear_hover))

    used = 0
    for vi, i in enumerate(range(start, end)):
        label = items[i]
        if vi > 0:
            frags.append(("", "  ", clear_hover))
            used += 2

        is_cursor = (i == _history_filter_cursor)
        is_hover  = (hover_panel == 0 and hover_row == i and not is_cursor)
        if is_cursor and filter_focused:
            style = C_BUTTON_ACTIVE_FOCUSED
        elif is_cursor:
            style = C_BUTTON_ACTIVE_UNFOCUSED
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

        pill_text = "  " + label + "  "
        frags.append((style, pill_text, _hover_at(0, i, on_event=_click)))
        used += pill_widths[i]

    if overflows:
        usable = max(0, cols - 2 * history_filter.EDGE_SLOT_W)
        trailing = max(0, usable - used)
        if trailing:
            frags.append(("", " " * trailing, clear_hover))

        def _click_right(ev):
            if ev.event_type == MouseEventType.MOUSE_DOWN and right_arrow:
                _history_set_focus(0)
                _history_pan_filter(1)
                return None
            return NotImplemented
        right_glyph = " ›" if right_arrow else "  "
        frags.append((C_BODY, right_glyph,
                      _hover_at(None, None, on_event=_click_right)))
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

    # Header row — always muted grey (C_HINT), regardless of focus.
    # The sort indicator glyph carries the active-column signal.
    header_style = C_HINT
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

        if is_cursor and table_focused:
            row_bg = C_BUTTON_ACTIVE_FOCUSED
        elif is_cursor:
            row_bg = C_BUTTON_ACTIVE_UNFOCUSED
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


# --- Options widget render (right column of the runs-table package) -------
def _history_options_text():
    """Render the button column: stacked `button_fragment` cells, no header.

    The first button row sits at row 0 of the VSplit so it top-aligns with
    the runs-table header row. State mapping per ADR 0085's button-cell
    grammar: cursor + options focused → `selected_focused` (gold bg);
    cursor + options unfocused → `selected_unfocused` (grey bg); hover on
    a non-cursor enabled button → `hover`; disabled → `disabled`; else
    `inactive`. Trailing blank rows pad the column down to the table_row
    VSplit height."""
    inner_w = _HISTORY_BUTTON_W
    actions = _history_menu_actions()
    options_focused = (_history_focused == 2)
    hover_panel, hover_row = _history_hover
    clear_hover = _hover_at(None, None)

    frags = []

    for i, (label, _action, enabled) in enumerate(actions):
        is_cursor = (i == _history_menu_cursor)
        is_hover  = (hover_panel == 2 and hover_row == i and enabled
                     and not is_cursor)
        if not enabled:
            state = "disabled"
        elif is_cursor and options_focused:
            state = "selected_focused"
        elif is_cursor:
            state = "selected_unfocused"
        elif is_hover:
            state = "hover"
        else:
            state = "inactive"
        style, cell_text = button_fragment(label, inner_w, state)

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

    # Pad trailing blank lines so the column fills the table_row height
    # (table_window_h = visible + 1 = header row + data rows).
    used = len(actions)
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
    frags.append((C_SECTION, title))
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

    footer = "0-5 Set · ←→ Adjust · Enter Save · ESC Cancel"
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
    frags.append((C_SECTION, title))
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
    footer = "Y to confirm · any other key to cancel"
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
# Fixed rows around the kills/pvps data rows in _history_detail_text:
# 1 leading blank + 1 header + 1 blank + 5 A/A (title+div+3) + 1 blank
# + 3 KP fixed (title+div+total) + 1 blank + 7 sparklines + 1 blank
# + 3 xp-linjal + 1 blank + 1 footer = 26. The footer is bottom-pinned
# via slack blank rows inserted between the xp-linjal and the footer
# (see _history_detail_text); this constant is the row budget the cap
# subtracts from _term_rows() so data_height fills the remaining space.
_HD_STATS_FIXED_LINES       = 26


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
    l_style = C_CURSOR_CELL if left_active  else C_SECTION
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
    k_style  = C_CURSOR_CELL if k_active else C_SECTION
    p_style  = C_CURSOR_CELL if p_active else C_SECTION

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
        title = "Session details"
        frags.append(("", "\n\n", clear))
        frags.append(("", _pad_centre(title, cols), clear))
        frags.append((_S_HINT, title, clear))
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
    title_text    = (f"◆ Session details  —  {summary.character}"
                     f"  ·  {date_text}  ·  {duration_text}")

    frags.append(("", "\n", clear))

    title_pad = max(0, (cols - len(title_text)) // 2)
    frags.append(("", " " * title_pad, clear))
    frags.append((_S_HINT, title_text, clear))
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

    # Absorb leftover terminal rows between the xp-linjal and the footer so
    # the footer pins to the final terminal row regardless of data_height —
    # matching the bottom-anchored footer contract of every other launcher
    # frame.
    slack = max(0, _term_rows() - _HD_STATS_FIXED_LINES - data_height)
    for _ in range(slack):
        body.append(("", "\n"))

    frags.extend(_hover_clear_frags(body))

    # --- Footer -----------------------------------------------------------
    footer = "ESC Back · ↑↓ Scroll · Tab/Shift+Tab Switch table"
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


def _banner_start_tick_task():
    """Kick off the main-page banner twinkle loop. Idempotent: a second
    call is a no-op once the task is running."""
    global _banner_tick_task
    if _banner_tick_task is not None:
        return
    if _app_loop is None:
        return
    _banner_tick_task = _app_loop.create_task(_banner_tick_loop())


async def _banner_tick_loop():
    """Persistent redraw loop for the main-page starfield. Unlike the
    credits loop, main is the home frame and is re-entered repeatedly,
    so this task never self-terminates — it just skips the invalidate
    while a different frame is showing. Invalidating unconditionally at
    _BANNER_TICK_HZ on main matches the _credits_tick_loop precedent."""
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


def _credits_brightness_to_hex(b: float, base_hex: str | None = None) -> str:
    """Interpolate per RGB channel between `base_hex` (brightness 0) and
    white (brightness 1). When `base_hex` is None, defaults to #000000 —
    producing the original greyscale ramp. Used both for the credits row
    fade and (implicitly) for the empty-canvas fallback."""
    base = base_hex or "#000000"
    return _interpolate_hex(base, "#ffffff", b)


def _interpolate_hex(base_hex: str, target_hex: str, t: float) -> str:
    """Per-channel linear interpolation between two `#rrggbb` colours.
    `t=0` returns base, `t=1` returns target; intermediate values are
    clamped to the byte range. Foundation for `_credits_brightness_to_hex`
    (target = white) and the editor-mode focused current-line band
    (target = black or white depending on terminal-bg brightness)."""
    br = int(base_hex[1:3], 16)
    bg = int(base_hex[3:5], 16)
    bb = int(base_hex[5:7], 16)
    tr = int(target_hex[1:3], 16)
    tg = int(target_hex[3:5], 16)
    tb = int(target_hex[5:7], 16)
    r  = max(0, min(255, int(round(br + (tr - br) * t))))
    g  = max(0, min(255, int(round(bg + (tg - bg) * t))))
    bl = max(0, min(255, int(round(bb + (tb - bb) * t))))
    return f"#{r:02x}{g:02x}{bl:02x}"


def _credits_text():
    """Build the credits scroll as a fragment list. One fragment per
    terminal row: a centred credit line, with brightness from the fade-band
    formula. When `_terminal_bg` is known, the ramp interpolates between
    the host terminal background (brightness 0) and white (brightness 1),
    and the explicit `bg:#000000` is dropped so the terminal background
    shows through — text fades cleanly to invisible at the bands instead
    of stranding dark grey on a tinted canvas. When `_terminal_bg` is
    None, the original black-canvas + greyscale-ramp behaviour is preserved."""
    bg_suffix = "" if _terminal_bg else " bg:#000000"
    if not _credits_lines or _credits_term_rows <= 0:
        empty_style = "" if _terminal_bg else "bg:#000000"
        return [(empty_style, " " * max(1, _term_cols()))]
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
        style = f"fg:{_credits_brightness_to_hex(brightness, _terminal_bg)}{bg_suffix}"
        frags.append((style, line))
        if tr < n - 1:
            frags.append(("", "\n"))
    return frags


def _credits_hint_text():
    """Top-right exit hint, rendered as a Float above the scroll. Dim grey,
    unaffected by the fade band. Drops the explicit `bg:#000000` when
    `_terminal_bg` is known so the terminal default shows through."""
    if _terminal_bg:
        return [("fg:#555555", "Escape to exit")]
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

    hint = "ESC Back"

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

    hint = "ESC Back · ←→ Prev/next"
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

    frame = _spotlight_frame_style
    frags = []
    # Top frame row: █ + ▀ × inner + █
    frags.append((frame, "█" + ("▀" * inner) + "█"))
    frags.append(("", "\n"))
    for kind, payload in interior_rows:
        frags.append((frame, "▌"))
        if kind == "nav":
            frags.extend(payload)
        else:
            frags.extend(_log_spotlight_box_row(payload, kind, inner))
        frags.append((frame, "▐"))
        frags.append(("", "\n"))
    # Bottom frame row: █ + ▄ × inner + █
    frags.append((frame, "█" + ("▄" * inner) + "█"))
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
    frame = _spotlight_frame_style
    frags = []
    frags.append((frame, "█" + ("▀" * inner) + "█"))
    frags.append(("", "\n"))
    for i in range(_SPOTLIGHT_BOX_H - 2):
        frags.append((frame, "▌"))
        frags.append((C_SPOTLIGHT_BOX_BG, " " * inner))
        frags.append((frame, "▐"))
        frags.append(("", "\n"))
    frags.append((frame, "█" + ("▄" * inner) + "█"))
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

    # Modal dialog: vertically centred via `_centered` (no `footer_block`
    # anchoring) — there is no persistent shortcut row. The title still
    # adopts `C_SECTION` via `title_block`.
    frags = []
    frags.extend(title_block(title, cols, blank_above=2))
    frags.append(("", "\n"))
    for line in _update_output.splitlines() or [""]:
        frags.append(("", _pad_centre(line, cols)))
        frags.append((body_style, line))
        frags.append(("", "\n"))
    frags.append(("", "\n"))
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


@kb.add("c-c", filter=~_in_frame("profile_editor"))
def _kb_ctrl_c(event):
    # `c-c` quits everywhere EXCEPT the profile editor, where the same
    # key copies text. ESC remains the documented editor exit; removing
    # the quit footgun here protects users from a stray ctrl-C wiping a
    # session of unsaved edits.
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


# Profile frame
@kb.add("tab", filter=_in_frame("profile"))
def _kb_profile_tab(event):
    _profile_cycle_focus(1)


@kb.add("s-tab", filter=_in_frame("profile"))
def _kb_profile_stab(event):
    _profile_cycle_focus(-1)


@kb.add("right", filter=_in_frame("profile"))
def _kb_profile_right(event):
    # Spatial: options (left) → table (right). No-op on table.
    if _profile_focused == 1:
        _profile_set_focus(0)


@kb.add("left", filter=_in_frame("profile"))
def _kb_profile_left(event):
    # Spatial: table (right) → options (left). No-op on options.
    if _profile_focused == 0:
        _profile_set_focus(1)


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


# Options — Panes submenu (colour grid). Eight navigable rows; ←/→ moves
# the column only on grid rows, and the column persists across grid rows.
@kb.add("up", filter=_in_frame("options_panes"))
def _kb_optp_up(event):
    if _options_panes_row > 0:
        _set_panes_cursor(_options_panes_row - 1)


@kb.add("down", filter=_in_frame("options_panes"))
def _kb_optp_down(event):
    if _options_panes_row < _PANES_LAST_ROW:
        _set_panes_cursor(_options_panes_row + 1)


@kb.add("left", filter=_in_frame("options_panes"))
def _kb_optp_left(event):
    if _options_panes_row < _PANES_GRID_ROWS and _options_panes_col > 0:
        _set_panes_cursor(_options_panes_row, _options_panes_col - 1)


@kb.add("right", filter=_in_frame("options_panes"))
def _kb_optp_right(event):
    if (_options_panes_row < _PANES_GRID_ROWS
            and _options_panes_col < _PANES_LAST_COL):
        _set_panes_cursor(_options_panes_row, _options_panes_col + 1)


@kb.add("enter", filter=_in_frame("options_panes"))
@kb.add(" ",     filter=_in_frame("options_panes"))
def _kb_optp_select(event):
    r = _options_panes_row
    if r < _PANES_GRID_ROWS:
        _apply_panes_grid_toggle(r, _options_panes_col)
    elif r == _PANES_HEADERS_ROW:
        _toggle_pane_headers()
    elif r == _PANES_BACK_ROW:
        _options_panes_back()


@kb.add("escape", filter=_in_frame("options_panes"), eager=True)
def _kb_optp_escape(event):
    _options_panes_back()


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


# Options — Terminal submenu. ↑↓ navigate the row catalog (Font / Size
# / Apply / Back); ←→ on the Size row drives the stepper; Enter / Space
# activates the cursor row; ESC discards pending edits and pops.
@kb.add("up", filter=_in_frame("options_terminal"))
def _kb_optt_up(event):
    _options_terminal_move(-1)


@kb.add("down", filter=_in_frame("options_terminal"))
def _kb_optt_down(event):
    _options_terminal_move(1)


@kb.add("left", filter=_in_frame("options_terminal"))
def _kb_optt_left(event):
    _options_terminal_arrow_step(-1)


@kb.add("right", filter=_in_frame("options_terminal"))
def _kb_optt_right(event):
    _options_terminal_arrow_step(1)


@kb.add("enter", filter=_in_frame("options_terminal"))
@kb.add(" ",     filter=_in_frame("options_terminal"))
def _kb_optt_select(event):
    _options_terminal_activate()


@kb.add("escape", filter=_in_frame("options_terminal"), eager=True)
def _kb_optt_escape(event):
    _options_terminal_back()


# Terminal — font picker. ↑↓ moves with wrap-around; Enter / Space
# commits; ESC pops without committing.
@kb.add("up", filter=_in_frame("terminal_font_picker"))
def _kb_tfp_up(event):
    _terminal_font_picker_move(-1)


@kb.add("down", filter=_in_frame("terminal_font_picker"))
def _kb_tfp_down(event):
    _terminal_font_picker_move(1)


@kb.add("pageup", filter=_in_frame("terminal_font_picker"))
def _kb_tfp_pgup(event):
    _terminal_font_picker_move(-_terminal_font_picker_visible_rows())


@kb.add("pagedown", filter=_in_frame("terminal_font_picker"))
def _kb_tfp_pgdn(event):
    _terminal_font_picker_move(_terminal_font_picker_visible_rows())


@kb.add("enter", filter=_in_frame("terminal_font_picker"))
@kb.add(" ",     filter=_in_frame("terminal_font_picker"))
def _kb_tfp_select(event):
    _terminal_font_picker_select()


@kb.add("escape", filter=_in_frame("terminal_font_picker"), eager=True)
def _kb_tfp_escape(event):
    _terminal_font_picker_back()


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


# Spotlights — empty-state placeholder (any key returns)
@kb.add("escape", filter=_in_frame("spotlights_empty"), eager=True)
def _kb_spemp_escape(event):
    _pop_frame()


@kb.add("<any>", filter=_in_frame("spotlights_empty"))
def _kb_spemp_any(event):
    _pop_frame()


# Scripts — single-column navigation. Up/Down steps the cursor through
# script rows and Back (skipping the blank spacer). PageUp/PageDown
# scrolls the detail panel unconditionally — there is no focus model
# to consult. Space / Enter on a script row toggles it; on Back, pops
# the frame (saving any pending toggles). ESC is the same exit.
@kb.add("up", filter=_in_frame("scripts"))
def _kb_scr_up(event):
    _scripts_move_up()


@kb.add("down", filter=_in_frame("scripts"))
def _kb_scr_down(event):
    _scripts_move_down()


@kb.add("pageup", filter=_in_frame("scripts"))
def _kb_scr_pgup(event):
    _scripts_scroll_detail(-_scripts_visible_rows())


@kb.add("pagedown", filter=_in_frame("scripts"))
def _kb_scr_pgdn(event):
    _scripts_scroll_detail(_scripts_visible_rows())


@kb.add(" ", filter=_in_frame("scripts"))
@kb.add("enter", filter=_in_frame("scripts"))
def _kb_scr_activate(event):
    _scripts_activate_cursor()


@kb.add("escape", filter=_in_frame("scripts"), eager=True)
def _kb_scr_escape(event):
    _scripts_save_and_pop()


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
    # Spatial: options is left of the table. On the filter pill row it
    # moves the pill cursor; on the table it focuses options; on options
    # it's a no-op.
    if _history_focused == 0:
        _history_move_filter(-1)
    elif _history_focused == 1:
        _history_set_focus(2)


@kb.add("right", filter=_in_frame("history"))
def _kb_hist_right(event):
    # Spatial: options(2) → table(1); on the table it's a no-op; on the
    # filter pill row it moves the pill cursor.
    if _history_focused == 0:
        _history_move_filter(1)
    elif _history_focused == 2:
        _history_set_focus(1)


@kb.add("up", filter=_in_frame("history"))
def _kb_hist_up(event):
    # Filter sits above both zones. ↑ at row 0 of the table and ↑ on the
    # topmost enabled button of the options column both fall through to
    # the filter pill row. Within the filter row ↑ is a no-op — pills
    # are arranged horizontally.
    global _history_menu_cursor
    if _history_focused == 1:
        if _history_table_cursor == 0:
            _history_set_focus(0)
        else:
            _history_move_table(-1)
    elif _history_focused == 2:
        enabled = _history_menu_enabled_indices()
        if enabled and _history_menu_cursor == enabled[0]:
            _history_set_focus(0)
        else:
            _history_menu_move(-1)


@kb.add("down", filter=_in_frame("history"))
def _kb_hist_down(event):
    # ↓ on the filter row drops into the options column at the topmost
    # enabled button (RUN LOG when it's enabled).
    global _history_menu_cursor
    if _history_focused == 0:
        enabled = _history_menu_enabled_indices()
        if enabled:
            _history_menu_cursor = enabled[0]
        _history_set_focus(2)
    elif _history_focused == 1:
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


def _build_history():
    """Build the History frame (P4):
        title · [filter | gap | table + sb | gap | options] · feedback · flex · footer.
    Filter sidebar is on the left, the runs table sits in the centre with
    its scrollbar, and the button column stays on the right (header
    dropped). Returns the three focusable windows
    (filter / table / options) plus the frame."""
    title  = Window(content=FormattedTextControl(text=_history_title_text, focusable=False),
                    height=title_block_height(2),
                    wrap_lines=False, always_hide_cursor=True)
    footer = Window(content=FormattedTextControl(text=_history_footer_text, focusable=False),
                    height=1, wrap_lines=False, always_hide_cursor=True)

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

    # Horizontal filter pill row, centred on the terminal. Single
    # focusable Window so the filter zone retains its own focus target
    # (focus-on-push, ADR 0066). A blank row separates the pill row from
    # the table package below.
    filter_win = Window(
        content=FormattedTextControl(text=_history_filter_pills_text,
                                     focusable=True),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )
    blank_below_filter = Window(
        content=FormattedTextControl(text=_make_filler_text(1), focusable=False),
        height=1, wrap_lines=False, always_hide_cursor=True,
    )

    # Centred package (P4.1): [left_spacer | options | gap | table | sb |
    # right_spacer] — options column left, table right, no inter-pane gap
    # after the scrollbar.
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
    options_table_gap = Window(
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
        [table_left_spacer, options_win, options_table_gap, table_win,
         table_sb_win, table_right_spacer],
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
        filter_win,
        blank_below_filter,
        table_row,
        feedback_win,
    ])
    # flex_spacer absorbs leftover terminal rows so the footer sits on the
    # final terminal row (ADR 0085 footer-anchoring contract).
    flex_spacer = Window()
    return (filter_win, table_win, options_win,
            HSplit([title, body, flex_spacer, footer]))


def _build_profile():
    """Build the Profile frame (P4):
        title · [options | gap | table + scrollbar] · feedback · flex · footer.
    Button column is left, table is right; the active profile's ✓ paints
    green (`C_OK`) and the focused cursor row paints gold
    (`C_BUTTON_ACTIVE_FOCUSED`). Returns the two focusable windows
    (table / options) plus the frame."""
    title  = Window(content=FormattedTextControl(text=_profile_title_text, focusable=False),
                    height=title_block_height(2),
                    wrap_lines=False, always_hide_cursor=True)
    footer = Window(content=FormattedTextControl(text=_profile_footer_text, focusable=False),
                    height=1, wrap_lines=False, always_hide_cursor=True)

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
        [table_left_spacer, options_win, gap_win, table_win, table_sb_win,
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
    # flex_spacer absorbs leftover terminal rows so the footer sits on the
    # final terminal row (ADR 0085 footer-anchoring contract).
    flex_spacer = Window()
    return (table_win, options_win,
            HSplit([title, body, flex_spacer, footer]))


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
    global _options_window, _options_panes_window
    global _options_connection_window, _options_connection_custom_window
    global _options_spotlights_window
    global _options_terminal_window
    global _terminal_font_picker_window
    global _spotlights_empty_window
    global _scripts_window, _about_window
    global _update_running_window, _update_result_window
    global _too_small_window
    global _history_filter_window, _history_table_window, _history_options_window
    global _history_detail_window, _history_rate_window
    global _history_delete_confirm_window
    global _log_view_window
    global _credits_window

    os.chdir(PROJECT_DIR)
    _one_shot_migrations()
    _load_conf()
    # Probe host-terminal background via OSC 11 while the tty is still in
    # cooked mode and the launcher owns it. Must happen before prompt_toolkit
    # takes over. Bounded ~0.25 s; never wedges startup. Reads
    # `terminal_bg_fallback` from `_conf`, so must run after `_load_conf()`.
    _probe_and_persist_terminal_bg()
    try:
        run_retention.prune_expired_runs()
    except Exception:
        pass
    _cockpit_version = _read_version_file()
    _spawn_version_check()
    _load_random_quote()
    _cache_mtime = _cache_mtime_now()
    _rebuild_main_items(preserve_label=False)

    # Post-relaunch resume: when the foot supervisor relaunches us after
    # the user hit Apply, the previous launcher dropped
    # `.launcher_resume` so this fresh launcher can land back on the
    # frame it left from. One-shot (consume deletes the file) and only
    # honoured under the managed-foot deployment; everything else
    # starts on main.
    if _FOOT_MANAGED:
        _resume = _consume_launcher_resume()
        if _resume is not None:
            _resume_frame, _resume_cursor = _resume
            if _resume_frame == "options_terminal":
                # Build the natural [main, options, options_terminal]
                # stack so ESC unwinds back through Options as if the
                # user had walked there manually.
                _enter_options_frame()
                _enter_options_terminal_frame(restore_cursor=_resume_cursor)

    _main_window,                  main_frame                = _build_simple(_main_text)
    (_profile_table_window, _profile_options_window,
     profile_frame)                                          = _build_profile()
    _profile_rename_window,        profile_rename_frame      = _build_simple(_profile_rename_text)
    _profile_create_name_window,   pcn_frame                 = _build_simple(_profile_create_name_text)
    _profile_create_choose_window, pcc_frame                 = _build_simple(_profile_create_choose_text)
    _profile_create_copy_window,   pcp_frame                 = _build_simple(_profile_create_copy_text)
    _profile_delete_window,        pd_frame                  = _build_simple(_profile_delete_text)
    # Profile editor frames: DynamicContainer since editor is recreated each time.
    profile_editor_frame = DynamicContainer(
        lambda: _profile_editor_instance.container()
        if _profile_editor_instance is not None else Window())
    peditor_keybind_frame = DynamicContainer(
        lambda: _profile_editor_instance.overlay_container()
        if _profile_editor_instance is not None else Window())
    _options_window,                    options_frame                  = _build_simple(_options_text)
    _options_panes_window,              options_panes_frame            = _build_simple(_options_panes_text)
    _options_connection_window,         options_connection_frame       = _build_simple(_options_connection_text)
    _options_connection_custom_window,  options_connection_custom_frame = _build_simple(_options_connection_custom_text)
    _options_spotlights_window,         options_spotlights_frame       = _build_simple(_options_spotlights_text)
    _options_terminal_window,           options_terminal_frame         = _build_simple(_options_terminal_text)
    _terminal_font_picker_window,       terminal_font_picker_frame     = _build_simple(_terminal_font_picker_text)
    _spotlights_empty_window,           spotlights_empty_frame         = _build_simple(_spotlights_empty_text)
    _scripts_window,               scripts_frame             = _build_simple(_scripts_text)
    _about_window,                 about_frame               = _build_simple(_about_text)
    _update_running_window,        update_running_frame      = _build_simple(_update_running_text)
    _update_result_window,         update_result_frame       = _build_simple(_update_result_text)
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

    # Credits frame — scrolling end-of-reel chronicle. Canvas matches the
    # host terminal background when OSC 11 detection succeeded, otherwise
    # falls back to an explicit black canvas. Mouse is intentionally not
    # bound (no handler on the control); only ESC exits early. The dim
    # "Escape to exit" hint floats top-right.
    _credits_window = Window(
        content=FormattedTextControl(text=_credits_text, focusable=True),
        wrap_lines=False,
        always_hide_cursor=True,
        style="" if _terminal_bg else "bg:#000000",
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
        "profile_editor_macro_keybind": peditor_keybind_frame,
        "options":                    options_frame,
        "options_panes":              options_panes_frame,
        "options_connection":         options_connection_frame,
        "options_connection_custom":  options_connection_custom_frame,
        "options_spotlights":         options_spotlights_frame,
        "options_terminal":           options_terminal_frame,
        "terminal_font_picker":       terminal_font_picker_frame,
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
    }

    def _root():
        if not _size_ok():
            return too_small_frame
        return frames.get(_current_frame, main_frame)

    layout = Layout(DynamicContainer(_root))

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
        _banner_start_tick_task()
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
