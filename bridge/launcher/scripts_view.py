# bridge/launcher/scripts_view.py — shared two-column Scripts view.
#
# Pure module: no prompt_toolkit import, no global state. Imported by both
# launcher.py (Options → Scripts) and ingame_menu.py (popup Options →
# Scripts) so the [ list | detail ] layout stays identical across the two
# surfaces. Precedent: panes_grid.py (ADR 0086).
#
# Responsibilities:
#   - Parse the @-tagged metadata header at the top of a lua/scripts/<name>.lua
#     file (mirrors lua/brain/loader.lua's parser).
#   - Read / write the flat bridge/runtime/scripts.conf enable-state file.
#   - Parse bridge/runtime/scripts.cache (the brain-written snapshot the
#     popup renders from).
#   - Render the two-column body region — list (with embedded scrollbar
#     when overflowing), gap, detail (also with an inline scrollbar when
#     overflowing).
#
# The renderer is parameterised by mode — `interactive` (launcher:
# script rows are toggleable) vs `readonly` (popup: same layout,
# no toggling). Both modes support hover and mouse handlers; the
# popup's read-only contract is enforced by its mouse handlers
# (clicks move the cursor without toggling), not by the renderer.

import os
import re
import textwrap
from dataclasses import dataclass, field

from menu_chrome import menu_row
from palette import (
    C_ACTIVE,
    C_BODY,
    C_HINT,
    C_ITEM,
    C_OK,
    C_PANE_OFF,
    C_SECTION,
)

__all__ = [
    "Script",
    "parse_script_header",
    "read_scripts_conf",
    "resolve_scripts_conf",
    "scan_scripts_dir",
    "parse_scripts_cache",
    "write_scripts_conf",
    "list_panel_width",
    "detail_panel_width",
    "package_width",
    "render_detail_lines",
    "render_body",
    "empty_state_rows",
    "MIN_LIST_W",
    "GAP",
    "SB_W",
    "OUTER_MARGIN",
]


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
MIN_LIST_W   = 16   # floor for the list column ("[X] coinlooter" + slack)
SB_W         = 1    # scrollbar cell width (list + detail)
GAP          = 3    # cells between the list/sb and the detail panel
OUTER_MARGIN = 2    # minimum cells of slack on each side of the package
MAX_DETAIL_W = 80   # cap on the detail panel — bounds the package width so
                    # the launcher's centred package has visible slack on
                    # wide terminals rather than stretching to fill them

_SB_THUMB_STYLE = "bold fg:#ffffff"
_SB_TRACK_STYLE = "fg:#585858"
_SB_THUMB_GLYPH = "█"
_SB_TRACK_GLYPH = "░"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Script:
    """One script as it appears in the launcher's catalog or the popup's
    cache. `aliases` is a list of `(name, desc)` tuples; `help` is a list
    of raw lines (blank lines preserved as empty strings)."""
    name:    str
    summary: str  = ""
    aliases: list = field(default_factory=list)
    help:    list = field(default_factory=list)
    enabled: bool = False


# ---------------------------------------------------------------------------
# Header parser — mirrors lua/brain/loader.lua's `_parse_script_header`.
# ---------------------------------------------------------------------------
def parse_script_header(path):
    """Parse `path`'s leading `--` comment block. Returns
    `(summary, aliases, help)` — see the `Script` dataclass for the
    field semantics. The block ends at the first non-comment line; a
    blank line ends the block too (the empty match falls out of the
    `^\\s*--(.*)$` test). Unknown `@key` lines are silently ignored."""
    summary = ""
    aliases = []
    help_lines = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                m = re.match(r"^\s*--(.*)$", line)
                if not m:
                    break
                comment = m.group(1)
                km = re.match(r"^\s*@(\w+)\s*(.*)$", comment)
                if not km:
                    continue
                key = km.group(1)
                val = km.group(2).rstrip()
                if key == "summary":
                    summary = val
                elif key == "alias":
                    parts = val.split(None, 1)
                    if parts:
                        aliases.append((
                            parts[0],
                            parts[1] if len(parts) > 1 else "",
                        ))
                elif key == "help":
                    help_lines.append(val)
                # other @keys: silently ignored (forward-compat)
    except OSError:
        pass
    return summary, aliases, help_lines


# ---------------------------------------------------------------------------
# scripts.conf — read / resolve / write
# ---------------------------------------------------------------------------
_CONF_LINE_RE = re.compile(r"^([\w\-]+)\s*=\s*([01])\s*$")


def read_scripts_conf(path):
    """Read `path` and return a dict `{name -> bool}`. Returns `None`
    when the file is missing (so callers can fall back to a template)."""
    if not os.path.exists(path):
        return None
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                m = _CONF_LINE_RE.match(stripped)
                if m:
                    out[m.group(1)] = (m.group(2) == "1")
    except OSError:
        return None
    return out


def resolve_scripts_conf(runtime_path, template_path):
    """Mirror the brain loader's resolution: runtime first, else the
    shipped template, else an empty dict (every script defaults to
    enabled — useful when dropping a private script in for ad-hoc work)."""
    return (read_scripts_conf(runtime_path)
            or read_scripts_conf(template_path)
            or {})


def write_scripts_conf(path, scripts):
    """Write an explicit `<name>=0/1` line for every script in `scripts`.

    Atomic via a sibling `*.tmp` + `os.replace`. The shipped template
    documents the format; the runtime file gets a short stub header so a
    user opening it sees something meaningful."""
    body = [
        "# scripts.conf — per-script enable state.",
        "# Written by the launcher's Scripts view on Back/ESC.",
        "# Format: <script-stem>=0 (disabled) or =1 (enabled).",
        "",
    ]
    for s in scripts:
        body.append(f"{s.name}={'1' if s.enabled else '0'}")
    body.append("")
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as fh:
            fh.write("\n".join(body))
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# lua/scripts/ live scan (launcher) and scripts.cache parse (popup)
# ---------------------------------------------------------------------------
def scan_scripts_dir(scripts_dir, scripts_conf):
    """Scan `scripts_dir`/*.lua, parse each header, join with
    `scripts_conf` to fill `enabled`, and return an alphabetically-
    sorted list of `Script`. A name missing from `scripts_conf`
    defaults to enabled — matching the brain loader."""
    if not os.path.isdir(scripts_dir):
        return []
    try:
        names = sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(scripts_dir)
            if f.endswith(".lua")
        )
    except OSError:
        return []
    out = []
    for name in names:
        path = os.path.join(scripts_dir, name + ".lua")
        summary, aliases, help_lines = parse_script_header(path)
        out.append(Script(
            name=name,
            summary=summary,
            aliases=aliases,
            help=help_lines,
            enabled=bool(scripts_conf.get(name, True)),
        ))
    return out


def parse_scripts_cache(path):
    """Parse the brain-written `bridge/runtime/scripts.cache`. Records
    are separated by `SCRIPT:` lines; each record may carry one
    `ENABLED:`/`SUMMARY:` line and any number of `ALIAS:`/`HELP:` lines.
    Lines outside any record are silently dropped."""
    if not os.path.exists(path):
        return []
    out = []
    cur = None
    try:
        with open(path) as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if line.startswith("SCRIPT:"):
                    if cur is not None:
                        out.append(cur)
                    cur = Script(name=line[len("SCRIPT:"):])
                elif cur is None:
                    continue
                elif line.startswith("ENABLED:"):
                    cur.enabled = (line[len("ENABLED:"):].strip() == "1")
                elif line.startswith("SUMMARY:"):
                    cur.summary = line[len("SUMMARY:"):]
                elif line.startswith("ALIAS:"):
                    payload = line[len("ALIAS:"):]
                    name, _, desc = payload.partition("|")
                    cur.aliases.append((name, desc))
                elif line.startswith("HELP:"):
                    cur.help.append(line[len("HELP:"):])
    except OSError:
        return out
    if cur is not None:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
def list_panel_width(scripts):
    """Longest composed `[X] name` width + 6 — the trailing 6 reserves
    the `<< `/` >>` marker cells the menu-row grammar adds around each
    module label (and the centred `<< Back >>` row that shares the
    column). Floored at `MIN_LIST_W` so the column doesn't collapse on a
    one-script catalog."""
    longest = max((len(s.name) for s in scripts), default=0)
    return max(MIN_LIST_W, 4 + longest + 6)


def detail_panel_width(term_cols, list_w):
    """Cells available for detail content (including the rightmost cell
    that the detail scrollbar will claim when content overflows).

    Floored at 20 cells and capped at `MAX_DETAIL_W` — the cap bounds
    the package width so the launcher's centred package keeps visible
    slack on wide terminals instead of stretching edge-to-edge."""
    package_inner = term_cols - 2 * OUTER_MARGIN - list_w - SB_W - GAP
    return max(20, min(MAX_DETAIL_W, package_inner))


def package_width(term_cols, list_w):
    """Total horizontal cells the package occupies — `list + sb + gap +
    detail`. Used by callers to centre it."""
    return list_w + SB_W + GAP + detail_panel_width(term_cols, list_w)


# ---------------------------------------------------------------------------
# Detail-panel content
# ---------------------------------------------------------------------------
def render_detail_lines(script, detail_w):
    """Return a list of fragment lists (one per visual row) describing
    `script`'s detail panel. All wrapped content is sized to
    `detail_w - SB_W` so it never overlaps the detail scrollbar column
    (reserved unconditionally — the unused cell is harmless when the
    panel doesn't overflow).

    Sections (top to bottom): name · status · summary · aliases · help.
    Empty sections are skipped. Caller slices into the visible viewport.

    Each row is a list of `(style, text)` 2-tuples; the renderer
    promotes them to 3-tuples and pads to `detail_w` at draw time."""
    rows = []
    content_w = max(1, detail_w - SB_W)

    # Title.
    rows.append([(C_SECTION, script.name)])

    # Status.
    if script.enabled:
        rows.append([(C_OK, "● Enabled")])
    else:
        rows.append([(C_PANE_OFF, "○ Disabled")])

    # Summary.
    if script.summary:
        rows.append([])
        for line in (textwrap.wrap(script.summary, content_w) or [""]):
            rows.append([(C_BODY, line)])

    # Aliases. Names render in `C_ACTIVE` (bright white) — gold is
    # reserved for cursor / focus indicators, blue for comm channels.
    if script.aliases:
        rows.append([])
        rows.append([(C_HINT, "Aliases")])
        for name, desc in script.aliases:
            label = f"  {name}"
            sep   = "  "
            indent = " " * (len(label) + len(sep))
            avail  = max(1, content_w - len(indent))
            wrapped = textwrap.wrap(desc, avail) if desc else []
            if wrapped:
                rows.append([
                    (C_ACTIVE, label),
                    (C_BODY,   sep + wrapped[0]),
                ])
                for cont in wrapped[1:]:
                    rows.append([
                        ("",     indent),
                        (C_BODY, cont),
                    ])
            else:
                rows.append([(C_ACTIVE, label)])

    # Help.
    if script.help:
        rows.append([])
        rows.append([(C_HINT, "Help")])
        for line in script.help:
            if not line.strip():
                rows.append([])
                continue
            for w in (textwrap.wrap(line, content_w) or [""]):
                rows.append([(C_ITEM, w)])

    return rows


def empty_state_rows(detail_w):
    """Detail-area fragments for the "no scripts in lua/scripts/" state.
    Returned as plain fragment rows; the caller centres them vertically
    inside the body."""
    return [
        [(C_BODY, "No scripts found —")],
        [(C_BODY, "drop a .lua file in lua/scripts/")],
        [],
        [(C_HINT, "see docs/scripts.md")],
    ]


# ---------------------------------------------------------------------------
# Body renderer
# ---------------------------------------------------------------------------
def render_body(scripts, cursor_idx, list_scroll, detail_scroll,
                term_cols, body_h, focus, mode,
                row_handler=None, sb_handler=None,
                detail_handler=None, detail_sb_handler=None,
                hover_row=None,
                detail_idx=None,
                extra_left_rows=None):
    """Render `body_h` rows of the two-column body region.

    Layout per row:
        ` ` × left_pad | list cell | scrollbar | ` ` × GAP | detail cell
        [ + detail-sb cell when overflowing ] | ` ` × right_pad | "\\n"

    Arguments:
      scripts        — list of `Script`; may be empty (renders the
                        empty-state pane in the detail area).
      cursor_idx     — index of the list row to highlight. Pass -1 (or
                        any out-of-range value) to suppress the
                        highlight — used by the launcher when the
                        cursor sits on an extra-left row (e.g. Back)
                        and no script row should glow.
      list_scroll    — first list row visible at body row 0.
      detail_scroll  — first detail row visible at body row 0.
      term_cols      — terminal width.
      body_h         — number of visual rows to emit.
      focus          — "list" or "detail". Drives the cursor-row
                        highlight (amber when list-focused, grey
                        otherwise — matches the panes-grid /
                        profile-editor colour grammar).
      mode           — "interactive" (launcher) or "readonly" (popup).
                        Swaps only the list-row leading marker:
                        `[X]`/`[ ]` checkbox vs ` ● `/` ○ ` status dot
                        (both 3 cells; see `_list_cell_frag`). Layout is
                        otherwise identical across modes.
      row_handler    — `f(list_row_idx) -> mouse_handler` attached to
                        every fragment on a list row. None → 2-tuples.
      sb_handler     — `f(body_row) -> mouse_handler` for the list
                        scrollbar cell. None → 2-tuple.
      detail_handler — `f(body_row) -> mouse_handler` for detail cells
                        (used to focus the detail and forward wheel
                        scroll in the launcher). None → 2-tuple.
      detail_sb_handler — `f(body_row) -> mouse_handler` for the detail
                        scrollbar cell. None → 2-tuple.
      hover_row      — list row currently under the mouse pointer, or
                        None. Applied in both modes.
      detail_idx     — index of the script whose detail content fills
                        the right column. Defaults to `cursor_idx` (so
                        the popup, which never passes this, keeps the
                        cursor-drives-detail behaviour). The launcher
                        passes the latched script index when the
                        cursor moves onto its in-column Back row, so
                        the last-browsed script stays visible while
                        the cursor sits on Back.
      extra_left_rows — optional list of pre-rendered fragment lists
                        (one per row) to render in the left column
                        immediately below the last visible script row
                        (not pinned to the bottom). The script list is
                        sized to `min(len(scripts), body_h - extra_n)`,
                        the extras follow directly underneath, and any
                        remaining rows are emitted as blank filler in
                        the left column. The detail panel still fills
                        the full `body_h`. Each fragment list should
                        cover exactly `list_w` cells — the renderer
                        pads with trailing blanks if short. Used by
                        the launcher and the popup to attach the
                        blank-spacer + Back row beneath their script
                        lists.

    The function never raises on a too-narrow terminal — `detail_w` is
    floored at 20 cells and the package may overflow rather than be
    clipped; the launcher's `_size_ok` gate handles tiny terminals."""
    list_w   = list_panel_width(scripts) if scripts else MIN_LIST_W
    detail_w = detail_panel_width(term_cols, list_w)
    pkg_w    = list_w + SB_W + GAP + detail_w
    left_pad = max(OUTER_MARGIN, (term_cols - pkg_w) // 2)
    right_pad = max(0, term_cols - left_pad - pkg_w)

    extra = list(extra_left_rows or [])
    extra_n = len(extra)
    # List capacity is `body_h - extra_n`; the actual list area is
    # `min(len(scripts), capacity)` so extras follow directly under
    # the last visible script row (not pinned to the bottom of the
    # column). Remaining rows below the extras are blank filler.
    list_capacity = max(0, body_h - extra_n)
    list_h = min(len(scripts), list_capacity)
    extras_end = list_h + extra_n

    # ----- List geometry --------------------------------------------------
    n = len(scripts)
    list_total   = n
    list_visible = list_h
    list_sb_top, list_sb_thumb_h = _thumb_geom(
        list_total, list_visible, list_h, list_scroll,
    ) if list_h > 0 else (0, 0)
    list_sb_visible = list_total > list_h and list_h > 0

    # ----- Detail rows + geometry ----------------------------------------
    if scripts:
        d_anchor = cursor_idx if detail_idx is None else detail_idx
        d_anchor = max(0, min(d_anchor, n - 1))
        cur = scripts[d_anchor]
        d_rows_all = render_detail_lines(cur, detail_w)
    else:
        d_rows_all = _centred_empty_state(detail_w, body_h)

    detail_total = len(d_rows_all)
    detail_sb_visible = detail_total > body_h
    d_content_w = detail_w - (SB_W if detail_sb_visible else 0)
    det_sb_top, det_sb_thumb_h = _thumb_geom(
        detail_total, body_h, body_h, detail_scroll,
    )

    # Clamp scrolls — defensive against stale scroll values across a
    # cursor jump that shrinks the detail content. The caller is
    # expected to drive scroll bounds too, but we never want to emit
    # negative paddings or thumb tops past the track.
    if detail_total <= body_h:
        detail_scroll = 0
    elif detail_scroll > detail_total - body_h:
        detail_scroll = detail_total - body_h
    if list_total <= list_h:
        list_scroll = 0
    elif list_scroll > list_total - list_h:
        list_scroll = list_total - list_h

    frags = []

    for body_row in range(body_h):
        frags.append(("", " " * left_pad))

        # ----- Left column: list cell, extra row, or blank filler -----
        if body_row < list_h:
            list_row = list_scroll + body_row
            frags.extend(_list_cell_frag(
                scripts, n, list_row, cursor_idx, focus, mode, hover_row,
                list_w, row_handler,
            ))
        elif body_row < extras_end:
            extra_idx = body_row - list_h
            extra_frags = list(extra[extra_idx])
            used = sum(len(t) for _, t in (
                (f[0], f[1]) if len(f) == 3 else f for f in extra_frags
            ))
            pad = max(0, list_w - used)
            for f in extra_frags:
                frags.append(f)
            if pad > 0:
                frags.append(("", " " * pad))
        else:
            frags.append(("", " " * list_w))

        # ----- List scrollbar cell -----
        if body_row < list_h and list_sb_visible:
            frags.append(_sb_cell(
                body_row, list_sb_top, list_sb_thumb_h, sb_handler,
            ))
        else:
            frags.append(("", " "))

        # ----- Gap -----
        frags.append(("", " " * GAP))

        # ----- Detail content cell -----
        d_idx = detail_scroll + body_row
        if 0 <= d_idx < detail_total:
            line = d_rows_all[d_idx]
        else:
            line = []
        used = sum(len(t) for _, t in line)
        pad  = max(0, d_content_w - used)

        for f in line:
            frags.append(_with_handler(f, detail_handler, body_row))
        frags.append(_with_handler(
            ("", " " * pad), detail_handler, body_row,
        ))

        # ----- Detail scrollbar cell -----
        if detail_sb_visible:
            frags.append(_sb_cell(
                body_row, det_sb_top, det_sb_thumb_h, detail_sb_handler,
            ))

        if right_pad > 0:
            frags.append(("", " " * right_pad))
        frags.append(("", "\n"))

    return frags


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _list_cell_frag(scripts, n, list_row, cursor_idx, focus, mode,
                    hover_row, list_w, row_handler):
    """Fragments for one list-column cell — either a script row in the
    `<< [X] name >>` menu-row grammar or blank padding when scrolled
    past the catalog. Returns a list of fragments spanning exactly
    `list_w` cells.

    The composed `[X] name` label is left-aligned to `list_w - 6` so
    the leading glyphs stack vertically down the column and the row
    spans the full width (the 6 trailing cells are the `<< `/` >>`
    markers menu_row adds). `focus` no longer splits the cursor colour —
    these frames always pass `focus="list"`; the cursor row is always
    the gold-arrow `selected` state. Disabled rows stay dim
    (`C_PANE_OFF`).

    `mode` swaps the 3-cell leading marker: `interactive` (launcher)
    shows the `[X]`/`[ ]` checkbox; `readonly` (popup) shows a centred
    status dot (` ● ` enabled / ` ○ ` disabled) so the view reads as a
    documentation browser rather than a toggle panel. Both markers are
    exactly 3 cells, so `list_panel_width`'s geometry is identical.

    In `readonly`, the enabled `●` is lifted out of the menu_row body
    into its own fragment painted `C_OK` (green) — matching the detail
    panel's `● Enabled` — so the dot stays green on every enabled row,
    cursor row included, independent of the row's state colour. The
    name keeps the menu_row grammar (`C_ACTIVE` on the cursor row,
    `C_ITEM`/`C_PANE_OFF` otherwise); the disabled hollow `○` is
    untouched and keeps inheriting the row's state colour."""
    if not (0 <= list_row < n):
        return [("", " " * list_w)]

    script = scripts[list_row]
    is_cursor = (list_row == cursor_idx)
    is_hover  = (hover_row is not None
                 and hover_row == list_row
                 and not is_cursor)
    if mode == "readonly":
        ck = " ● " if script.enabled else " ○ "
    else:
        ck = "[X]" if script.enabled else "[ ]"
    label = f"{ck} {script.name}".ljust(max(0, list_w - 6))

    if is_cursor:
        state, inactive_style = "selected", C_ITEM
    elif is_hover:
        state, inactive_style = "hover", C_ITEM
    elif script.enabled:
        state, inactive_style = "inactive", C_ITEM
    else:
        state, inactive_style = "inactive", C_PANE_OFF

    h = row_handler(list_row) if row_handler is not None else None
    row = menu_row(label, state, mouse_handler=h,
                   inactive_style=inactive_style)

    # Readonly + enabled: recolour the leading 3-cell marker slot to
    # C_OK (green), splitting it off the menu_row body so the `●` is
    # green on every enabled row — the cursor row included — while the
    # name keeps the body's state colour. menu_row returns
    # `[prefix, body, suffix]`; `body[1]` is the composed marker+name
    # label, and any mouse handler rides as the fragment's 3rd element.
    if mode == "readonly" and script.enabled:
        prefix, body, suffix = row
        tail = body[2:]  # mouse handler, if present
        marker, rest = body[1][:3], body[1][3:]
        row = [
            prefix,
            (C_OK, marker, *tail),
            (body[0], rest, *tail),
            suffix,
        ]
    return row


def _sb_cell(body_row, sb_top, sb_thumb_h, sb_handler):
    """One scrollbar cell — thumb or track glyph, optionally carrying a
    mouse handler when `sb_handler` is supplied."""
    if sb_top <= body_row < sb_top + sb_thumb_h:
        style, ch = _SB_THUMB_STYLE, _SB_THUMB_GLYPH
    else:
        style, ch = _SB_TRACK_STYLE, _SB_TRACK_GLYPH
    if sb_handler is not None:
        h = sb_handler(body_row)
        if h is not None:
            return (style, ch, h)
    return (style, ch)


def _with_handler(frag, handler_factory, body_row):
    """Promote a 2-tuple to a 3-tuple by attaching `handler_factory`'s
    handler for `body_row` (or leave the 2-tuple alone when the factory
    is None / returns None)."""
    if handler_factory is None:
        return frag
    h = handler_factory(body_row)
    if h is None:
        return frag
    return (frag[0], frag[1], h)


def _thumb_geom(total, visible, height, offset):
    """Thumb-top and thumb-height for a track of `height` cells where
    `visible` of `total` rows are shown starting at `offset`. Mirrors
    `widgets/scrollbar.py:Scrollbar._thumb_geometry` — duplicated here
    to keep this module dependency-free of prompt_toolkit."""
    if total <= 0 or height <= 0 or visible >= total:
        return 0, height if visible >= total else 0
    ratio = visible / total
    thumb_h = max(1, min(height, round(ratio * height)))
    max_top = height - thumb_h
    max_off = max(0, total - visible)
    if max_off <= 0 or max_top <= 0:
        return 0, thumb_h
    top = round(offset / max_off * max_top)
    top = max(0, min(max_top, top))
    return top, thumb_h


def _centred_empty_state(detail_w, body_h):
    """Pad the empty-state rows above and below so they centre
    vertically in the body region. Returned as a list of fragment rows
    (the body renderer will slice it like a normal detail-rows list)."""
    msg = empty_state_rows(detail_w)
    pad = max(0, (body_h - len(msg)) // 2)
    return [[]] * pad + msg
