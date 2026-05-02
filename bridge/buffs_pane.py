#!/usr/bin/env python3
# bridge/buffs_pane.py — affect grid renderer for the buffs pane.
# 4-per-row coloured grid: untimed group first (alphabetical by name),
# then timed group by expires_at descending (alphabetical tie-break).
# Overflow indicator on last row when not all rows fit.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.output import ColorDepth
except ImportError:
    print("Error: prompt_toolkit is not installed.")
    print("Run: pip install prompt_toolkit --break-system-packages")
    exit(1)

import asyncio
import atexit
import json
import math
import os
import signal
import sys

BUFFS_STATE_PATH = os.environ.get(
    "BUFFS_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "buffs.state"),
)
POLL_MS = 0.1

C_CELL_BG   = "bg:#66b2ff"
C_CELL_FG   = "fg:#000000"
C_SEP       = "fg:#66b2ff bg:#000000"
C_INDICATOR = "fg:#d4a04e italic"

C_CELL = C_CELL_FG + " " + C_CELL_BG

_affects    = []
_last_mtime = None
_app        = None


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


def _sort_key(e):
    ea = e.get("expires_at")
    if ea is None:
        return (0, e.get("name", "").lower())
    return (1, -ea, e.get("name", "").lower())


def _cell_widths(W):
    base = W // 4
    rem  = W % 4
    return [base + 1] * rem + [base] * (4 - rem)


def _is_overflow():
    n = len(_affects)
    if n == 0:
        return False
    H           = max(1, _term_rows())
    total_rows  = math.ceil(n / 4)
    return total_rows > H


def _grid_text():
    sorted_affects = sorted(_affects, key=_sort_key)
    n              = len(sorted_affects)
    W              = max(4, _term_cols())
    H              = max(1, _term_rows())
    widths         = _cell_widths(W)

    total_rows   = math.ceil(n / 4) if n > 0 else 0
    overflow     = total_rows > H
    visible_rows = (H - 1) if overflow else total_rows

    frags = []
    for row in range(visible_rows):
        if row > 0:
            frags.append(("", "\n"))
        for col in range(4):
            idx = row * 4 + col
            if idx >= n:
                break
            entry  = sorted_affects[idx]
            name   = entry.get("name", "")
            cell_w = widths[col]
            label  = name.upper()[: cell_w - 1].ljust(cell_w - 1)
            frags.append((C_CELL, label))
            frags.append((C_SEP, "▌"))

    return frags


def _indicator_text():
    n = len(_affects)
    if n == 0:
        return []
    H          = max(1, _term_rows())
    total_rows = math.ceil(n / 4)
    if total_rows <= H:
        return []
    hidden = total_rows - (H - 1)
    return [(C_INDICATOR, f"↓ {hidden} more rows")]


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


async def _poll_state(app):
    global _affects, _last_mtime

    while True:
        try:
            mtime = os.stat(BUFFS_STATE_PATH).st_mtime
        except OSError:
            mtime = None

        if mtime != _last_mtime:
            _last_mtime = mtime
            if mtime is not None:
                try:
                    with open(BUFFS_STATE_PATH, "r") as fh:
                        loaded = json.load(fh)
                    if isinstance(loaded, list):
                        _affects = loaded
                    else:
                        _affects = []
                except Exception:
                    pass
            else:
                _affects = []
            app.invalidate()

        await asyncio.sleep(POLL_MS)


async def _tick(app):
    """Unconditional 1 Hz redraw — keeps sort order fresh as expires_at values move."""
    while True:
        await asyncio.sleep(1.0)
        app.invalidate()


kb = KeyBindings()


@kb.add("q")
@kb.add("c-c")
def _quit(event):
    event.app.exit()


def main():
    global _app

    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()
    atexit.register(_restore_cursor)

    grid_window = Window(
        content=FormattedTextControl(text=_grid_text, focusable=False),
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text, focusable=False),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(_is_overflow),
    )

    root   = HSplit([grid_window, indicator_container])
    layout = Layout(root)

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=False,
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
        poll_task = asyncio.ensure_future(_poll_state(app))
        tick_task = asyncio.ensure_future(_tick(app))
        try:
            await app.run_async()
        finally:
            for task in (poll_task, tick_task):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
