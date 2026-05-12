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
import json
import os
import shutil
import signal
import subprocess
import sys
import time

import run_stats
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
STATUS_STATE_PATH     = os.path.join(RUNTIME_DIR, "status.state")
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
# Statistics-frame palette (mockup-driven; isolated from the other frames so
# the main/options/scripts palettes are unaffected).
# ---------------------------------------------------------------------------
C_HEADER   = "bold fg:#ffd060"  # gold ◆ STATISTICS banner only
C_SECTION  = "bold fg:#008787"  # muted cyan section titles (KILLS, PvPs, …, XP/h, TP/h)
C_DIVIDER  = C_HINT             # muted gray section rules and chart frame strokes
_S_VALUE   = "fg:#ffffff"       # data values, names
_S_LABEL   = "fg:#909090"       # axis numbers, column headers
_S_GAINED  = "fg:#6fe060"       # XP bar gained portion, XP/h bars, XP-linjal label
_S_LOSS    = "fg:#e03c3c"       # XP-linjal loss band + bracket label (negative session gain)
_S_TP_BAR  = "fg:#ffc847"       # TP/h bars
_S_TRACK   = "fg:#1f1f1f"       # scrollbar track, untraversed bar (full-block █)
_S_MARKER  = "fg:#1f1f1f bg:#1f1f1f"  # XP-linjal ▌▐ markers — bg matches row-2 fill
_S_THUMB   = "fg:#707070"       # scrollbar thumb (mid grey)
_S_TOTAL   = "bold fg:#b0b0b0"  # sticky Total rows
_S_ARROW   = "fg:#b0b0b0"       # arrow brackets around XP-gain label
_S_HINT    = "fg:#5c5c5c"       # footer hints
_S_PVP     = "fg:#ff5f5f"       # ⚔ glyph before PvPs data rows
_S_ALLY    = "fg:#00d7d7"       # ♦ glyph before ALLIES data rows
_S_STAR    = "fg:#ffd060"       # ★ glyph before ACHIEVEMENTS data rows

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
_app                 = None
_main_window         = None     # set in main(); referenced for focus
_options_window      = None     # set in main(); referenced for render_info / focus
_scripts_window      = None     # set in main(); referenced for render_info / focus
_statistics_window   = None     # set in main(); referenced for focus
_exit_confirm_window = None     # set in main(); referenced for focus
_stats_data       = None        # cached run_stats.RunStats for statistics frame
_stats_status     = None        # cached status.state dict (xp_progress source)
_stats_char       = None        # character name driving the statistics view
_stats_kills_sort  = ("XP tot", "desc")
_stats_pkills_sort = ("XP", "desc")
_stats_focused     = 0          # 0=Kills, 1=PKills, 2=Allies, 3=Achievements
_stats_run_ended   = False
_stats_tick_task   = None       # asyncio.Task for the 60 s refresh loop
_kills_sb          = None       # Scrollbar instances, created on first push
_pkills_sb         = None
_allies_sb         = None
_achievements_sb   = None


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
    win = {
        "main":         _main_window,
        "options":      _options_window,
        "scripts":      _scripts_window,
        "statistics":   _statistics_window,
        "exit_confirm": _exit_confirm_window,
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
    items = []
    if _is_connected():
        items.append(("Continue", "continue"))
    items.append(("Reconnect",    "reconnect"))
    items.append(("Save profile", "save"))
    if _statistics_character() is not None:
        items.append(("Statistics", "statistics"))
    items.append(("Options",      "options"))
    items.append(("Scripts",      "scripts"))
    items.append(("Exit session", "exit"))
    return items


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
    elif action == "statistics":
        char = _statistics_character()
        if char:
            _load_statistics(char)
            _push_frame("statistics")
            _start_stats_tick()
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
    if stats.min_level is None or stats.current_level is None:
        return
    min_lv = max(1, stats.min_level)
    cur_lv = stats.current_level
    hi_lv  = cur_lv + 1
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


def _make_focus_handler(idx):
    def _handler(ev):
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return
        global _stats_focused
        _stats_focused = idx
        if _app:
            _app.invalidate()
    return _handler


def _scrollbar_row_cells(sb, table_idx):
    """Render `sb` and return one fragment per row (newlines stripped).

    Wraps each cell handler so a click also moves keyboard focus to this table.
    """
    out = []
    for f in sb.render():
        if len(f) >= 2 and f[1] == "\n":
            continue
        if len(f) == 3:
            style, text, orig = f

            def _wrapped(ev, orig=orig, idx=table_idx):
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
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return
        global _stats_kills_sort, _stats_focused
        _stats_focused = 0
        _stats_kills_sort = _toggle_sort(_stats_kills_sort, col)
        _kills_sb.scroll_to(0)
        if _app:
            _app.invalidate()
    return _h


def _make_pkill_header_handler(col):
    def _h(ev):
        if ev.event_type != MouseEventType.MOUSE_DOWN:
            return
        global _stats_pkills_sort, _stats_focused
        _stats_focused = 1
        _stats_pkills_sort = _toggle_sort(_stats_pkills_sort, col)
        _pkills_sb.scroll_to(0)
        if _app:
            _app.invalidate()
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
    l_style = C_ACTIVE if left_active else C_SECTION
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
    k_style  = C_ACTIVE if k_active else C_SECTION
    p_style  = C_ACTIVE if p_active else C_SECTION

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

    cur_lv = stats.current_level
    if cur_lv is None:
        cur_lv = status.get("level", "?")
    base_header = (
        f"◆ STATISTICS  —  {_stats_char}  "
        f"·  Lvl {cur_lv}  ·  Run {_fmt_duration(stats.duration_seconds)}"
    )
    suffix = " · Run ended" if _stats_run_ended else ""
    frags.append(("", "\n"))
    frags.append(("", _pad_centre(base_header + suffix, cols)))
    frags.append((C_HEADER, base_header))
    if suffix:
        frags.append((_S_HINT, suffix))
    frags.append(("", "\n\n"))

    _append_allies_achievements(frags, stats, cols)
    frags.append(("", "\n"))

    _append_kills_pvps(frags, stats, cols, visible)
    frags.append(("", "\n"))

    _append_sparklines(frags, stats, cols)
    frags.append(("", "\n"))

    _append_xp_linjalen(frags, stats, cols)

    footer = "ESC Back     ↑↓ Scroll     Tab/Shift+Tab Switch table"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((_S_HINT, footer))

    return frags


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
    global _exit_confirm_window
    _exit_confirm_window = Window(
        content=FormattedTextControl(text=_exit_confirm_text, focusable=True),
        wrap_lines=False,
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
        "statistics":   _build_statistics_container(),
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
