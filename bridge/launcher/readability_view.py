# bridge/launcher/readability_view.py — shared two-column Readability view.
#
# Pure module: no prompt_toolkit import, no global state. Mirrors
# scripts_view.py for layout, navigation, and rendering. Imported by
# launcher.py (Options → Readability).
#
# Responsibilities:
#   - Parse the TOML .meta sidecar for each .tin module.
#   - Read / write the readability_enabled key in startup.conf.
#   - Scan ttpp/readability/modules/ for .tin files.
#   - Render the two-column body region — list (with embedded scrollbar
#     when overflowing), gap, detail (also with an inline scrollbar when
#     overflowing).

import os
import re
import textwrap
from dataclasses import dataclass, field

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from palette import (
    C_BODY,
    C_BUTTON_ACTIVE_FOCUSED,
    C_BUTTON_ACTIVE_UNFOCUSED,
    C_HINT,
    C_HOVER,
    C_ITEM,
    C_OK,
    C_PANE_OFF,
    C_SECTION,
)

__all__ = [
    "ReadabilityModule",
    "parse_meta",
    "scan_modules_dir",
    "read_enabled",
    "write_enabled",
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
# Layout constants (mirrored from scripts_view)
# ---------------------------------------------------------------------------
MIN_LIST_W   = 16
SB_W         = 1
GAP          = 3
OUTER_MARGIN = 2
MAX_DETAIL_W = 80

_SB_THUMB_STYLE = "bold fg:#ffffff"
_SB_TRACK_STYLE = "fg:#585858"
_SB_THUMB_GLYPH = "█"
_SB_TRACK_GLYPH = "░"

_MAX_EXAMPLE_LINES = 6

_ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ReadabilityModule:
    name:           str
    description:    str | None  = None
    example_before: list | None = field(default=None)
    example_after:  list | None = field(default=None)
    enabled:        bool        = False


# ---------------------------------------------------------------------------
# .meta parser
# ---------------------------------------------------------------------------
def parse_meta(path):
    """Parse a TOML .meta sidecar. Returns (description, before, after).
    Any I/O or parse error returns (None, None, None)."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None, None, None

    desc = data.get("description")
    if not isinstance(desc, str):
        desc = None

    before = data.get("example_before")
    if isinstance(before, list):
        before = [str(x) for x in before[:_MAX_EXAMPLE_LINES]]
    else:
        before = None

    after = data.get("example_after")
    if isinstance(after, list):
        after = [str(x) for x in after[:_MAX_EXAMPLE_LINES]]
    else:
        after = None

    return desc, before, after


# ---------------------------------------------------------------------------
# Module scanner
# ---------------------------------------------------------------------------
def scan_modules_dir(modules_dir, enabled_set):
    """Scan modules_dir/*.tin, parse sibling .meta files, return an
    alphabetically-sorted list of ReadabilityModule."""
    if not os.path.isdir(modules_dir):
        return []
    try:
        names = sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(modules_dir)
            if f.endswith(".tin")
        )
    except OSError:
        return []
    out = []
    for name in names:
        meta_path = os.path.join(modules_dir, name + ".meta")
        if os.path.exists(meta_path):
            desc, before, after = parse_meta(meta_path)
        else:
            desc, before, after = None, None, None
        out.append(ReadabilityModule(
            name=name,
            description=desc,
            example_before=before,
            example_after=after,
            enabled=(name in enabled_set),
        ))
    return out


# ---------------------------------------------------------------------------
# startup.conf — read / write readability_enabled
# ---------------------------------------------------------------------------
_CONF_RE = re.compile(r"^([\w\-]+)\s*=\s*(.*?)\s*$")


def read_enabled(conf_path):
    """Parse conf_path for the readability_enabled key (comma-separated).
    Empty / absent → empty set."""
    if not os.path.exists(conf_path):
        return set()
    try:
        with open(conf_path) as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                m = _CONF_RE.match(stripped)
                if m and m.group(1) == "readability_enabled":
                    val = m.group(2).strip()
                    if not val:
                        return set()
                    return {s.strip() for s in val.split(",") if s.strip()}
    except OSError:
        pass
    return set()


def write_enabled(conf_path, enabled_set):
    """Update only the readability_enabled key in conf_path.
    Atomic via sibling *.tmp + os.replace. Preserves all other keys."""
    value = ",".join(sorted(enabled_set))
    lines = []
    found = False
    try:
        with open(conf_path) as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                m = _CONF_RE.match(line)
                if m and m.group(1) == "readability_enabled":
                    lines.append(f"readability_enabled={value}")
                    found = True
                else:
                    lines.append(line)
    except OSError:
        lines = []
    if not found:
        lines.append(f"readability_enabled={value}")
    tmp = conf_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        with open(tmp, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, conf_path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# ANSI SGR → fragment helper
# ---------------------------------------------------------------------------
_SGR_TO_STYLE = {
    "0":  "",
    "1":  "bold",
    "3":  "italic",
    "4":  "underline",
    "5":  "blink",
    "7":  "reverse",
    "30": "fg:#000000", "31": "fg:#aa0000", "32": "fg:#00aa00",
    "33": "fg:#aa5500", "34": "fg:#0000aa", "35": "fg:#aa00aa",
    "36": "fg:#00aaaa", "37": "fg:#aaaaaa",
    "90": "fg:#555555", "91": "fg:#ff5555", "92": "fg:#55ff55",
    "93": "fg:#ffff55", "94": "fg:#5555ff", "95": "fg:#ff55ff",
    "96": "fg:#55ffff", "97": "fg:#ffffff",
    "40": "bg:#000000", "41": "bg:#aa0000", "42": "bg:#00aa00",
    "43": "bg:#aa5500", "44": "bg:#0000aa", "45": "bg:#aa00aa",
    "46": "bg:#00aaaa", "47": "bg:#aaaaaa",
}

_ANSI_16_HEX = tuple(
    _SGR_TO_STYLE[c][len("fg:"):]
    for c in ("30", "31", "32", "33", "34", "35", "36", "37",
              "90", "91", "92", "93", "94", "95", "96", "97")
)


def _xterm256_to_hex(n):
    """xterm-256 palette index → #rrggbb."""
    if n < 16:
        return _ANSI_16_HEX[n]
    if n < 232:
        i = n - 16
        r, g, b = i // 36, (i // 6) % 6, i % 6
        chan = lambda v: 0 if v == 0 else 55 + 40 * v
        return f"#{chan(r):02x}{chan(g):02x}{chan(b):02x}"
    level = min(255, 8 + 10 * (n - 232))
    return f"#{level:02x}{level:02x}{level:02x}"


def _ansi_line_to_fragments(text):
    """Convert a string with ANSI SGR escapes into a list of
    (style, text) tuples suitable for prompt_toolkit rendering."""
    frags = []
    style = C_ITEM
    pos = 0
    for m in _ANSI_SGR_RE.finditer(text):
        start = m.start()
        if start > pos:
            frags.append((style, text[pos:start]))
        params = m.group(1)
        if not params or params == "0":
            style = C_ITEM
        else:
            codes = params.split(";")
            parts = []
            i = 0
            while i < len(codes):
                code = codes[i]
                if code in ("38", "48") and i + 1 < len(codes):
                    prefix = "fg" if code == "38" else "bg"
                    sub = codes[i + 1]
                    if sub == "2" and i + 4 < len(codes):
                        try:
                            r = int(codes[i + 2])
                            g = int(codes[i + 3])
                            b = int(codes[i + 4])
                            parts.append(
                                f"{prefix}:#{r:02x}{g:02x}{b:02x}"
                            )
                            i += 5
                            continue
                        except ValueError:
                            pass
                    elif sub == "5" and i + 2 < len(codes):
                        try:
                            n = int(codes[i + 2])
                            parts.append(
                                f"{prefix}:{_xterm256_to_hex(n)}"
                            )
                            i += 3
                            continue
                        except ValueError:
                            pass
                s = _SGR_TO_STYLE.get(code, "")
                if s:
                    parts.append(s)
                i += 1
            style = " ".join(parts) if parts else C_ITEM
        pos = m.end()
    if pos < len(text):
        frags.append((style, text[pos:]))
    return frags


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------
def list_panel_width(modules):
    """[X]  (4 cells) + longest module name + 1 right-pad. Floored at
    MIN_LIST_W."""
    longest = max((len(m.name) for m in modules), default=0)
    return max(MIN_LIST_W, 4 + longest + 1)


def detail_panel_width(term_cols, list_w):
    """Cells available for detail content. Floored at 20, capped at
    MAX_DETAIL_W."""
    package_inner = term_cols - 2 * OUTER_MARGIN - list_w - SB_W - GAP
    return max(20, min(MAX_DETAIL_W, package_inner))


def package_width(term_cols, list_w):
    """Total horizontal cells the package occupies."""
    return list_w + SB_W + GAP + detail_panel_width(term_cols, list_w)


# ---------------------------------------------------------------------------
# Detail-panel content
# ---------------------------------------------------------------------------
def render_detail_lines(module, detail_w):
    """Return a list of fragment lists (one per visual row) describing
    the module's detail panel."""
    rows = []

    # Title.
    rows.append([(C_SECTION, module.name)])

    # Status.
    if module.enabled:
        rows.append([(C_OK, "● Enabled")])
    else:
        rows.append([(C_PANE_OFF, "○ Disabled")])

    # Description.
    if module.description:
        rows.append([])
        for line in (textwrap.wrap(module.description, detail_w) or [""]):
            rows.append([(C_BODY, line)])

    # Before.
    if module.example_before:
        rows.append([])
        rows.append([(C_HINT, "Before")])
        for line in module.example_before:
            rows.append([(C_ITEM, "  " + line)])

    # After (with ANSI rendering).
    if module.example_after:
        rows.append([])
        rows.append([(C_HINT, "After")])
        for line in module.example_after:
            frags = _ansi_line_to_fragments("  " + line)
            rows.append(frags)

    return rows


def empty_state_rows(detail_w):
    """Detail-area fragments for the "no modules" state."""
    return [
        [(C_BODY, "No readability modules found —")],
        [(C_BODY, "drop a .tin file in")],
        [(C_BODY, "ttpp/readability/modules/")],
        [],
        [(C_HINT, "see docs/readability.md")],
    ]


# ---------------------------------------------------------------------------
# Body renderer
# ---------------------------------------------------------------------------
def render_body(modules, cursor_idx, list_scroll, detail_scroll,
                term_cols, body_h, focus, mode,
                row_handler=None, sb_handler=None,
                detail_handler=None, detail_sb_handler=None,
                hover_row=None,
                detail_idx=None,
                extra_left_rows=None):
    """Render body_h rows of the two-column body region.
    Mirror of scripts_view.render_body — see that module for the full
    argument docstring."""
    list_w   = list_panel_width(modules) if modules else MIN_LIST_W
    detail_w = detail_panel_width(term_cols, list_w)
    pkg_w    = list_w + SB_W + GAP + detail_w
    left_pad = max(OUTER_MARGIN, (term_cols - pkg_w) // 2)
    right_pad = max(0, term_cols - left_pad - pkg_w)

    extra = list(extra_left_rows or [])
    extra_n = len(extra)
    list_capacity = max(0, body_h - extra_n)
    list_h = min(len(modules), list_capacity)
    extras_end = list_h + extra_n

    # ----- List geometry --------------------------------------------------
    n = len(modules)
    list_total   = n
    list_visible = list_h
    list_sb_top, list_sb_thumb_h = _thumb_geom(
        list_total, list_visible, list_h, list_scroll,
    ) if list_h > 0 else (0, 0)
    list_sb_visible = list_total > list_h and list_h > 0

    # ----- Detail rows + geometry ----------------------------------------
    if modules:
        d_anchor = cursor_idx if detail_idx is None else detail_idx
        d_anchor = max(0, min(d_anchor, n - 1))
        cur = modules[d_anchor]
        d_rows_all = render_detail_lines(cur, detail_w)
    else:
        d_rows_all = _centred_empty_state(detail_w, body_h)

    detail_total = len(d_rows_all)
    detail_sb_visible = detail_total > body_h
    d_content_w = detail_w - (SB_W if detail_sb_visible else 0)
    det_sb_top, det_sb_thumb_h = _thumb_geom(
        detail_total, body_h, body_h, detail_scroll,
    )

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
            list_frag = _list_cell_frag(
                modules, n, list_row, cursor_idx, focus, mode, hover_row,
                list_w, row_handler,
            )
            frags.append(list_frag)
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
def _list_cell_frag(modules, n, list_row, cursor_idx, focus, mode,
                    hover_row, list_w, row_handler):
    if not (0 <= list_row < n):
        return ("", " " * list_w)

    module = modules[list_row]
    is_cursor = (list_row == cursor_idx)
    is_hover  = (hover_row is not None
                 and hover_row == list_row
                 and not is_cursor)
    ck = "[X]" if module.enabled else "[ ]"
    text = f"{ck} {module.name}".ljust(list_w)

    if is_cursor:
        style = (C_BUTTON_ACTIVE_FOCUSED if focus == "list"
                 else C_BUTTON_ACTIVE_UNFOCUSED)
    elif is_hover:
        style = C_HOVER
    elif module.enabled:
        style = C_ITEM
    else:
        style = C_PANE_OFF

    if row_handler is not None:
        h = row_handler(list_row)
        if h is not None:
            return (style, text, h)
    return (style, text)


def _sb_cell(body_row, sb_top, sb_thumb_h, sb_handler):
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
    if handler_factory is None:
        return frag
    h = handler_factory(body_row)
    if h is None:
        return frag
    return (frag[0], frag[1], h)


def _thumb_geom(total, visible, height, offset):
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
    msg = empty_state_rows(detail_w)
    pad = max(0, (body_h - len(msg)) // 2)
    return [[]] * pad + msg
