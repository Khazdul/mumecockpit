#!/usr/bin/env python3
# bridge/panes/group_pane.py — group member bars renderer.
# Three horizontal bars per member (HP / Mana / Moves) with a name overlay
# centred across the full row. Anchor-top; overflow indicator when clipped.
# Polling and prompt_toolkit patterns mirror timers_pane.py.

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
import os
import shutil
import signal
import sys

GROUP_STATE_PATH = os.environ.get(
    "GROUP_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "group.state"),
)
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
)
POLL_MS = 0.1

# ---------------------------------------------------------------------------
# Colour constants (24-bit truecolor; swap values here to retheme)
# ---------------------------------------------------------------------------
HP_DEFAULT_BG   = "#0FA838"
HP_DEFAULT_FG   = "#0FA838"
MANA_DEFAULT_BG = "#0F38B0"
MANA_DEFAULT_FG = "#0F38B0"
MP_DEFAULT_BG   = "#8A7838"
MP_DEFAULT_FG   = "#8A7838"
ORANGE_BG       = "#ff7020"
ORANGE_FG       = "#ff7020"
RED_BG          = "#e02020"
RED_FG          = "#e02020"

C_NAME_ON_FILL  = "fg:#000000"   # name char that falls inside the fill region
C_NAME_ON_EMPTY = "fg:#cccccc"   # name char that falls outside the fill region
C_INDICATOR     = "fg:#d4a04e italic"

# ---------------------------------------------------------------------------
# Renderer state
# ---------------------------------------------------------------------------
_members    = []
_last_mtime = None
_app        = None
_run_active = False


def _term_rows():
    try:
        return os.get_terminal_size().lines
    except OSError:
        return 24


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _bar_widths(total):
    """Distribute `total` columns across 3 bars, left-to-right rounding."""
    base  = total // 3
    extra = total %  3
    return [base + (1 if i < extra else 0) for i in range(3)]


def _bar_palette(pct, default_bg, default_fg):
    """Return style_fill for a bar based on pct threshold."""
    if pct is not None and pct <= 0.25:
        bg = RED_BG
    elif pct is not None and pct <= 0.45:
        bg = ORANGE_BG
    else:
        bg = default_bg
    return f"bg:{bg}"


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

def _member_frags(member, W):
    """Return prompt_toolkit fragments for one member row at terminal width W.

    Three bars fill all W columns (no name prefix column). The member name
    is left-aligned from column 0 across the row. Per-column style: black
    on bar-BG when the column is within that bar's fill, grey on terminal-BG
    when outside fill.
    """
    hp_pct   = member.get("hp_pct")
    mana_pct = member.get("mana_pct")
    mp_pct   = member.get("mp_pct")
    name     = member.get("label") or member.get("name") or ""

    bar_hp_w, bar_mana_w, bar_mp_w = _bar_widths(W)
    bar_widths_list = [bar_hp_w, bar_mana_w, bar_mp_w]
    bar_pcts        = [hp_pct, mana_pct, mp_pct]
    bar_default_bgs = [HP_DEFAULT_BG, MANA_DEFAULT_BG, MP_DEFAULT_BG]
    bar_default_fgs = [HP_DEFAULT_FG, MANA_DEFAULT_FG, MP_DEFAULT_FG]

    fills  = []
    styles = []
    for i in range(3):
        pct = bar_pcts[i]
        bw  = bar_widths_list[i]
        fills.append(int(pct * bw + 0.5) if pct is not None else 0)
        styles.append(_bar_palette(pct, bar_default_bgs[i], bar_default_fgs[i]))

    name_trunc = name[:W]
    name_start = 0
    name_end   = len(name_trunc)

    frags = []
    for c in range(W):
        if c < bar_hp_w:
            bi, local = 0, c
        elif c < bar_hp_w + bar_mana_w:
            bi, local = 1, c - bar_hp_w
        else:
            bi, local = 2, c - bar_hp_w - bar_mana_w

        bw         = bar_widths_list[bi]
        fill       = fills[bi]
        style_fill = styles[bi]

        if name_start <= c < name_end:
            ch = name_trunc[c - name_start]
            if local < fill:
                frags.append((C_NAME_ON_FILL + " " + style_fill, ch))
            else:
                frags.append((C_NAME_ON_EMPTY, ch))
        elif local < fill:
            frags.append((style_fill, " "))
        else:
            frags.append(("", " "))

    return frags


# ---------------------------------------------------------------------------
# prompt_toolkit text providers
# ---------------------------------------------------------------------------

def _rows_text():
    if not _run_active:
        return [("", "")]
    if not _members:
        return []
    W     = max(3, shutil.get_terminal_size().columns)
    H     = max(1, _term_rows())
    total = len(_members)
    # Reserve 1 row for the overflow indicator when it will be shown.
    list_height = H - 1 if total > H else H

    frags = []
    for i, member in enumerate(_members[:list_height]):
        if i > 0:
            frags.append(("", "\n"))
        frags.extend(_member_frags(member, W))
    return frags


def _indicator_text():
    if not _run_active:
        return [("", "")]
    total = len(_members)
    H     = max(1, _term_rows())
    if total > H:
        hidden = total - (H - 1)
        return [(C_INDICATOR, f"↓ {hidden} more members")]
    return []


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------

def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


async def _poll_state(app):
    global _members, _last_mtime, _run_active

    while True:
        try:
            mtime = os.stat(GROUP_STATE_PATH).st_mtime
        except OSError:
            mtime = None

        if mtime != _last_mtime:
            _last_mtime = mtime
            if mtime is not None:
                try:
                    with open(GROUP_STATE_PATH, "r") as fh:
                        loaded = json.load(fh)
                    _members = loaded.get("members", [])
                except Exception:
                    pass
            else:
                _members = []
            app.invalidate()

        new_run_active = os.path.exists(CONNECTION_STATE_PATH)
        if new_run_active != _run_active:
            _run_active = new_run_active
            app.invalidate()

        await asyncio.sleep(POLL_MS)


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

    rows_window = Window(
        content=FormattedTextControl(_rows_text, focusable=False),
        wrap_lines=False,
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text, focusable=False),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _run_active and len(_members) > _term_rows()),
    )

    root   = HSplit([rows_window, indicator_container])
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
        try:
            await app.run_async()
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
