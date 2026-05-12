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
C_GAINED  = "fg:#6fe060"        # statistics: traversed XP bar / sparkline bars

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
_stats_data       = None        # cached run_stats.RunStats for statistics frame
_stats_status     = None        # cached status.state dict (xp_progress source)
_stats_char       = None        # character name driving the statistics view


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
# Statistics frame (static layout in this commit; sort/focus/scroll lands next)
# ---------------------------------------------------------------------------
_STAT_BAR_WIDTH     = 84
_STAT_SPARK_WIDTH   = 30      # bucket columns per sparkline
_STAT_Y_LABEL_W     = 5       # right-aligned y-axis label width
_STAT_TABLE_LEFT_W  = 40
_STAT_TABLE_RIGHT_W = 40
_STAT_TABLE_GAP     = "  "
_STAT_BLOCKS        = "▁▂▃▄▅▆▇█"


def _load_statistics(character):
    global _stats_data, _stats_status, _stats_char
    _stats_char   = character
    _stats_status = _read_status_state()
    try:
        _stats_data = run_stats.load_current_run_stats(character)
    except Exception:
        _stats_data = None


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


def _append_xp_bar(frags, stats, status, cols):
    bar_w = _STAT_BAR_WIDTH
    if stats.min_level is None or stats.current_level is None:
        return
    min_lv = stats.min_level
    cur_lv = stats.current_level
    hi_lv  = cur_lv + 2
    span   = max(1, hi_lv - min_lv)

    try:
        xp_progress = float(status.get("xp_progress") or 0.0)
    except (TypeError, ValueError):
        xp_progress = 0.0
    xp_progress = max(0.0, min(0.999, xp_progress))

    pos_levels = (cur_lv - min_lv) + xp_progress
    filled = max(0, min(bar_w, int(round(pos_levels / span * bar_w))))

    margin = max(0, (cols - bar_w) // 2)
    pad    = " " * margin

    gained_str = f"{stats.xp_gained:,} XP gained"
    frags.append(("", _pad_centre(gained_str, cols)))
    frags.append((C_ACCENT, gained_str))
    frags.append(("", "\n"))

    frags.append(("", pad))
    if filled > 0:
        frags.append((C_GAINED, "█" * filled))
    if filled < bar_w:
        frags.append((C_HINT, "░" * (bar_w - filled)))
    frags.append(("", "\n"))

    line = [" "] * bar_w
    for lv_offset in range(span + 1):
        col = int(round(lv_offset / span * bar_w))
        label = f"| {min_lv + lv_offset}"
        if col + len(label) > bar_w:
            col = bar_w - len(label)
        if col < 0:
            col = 0
        for i, ch in enumerate(label):
            if 0 <= col + i < bar_w:
                line[col + i] = ch
    frags.append(("", pad))
    frags.append((C_HINT, "".join(line)))


def _append_sparklines(frags, stats, cols):
    n = _STAT_SPARK_WIDTH
    start    = stats.start_ts
    end      = max(stats.end_ts, start + 1)
    duration = end - start

    xp_buckets = _bucket_event_sums(stats.kill_events, n, start, end)
    tp_buckets = _bucket_event_sums(stats.tp_events,   n, start, end)

    bucket_secs = duration / n if n > 0 else 1
    if bucket_secs <= 0:
        bucket_secs = 1
    xp_rates = [b * 3600.0 / bucket_secs for b in xp_buckets]
    tp_rates = [b * 3600.0 / bucket_secs for b in tp_buckets]

    xp_max = max(xp_rates) if xp_rates else 0.0
    tp_max = max(tp_rates) if tp_rates else 0.0

    xp_rows = _sparkline_rows(xp_rates, xp_max, rows=3)
    tp_rows = _sparkline_rows(tp_rates, tp_max, rows=3)

    label_w = _STAT_Y_LABEL_W
    side_w  = label_w + 1 + n
    gap     = "    "
    total_w = side_w * 2 + len(gap)
    margin  = max(0, (cols - total_w) // 2)
    pad     = " " * margin

    # Title line (above each sparkline)
    title_xp = "XP/h"
    title_tp = "TP/h"
    left_title  = (" " * (label_w + 1)) + title_xp.ljust(n)
    right_title = (" " * (label_w + 1)) + title_tp.ljust(n)
    frags.append(("", pad))
    frags.append((C_BODY, left_title))
    frags.append(("", gap))
    frags.append((C_BODY, right_title))
    frags.append(("", "\n"))

    xp_labels = [_fmt_xp_short(xp_max), _fmt_xp_short(xp_max / 2), "0"]
    tp_labels = [_fmt_xp_short(tp_max), _fmt_xp_short(tp_max / 2), "0"]

    for r in range(3):
        frags.append(("", pad))
        frags.append((C_HINT, xp_labels[r].rjust(label_w) + " "))
        frags.append((C_GAINED, xp_rows[r]))
        frags.append(("", gap))
        frags.append((C_HINT, tp_labels[r].rjust(label_w) + " "))
        frags.append((C_GAINED, tp_rows[r]))
        frags.append(("", "\n"))

    x_left  = "00:00"
    x_right = _fmt_duration(duration)[:5]
    fill    = max(1, n - len(x_left) - len(x_right))
    x_line  = (" " * (label_w + 1)) + x_left + (" " * fill) + x_right
    frags.append(("", pad))
    frags.append((C_HINT, x_line))
    frags.append(("", gap))
    frags.append((C_HINT, x_line))


def _append_kills_pkills(frags, stats, cols):
    left_w  = _STAT_TABLE_LEFT_W
    right_w = _STAT_TABLE_RIGHT_W
    gap     = _STAT_TABLE_GAP
    margin  = max(0, (cols - (left_w + right_w + len(gap))) // 2)
    pad     = " " * margin

    frags.append(("", pad))
    frags.append((C_TITLE, "Kills".ljust(left_w)))
    frags.append(("", gap))
    frags.append((C_TITLE, "Player Kills".ljust(right_w)))
    frags.append(("", "\n"))

    k_hdr  = _format_kill_row("Mob", "N", "XP/N", "XP tot", left_w)
    pk_hdr = _format_pkill_row("Player", "N", "XP", right_w)
    frags.append(("", pad))
    frags.append((C_HINT, k_hdr))
    frags.append(("", gap))
    frags.append((C_HINT, pk_hdr))
    frags.append(("", "\n"))

    kills  = sorted(stats.kills.items(),  key=lambda kv: -kv[1].total_xp)[:5]
    pkills = sorted(stats.pkills.items(), key=lambda kv: -kv[1].total_xp)[:5]

    n_rows = max(len(kills), len(pkills), 1)
    for i in range(n_rows):
        if i < len(kills):
            name, agg = kills[i]
            avg = agg.total_xp // agg.count if agg.count else 0
            k_line = _format_kill_row(name, str(agg.count), str(avg), str(agg.total_xp), left_w)
        else:
            k_line = " " * left_w
        if i < len(pkills):
            name, agg = pkills[i]
            pk_line = _format_pkill_row(name, str(agg.count), str(agg.total_xp), right_w)
        else:
            pk_line = " " * right_w
        frags.append(("", pad))
        frags.append((C_ITEM, k_line))
        frags.append(("", gap))
        frags.append((C_ITEM, pk_line))
        frags.append(("", "\n"))

    k_cnt = sum(a.count for a in stats.kills.values())
    k_xp  = sum(a.total_xp for a in stats.kills.values())
    k_avg = k_xp // k_cnt if k_cnt else 0
    p_cnt = sum(a.count for a in stats.pkills.values())
    p_xp  = sum(a.total_xp for a in stats.pkills.values())

    k_total  = _format_kill_row("Total",  str(k_cnt), str(k_avg), str(k_xp), left_w)
    pk_total = _format_pkill_row("Total", str(p_cnt), str(p_xp), right_w)
    frags.append(("", pad))
    frags.append((C_ACCENT, k_total))
    frags.append(("", gap))
    frags.append((C_ACCENT, pk_total))
    frags.append(("", "\n"))


def _append_allies_achievements(frags, stats, cols):
    left_w  = _STAT_TABLE_LEFT_W
    right_w = _STAT_TABLE_RIGHT_W
    gap     = _STAT_TABLE_GAP
    margin  = max(0, (cols - (left_w + right_w + len(gap))) // 2)
    pad     = " " * margin

    frags.append(("", pad))
    frags.append((C_TITLE, "Allies".ljust(left_w)))
    frags.append(("", gap))
    frags.append((C_TITLE, "Achievements".ljust(right_w)))
    frags.append(("", "\n"))

    allies = stats.allies[:6]
    ally_rows = []
    for i in range(0, len(allies), 3):
        ally_rows.append(", ".join(allies[i:i + 3]))
    while len(ally_rows) < 2:
        ally_rows.append("")
    ally_rows = ally_rows[:2]

    ach_rows = [a[1] for a in stats.achievements[:2]]
    while len(ach_rows) < 2:
        ach_rows.append("")

    for i in range(2):
        a = ally_rows[i]
        if len(a) > left_w:
            a = a[:left_w - 1] + "…"
        b = ach_rows[i]
        if len(b) > right_w:
            b = b[:right_w - 1] + "…"
        frags.append(("", pad))
        frags.append((C_ITEM, a.ljust(left_w)))
        frags.append(("", gap))
        frags.append((C_ITEM, b.ljust(right_w)))
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
            (C_HINT, hint),
        ]

    frags = []

    cur_lv = stats.current_level
    if cur_lv is None:
        cur_lv = status.get("level", "?")
    header = (
        f"◆ RUN STATISTICS  —  {_stats_char}  "
        f"·  Lv {cur_lv}  ·  Run {_fmt_duration(stats.duration_seconds)}"
    )
    frags.append(("", "\n"))
    frags.append(("", _pad_centre(header, cols)))
    frags.append((C_TITLE, header))
    frags.append(("", "\n\n"))

    _append_xp_bar(frags, stats, status, cols)
    frags.append(("", "\n\n"))

    _append_sparklines(frags, stats, cols)
    frags.append(("", "\n\n"))

    _append_kills_pkills(frags, stats, cols)
    frags.append(("", "\n"))
    _append_allies_achievements(frags, stats, cols)

    frags.append(("", "\n"))
    footer = "ESC Back     R Refresh     E Export run data"
    frags.append(("", _pad_centre(footer, cols)))
    frags.append((C_HINT, footer))

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
    _pop_frame()


@kb.add("r", filter=_in_frame("statistics"))
@kb.add("R", filter=_in_frame("statistics"))
def _stat_refresh(event):
    if _stats_char:
        _load_statistics(_stats_char)
    if _app:
        _app.invalidate()


@kb.add("e", filter=_in_frame("statistics"))
@kb.add("E", filter=_in_frame("statistics"))
def _stat_export(event):
    # Placeholder — export lands in a follow-up commit.
    pass


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


def _build_statistics_container():
    return Window(
        content=FormattedTextControl(text=_statistics_text, focusable=False),
        wrap_lines=False,
        always_hide_cursor=True,
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
