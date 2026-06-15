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

import pane_frame
from pane_frame import inner_height, inner_width

GROUP_STATE_PATH = os.environ.get(
    "GROUP_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "group.state"),
)
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
)
STARTUP_CONF_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "startup.conf"
)
POLL_MS = 0.1

# ---------------------------------------------------------------------------
# Display-option keys (restated, not imported — bridge/panes shares no import
# path with bridge/launcher; see ADR 0126 and bridge/launcher/group_options.py).
#   group_show_players — "1" (default) / "0"
#   group_npc_mode     — "labeled" (default) / "off" / "all"; any unknown
#                        value is treated as labeled. "all" additionally shows
#                        unlabeled group-NPCs (the unlabeled_npcs list).
# ---------------------------------------------------------------------------
GROUP_SHOW_PLAYERS_KEY     = "group_show_players"
GROUP_NPC_MODE_KEY         = "group_npc_mode"
GROUP_SHOW_PLAYERS_DEFAULT = True
GROUP_NPC_MODE_DEFAULT     = "labeled"

# ---------------------------------------------------------------------------
# Colour constants (24-bit truecolor; swap values here to retheme)
# ---------------------------------------------------------------------------
HP_DEFAULT_BG   = "#005A18"
HP_DEFAULT_FG   = "#005A18"
MANA_DEFAULT_BG = "#0000AA"
MANA_DEFAULT_FG = "#0000AA"
MP_DEFAULT_BG   = "#5A3C1E"
MP_DEFAULT_FG   = "#5A3C1E"
ORANGE_BG       = "#ff7020"
ORANGE_FG       = "#ff7020"
RED_BG          = "#e02020"
RED_FG          = "#e02020"

C_NAME_ON_FILL  = "fg:#aaaaaa"   # name char that falls inside the fill region
C_NAME_ON_EMPTY = "fg:#aaaaaa"   # name char that falls outside the fill region
C_INDICATOR     = "fg:#d4a04e italic"

# ---------------------------------------------------------------------------
# Renderer state
# ---------------------------------------------------------------------------
_members      = []
_unlabeled    = []
_last_mtime   = None
_app          = None
_run_active   = False
_show_players = GROUP_SHOW_PLAYERS_DEFAULT
_npc_mode     = GROUP_NPC_MODE_DEFAULT
_conf_mtime   = None


def _read_display_options():
    """Re-read the two display-option keys from startup.conf. Missing file or
    keys fall through to the runtime defaults (players-on / NPC-labeled)."""
    global _show_players, _npc_mode
    show_players = GROUP_SHOW_PLAYERS_DEFAULT
    npc_mode     = GROUP_NPC_MODE_DEFAULT
    try:
        with open(STARTUP_CONF_PATH) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if key == GROUP_SHOW_PLAYERS_KEY:
                    show_players = (val != "0")
                elif key == GROUP_NPC_MODE_KEY:
                    npc_mode = val if val in ("off", "labeled", "all") else "labeled"
    except OSError:
        pass
    _show_players = show_players
    _npc_mode     = npc_mode


def _displayed_members():
    """Presentation-only filter over the raw member set:
      - allies (players) included iff group_show_players is on;
      - labeled NPCs included iff group_npc_mode is not "off";
      - in group_npc_mode == "all", unlabeled group-NPCs are appended too;
      - any other / unknown type is kept (defensive parity with the collector).
    The combined set is id-sorted so members and unlabeled NPCs interleave.
    """
    out = []
    for m in _members:
        t = m.get("type")
        if t == "ally":
            if _show_players:
                out.append(m)
        elif t == "npc":
            if _npc_mode != "off":
                out.append(m)
        else:
            out.append(m)
    if _npc_mode == "all":
        out.extend(_unlabeled)
    out.sort(key=lambda m: m.get("id") if isinstance(m.get("id"), (int, float)) else float("inf"))
    return out


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
    # Overlay text: labeled NPCs render as "Name (LABEL)"; players and any
    # other type render as the bare name (no player labels).
    name     = member.get("name") or ""
    if member.get("type") == "npc":
        label = member.get("label")
        if isinstance(label, str) and label:
            name = f"{name} ({label})"

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
    members = _displayed_members()
    if not members:
        return []
    W     = max(3, inner_width(shutil.get_terminal_size().columns))
    H     = max(1, inner_height(_term_rows()))
    total = len(members)
    # Reserve 1 row for the overflow indicator when it will be shown.
    list_height = H - 1 if total > H else H

    frags = []
    for i, member in enumerate(members[:list_height]):
        if i > 0:
            frags.append(("", "\n"))
        frags.extend(_member_frags(member, W))
    return frags


def _indicator_text():
    if not _run_active:
        return [("", "")]
    total = len(_displayed_members())
    H     = max(1, inner_height(_term_rows()))
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
    global _members, _unlabeled, _last_mtime, _run_active, _conf_mtime

    while True:
        try:
            conf_mtime = os.stat(STARTUP_CONF_PATH).st_mtime
        except OSError:
            conf_mtime = None
        if conf_mtime != _conf_mtime:
            _conf_mtime = conf_mtime
            _read_display_options()
            app.invalidate()

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
                    _members   = loaded.get("members", [])
                    _unlabeled = loaded.get("unlabeled_npcs", [])
                except Exception:
                    pass
            else:
                _members   = []
                _unlabeled = []
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
        filter=Condition(lambda: _run_active and len(_displayed_members()) > inner_height(_term_rows())),
    )

    inner_root = HSplit([rows_window, indicator_container])
    root       = pane_frame.framed(inner_root, "group")
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
        poll_task  = asyncio.ensure_future(_poll_state(app))
        frame_task = pane_frame.start_poll(app)
        try:
            await app.run_async()
        finally:
            poll_task.cancel()
            frame_task.cancel()
            for t in (poll_task, frame_task):
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    asyncio.run(_run())


if __name__ == "__main__":
    main()
