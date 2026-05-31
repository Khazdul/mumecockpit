#!/usr/bin/env python3
# bridge/panes/buffs_pane.py — affect grid renderer for the buffs pane.
# 4-per-row coloured grid grouped by type: spells (blue), buffs (green),
# debuffs (red). Within each group: untimed first (alphabetical), then timed
# by expires_at descending (alphabetical tie-break). Empty groups produce no
# rows. Row-based scroll via mouse wheel; anchor-top; bidirectional overflow indicator.

try:
    from prompt_toolkit import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import (
        ConditionalContainer,
        Float,
        FloatContainer,
        HSplit,
        Window,
    )
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
import subprocess
import sys
import time

BUFFS_STATE_PATH = os.environ.get(
    "BUFFS_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "buffs.state"),
)
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
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

# Stored — magenta; untracked variant grey
C_STORED_FILL_BG         = "bg:#ff66ff"
C_STORED_SEP_FG          = "fg:#ff66ff"
C_STORED_UNTRACKED_BG    = "bg:#cccccc"
C_STORED_UNTRACKED_FG    = "fg:#cccccc"

# Blinds — cyan (distinct from the spell light-blue)
C_BLIND_FILL_BG = "bg:#00cccc"
C_BLIND_SEP_FG  = "fg:#00cccc"

# Charms — one per row, no bar (see _charm_row_frags)
C_CHARM_NAME_FG = "fg:#B388FF"   # light violet — matches the char_ui CHARM tag (Step 4)
C_CHARM_MINS_FG = "fg:#888888"   # darker grey
C_CHARM_X_FG    = "fg:#CC5555"   # muted red (not a screaming red)
C_CHARM_X_HOVER_FG = "fg:#E88888"   # lighter than C_CHARM_X_FG — hover cue

# Herblore add-view accent — shared by the grid ⊕ overlay and the add-view ╳
# (gold, matches the overflow indicator; deliberately NOT the charm red).
C_ACCENT_FG        = "fg:#d4a04e"   # gold — add ⊕ and close ╳
C_ACCENT_HOVER_FG  = "fg:#f0c070"   # brighter gold on hover
# Add-view catalog rows — per-fragment "[±] Name" styling.
C_HERB_BRACKET     = "fg:#666666"   # dark grey  [ ]
C_HERB_ADD         = "fg:#7ED07E"   # light green + (inactive row)
C_HERB_REMOVE      = "fg:#E88888"   # light red  - (active row)
C_HERB_NAME        = "fg:#999999"   # medium grey name
C_HERB_NAME_HOVER  = "fg:#cccccc"   # name on hover

C_CELL_FG       = "fg:#000000"
C_INDICATOR     = "fg:#d4a04e italic"
C_NAME_DEPLETED = "fg:#666666"
# Untracked affect cells (reconciled from stat/info, no observed timing yet):
# render with no bar fill and a darker grey than the depleted-name grey, so
# they read as "present but unknown duration" without looking like the
# untracked-stored grey bar.
C_NAME_UNTRACKED_AFFECT = "fg:#3a3a3a"

# Each palette tuple: (filled_cell_style, filled_sep_style)
_PALETTES = {
    "spell":  (C_CELL_FG + " " + C_SPELL_FILL_BG,  C_SPELL_SEP_FG),
    "buff":   (C_CELL_FG + " " + C_BUFF_FILL_BG,   C_BUFF_SEP_FG),
    "debuff": (C_CELL_FG + " " + C_DEBUFF_FILL_BG,  C_DEBUFF_SEP_FG),
    "stored": (C_CELL_FG + " " + C_STORED_FILL_BG,  C_STORED_SEP_FG),
    "blind":  (C_CELL_FG + " " + C_BLIND_FILL_BG,   C_BLIND_SEP_FG),
}

_affects          = []
_stored_spells    = []
_blinds           = []
_charms           = []
_herblores        = []
_herblore_catalog = []   # static catalog keys, for the add-view
_last_mtime    = None
_app           = None
_scroll_offset = 0   # 0 = top (first row at top of pane); N = N rows hidden above
_run_active    = False
_hover_charm_id = None   # charm id whose X the pointer is currently over (hover cue)

_view_mode          = "grid"   # "grid" | "add" — add-view is the herblore picker
_hover_plus         = False    # pointer is over the ⊕ overlay button
_hover_herblore_key = None     # catalog key whose row the pointer is over
_hover_close        = False    # pointer is over the add-view's X (return-to-grid)


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


def _blind_cell_widths(W):
    base  = W // 2
    extra = W % 2
    return [base + (1 if i < extra else 0) for i in range(2)]


def _split_groups():
    spells  = sorted([e for e in _affects if e.get("type") == "spell"],  key=_sort_key)
    # Herblores render as ordinary affect cells: the current phase's type routes
    # it into the debuff or buff group, so it moves between groups by itself when
    # a phase flips type. They carry name/type/expires_at/expected_duration, so
    # _cell_frags renders palette and bar-drain unchanged.
    debuff_src = [e for e in _affects if e.get("type") == "debuff"]
    buff_src   = [e for e in _affects if e.get("type") not in ("spell", "debuff")]
    for h in _herblores:
        if h.get("type") == "debuff":
            debuff_src.append(h)
        else:
            buff_src.append(h)
    debuffs = sorted(debuff_src, key=_sort_key)
    buffs   = sorted(buff_src,   key=_sort_key)
    tracked   = sorted(
        [e for e in _stored_spells if e.get("tracked")],
        key=lambda e: (-(e.get("expires_at") or 0), e.get("name", "").lower()),
    )
    untracked = sorted(
        [e for e in _stored_spells if not e.get("tracked")],
        key=lambda e: e.get("name", "").lower(),
    )
    stored = tracked + untracked
    blinds = sorted(
        _blinds,
        key=lambda e: (-(e.get("expires_at") or 0), e.get("name", "").lower()),
    )
    # Charms render one per row, oldest first (ascending started_at) so the
    # longest-running — most likely stale — sits at the top.
    charms = sorted(_charms, key=lambda e: (e.get("started_at") or 0))
    return spells, buffs, debuffs, stored, blinds, charms


def _total_rows(spells, buffs, debuffs, stored, blinds, charms):
    return (
        (math.ceil(len(spells)  / 4) if spells  else 0) +
        (math.ceil(len(buffs)   / 4) if buffs   else 0) +
        (math.ceil(len(debuffs) / 4) if debuffs else 0) +
        (math.ceil(len(stored)  / 4) if stored  else 0) +
        (math.ceil(len(blinds)  / 2) if blinds  else 0) +
        len(charms)
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
        elif blinking and not visible:
            frags.append(("", " "))
        else:
            frags.append((C_NAME_DEPLETED, ch))

    if filled >= cell_w:
        frags.append((sep_style, "▌"))
    else:
        frags.append(("", " "))

    return frags


def _untracked_cell_frags(entry, cell_w):
    name  = entry.get("name", "")
    label = name.upper()[:cell_w - 1].ljust(cell_w - 1)
    frags = [("fg:#000000 bg:#cccccc", ch) for ch in label]
    frags.append((C_STORED_UNTRACKED_FG, "▌"))
    return frags


def _untracked_affect_cell_frags(entry, cell_w):
    """No bar, darker-grey name, no blink — see C_NAME_UNTRACKED_AFFECT."""
    name  = entry.get("name", "")
    label = name.upper()[:cell_w - 1].ljust(cell_w - 1)
    frags = [(C_NAME_UNTRACKED_AFFECT, ch) for ch in label]
    frags.append(("", " "))
    return frags


def _send_charm_drop(cid):
    """Fire-and-forget: reach the game/tt++ pane to invoke the Step-4 drop alias.

    Reuses the same tmux send-keys channel input_pane.py forwards keystrokes
    through. Never blocks or raises into the render loop; the state file stays
    authoritative, so the row disappears only once tt++ rewrites buffs.state.
    """
    if cid is None:
        return
    target = "mume:cockpit.0"   # the game/tt++ pane — same target input_pane.py forwards to
    try:
        # Match input_pane.py's send(): one send-keys call, line and Enter
        # together, no -l — keeps the command out of the tt++ window.
        subprocess.run(["tmux", "send-keys", "-t", target, f"_cp_charm_drop {cid}", "Enter"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass


def _send_herblore(action, key):
    """Fire-and-forget: invoke the PR-1 add/remove alias in the game/tt++ pane.

    Mirrors _send_charm_drop. No optimistic UI update — the [+]/[-] flips on the
    next poll once Lua rewrites buffs.state (~100 ms lag). Catalog keys are
    single tokens, so no quoting is needed.
    """
    if not key:
        return
    alias  = "_cp_herblore_add" if action == "add" else "_cp_herblore_remove"
    target = "mume:cockpit.0"   # the game/tt++ pane — same target input_pane.py forwards to
    try:
        subprocess.run(["tmux", "send-keys", "-t", target, f"{alias} {key}", "Enter"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        pass


def _charm_row_frags(entry, W):
    """One charm per row, full width, no bar: name (violet) · mins (grey) · × (red)."""
    cid        = entry.get("id")
    name       = entry.get("name", "")
    started_at = entry.get("started_at")
    if entry.get("expires_at") is None:
        mins_txt = "   "                        # permanent controlled mob — no timer shown
    else:
        mins = 0
        if started_at:
            mins = min(99, int((time.time() - started_at) // 60))
        mins_txt = f"{mins}m".rjust(3)          # " 0m" .. "99m"
    name_w     = max(0, W - 6)                  # 1 X + 1 gap + 3 mins + 1 gap
    disp       = (name[:1].upper() + name[1:]) if name else name   # capitalise first letter
    name_txt   = disp[:name_w].ljust(name_w)    # preserve inner case (mob long-name)

    frags = [(C_CHARM_NAME_FG, ch) for ch in name_txt]
    frags.append(("", " "))
    frags.extend((C_CHARM_MINS_FG, ch) for ch in mins_txt)
    frags.append(("", " "))

    x_style = C_CHARM_X_HOVER_FG if cid == _hover_charm_id else C_CHARM_X_FG
    def _x_handler(mouse_event, _cid=cid):      # capture id via default arg —
        global _hover_charm_id                  # avoids the loop late-bind bug
        if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
            _send_charm_drop(_cid)
        elif mouse_event.event_type == MouseEventType.MOUSE_MOVE:
            if _hover_charm_id != _cid:
                _hover_charm_id = _cid
                if _app:
                    _app.invalidate()
    frags.append((x_style, "×", _x_handler))
    return frags


def _build_all_rows():
    """Return every grid row as a list of fragment-lists (one per row)."""
    spells, buffs, debuffs, stored, blinds, charms = _split_groups()
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
                entry = group[idx]
                if entry.get("tracked") is False:
                    row_frags.extend(_untracked_affect_cell_frags(entry, widths[col]))
                else:
                    row_frags.extend(_cell_frags(entry, widths[col], palette))
            all_rows.append(row_frags)

    if stored:
        n = len(stored)
        for row in range(math.ceil(n / 4)):
            row_frags = []
            for col in range(4):
                idx = row * 4 + col
                if idx >= n:
                    break
                entry = stored[idx]
                if entry.get("tracked"):
                    row_frags.extend(_cell_frags(entry, widths[col], _PALETTES["stored"]))
                else:
                    row_frags.extend(_untracked_cell_frags(entry, widths[col]))
            all_rows.append(row_frags)

    if blinds:
        blind_widths = _blind_cell_widths(W)
        n = len(blinds)
        for row in range(math.ceil(n / 2)):
            row_frags = []
            for col in range(2):
                idx = row * 2 + col
                if idx >= n:
                    break
                row_frags.extend(_cell_frags(blinds[idx], blind_widths[col], _PALETTES["blind"]))
            all_rows.append(row_frags)

    for c in charms:
        all_rows.append(_charm_row_frags(c, W))

    return all_rows


def _open_handler(mouse_event):
    global _view_mode, _scroll_offset, _hover_plus, _hover_close
    if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
        _view_mode     = "add"
        _scroll_offset = 0          # every view switch starts at the top
        if _app:
            _app.invalidate()
    elif mouse_event.event_type == MouseEventType.MOUSE_MOVE:
        if not _hover_plus or _hover_close:
            _hover_plus  = True
            _hover_close = False
            if _app:
                _app.invalidate()


def _close_handler(mouse_event):
    global _view_mode, _scroll_offset, _hover_plus, _hover_close
    if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
        _view_mode     = "grid"
        _scroll_offset = 0          # every view switch starts at the top
        if _app:
            _app.invalidate()
    elif mouse_event.event_type == MouseEventType.MOUSE_MOVE:
        if not _hover_close or _hover_plus:
            _hover_close = True
            _hover_plus  = False
            if _app:
                _app.invalidate()


def _corner_text():
    """The position-pinned ⊕/╳ corner control (owned by a top-right Float, not by
    any row). No background on the fragment, so it renders on the pane's default
    window bg, overwriting whatever cell sits beneath it. Blank when the run is
    inactive; ⊕ (open add-view) in grid mode, ╳ (return to grid) in add mode."""
    if not _run_active:
        return []
    if _view_mode == "add":
        fg = C_ACCENT_HOVER_FG if _hover_close else C_ACCENT_FG
        return [(fg, "╳", _close_handler)]
    fg = C_ACCENT_HOVER_FG if _hover_plus else C_ACCENT_FG
    return [(fg, "⊕", _open_handler)]


def _add_view_frags():
    """The herblore picker: one [+]/[-] toggle row per catalog key. The return-to-
    grid ╳ is NOT drawn here — the top-right corner Float owns it (see
    _corner_text). Mouse-driven, no keybindings. Click flips add/remove via the
    PR-1 aliases; the row label follows the state file on the next poll. Paginated
    by _scroll_offset exactly like _grid_text, so the overflow indicator works in
    this view too."""
    global _scroll_offset
    H      = max(1, _term_rows())
    W      = max(4, _term_cols())
    active = {e.get("key") for e in _herblores}

    all_rows = []
    for key in _herblore_catalog:
        is_active  = key in active
        sign       = "-" if is_active else "+"
        sign_style = C_HERB_REMOVE if is_active else C_HERB_ADD
        name_style = C_HERB_NAME_HOVER if key == _hover_herblore_key else C_HERB_NAME
        name_w     = max(0, W - 3)              # 3 = "[" + sign + "]"
        name_txt   = (" " + str(key))[:name_w].ljust(name_w)

        def _row_handler(mouse_event, _key=key, _active=is_active):
            global _hover_herblore_key
            if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                _send_herblore("remove" if _active else "add", _key)
            elif mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                if _hover_herblore_key != _key:
                    _hover_herblore_key = _key
                    if _app:
                        _app.invalidate()

        # The toggle handler rides every fragment, so the whole row is clickable.
        all_rows.append([
            (C_HERB_BRACKET, "[",      _row_handler),
            (sign_style,     sign,     _row_handler),
            (C_HERB_BRACKET, "]",      _row_handler),
            (name_style,     name_txt, _row_handler),
        ])

    total          = len(all_rows)
    list_height    = H - (1 if (_scroll_offset > 0 or total > H) else 0)
    max_offset     = max(0, total - list_height)
    _scroll_offset = max(0, min(_scroll_offset, max_offset))
    start_idx      = _scroll_offset
    end_idx        = min(total, start_idx + list_height)
    visible        = all_rows[start_idx:end_idx]

    frags = []
    for i, row_frags in enumerate(visible):
        if i > 0:
            frags.append(("", "\n"))
        frags.extend(row_frags)
    return frags


def _list_text():
    """Text provider for the ListControl: dispatch grid vs add-view."""
    if not _run_active:
        return [("", "")]
    if _view_mode == "add":
        return _add_view_frags()
    return _grid_text()


def _grid_text():
    global _scroll_offset

    if not _run_active:
        return [("", "")]

    H        = max(1, _term_rows())
    W        = max(4, _term_cols())
    all_rows = _build_all_rows()
    total    = len(all_rows)

    if total == 0:
        # Run active but no rows: the corner Float still shows the ⊕ over a blank pane.
        return [("", "")]

    list_height    = H - (1 if (_scroll_offset > 0 or total > H) else 0)
    max_offset     = max(0, total - list_height)
    _scroll_offset = max(0, min(_scroll_offset, max_offset))
    start_idx      = _scroll_offset
    end_idx        = min(total, start_idx + list_height)
    visible        = all_rows[start_idx:end_idx]

    frags = []
    for i, row_frags in enumerate(visible):
        if i > 0:
            frags.append(("", "\n"))
        frags.extend(row_frags)

    return frags


def _current_total_rows():
    """Logical row count for the active view — drives the overflow indicator and
    the scroll clamp in both views. Grid: the grouped grid rows. Add: one row per
    catalog key (the X shares the first row, so it adds none); an empty catalog
    still yields the single blank X row."""
    if _view_mode == "add":
        return max(1, len(_herblore_catalog))
    return _total_rows(*_split_groups())


def _indicator_text():
    if not _run_active:
        return [("", "")]

    H     = max(1, _term_rows())
    total = _current_total_rows()

    if _scroll_offset > 0:
        def _handler(mouse_event):
            global _scroll_offset
            if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                _scroll_offset = 0
                if _app:
                    _app.invalidate()
        return [(C_INDICATOR, f"↑ {_scroll_offset} rows above", _handler)]

    if total > H:
        hidden = total - (H - 1)
        return [(C_INDICATOR, f"↓ {hidden} more rows")]

    return []


class ListControl(FormattedTextControl):
    def mouse_handler(self, mouse_event):
        global _scroll_offset, _hover_charm_id, _hover_plus, _hover_herblore_key, _hover_close
        # Let fragment handlers (the charm ×, ⊕, add-view rows) fire first — mirrors ui_pane.py.
        result = super().mouse_handler(mouse_event)
        if result is not NotImplemented:
            return result
        # No fragment handled it: a move landed on a non-interactive cell — clear hover.
        if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
            changed = False
            if _hover_charm_id is not None:
                _hover_charm_id = None
                changed = True
            if _hover_plus:
                _hover_plus = False
                changed = True
            if _hover_herblore_key is not None:
                _hover_herblore_key = None
                changed = True
            if _hover_close:
                _hover_close = False
                changed = True
            if changed and _app:
                _app.invalidate()
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            total          = _current_total_rows()
            H              = max(1, _term_rows())
            list_height    = H - (1 if (_scroll_offset > 0 or total > H) else 0)
            max_offset     = max(0, total - list_height)
            _scroll_offset = min(_scroll_offset + 1, max_offset)
            if _app:
                _app.invalidate()
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            if _scroll_offset > 0:
                _scroll_offset -= 1
            if _app:
                _app.invalidate()
            return None
        return NotImplemented


def _restore_cursor():
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


async def _poll_state(app):
    global _affects, _stored_spells, _blinds, _charms, _herblores, _herblore_catalog
    global _last_mtime, _run_active, _scroll_offset
    global _view_mode, _hover_plus, _hover_herblore_key, _hover_close, _hover_charm_id

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
                        _affects          = loaded
                        _stored_spells    = []
                        _blinds           = []
                        _charms           = []
                        _herblores        = []
                        _herblore_catalog = []
                    else:
                        _affects          = loaded.get("affects", [])
                        _stored_spells    = loaded.get("stored_spells", [])
                        _blinds           = loaded.get("blinds", [])
                        _charms           = loaded.get("charms", [])
                        _herblores        = loaded.get("herblores", [])
                        _herblore_catalog = loaded.get("herblore_catalog", [])
                except Exception:
                    pass
            else:
                _affects          = []
                _stored_spells    = []
                _blinds           = []
                _charms           = []
                _herblores        = []
                _herblore_catalog = []
            app.invalidate()

        new_run_active = os.path.exists(CONNECTION_STATE_PATH)
        if new_run_active != _run_active:
            if not new_run_active:
                # Disconnect mid-add-view: fall back to the grid and drop hover cues.
                _view_mode          = "grid"
                _scroll_offset      = 0
                _hover_plus         = False
                _hover_herblore_key = None
                _hover_close        = False
                _hover_charm_id     = None
            _run_active = new_run_active
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
        content=ListControl(text=_list_text, focusable=False),
    )

    indicator_container = ConditionalContainer(
        content=Window(
            content=FormattedTextControl(_indicator_text, focusable=False),
            height=1,
            dont_extend_height=True,
        ),
        filter=Condition(lambda: _run_active and (_scroll_offset > 0 or _current_total_rows() > _term_rows())),
    )

    corner_float = Float(
        top=0,
        right=0,
        content=Window(
            content=FormattedTextControl(_corner_text, focusable=False),
            width=1,
            height=1,
            dont_extend_width=True,
            dont_extend_height=True,
        ),
    )
    root = FloatContainer(
        content=HSplit([grid_window, indicator_container]),
        floats=[corner_float],
    )
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
