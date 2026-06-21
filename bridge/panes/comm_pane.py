# Communication channel pane.
#
# prompt_toolkit full-screen Application with mouse_support=True.
# Layout: fixed 1-row header + scrollable list + conditional indicator (HSplit).
# Header: per-channel label (clickable), fg-colored by channel or greyed when off.
# List: history filtered by channel, with sticky-bottom scrollback.
# Indicator: "↓ N newer messages" in its own Window below the list, only when
#   _scroll_offset > 0 — prevents list wrapping from clipping it.
# Polls bridge/runtime/comm.state every 250 ms via mtime comparison.
# Filters are read/written here (bridge/runtime/comm_filters.conf), but no
# longer exclusively: the same poll loop re-reads comm_filters.conf and
# comm_prefs.conf on mtime change, so external edits (in-game popup, launcher)
# apply to the live pane within one tick.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.mouse_events import MouseButton, MouseEventType  # prompt_toolkit >= 3.0
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import atexit
import asyncio
import json
import os
import re
import signal
import sys
import time

import pane_frame
from pane_frame import inner_height, inner_width

# The light/dark gate is resolved PER RENDER (not at load), derived from the comm
# pane's OWN bg (a named pane colour reads from its dark fill; the terminal-default
# pane reads from the terminal). Resolving per frame means a live pane-colour
# change (popup → tmux re-applies bg; pane_frame.start_poll refreshes the cached
# colours and invalidates) flips the treatment within a frame. On a light
# effective bg the content colours are pulled darker/more-saturated via
# pane_frame.light_shift so they stay legible instead of washing out; on a dark bg
# everything passes through unchanged (the comm pane is then byte-for-byte
# identical). See _resolve_colors.
_LIGHT = False


def _light_content_style(style):
    """Light-background shift for a `fg:#rrggbb` content style string.

    When `_LIGHT`, pull the hex through `pane_frame.light_shift` (darker,
    more-saturated) and reassemble the `fg:` prefix. On a dark terminal, or for
    any value without a `fg:#` hex, return it unchanged — `light_shift` itself
    also no-ops on achromatic / non-`#rrggbb` input."""
    if not _LIGHT or not style.startswith("fg:#"):
        return style
    return "fg:" + pane_frame.light_shift(style[len("fg:"):])


_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")

COMM_STATE_PATH   = os.environ.get(
    "COMM_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "comm.state"),
)
COMM_FILTERS_CONF = os.environ.get(
    "COMM_FILTERS_CONF",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "comm_filters.conf"),
)
COMM_FILTERS_TMP  = COMM_FILTERS_CONF + ".tmp"
# comm_prefs.conf — cross-package contract with bridge/launcher/comm_channels.py.
# Single key: `show_header=true|false`. Missing file or key → default True.
# Restated here rather than imported: the launcher is the writer, this pane the
# reader, and the conf file is the only coupling between them (mirrors how
# comm_filters.conf is shared).
COMM_PREFS_CONF   = os.environ.get(
    "COMM_PREFS_CONF",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "comm_prefs.conf"),
)
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
)
POLL_MS           = 0.25

# ---------------------------------------------------------------------------
# Channel tables
# ---------------------------------------------------------------------------

CHANNEL_VERBS = {
    "tales":     ("narrate",  "narrates"),
    "tells":     ("tell",     "tells"),
    "emotes":    ("emote",    "emotes"),
    "says":      ("say",      "says"),
    "yells":     ("yell",     "yells"),
    "whispers":  ("whisper",  "whispers"),
    "prayers":   ("pray",     "prays"),
    "songs":     ("sing",     "sings"),
    "questions": ("ask",      "asks"),
    "socials":   ("social",   "socials"),
}

QUOTED_CHANNELS   = {"tales", "tells", "says", "yells", "whispers",
                     "prayers", "songs", "questions"}
ACTION_CHANNELS   = {"emotes", "socials"}
DIRECTED_CHANNELS = {"tells", "whispers"}
DESTINATION_PREPOSITIONS = {
    "whispers": "to",
}

CHANNEL_ORDER = [
    "tales",
    "tells",
    "says",
    "yells",
    "prayers",
    "emotes",
    "whispers",
    "questions",
    "songs",
    "socials",
]

# Display-only overrides for channels whose header label must differ from
# both the GMCP name and the server-provided caption. Sparse: missing key
# falls back to caption, then to name.title(). Handlers, filter keys, and
# comm_filters.conf all stay keyed on the GMCP channel name.
CHANNEL_DISPLAY = {
    "tales": "Narrates",
}

# ---------------------------------------------------------------------------
# Colour palette (24-bit truecolor, CSS-style for prompt_toolkit)
# ---------------------------------------------------------------------------

C_TIME           = "fg:#687685"               # 104,118,133 — muted blue-grey
C_LABEL_OFF      = "fg:#3a3a3a"               # grey when filter off

# Base (unshifted) content colours. The render-time light-shifted copies live in
# the like-named globals below, recomputed each frame by _resolve_colors from
# these bases.
_BASE_C_TALKER_YOU    = "fg:#afd2d2"          # soft cyan — "you" as talker or destination
_BASE_C_TALKER_OTHER  = "fg:#c2a878"          # warm tan — contrasts with light-blue message
_BASE_C_MESSAGE_SELF  = "fg:#c3e6e9"          # 195,230,233
_BASE_C_MESSAGE_OTHER = "fg:#91bec1"          # 145,190,193

_BASE_CHANNEL_COLORS = {
    "tales":     "fg:#949400",  # 148,148,0
    "tells":     "fg:#008000",  # 0,128,0
    "emotes":    "fg:#008000",
    "says":      "fg:#008f8f",  # 0,143,143
    "yells":     "fg:#640064",  # 100,0,100
    "whispers":  "fg:#965a00",  # 150,90,0
    "prayers":   "fg:#c3c36e",  # 195,195,110
    "songs":     "fg:#b49696",  # 180,150,150
    "questions": "fg:#008f8f",
    "socials":   "fg:#9600a0",  # 150,0,160
}

C_VERB_UNKNOWN   = "fg:#78909c"               # neutral grey for unknown channels
C_INDICATOR      = "fg:#d4a04e italic"        # amber, italic — system message

# Render-time content colours, recomputed each frame by _resolve_colors. Applies
# only to the CONTENT colours — channel verb/label, talker names, message text —
# so they stop washing out on a "paper" terminal. The muted/structural colours
# are left untouched on purpose: C_TIME and C_LABEL_OFF are meant to recede
# (light_shift's saturation floor would make them *more* prominent, fighting that
# intent), and C_INDICATOR is the shared cross-pane overflow amber (shifting it
# would desync the other panes' indicators on a light terminal). On a dark
# terminal every value is returned unchanged. Initialised to the base values so a
# render before the first resolve still has valid styles.
CHANNEL_COLORS   = dict(_BASE_CHANNEL_COLORS)
C_TALKER_YOU     = _BASE_C_TALKER_YOU
C_TALKER_OTHER   = _BASE_C_TALKER_OTHER
C_MESSAGE_SELF   = _BASE_C_MESSAGE_SELF
C_MESSAGE_OTHER  = _BASE_C_MESSAGE_OTHER


def _resolve_colors():
    """Recompute the light/dark gate and the light-shifted content colours from
    their base values, once per render. The comm pane's effective bg is
    live-mutable via the popup, so this can't be cached at module load."""
    global _LIGHT, CHANNEL_COLORS, C_TALKER_YOU, C_TALKER_OTHER
    global C_MESSAGE_SELF, C_MESSAGE_OTHER
    _LIGHT          = pane_frame.pane_is_light("comm")
    CHANNEL_COLORS  = {name: _light_content_style(style)
                       for name, style in _BASE_CHANNEL_COLORS.items()}
    C_TALKER_YOU    = _light_content_style(_BASE_C_TALKER_YOU)
    C_TALKER_OTHER  = _light_content_style(_BASE_C_TALKER_OTHER)
    C_MESSAGE_SELF  = _light_content_style(_BASE_C_MESSAGE_SELF)
    C_MESSAGE_OTHER = _light_content_style(_BASE_C_MESSAGE_OTHER)

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
_state          = None      # decoded comm.state dict
_last_mtime     = None
_scroll_offset  = 0         # 0 = bottom (live-follow); N = N newer msgs hidden
_prev_filtered  = 0         # filtered-list length before last update
_app            = None      # set in main() after Application is created
_filters        = {}        # sparse map: missing key = enabled (True)
_solo_channel   = None      # name of currently soloed channel, or None
_solo_snapshot  = None      # dict copy of _filters at solo entry, or None
_run_active     = False
_show_header    = True      # comm_prefs.conf show_header; live-reloaded
_filters_mtime  = None      # mtime of comm_filters.conf at last read
_prefs_mtime    = None      # mtime of comm_prefs.conf at last read

# ---------------------------------------------------------------------------
# Filter persistence
# ---------------------------------------------------------------------------

def _load_filters():
    """Read comm_filters.conf into _filters (clears first). Missing file is fine.
    Clearing here means startup and the live re-read path share one clean-load
    behaviour — a key dropped from the file on an external edit is dropped here
    too, reverting that channel to its enabled default."""
    _filters.clear()
    try:
        with open(COMM_FILTERS_CONF, "r") as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line:
                    continue
                name, _, val = line.partition("=")
                if val in ("true", "false"):
                    _filters[name] = (val == "true")
    except OSError:
        pass


def _load_prefs():
    """Read show_header from comm_prefs.conf into _show_header. Missing file or
    key → keep default True. Mirrors comm_channels.read_show_header()."""
    global _show_header
    _show_header = True
    try:
        with open(COMM_PREFS_CONF, "r") as fh:
            for line in fh:
                line = line.strip()
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == "show_header" and val.strip() in ("true", "false"):
                    _show_header = (val.strip() == "true")
    except OSError:
        pass


def _save_filters():
    """Atomic write of _filters to comm_filters.conf. Sparse: only explicit keys.
    Records the new file mtime so the poll loop does not re-process the pane's
    own write (which would needlessly reload and drop any active solo)."""
    global _filters_mtime
    try:
        with open(COMM_FILTERS_TMP, "w") as fh:
            for name, val in _filters.items():
                fh.write(f"{name}={'true' if val else 'false'}\n")
        os.replace(COMM_FILTERS_TMP, COMM_FILTERS_CONF)
        try:
            _filters_mtime = os.stat(COMM_FILTERS_CONF).st_mtime
        except OSError:
            pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_filtered(state):
    """Return history entries that pass the current channel filter."""
    if state is None:
        return []
    history = state.get("history") or []
    return [e for e in history if _filters.get(e.get("channel", ""), True)]


def _strip_descriptor(name):
    """Return name with ' the <descriptor>' suffix stripped.
    'Takhr the orkish warden' -> 'Takhr'.
    Returns name unchanged when there is no ' the ' inside it,
    when name starts with 'the ' (article-prefix mob, no proper
    name to keep), or when name is empty/None."""
    if not name:
        return name
    idx = name.find(' the ')
    if idx > 0:
        return name[:idx]
    return name


def _match_visible_prefix(text, prefix):
    """Walk text, skipping ANSI SGR sequences, and try to consume a
    case-insensitive match for prefix from the visible characters.
    Returns (matched_visible, body_byte_offset) on success — where
    matched_visible is the matched run with the original casing from text
    (visible chars only, no ANSI bytes), and body_byte_offset is the byte
    index in text where the body begins. Returns None on mismatch."""
    pi = 0
    ti = 0
    matched_visible = ""

    while pi < len(prefix):
        if ti >= len(text):
            return None
        m = _SGR_RE.match(text, ti)
        if m:
            ti = m.end()
            continue
        if text[ti].lower() != prefix[pi].lower():
            return None
        matched_visible += text[ti]
        ti += 1
        pi += 1

    return (matched_visible, ti)


def _channel_verb(channel, talker):
    verbs = CHANNEL_VERBS.get(channel)
    if verbs is None:
        return channel
    return verbs[0] if talker == "you" else verbs[1]


def _channel_color(channel):
    return CHANNEL_COLORS.get(channel, C_VERB_UNKNOWN)


def _ts_str(ts):
    now = time.time()
    if not ts:
        return "??:??"
    elif now - ts < 86400:
        return time.strftime("%H:%M", time.localtime(ts))
    else:
        return time.strftime("%d/%m", time.localtime(ts))


def _render_quoted_row(entry, channels, with_time):
    """Fragments for a quoted-channel row: [time +] Talker + verb + [dest] + 'message'."""
    frags       = []
    channel     = entry.get("channel", "")
    talker      = entry.get("talker", "")
    text        = entry.get("text", "")
    destination = entry.get("destination") or ""

    if not destination and channel in DIRECTED_CHANNELS and talker != "you":
        destination = "you"

    if talker == "you":
        display_talker = "You"
    elif talker:
        stripped = _strip_descriptor(talker)
        display_talker = stripped[0].upper() + stripped[1:]
    else:
        display_talker = talker

    talker_style = C_TALKER_YOU if talker == "you" else C_TALKER_OTHER
    verb_style   = _channel_color(channel)
    msg_style    = C_MESSAGE_SELF if talker == "you" else C_MESSAGE_OTHER

    if channel in QUOTED_CHANNELS:
        if talker == "you":
            open_q, msg_body, close_q = ("'", text, "'")
        else:
            first = text.find("'")
            last  = text.rfind("'")
            if first != -1 and last != -1 and last > first:
                open_q, msg_body, close_q = ("'", text[first + 1:last], "'")
            else:
                open_q, msg_body, close_q = ("'", text, "'")
    else:
        open_q, msg_body, close_q = ("", text, "")

    if with_time:
        frags.append((C_TIME, _ts_str(entry.get("ts", 0)) + " "))
    frags.append((talker_style, display_talker + " "))
    frags.append((verb_style, _channel_verb(channel, talker) + " "))

    if destination:
        prep = DESTINATION_PREPOSITIONS.get(channel)
        if prep:
            frags.append((verb_style, prep + " "))
        if destination == "you":
            display_dest = "you"
        else:
            stripped_dest = _strip_descriptor(destination)
            display_dest = stripped_dest[0].upper() + stripped_dest[1:]
        dest_style = C_TALKER_YOU if destination == "you" else C_TALKER_OTHER
        frags.append((dest_style, display_dest + " "))

    if open_q:
        frags.append((msg_style, open_q))

    if msg_body:
        try:
            ansi_frags = to_formatted_text(ANSI(msg_body))
            frags.extend((msg_style if s == "" else s, t) for s, t in ansi_frags)
        except Exception:
            frags.append((msg_style, msg_body))

    if close_q:
        frags.append((msg_style, close_q))

    return frags


def _render_action_row(entry, with_time):
    """Fragments for an action-channel row: [time +] text with talker-prefix color split."""
    frags  = []
    talker = entry.get("talker", "")
    text   = entry.get("text", "")

    if with_time:
        frags.append((C_TIME, _ts_str(entry.get("ts", 0)) + " "))

    result = _match_visible_prefix(text, "You ")
    if result is not None:
        _, body_start = result
        frags.append((C_TALKER_YOU, "You "))
        rest = text[body_start:]
        try:
            ansi_frags = to_formatted_text(ANSI(rest))
            frags.extend((C_MESSAGE_SELF if s == "" else s, t) for s, t in ansi_frags)
        except Exception:
            frags.append((C_MESSAGE_SELF, rest))
    else:
        result = _match_visible_prefix(text, talker + " ") if talker else None
        if result is not None:
            matched_visible, body_start = result
            display_talker = _strip_descriptor(matched_visible.rstrip()) + " "
            frags.append((C_TALKER_OTHER, display_talker))
            rest = text[body_start:]
            try:
                ansi_frags = to_formatted_text(ANSI(rest))
                frags.extend((C_MESSAGE_OTHER if s == "" else s, t) for s, t in ansi_frags)
            except Exception:
                frags.append((C_MESSAGE_OTHER, rest))
        else:
            if talker == "you":
                display_talker = "You"
            elif talker:
                stripped = _strip_descriptor(talker)
                display_talker = stripped[0].upper() + stripped[1:]
            else:
                display_talker = ""
            talker_style = C_TALKER_YOU if talker == "you" else C_TALKER_OTHER
            msg_style    = C_MESSAGE_SELF if talker == "you" else C_MESSAGE_OTHER
            if display_talker:
                frags.append((talker_style, display_talker + " "))
            try:
                ansi_frags = to_formatted_text(ANSI(text))
                frags.extend((msg_style if s == "" else s, t) for s, t in ansi_frags)
            except Exception:
                frags.append((msg_style, text))

    return frags


def _term_rows():
    """Height of the pane (rows available for the whole application)."""
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


def _term_cols():
    """Width of the pane (columns available for the whole application)."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


# ---------------------------------------------------------------------------
# Fragment-aware word-wrap helpers
# ---------------------------------------------------------------------------

def _visual_len(text):
    """Visible character count of text (ANSI SGR sequences are zero-width)."""
    return len(_SGR_RE.sub("", text))


def _split_at_visual(text, n):
    """Split text at n visible characters; return (head, tail).
    head contains exactly min(n, visible_len) visible chars."""
    count = 0
    i = 0
    while i < len(text):
        if count >= n:
            break
        m = _SGR_RE.match(text, i)
        if m:
            i = m.end()
        else:
            count += 1
            i += 1
    return text[:i], text[i:]


def _tokenize_fragments(fragments):
    """Split (style, text) fragments into (is_ws, frags) tokens.

    A token is a maximal run of whitespace-only or non-whitespace visible
    characters, spanning fragment boundaries while preserving per-character
    style. ANSI SGR sequences are zero-width and attached to the preceding
    visible-char accumulator."""
    tokens    = []
    cur_ws    = None
    cur_parts = []
    cur_style = None
    cur_buf   = ""

    def _flush_buf():
        nonlocal cur_buf
        if cur_buf:
            cur_parts.append((cur_style, cur_buf))
            cur_buf = ""

    def _flush_tok():
        nonlocal cur_ws, cur_parts, cur_style, cur_buf
        _flush_buf()
        if cur_parts:
            tokens.append((bool(cur_ws), cur_parts))
        cur_ws    = None
        cur_parts = []
        cur_style = None

    for style, text in fragments:
        i = 0
        while i < len(text):
            m = _SGR_RE.match(text, i)
            if m:
                if cur_style is None:
                    cur_style = style
                elif cur_style != style:
                    _flush_buf()
                    cur_style = style
                cur_buf += m.group()
                i = m.end()
            else:
                ch = text[i]
                ws = ch in " \t"
                if cur_ws is None:
                    cur_ws = ws
                    if cur_style is None:
                        cur_style = style
                elif ws != cur_ws:
                    _flush_tok()
                    cur_ws    = ws
                    cur_style = style
                elif cur_style != style:
                    _flush_buf()
                    cur_style = style
                cur_buf += ch
                i += 1

    _flush_tok()
    return tokens


def _wrap_fragments(fragments, cols):
    """Word-wrap a list of (style, text) fragments into a list of display rows.

    Each row is itself a list of (style, text) fragments. Returns at least
    one row even when fragments is empty (the empty list).

    Greedy line filling with word-boundary breaks. Tokens wider than cols
    fall back to a hard char-break at exactly cols visible chars. Leading
    whitespace on continuation rows is never emitted (R4)."""
    if not fragments:
        return [[]]

    tokens = _tokenize_fragments(fragments)

    rows          = []
    row           = []
    row_w         = 0
    pend_ws_frags = []
    pend_ws_w     = 0

    def _place(frags, w):
        nonlocal row, row_w
        row.extend(frags)
        row_w += w

    def _hard_place(frags):
        nonlocal row, row_w
        remaining = list(frags)
        while remaining:
            space     = cols - row_w
            chunk     = []
            taken     = 0
            leftovers = []
            broke     = False

            for idx, (sty, txt) in enumerate(remaining):
                tw = _visual_len(txt)
                if taken + tw <= space:
                    chunk.append((sty, txt))
                    taken += tw
                else:
                    need = space - taken
                    if need > 0:
                        h, t = _split_at_visual(txt, need)
                        if h:
                            chunk.append((sty, h))
                            taken += _visual_len(h)
                        leftovers = ([(sty, t)] if t else []) + remaining[idx + 1:]
                    else:
                        leftovers = remaining[idx:]
                    broke = True
                    break

            if not broke:
                leftovers = []

            if taken == 0:
                # No visible progress (zero-width content); dump and exit.
                row.extend(remaining)
                break

            row.extend(chunk)
            row_w += taken
            remaining = leftovers

            if remaining:
                rows.append(row)
                row   = []
                row_w = 0

    for is_ws, frags in tokens:
        w = sum(_visual_len(t) for _, t in frags)

        if is_ws:
            pend_ws_frags = frags
            pend_ws_w     = w
            continue

        ws_w    = pend_ws_w    if (pend_ws_frags and row_w > 0) else 0
        ws_frags = pend_ws_frags if (pend_ws_frags and row_w > 0) else []

        if row_w + ws_w + w <= cols:
            _place(ws_frags, ws_w)
            _place(frags, w)
        elif row_w > 0:
            rows.append(row)
            row   = []
            row_w = 0
            if w <= cols:
                _place(frags, w)
            else:
                _hard_place(frags)
        else:
            _hard_place(frags)

        pend_ws_frags = []
        pend_ws_w     = 0

    if row:
        rows.append(row)
    if not rows:
        rows.append([])
    return rows


def _entry_to_rows(entry, cols, channels, with_time):
    """Render entry to a list of display rows (single layout authority)."""
    channel = entry.get("channel", "")
    if channel in ACTION_CHANNELS:
        frags = _render_action_row(entry, with_time)
    else:
        frags = _render_quoted_row(entry, channels, with_time)
    return _wrap_fragments(frags, cols)


def _row_count(entry, cols, channels, with_time):
    return len(_entry_to_rows(entry, cols, channels, with_time))


def forward_toggle(name):
    """Toggle filter for a named channel, persist, and invalidate the app."""
    global _solo_channel, _solo_snapshot
    if _solo_channel is not None:
        _solo_channel = None
        _solo_snapshot = None
    current = _filters.get(name, True)
    _filters[name] = not current
    _save_filters()
    if _app:
        _app.invalidate()


def forward_solo(name):
    """Right-click handler: solo a channel, or restore on re-click."""
    global _solo_channel, _solo_snapshot

    if _solo_channel == name:
        if _solo_snapshot is not None:
            _filters.clear()
            _filters.update(_solo_snapshot)
        _solo_channel = None
        _solo_snapshot = None
    else:
        if _solo_channel is None:
            _solo_snapshot = dict(_filters)
        channels = (_state or {}).get("channels") or []
        for ch in channels:
            cn = ch.get("name", "")
            if cn:
                _filters[cn] = (cn == name)
        _solo_channel = name

    _save_filters()
    if _app:
        _app.invalidate()


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Text functions (called each render cycle by prompt_toolkit)
# ---------------------------------------------------------------------------

def _header_layout(caps, W):
    """Layout for the width-responsive channel-filter header.

    `caps` is the list of display-name strings, one per advertised channel
    in render order. `W` is the available column count. Returns
    `(cells, sep)`: each cell is a truncated, space-padded label for one
    channel; cells are intended to be joined by `sep` space(s). Total
    visible width is `W` or less by construction — trailing channels are
    dropped only when `W` is below one column per channel."""
    N = len(caps)
    if N == 0 or W <= 0:
        return [], 0

    if W - (N - 1) >= N:
        sep, budget, visible = 1, W - (N - 1), N
    elif W >= N:
        sep, budget, visible = 0, W, N
    else:
        sep, visible = 0, W
        budget = visible

    max_cap = max(len(caps[i]) for i in range(visible))
    target  = budget // visible
    rem     = budget %  visible

    cells = []
    if target >= max_cap:
        for i in range(visible):
            cells.append(caps[i])
    else:
        for i in range(visible):
            w = target + (1 if i < rem else 0)
            cells.append(caps[i][:w].ljust(w))
    return cells, sep


def _header_text():
    """Fragments for the 1-row channel-filter header."""
    if not _run_active:
        return [("", "")]
    _resolve_colors()
    frags = []
    if _state is None:
        return frags
    channels    = _state.get("channels") or []
    advertised  = {ch.get("name", "") for ch in channels}
    cap_by_name = {ch.get("name", ""): ch.get("caption", "") for ch in channels}

    def _display(name):
        if name in CHANNEL_DISPLAY:
            return CHANNEL_DISPLAY[name]
        cap = cap_by_name.get(name, "")
        if cap:
            return cap
        return name.title()

    known   = set(CHANNEL_ORDER)
    ordered = [n for n in CHANNEL_ORDER if n in advertised]
    for ch in channels:
        n = ch.get("name", "")
        if n and n not in known and n not in ordered:
            ordered.append(n)

    caps        = [_display(n) for n in ordered]
    cells, sep  = _header_layout(caps, max(1, inner_width(_term_cols())))

    for i, cell in enumerate(cells):
        name    = ordered[i]
        enabled = _filters.get(name, True)
        style   = _channel_color(name) if enabled else C_LABEL_OFF

        def _make_handler(n=name):
            def _handler(mouse_event):
                if mouse_event.event_type != MouseEventType.MOUSE_DOWN:
                    return
                if mouse_event.button == MouseButton.RIGHT:
                    forward_solo(n)
                else:
                    forward_toggle(n)
            return _handler

        frags.append((style, cell, _make_handler()))
        if sep == 1 and i < len(cells) - 1:
            frags.append(("", " "))

    return frags


def _list_text():
    """Fragments for the scrollable message list."""
    global _scroll_offset

    if not _run_active:
        return [("", "")]

    _resolve_colors()
    frags = []
    if _state is None:
        return frags

    filtered = _get_filtered(_state)
    total    = len(filtered)
    channels = _state.get("channels") or []

    if total == 0:
        return frags

    # Clamp so anchor_idx stays in [0, total-1]; wrap-aware upper bound is
    # enforced by the mouse handler before offsets grow too large.
    _scroll_offset = max(0, min(_scroll_offset, total - 1))

    rows        = inner_height(_term_rows())
    cols        = max(1, inner_width(_term_cols()))
    list_height = max(1, rows - (1 if _show_header else 0)
                            - (1 if _scroll_offset > 0 else 0))
    with_time   = (_scroll_offset > 0)
    anchor_idx  = total - 1 - _scroll_offset

    # Walk backward from anchor accumulating wrapped display rows until the
    # window is filled or index 0 is reached.  The anchor is always included
    # even when it alone exceeds list_height (clip-top handles the overflow).
    accumulated = 0
    start       = anchor_idx
    for i in range(anchor_idx, -1, -1):
        rc = _row_count(filtered[i], cols, channels, with_time)
        if accumulated + rc > list_height and i < anchor_idx:
            break
        accumulated += rc
        start = i
        if accumulated >= list_height:
            break

    visible  = filtered[start:anchor_idx + 1]
    last_idx = len(visible) - 1
    for idx, entry in enumerate(visible):
        entry_rows = _entry_to_rows(entry, cols, channels, with_time)
        for row_idx, entry_row in enumerate(entry_rows):
            frags.extend(entry_row)
            if row_idx < len(entry_rows) - 1:
                frags.append(("", "\n"))
        if idx < last_idx:
            frags.append(("", "\n"))

    return frags


def _indicator_text():
    """Single-fragment row shown below the list when scroll_offset > 0."""
    if not _run_active:
        return [("", "")]
    if _state is None or _scroll_offset <= 0:
        return []
    newer = _scroll_offset

    def _handler(mouse_event):
        global _scroll_offset
        if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
            _scroll_offset = 0
            if _app:
                _app.invalidate()

    return [(C_INDICATOR, f"↓ {newer} newer messages", _handler)]


# ---------------------------------------------------------------------------
# ListControl — FormattedTextControl subclass with mouse wheel scroll support
# ---------------------------------------------------------------------------

class ListControl(FormattedTextControl):
    def mouse_handler(self, mouse_event):
        result = super().mouse_handler(mouse_event)
        if result is NotImplemented:
            global _scroll_offset
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                if _state is not None:
                    filtered    = _get_filtered(_state)
                    total       = len(filtered)
                    channels    = _state.get("channels") or []
                    rows        = inner_height(_term_rows())
                    cols        = max(1, inner_width(_term_cols()))
                    list_height = max(1, rows - (1 if _show_header else 0)
                                            - (1 if _scroll_offset > 0 else 0))
                    # Wrap-aware max_offset: walk forward to find the oldest
                    # entry that pins at the top when fully scrolled up.
                    # with_time=True: the scrolled view always carries timestamps.
                    running    = 0
                    max_offset = 0
                    for i, entry in enumerate(filtered):
                        running += _row_count(entry, cols, channels, True)
                        if running >= list_height:
                            max_offset = total - 1 - i
                            break
                    _scroll_offset = min(_scroll_offset + 1, max_offset)
                if _app:
                    _app.invalidate()
                return None
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                if _scroll_offset > 0:
                    _scroll_offset -= 1
                if _app:
                    _app.invalidate()
                return None
        return result


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------
kb = KeyBindings()


@kb.add("q")
@kb.add("c-c")
def _quit(event):
    event.app.exit()


# ---------------------------------------------------------------------------
# Async polling loop
# ---------------------------------------------------------------------------

async def _poll_state(app):
    global _state, _last_mtime, _scroll_offset, _prev_filtered, _run_active
    global _filters_mtime, _prefs_mtime, _solo_channel, _solo_snapshot

    while True:
        try:
            mtime = os.stat(COMM_STATE_PATH).st_mtime
        except OSError:
            mtime = None

        if mtime != _last_mtime:
            _last_mtime = mtime
            if mtime is not None:
                try:
                    with open(COMM_STATE_PATH, "r") as fh:
                        new_state = json.load(fh)

                    # Sticky-bottom: when scrolled up, advance offset by the
                    # number of new filtered messages so the view doesn't shift.
                    if _scroll_offset > 0 and _state is not None:
                        old_count = len(_get_filtered(_state))
                        # Temporarily swap state to count new filtered entries
                        _state = new_state
                        new_count = len(_get_filtered(_state))
                        delta = new_count - old_count
                        if delta > 0:
                            _scroll_offset = min(
                                _scroll_offset + delta,
                                new_count,
                            )
                    else:
                        _state = new_state

                    app.invalidate()
                except Exception:
                    pass  # keep last good state; silent recovery

        new_run_active = os.path.exists(CONNECTION_STATE_PATH)
        if new_run_active != _run_active:
            _run_active = new_run_active
            app.invalidate()

        # Live re-read of filters/prefs on external edits (in-game popup,
        # launcher). Self-writes are suppressed because _save_filters() stamps
        # _filters_mtime with the post-write mtime.
        try:
            f_mtime = os.stat(COMM_FILTERS_CONF).st_mtime
        except OSError:
            f_mtime = None
        if f_mtime != _filters_mtime:
            _filters_mtime = f_mtime
            _load_filters()
            # An external filter edit invalidates the runtime-only solo
            # snapshot — same rule as a manual left-click while soloed.
            _solo_channel = None
            _solo_snapshot = None
            app.invalidate()

        try:
            p_mtime = os.stat(COMM_PREFS_CONF).st_mtime
        except OSError:
            p_mtime = None
        if p_mtime != _prefs_mtime:
            _prefs_mtime = p_mtime
            _load_prefs()
            app.invalidate()

        await asyncio.sleep(POLL_MS)


# ---------------------------------------------------------------------------
# Vertical scroll anchor
# ---------------------------------------------------------------------------

def _anchor_bottom(window):
    """Pin list content to the bottom of the window (clip-top for overflow)."""
    info = window.render_info
    if info is None:
        return 0
    return max(0, info.content_height - info.window_height)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _app

    # Hide cursor; restore on any exit path
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()
    atexit.register(_restore_cursor)

    global _filters_mtime, _prefs_mtime
    _load_filters()
    _load_prefs()
    try:
        _filters_mtime = os.stat(COMM_FILTERS_CONF).st_mtime
    except OSError:
        _filters_mtime = None
    try:
        _prefs_mtime = os.stat(COMM_PREFS_CONF).st_mtime
    except OSError:
        _prefs_mtime = None

    header_window = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(text=_header_text, focusable=False),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _show_header),
    )

    list_window = Window(
        content=ListControl(text=_list_text, focusable=False),
        wrap_lines=False,
        get_vertical_scroll=_anchor_bottom,
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text),
            height=1,
        ),
        filter=Condition(lambda: _run_active and _scroll_offset > 0),
    )

    inner_root = HSplit([header_window, list_window, indicator_container])
    root       = pane_frame.framed(inner_root, "comm")
    layout     = Layout(root)

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        color_depth=ColorDepth.DEPTH_24_BIT,
    )
    _app = app

    # SIGWINCH: force redraw on terminal resize
    def _on_sigwinch(signum, frame):
        if _app:
            _app.invalidate()

    signal.signal(signal.SIGWINCH, _on_sigwinch)
    signal.signal(signal.SIGTERM, lambda s, f: (_restore_cursor(), sys.exit(0)))
    signal.signal(signal.SIGINT,  signal.SIG_IGN)

    async def _run():
        task       = asyncio.ensure_future(_poll_state(app))
        frame_task = pane_frame.start_poll(app)
        try:
            await app.run_async()
        finally:
            task.cancel()
            frame_task.cancel()
            for t in (task, frame_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
