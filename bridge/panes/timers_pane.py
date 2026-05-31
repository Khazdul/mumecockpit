#!/usr/bin/env python3
# bridge/panes/timers_pane.py — affect grid renderer for the timers pane.
# Coloured grid grouped by type: spells (blue), buffs (green), debuffs (red),
# stored (magenta), blinds (cyan), charms (violet). Within each group: untimed
# first (alphabetical), then timed by expires_at descending (alphabetical
# tie-break). Empty groups produce no rows. Group colours, per-group column
# counts, and per-group visibility are read from bridge/runtime/timers_layout.conf
# (defaults below reproduce the historic hardcoded behaviour when the file is
# absent). Row-based scroll via mouse wheel; anchor-top; bidirectional overflow indicator.

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
import re
import signal
import subprocess
import sys
import time

TIMERS_STATE_PATH = os.environ.get(
    "TIMERS_STATE_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "timers.state"),
)
TIMERS_LAYOUT_PATH = os.environ.get(
    "TIMERS_LAYOUT_PATH",
    os.path.join(os.environ["HOME"], "MUME", "bridge", "runtime", "timers_layout.conf"),
)
CONNECTION_STATE_PATH = os.path.join(
    os.environ["HOME"], "MUME", "bridge", "runtime", "connection.state"
)
POLL_MS = 0.1

# Group fill/separator colours are read from timers_layout.conf (see
# _LAYOUT_DEFAULTS / _palette below). The historic hardcoded values now live as
# the per-type defaults in _LAYOUT_DEFAULTS.

# Stored untracked variant — fixed grey, NOT themed: the grey is a degraded-state
# signal (post magic-blast), not a colour choice, so it ignores the config.
C_STORED_UNTRACKED_BG    = "bg:#cccccc"
C_STORED_UNTRACKED_FG    = "fg:#cccccc"

# Charms — no bar (see _charm_cell_frags). The name FG is themed from
# layout["charm"].color; the minutes and × keep these fixed colours.
C_CHARM_MINS_FG = "fg:#888888"   # darker grey
C_CHARM_X_FG    = "fg:#CC5555"   # muted red (not a screaming red)
C_CHARM_X_HOVER_FG = "fg:#E88888"   # lighter than C_CHARM_X_FG — hover cue

# Herblore add-view accent — shared by the grid + button and the add-view ×.
# Gold glyph on the terminal/pane background (gold matches the overflow
# indicator; deliberately NOT the charm red).
C_ACCENT_FG       = "fg:#d4a04e"   # gold glyph on the terminal/pane bg
C_ACCENT_HOVER_FG = "fg:#f0c070"   # brighter gold glyph on hover
# Add-view catalog rows — per-fragment "[±] Name" styling.
C_HERB_BRACKET     = "fg:#666666"   # dark grey  [ ]
C_HERB_ADD         = "fg:#7ED07E"   # light green + (inactive row)
C_HERB_REMOVE      = "fg:#E88888"   # light red  - (active row)
C_HERB_NAME        = "fg:#999999"   # medium grey name
C_HERB_NAME_HOVER  = "fg:#cccccc"   # name on hover

C_CELL_FG       = "fg:#000000"
# Group header label rows ("Spells:" etc). fg ONLY — no bg — so the label
# renders directly on the tmux pane bg tint. Mid grey, unified with the char
# (status) pane's data-row labels (status_pane.C_LABEL = #606060); keep the two
# in sync. Legible on every PANE_COLORS tint (tightest against grey #161616).
C_GROUP_HEADER_FG = "fg:#606060"
C_INDICATOR     = "fg:#d4a04e italic"
C_NAME_DEPLETED = "fg:#666666"
# Untracked affect cells (reconciled from stat/info, no observed timing yet):
# render with no bar fill and a darker grey than the depleted-name grey, so
# they read as "present but unknown duration" without looking like the
# untracked-stored grey bar.
C_NAME_UNTRACKED_AFFECT = "fg:#3a3a3a"

# Layout config (bridge/runtime/timers_layout.conf). Each type carries an
# enabled flag, a #rrggbb colour, and a per-group column count. The defaults
# below reproduce the historic hardcoded grid exactly, so an absent config file
# (or any missing key) leaves the pane visually unchanged.
_LAYOUT_TYPES    = ("spell", "buff", "debuff", "stored", "blind", "charm")
_LAYOUT_DEFAULTS = {
    "spell":  {"enabled": True, "color": "#66b2ff", "cols": 4},
    "buff":   {"enabled": True, "color": "#00d900", "cols": 4},
    "debuff": {"enabled": True, "color": "#d90000", "cols": 4},
    "stored": {"enabled": True, "color": "#ff66ff", "cols": 4},
    "blind":  {"enabled": True, "color": "#00cccc", "cols": 2},
    "charm":  {"enabled": True, "color": "#B388FF", "cols": 1},
}
# Group header labels above each rendered group. GLOBAL toggle (not per-type):
# True (default) renders a dim "Group:" label row above each rendered (enabled
# and non-empty) group — the header row doubles as the separator, so there are
# no blank rows; False = historic dense layout (no headers, no blanks). Restated
# here and in bridge/launcher/timers_layout_grid.py — the two packages share no
# import path (same cross-package reason as _LAYOUT_DEFAULTS; see ADR 0126).
TIMERS_HEADERS_DEFAULT = True

# Display names for each group's header row, mirroring
# timers_layout_grid.TIMERS_LAYOUT_LABELS. Restated locally for the same
# cross-package reason as _LAYOUT_DEFAULTS (the two packages share no import
# path; see ADR 0126).
_GROUP_LABELS = {
    "spell":  "Spells",
    "buff":   "Buffs",
    "debuff": "Debuffs",
    "stored": "Stored",
    "blind":  "Blinds",
    "charm":  "Charmies",
}
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clamp_cols(typ, raw):
    """Parse and clamp a cols value: charm → [1, 2]; others → [1, 6]; floor 1.
    Returns None when unparseable (caller keeps the type's default)."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    lo, hi = (1, 2) if typ == "charm" else (1, 6)
    return max(lo, min(hi, n))


def _load_layout():
    """Resolve the layout dict from _LAYOUT_DEFAULTS overridden by
    timers_layout.conf (key=value, one per line; same trivial format as
    startup.conf). Unknown keys are ignored; an unparseable value falls back to
    that key's default. Keys: timers_<type>_{enabled,color,cols} plus the
    global timers_headers. Returns (layout, headers); an absent or unparseable
    timers_headers resolves to TIMERS_HEADERS_DEFAULT."""
    layout = {t: dict(v) for t, v in _LAYOUT_DEFAULTS.items()}
    headers = TIMERS_HEADERS_DEFAULT
    try:
        with open(TIMERS_LAYOUT_PATH, "r") as fh:
            raw = fh.read()
    except OSError:
        return layout, headers
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # timers_headers is a global toggle with no second underscore, so it
        # must branch before the type-split below (which would drop it).
        if key == "timers_headers":
            if val in ("0", "1"):
                headers = (val == "1")
            continue
        if not key.startswith("timers_"):
            continue
        rest = key[len("timers_"):]
        idx  = rest.rfind("_")          # type tokens have no underscore; attr is the last segment
        if idx < 0:
            continue
        typ, attr = rest[:idx], rest[idx + 1:]
        if typ not in layout:
            continue
        if attr == "enabled":
            if val in ("0", "1"):
                layout[typ]["enabled"] = (val == "1")
        elif attr == "color":
            if _COLOR_RE.match(val):
                layout[typ]["color"] = val
        elif attr == "cols":
            n = _clamp_cols(typ, val)
            if n is not None:
                layout[typ]["cols"] = n
    return layout, headers


def _palette(typ):
    """(filled_cell_style, sep_style) for a group from its configured colour."""
    hex_ = _layout[typ]["color"]
    return (C_CELL_FG + " bg:" + hex_, "fg:" + hex_)


_layout, _headers  = _load_layout()
_last_layout_mtime = None

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
_hover_plus         = False    # pointer is over the + corner button
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


def _cell_widths(W, n):
    base = W // n
    rem  = W % n
    return [base + 1] * rem + [base] * (n - rem)


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


def _rendered_groups(spells, buffs, debuffs, stored, blinds, charms):
    """Ordered list of (items, typ) for each group that actually renders — i.e.
    is enabled AND non-empty. The single source of truth for both the header-row
    placement in _build_all_rows and the header-row count in _total_rows, so the
    overflow indicator, scroll clamp, and corner-yield never desync."""
    groups = (
        (spells,  "spell"),  (buffs,  "buff"),  (debuffs, "debuff"),
        (stored,  "stored"), (blinds, "blind"), (charms,  "charm"),
    )
    return [(items, typ) for items, typ in groups
            if items and _layout[typ]["enabled"]]


def _total_rows(spells, buffs, debuffs, stored, blinds, charms):
    rendered = _rendered_groups(spells, buffs, debuffs, stored, blinds, charms)
    body = sum(math.ceil(len(items) / _layout[typ]["cols"])
               for items, typ in rendered)
    # Each rendered group contributes one header row when headers are on.
    headers_extra = len(rendered) if _headers else 0
    return body + headers_extra


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
    authoritative, so the row disappears only once tt++ rewrites timers.state.
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
    next poll once Lua rewrites timers.state (~100 ms lag). Catalog keys are
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


def _charm_cell_frags(entry, cell_w, name_fg):
    """One charm cell, width cell_w, no bar: name (themed) · mins (grey) · × (red).

    The right side reserves 6 columns (× + gap + 3 mins + gap), so the name
    truncates to cell_w - 6. When cell_w - 6 < 5 (cell_w < 11) the minutes region
    is dropped for the whole cell and the name takes cell_w - 2 (gap + ×). The
    test is on cell_w only — never on whether the entry is timed — so a timed and
    a permanent charm in the same column keep identical geometry. At charm_cols=1
    (cell_w == W) this reproduces the historic full-width row exactly."""
    cid        = entry.get("id")
    name       = entry.get("name", "")
    started_at = entry.get("started_at")

    show_mins  = (cell_w - 6) >= 5              # cell_w >= 11
    name_w     = max(0, cell_w - 6) if show_mins else max(0, cell_w - 2)
    disp       = (name[:1].upper() + name[1:]) if name else name   # capitalise first letter
    name_txt   = disp[:name_w].ljust(name_w)    # preserve inner case (mob long-name)

    frags = [(name_fg, ch) for ch in name_txt]
    if show_mins:
        if entry.get("expires_at") is None:
            mins_txt = "   "                    # permanent controlled mob — no timer shown
        else:
            mins = 0
            if started_at:
                mins = min(99, int((time.time() - started_at) // 60))
            mins_txt = f"{mins}m".rjust(3)      # " 0m" .. "99m"
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


def _group_rows(items, typ, W):
    """Render one group's items into a list of row fragment-lists. The cell
    style depends on the group: charms have no bar (name · mins · ×); stored
    splits tracked vs untracked-grey; spell/buff/debuff/blind use the themed
    bar, with an affect whose tracked is False rendered as the no-bar grey
    variant (blinds never carry tracked, so they always take the bar)."""
    cols   = _layout[typ]["cols"]
    widths = _cell_widths(W, cols)
    n      = len(items)
    rows   = []

    if typ == "charm":
        name_fg = "fg:" + _layout["charm"]["color"]
        for row in range(math.ceil(n / cols)):
            row_frags = []
            for col in range(cols):
                idx = row * cols + col
                if idx >= n:
                    break
                row_frags.extend(_charm_cell_frags(items[idx], widths[col], name_fg))
            rows.append(row_frags)
        return rows

    palette = _palette(typ)
    for row in range(math.ceil(n / cols)):
        row_frags = []
        for col in range(cols):
            idx = row * cols + col
            if idx >= n:
                break
            entry = items[idx]
            if typ == "stored":
                if entry.get("tracked"):
                    row_frags.extend(_cell_frags(entry, widths[col], palette))
                else:
                    row_frags.extend(_untracked_cell_frags(entry, widths[col]))
            elif entry.get("tracked") is False:
                row_frags.extend(_untracked_affect_cell_frags(entry, widths[col]))
            else:
                row_frags.extend(_cell_frags(entry, widths[col], palette))
        rows.append(row_frags)
    return rows


def _build_all_rows():
    """Return every grid row as a list of fragment-lists (one per row).

    Column counts, colours, and per-group visibility come from _layout. A group
    with enabled == 0 is skipped entirely (no rows); since herblores fold into
    the buff/debuff groups, disabling buff/debuff hides their herblores too.
    When _headers is True, a single dim "Group:" label row is emitted immediately
    above each rendered group's content (including the first), doubling as the
    separator — no blank rows anywhere. When _headers is False: today's dense
    layout (no headers, no blanks). Header placement is derived from the same
    _rendered_groups list _total_rows counts, keeping the two in lockstep."""
    spells, buffs, debuffs, stored, blinds, charms = _split_groups()
    W = max(4, _term_cols())

    all_rows = []
    for items, typ in _rendered_groups(
            spells, buffs, debuffs, stored, blinds, charms):
        if _headers:
            label = f"{_GROUP_LABELS[typ]}:"[:W]   # left-aligned at col 0
            all_rows.append([(C_GROUP_HEADER_FG, label)])   # non-interactive
        all_rows.extend(_group_rows(items, typ, W))

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


def _charm_row_at_top():
    """True when the topmost *visible* grid row belongs to the charm group. In that
    case the corner + must yield so the charm's own drop × (rendered by the grid
    beneath the Float) is clickable. Shared by _corner_visible and _corner_text so
    the two never diverge."""
    groups = _split_groups()
    charms = groups[5]
    if not (charms and _layout["charm"]["enabled"]):
        return False
    charm_row_count = math.ceil(len(charms) / _layout["charm"]["cols"])
    first_charm_row = _total_rows(*groups) - charm_row_count
    return _scroll_offset >= first_charm_row


def _corner_visible():
    """Filter for the corner Float: True exactly when _corner_text yields a glyph.
    When False the Float's ConditionalContainer collapses to zero size and paints
    nothing, so a charm row's own × shows through and stays clickable (a fixed-size
    Float never vacates its cell — returning [] alone leaves a blank cell that eats
    the click)."""
    if not _run_active:
        return False
    if _view_mode == "add":
        return True
    return not _charm_row_at_top()


def _corner_text():
    """The position-pinned +/× corner control (owned by a top-right Float, not by
    any row). The fragment carries a gold fg and no bg, so the 1×1 Float renders
    the glyph on the terminal/pane background (no filled button); hover brightens
    the glyph. + and × are ASCII/Latin-1, single-width. Visibility is owned by the
    _corner_visible filter; this returns [] in the suppressed cases as a belt-and-
    braces guard. + (open add-view) in grid mode, × (return to grid) in add mode."""
    if not _run_active:
        return []
    if _view_mode == "add":
        style = C_ACCENT_HOVER_FG if _hover_close else C_ACCENT_FG
        return [(style, "×", _close_handler)]
    # Grid mode: when the topmost *visible* row is a charm row, yield the corner
    # so that charm's own drop × (in the grid window beneath the Float) is
    # clickable — otherwise the + Float would sit over it. + reappears once the
    # charm group empties, is disabled, or is scrolled away from the top. The
    # add-view has no charm rows, so its close × (above) is unaffected.
    if _charm_row_at_top():
        return []
    style = C_ACCENT_HOVER_FG if _hover_plus else C_ACCENT_FG
    return [(style, "+", _open_handler)]


def _add_view_frags():
    """The herblore picker: one [+]/[-] toggle row per catalog key. The return-to-
    grid × is NOT drawn here — the top-right corner Float owns it (see
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
        label_txt  = (" " + str(key))[:name_w]
        pad_txt    = " " * (name_w - len(label_txt))

        def _row_handler(mouse_event, _key=key, _active=is_active):
            global _hover_herblore_key
            if mouse_event.event_type == MouseEventType.MOUSE_DOWN:
                _send_herblore("remove" if _active else "add", _key)
            elif mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                if _hover_herblore_key != _key:
                    _hover_herblore_key = _key
                    if _app:
                        _app.invalidate()

        # The toggle handler rides the label (brackets + sign + name) so it stays
        # clickable, but the trailing pad is handler-less: that bare surface lets
        # the ListControl fallthrough clear _hover_herblore_key on mouse-out.
        all_rows.append([
            (C_HERB_BRACKET, "[",        _row_handler),
            (sign_style,     sign,       _row_handler),
            (C_HERB_BRACKET, "]",        _row_handler),
            (name_style,     label_txt,  _row_handler),
            ("",             pad_txt),
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
        # Run active but no rows: the corner Float still shows the + over a blank pane.
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
        # Let fragment handlers (the charm ×, +, add-view rows) fire first — mirrors ui_pane.py.
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
    global _layout, _headers, _last_layout_mtime

    while True:
        try:
            layout_mtime = os.stat(TIMERS_LAYOUT_PATH).st_mtime
        except OSError:
            layout_mtime = None
        if layout_mtime != _last_layout_mtime:
            _last_layout_mtime = layout_mtime
            _layout, _headers = _load_layout()   # absent file → defaults; live re-colour / re-layout / re-headers
            app.invalidate()

        try:
            mtime = os.stat(TIMERS_STATE_PATH).st_mtime
        except OSError:
            mtime = None

        if mtime != _last_mtime:
            _last_mtime = mtime
            if mtime is not None:
                try:
                    with open(TIMERS_STATE_PATH, "r") as fh:
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
        content=ConditionalContainer(
            content=Window(
                content=FormattedTextControl(_corner_text, focusable=False),
                width=1,
                height=1,
                dont_extend_width=True,
                dont_extend_height=True,
            ),
            filter=Condition(_corner_visible),
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
