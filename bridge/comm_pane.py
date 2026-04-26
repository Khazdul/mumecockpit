# Communication channel pane.
#
# prompt_toolkit full-screen Application with mouse_support=True.
# Layout: fixed 1-row header + scrollable list (HSplit).
# Header: per-channel label (clickable), fg-colored by channel or greyed when off.
# List: history filtered by channel, with sticky-bottom scrollback.
# Polls bridge/comm.state every 250 ms via mtime comparison.
# Filters are owned here: read/write bridge/comm_filters.conf directly.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import atexit
import asyncio
import json
import os
import signal
import sys
import time

COMM_STATE_PATH   = os.path.join(os.environ["HOME"], "MUME", "bridge", "comm.state")
COMM_FILTERS_CONF = os.path.join(os.environ["HOME"], "MUME", "bridge", "comm_filters.conf")
COMM_FILTERS_TMP  = COMM_FILTERS_CONF + ".tmp"
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

CHANNEL_LABELS = {
    "tales": "Na", "tells": "Te", "says": "Sa", "yells": "Ye",
    "prayers": "Pr", "emotes": "Em", "whispers": "Wh",
    "questions": "Qu", "songs": "Son", "socials": "Soc",
}

# ---------------------------------------------------------------------------
# Colour palette (24-bit truecolor, CSS-style for prompt_toolkit)
# ---------------------------------------------------------------------------

C_TIME           = "fg:#687685"               # 104,118,133
C_TALKER_SELF    = "fg:#afd2d2"               # 175,210,210
C_TALKER_OTHER   = "fg:#96b9bc"               # 150,185,188
C_MESSAGE_SELF   = "fg:#c3e6e9"               # 195,230,233
C_MESSAGE_OTHER  = "fg:#91bec1"               # 145,190,193
C_LABEL_OFF      = "fg:#666666"               # grey when filter off

CHANNEL_COLORS = {
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

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
_state          = None      # decoded comm.state dict
_last_mtime     = None
_scroll_offset  = 0         # 0 = bottom (live-follow); N = N newer msgs hidden
_prev_filtered  = 0         # filtered-list length before last update
_app            = None      # set in main() after Application is created
_filters        = {}        # sparse map: missing key = enabled (True)

# ---------------------------------------------------------------------------
# Filter persistence
# ---------------------------------------------------------------------------

def _load_filters():
    """Read comm_filters.conf into _filters at startup. Missing file is fine."""
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


def _save_filters():
    """Atomic write of _filters to comm_filters.conf. Sparse: only explicit keys."""
    try:
        with open(COMM_FILTERS_TMP, "w") as fh:
            for name, val in _filters.items():
                fh.write(f"{name}={'true' if val else 'false'}\n")
        os.replace(COMM_FILTERS_TMP, COMM_FILTERS_CONF)
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


def _channel_label(name):
    return CHANNEL_LABELS.get(name, name[:2].capitalize())


def _channel_verb(channel, talker):
    verbs = CHANNEL_VERBS.get(channel)
    if verbs is None:
        return channel
    return verbs[0] if talker == "you" else verbs[1]


def _channel_color(channel):
    return CHANNEL_COLORS.get(channel, C_VERB_UNKNOWN)


def _extract_message(channel, talker, text):
    """Normalize raw GMCP text to (open_quote, body, close_quote).

    Quoted channels: extract between first and last single-quote in text.
    Action channels: strip leading "<talker> " or "You " prefix.
    open/close_quote is "'" for quoted channels, "" for action/unknown.
    When talker is "you" on a quoted channel, text is already the bare message.
    """
    quoted  = {"tales", "tells", "says", "yells", "whispers",
               "prayers", "songs", "questions"}
    actions = {"emotes", "socials"}

    if channel in quoted:
        if talker == "you":
            return ("'", text, "'")
        first = text.find("'")
        last  = text.rfind("'")
        if first != -1 and last != -1 and last > first:
            return ("'", text[first + 1:last], "'")
        return ("'", text, "'")

    if channel in actions:
        if talker == "you":
            return ("", text, "")
        prefix = talker + " "
        if text.startswith(prefix):
            return ("", text[len(prefix):], "")
        if text.startswith("You "):
            return ("", text[4:], "")
        return ("", text, "")

    return ("", text, "")


def _term_rows():
    """Height of the pane (rows available for the whole application)."""
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


def forward_toggle(name):
    """Toggle filter for a named channel, persist, and invalidate the app."""
    current = _filters.get(name, True)
    _filters[name] = not current
    _save_filters()
    if _app:
        _app.invalidate()


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Text functions (called each render cycle by prompt_toolkit)
# ---------------------------------------------------------------------------

def _header_text():
    """Fragments for the 1-row channel-filter header."""
    frags = []
    if _state is None:
        return frags
    channels = _state.get("channels") or []

    frags.append(("", " "))  # leading inert space

    for ch in channels:
        name    = ch.get("name", "")
        label   = _channel_label(name)
        enabled = _filters.get(name, True)
        style   = _channel_color(name) if enabled else C_LABEL_OFF

        def _make_handler(n=name):
            def _handler(mouse_event):
                if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                    forward_toggle(n)
            return _handler

        frags.append((style, label, _make_handler()))
        frags.append(("", " "))  # trailing space (also acts as separator)

    return frags


def _list_text():
    """Fragments for the scrollable message list."""
    global _scroll_offset

    frags = []
    if _state is None:
        return frags

    filtered  = _get_filtered(_state)
    total     = len(filtered)

    rows         = _term_rows()
    list_height  = max(1, rows - 1)               # minus 1 for the header
    max_offset   = max(0, total - (list_height - 1))
    _scroll_offset = min(_scroll_offset, max_offset)

    newer         = _scroll_offset
    indicator_h   = 1 if newer > 0 else 0
    visible_rows  = max(0, list_height - indicator_h)

    end   = total - _scroll_offset
    start = max(0, end - visible_rows)
    visible = filtered[start:end]

    now      = time.time()
    last_idx = len(visible) - 1
    for idx, entry in enumerate(visible):
        ts      = entry.get("ts", 0)
        channel = entry.get("channel", "")
        talker  = entry.get("talker", "")
        text    = entry.get("text", "")

        # Time
        if not ts:
            time_str = "??:??"
        elif now - ts < 86400:
            time_str = time.strftime("%H:%M", time.localtime(ts))
        else:
            time_str = time.strftime("%d/%m", time.localtime(ts))

        # Talker: capitalize first character only, preserve internal case
        if talker == "you":
            display_talker = "You"
        elif talker:
            display_talker = talker[0].upper() + talker[1:]
        else:
            display_talker = talker

        talker_style = C_TALKER_SELF if talker == "you" else C_TALKER_OTHER
        verb         = _channel_verb(channel, talker)
        verb_style   = _channel_color(channel)
        msg_style    = C_MESSAGE_SELF if talker == "you" else C_MESSAGE_OTHER

        open_q, msg_body, close_q = _extract_message(channel, talker, text)

        frags.append((C_TIME, time_str + " "))
        frags.append((talker_style, display_talker + " "))
        frags.append((verb_style, verb + " "))

        if open_q:
            frags.append((msg_style, open_q))

        if msg_body:
            try:
                # Apply msg_style as default; ANSI codes in msg_body override it.
                ansi_frags = to_formatted_text(ANSI(msg_body))
                frags.extend((msg_style if s == "" else s, t) for s, t in ansi_frags)
            except Exception:
                frags.append((msg_style, msg_body))

        if close_q:
            frags.append((msg_style, close_q))

        if idx < last_idx:
            frags.append(("", "\n"))

    if newer > 0:
        indicator_text = f"↓ {newer} newer messages"

        def _indicator_handler(mouse_event):
            global _scroll_offset
            if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                _scroll_offset = 0
                if _app:
                    _app.invalidate()

        frags.append(("", "\n"))
        frags.append((C_INDICATOR, indicator_text, _indicator_handler))

    return frags


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
                    total = len(_get_filtered(_state))
                    rows = _term_rows()
                    list_height = max(1, rows - 1)
                    max_offset = max(0, total - (list_height - 1))
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
    global _state, _last_mtime, _scroll_offset, _prev_filtered

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

        await asyncio.sleep(POLL_MS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _app

    # Hide cursor; restore on any exit path
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()
    atexit.register(_restore_cursor)

    _load_filters()

    header_window = Window(
        content=FormattedTextControl(text=_header_text, focusable=False),
        height=1,
        dont_extend_height=True,
    )

    list_window = Window(
        content=ListControl(text=_list_text, focusable=False),
    )

    root      = HSplit([header_window, list_window])
    layout    = Layout(root)

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
        task = asyncio.ensure_future(_poll_state(app))
        try:
            await app.run_async()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
