#!/usr/bin/env python3
# bridge/panes/ui_pane.py — UI log pane renderer.
# prompt_toolkit Application. Tails logs/ui.log directly (no state file).
# Anchor-bottom scroll with wrap-aware capacity; indicator when scrolled.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.formatted_text import ANSI, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import atexit
import asyncio
import math
import os
import re
import signal
import sys

import pane_frame
from pane_frame import inner_height, inner_width

_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")

# Light-background render-time recolour, resolved PER RENDER (not at load) so a
# live pane-colour change (popup → tmux re-applies bg; pane_frame.start_poll
# refreshes the cached colours and invalidates) flips the treatment within a
# frame. On a "paper" terminal the baked-in ANSI colours in logs/ui.log
# (bright-white base text + washed-out chromatic prefixes) read poorly; _recolor
# rewrites them at the render choke point only — the on-disk log and the Lua
# emitters are never touched, and dark terminals pass through byte-for-byte.
# `_resolve_light()` recomputes the two globals below; `_recolor` reads them.
_LIGHT     = False
_LIGHT_INK = "\x1b[1;97m"

# Truecolor FOREGROUND introducer only (`38;2;R;G;B`); backgrounds (`48;2;…`) are
# left alone. A leading `1;` (bold, as on the ui_var value) sits before the match
# and is preserved.
_TRUECOLOR_FG_RE = re.compile(r"38;2;(\d{1,3});(\d{1,3});(\d{1,3})")


def _resolve_light():
    """Recompute the light/dark recolour state from the UI pane's OWN effective
    bg, once per render (top of _list_text). The pane colour is live-mutable via
    the popup, so this can't be cached at module load.

    `_LIGHT_INK` is the bold dark ink that replaces the achromatic bright-white
    base text (`\\x1b[1;97m`), the one case light_shift can't help (no hue to
    saturate). It is tinted toward the pane's effective bg
    (pane_frame.dark_ink(effective_bg("ui"))) so on "paper" it reads as a very
    dark WARM ink that blends instead of a flat near-black; the leading `1;`
    keeps the text bold."""
    global _LIGHT, _LIGHT_INK
    _LIGHT   = pane_frame.pane_is_light("ui")
    dark_ink = pane_frame.dark_ink(pane_frame.effective_bg("ui"))
    _LIGHT_INK = "\x1b[1;38;2;%d;%d;%dm" % (
        int(dark_ink[1:3], 16), int(dark_ink[3:5], 16), int(dark_ink[5:7], 16)
    )


def _shift_truecolor(m):
    """Pull one `38;2;R;G;B` foreground toward a darker, more-saturated target."""
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    shifted  = pane_frame.light_shift("#%02x%02x%02x" % (r, g, b))
    return "38;2;%d;%d;%d" % (
        int(shifted[1:3], 16), int(shifted[3:5], 16), int(shifted[5:7], 16)
    )


def _recolor(line):
    """Return a light-bg-legible copy of a raw log line (never mutates _lines).

    No-op on dark terminals. Truecolor foregrounds run through light_shift
    (catching every chromatic prefix and the bold-yellow ui_var value); the
    bright-white base text is then swapped for bold dark ink. Backgrounds,
    resets, and attr-only params are untouched."""
    if not _LIGHT:
        return line
    line = _TRUECOLOR_FG_RE.sub(_shift_truecolor, line)
    return line.replace("\x1b[1;97m", _LIGHT_INK)

UI_LOG_PATH = os.path.join(os.environ["HOME"], "MUME", "logs", "ui.log")
POLL_MS     = 0.25
MAX_LINES   = 1000

C_INDICATOR = "fg:#d4a04e italic"

_lines         = []    # in-memory list of raw log lines (ANSI strings)
_byte_offset   = 0     # bytes read from the file so far
_file_inode    = None  # last known inode for rotation/truncation detection
_scroll_offset = 0     # 0 = bottom (live-follow); N = N newer lines hidden
_app           = None


def _term_rows():
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


def _term_cols():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _row_count(line, cols):
    """Approximate wrapped display row count for a log line."""
    visible = len(_SGR_RE.sub("", line))
    return max(1, math.ceil(visible / cols)) if visible else 1


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


def _list_text():
    """Fragments for the scrollable log list (anchor-bottom)."""
    global _scroll_offset

    _resolve_light()

    if not _lines:
        return []

    total = len(_lines)
    _scroll_offset = max(0, min(_scroll_offset, total - 1))

    rows        = inner_height(_term_rows())
    cols        = max(1, inner_width(_term_cols()))
    list_height = max(1, rows - (1 if _scroll_offset > 0 else 0))
    anchor_idx  = total - 1 - _scroll_offset

    # Walk backward from anchor accumulating wrapped rows until window filled.
    # Anchor is always included even if it alone exceeds list_height (clip-top).
    accumulated = 0
    start       = anchor_idx
    for i in range(anchor_idx, -1, -1):
        rc = _row_count(_lines[i], cols)
        if accumulated + rc > list_height and i < anchor_idx:
            break
        accumulated += rc
        start = i
        if accumulated >= list_height:
            break

    frags   = []
    visible = _lines[start:anchor_idx + 1]
    for idx, line in enumerate(visible):
        if idx > 0:
            frags.append(("", "\n"))
        try:
            frags.extend(to_formatted_text(ANSI(_recolor(line))))
        except Exception:
            frags.append(("", line))
    return frags


def _indicator_text():
    """Single-fragment row shown below the list when scroll_offset > 0."""
    if _scroll_offset <= 0:
        return []

    def _handler(mouse_event):
        global _scroll_offset
        if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
            _scroll_offset = 0
            if _app:
                _app.invalidate()

    return [(C_INDICATOR, f"↓ {_scroll_offset} newer messages", _handler)]


class ListControl(FormattedTextControl):
    def mouse_handler(self, mouse_event):
        result = super().mouse_handler(mouse_event)
        if result is NotImplemented:
            global _scroll_offset
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                total       = len(_lines)
                rows        = inner_height(_term_rows())
                cols        = max(1, inner_width(_term_cols()))
                list_height = max(1, rows - (1 if _scroll_offset > 0 else 0))
                # Wrap-aware max_offset: walk forward from index 0 to find the
                # oldest entry that pins at the top when fully scrolled up.
                running    = 0
                max_offset = 0
                for i, line in enumerate(_lines):
                    running += _row_count(line, cols)
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


kb = KeyBindings()


@kb.add("q")
@kb.add("c-c")
def _quit(event):
    event.app.exit()


def _anchor_bottom(window):
    """Pin list content to the bottom of the window (clip-top for overflow)."""
    info = window.render_info
    if info is None:
        return 0
    return max(0, info.content_height - info.window_height)


def _read_tail(path, max_lines):
    """Read the last max_lines lines of path. Returns (lines, byte_offset, inode)."""
    try:
        with open(path, "rb") as fh:
            st   = os.fstat(fh.fileno())
            data = fh.read()
        lines = data.decode("utf-8", errors="replace").splitlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return lines, len(data), st.st_ino
    except OSError:
        return [], 0, None


async def _poll_log(app):
    global _lines, _byte_offset, _file_inode, _scroll_offset

    initial_lines, _byte_offset, _file_inode = _read_tail(UI_LOG_PATH, MAX_LINES)
    if initial_lines:
        _lines = initial_lines
        app.invalidate()

    while True:
        await asyncio.sleep(POLL_MS)

        try:
            st = os.stat(UI_LOG_PATH)
        except OSError:
            if _lines:
                _lines        = []
                _byte_offset  = 0
                _file_inode   = None
                app.invalidate()
            continue

        size  = st.st_size
        inode = st.st_ino

        if inode != _file_inode or size < _byte_offset:
            # Rotation or truncation — re-read from start
            new_lines, _byte_offset, _file_inode = _read_tail(UI_LOG_PATH, MAX_LINES)
            _lines = new_lines
            app.invalidate()
        elif size > _byte_offset:
            # New bytes appended
            try:
                with open(UI_LOG_PATH, "rb") as fh:
                    fh.seek(_byte_offset)
                    data = fh.read()
                _byte_offset += len(data)
                new_lines = data.decode("utf-8", errors="replace").splitlines()
                if new_lines:
                    if _scroll_offset > 0:
                        _scroll_offset += len(new_lines)
                    _lines.extend(new_lines)
                    if len(_lines) > MAX_LINES:
                        _lines = _lines[len(_lines) - MAX_LINES:]
                    app.invalidate()
            except OSError:
                pass


def main():
    global _app

    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()
    atexit.register(_restore_cursor)

    list_window = Window(
        content=ListControl(text=_list_text, focusable=False),
        wrap_lines=True,
        get_vertical_scroll=_anchor_bottom,
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text),
            height=1,
        ),
        filter=Condition(lambda: _scroll_offset > 0),
    )

    inner_root = HSplit([list_window, indicator_container])
    root       = pane_frame.framed(inner_root, "ui")
    layout     = Layout(root)

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
        color_depth=ColorDepth.DEPTH_24_BIT,
    )
    _app = app

    def _on_sigwinch(signum, frame):
        if _app:
            _app.invalidate()

    signal.signal(signal.SIGWINCH, _on_sigwinch)
    signal.signal(signal.SIGTERM, lambda s, f: (_restore_cursor(), sys.exit(0)))
    signal.signal(signal.SIGINT,  signal.SIG_IGN)

    async def _run():
        task       = asyncio.ensure_future(_poll_log(app))
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
