#!/usr/bin/env python3
# bridge/buffs_pane.py — affect grid renderer for the buffs pane.
# 4-per-row coloured grid grouped by type: spells (blue), buffs (green),
# debuffs (red). Within each group: untimed first (alphabetical), then timed
# by expires_at descending (alphabetical tie-break). Empty groups produce no
# rows. Row-based scroll via mouse wheel; sticky-bottom; overflow indicator.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
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
import math
import os
import signal
import sys
import time

BUFFS_STATE_PATH = os.environ.get(
    "BUFFS_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "buffs.state"),
)
POLL_MS = 0.1

# Spells — blue
C_SPELL_FILL_BG = "bg:#66b2ff"
C_SPELL_SEP_FG  = "fg:#66b2ff"

# Buffs — green
C_BUFF_FILL_BG  = "bg:#00d900"
C_BUFF_SEP_FG   = "fg:#00d900"

# Debuffs — red
C_DEBUFF_FILL_BG = "bg:#d90000"
C_DEBUFF_SEP_FG  = "fg:#d90000"

C_CELL_FG       = "fg:#000000"
C_INDICATOR     = "fg:#d4a04e italic"
C_NAME_DEPLETED = "fg:#1e1e1e bg:#000000"
C_SEP_DEPLETED  = "fg:#000000 bg:#000000"
C_NAME_HIDDEN   = "fg:#000000 bg:#000000"

# Each palette tuple: (filled_cell_style, filled_sep_style)
_PALETTES = {
    "spell":  (C_CELL_FG + " " + C_SPELL_FILL_BG,  C_SPELL_SEP_FG  + " bg:#000000"),
    "buff":   (C_CELL_FG + " " + C_BUFF_FILL_BG,   C_BUFF_SEP_FG   + " bg:#000000"),
    "debuff": (C_CELL_FG + " " + C_DEBUFF_FILL_BG,  C_DEBUFF_SEP_FG + " bg:#000000"),
}

_affects       = []
_last_mtime    = None
_app           = None
_scroll_offset = 0   # 0 = bottom (live-follow); N = N newer rows hidden


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


def _split_groups():
    spells  = sorted([e for e in _affects if e.get("type") == "spell"],  key=_sort_key)
    debuffs = sorted([e for e in _affects if e.get("type") == "debuff"], key=_sort_key)
    buffs   = sorted(
        [e for e in _affects if e.get("type") not in ("spell", "debuff")],
        key=_sort_key,
    )
    return spells, buffs, debuffs


def _total_rows(spells, buffs, debuffs):
    return (
        (math.ceil(len(spells)  / 4) if spells  else 0) +
        (math.ceil(len(buffs)   / 4) if buffs   else 0) +
        (math.ceil(len(debuffs) / 4) if debuffs else 0)
    )


def _cell_frags(entry, cell_w, palette):
    filled_style, sep_style = palette
    now               = time.time()
    expires_at        = entry.get("expires_at")
    expected_duration = entry.get("expected_duration")
    name              = entry.get("name", "")
    label             = name.upper()[: cell_w - 1].ljust(cell_w - 1)

    if expected_duration is None or expires_at is None:
        filled = cell_w
    else:
        remaining = expires_at - now
        pct       = max(0.0, min(1.0, remaining / expected_duration))
        filled    = int(pct * cell_w + 0.5)

    blinking = False
    if expected_duration is not None and expires_at is not None:
        remaining = expires_at - now
        blinking  = filled == 0 and remaining <= 30

    visible = int(now) % 2 == 0

    frags = []
    for i in range(cell_w - 1):
        ch = label[i]
        if i < filled:
            frags.append((filled_style, ch))
        elif blinking:
            frags.append((C_NAME_DEPLETED if visible else C_NAME_HIDDEN, ch))
        else:
            frags.append((C_NAME_DEPLETED, ch))

    if filled >= cell_w:
        frags.append((sep_style, "▌"))
    else:
        frags.append((C_SEP_DEPLETED, "▌"))

    return frags


def _build_all_rows():
    """Return every grid row as a list of fragment-lists (one per row)."""
    spells, buffs, debuffs = _split_groups()
    W      = max(4, _term_cols())
    widths = _cell_widths(W)

    all_rows = []
    for group, palette in (
        (spells,  _PALETTES["spell"]),
        (buffs,   _PALETTES["buff"]),
        (debuffs, _PALETTES["debuff"]),
    ):
        if not group:
            continue
        n = len(group)
        for row in range(math.ceil(n / 4)):
            row_frags = []
            for col in range(4):
                idx = row * 4 + col
                if idx >= n:
                    break
                row_frags.extend(_cell_frags(group[idx], widths[col], palette))
            all_rows.append(row_frags)

    return all_rows


def _grid_text():
    global _scroll_offset

    H        = max(1, _term_rows())
    all_rows = _build_all_rows()
    total    = len(all_rows)

    if total == 0:
        return []

    visible_capacity = max(1, H - (1 if _scroll_offset > 0 else 0))
    max_offset       = max(0, total - visible_capacity)
    _scroll_offset   = max(0, min(_scroll_offset, max_offset))

    anchor_idx = total - 1 - _scroll_offset
    start_idx  = max(0, anchor_idx - (visible_capacity - 1))
    visible    = all_rows[start_idx : anchor_idx + 1]

    frags = []
    for i, row_frags in enumerate(visible):
        if i > 0:
            frags.append(("", "\n"))
        frags.extend(row_frags)

    return frags


def _indicator_text():
    H     = max(1, _term_rows())
    total = _total_rows(*_split_groups())

    if _scroll_offset > 0:
        def _handler(mouse_event):
            global _scroll_offset
            if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                _scroll_offset = 0
                if _app:
                    _app.invalidate()
        return [(C_INDICATOR, f"↓ {_scroll_offset} newer rows", _handler)]

    if total > H:
        hidden = total - (H - 1)
        return [(C_INDICATOR, f"↓ {hidden} more rows")]

    return []


class ListControl(FormattedTextControl):
    def mouse_handler(self, mouse_event):
        global _scroll_offset
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            spells, buffs, debuffs = _split_groups()
            total            = _total_rows(spells, buffs, debuffs)
            H                = max(1, _term_rows())
            visible_capacity = max(1, H - (1 if _scroll_offset > 0 else 0))
            max_offset       = max(0, total - visible_capacity)
            _scroll_offset   = min(_scroll_offset + 1, max_offset)
            if _app:
                _app.invalidate()
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            if _scroll_offset > 0:
                _scroll_offset -= 1
            if _app:
                _app.invalidate()
            return None
        return super().mouse_handler(mouse_event)


def _anchor_bottom(window):
    """Pin list content to the bottom of the window (clip-top for overflow)."""
    info = window.render_info
    if info is None:
        return 0
    return max(0, info.content_height - info.window_height)


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


async def _poll_state(app):
    global _affects, _last_mtime, _scroll_offset

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
                    new_affects = loaded if isinstance(loaded, list) else []

                    if _scroll_offset > 0:
                        old_total = _total_rows(*_split_groups())
                        _affects  = new_affects
                        new_total = _total_rows(*_split_groups())
                        delta = new_total - old_total
                        if delta > 0:
                            H                = max(1, _term_rows())
                            visible_capacity = max(1, H - 1)
                            max_offset       = max(0, new_total - visible_capacity)
                            _scroll_offset   = min(_scroll_offset + delta, max_offset)
                    else:
                        _affects = new_affects
                except Exception:
                    pass
            else:
                _affects = []
            app.invalidate()

        await asyncio.sleep(POLL_MS)


async def _tick(app):
    """Invalidate just after each wall-clock second boundary so blink halves stay equal."""
    while True:
        now = time.time()
        await asyncio.sleep(1.0 - (now - int(now)) + 0.01)
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
        content=ListControl(text=_grid_text, focusable=False),
        get_vertical_scroll=_anchor_bottom,
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text, focusable=False),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _scroll_offset > 0 or _total_rows(*_split_groups()) > _term_rows()),
    )

    root   = HSplit([grid_window, indicator_container])
    layout = Layout(root)

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
