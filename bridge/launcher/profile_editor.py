# bridge/launcher/profile_editor.py — self-contained profile editor UI.
# Extracted from launcher.py.  The ProfileEditor class wraps all
# state, rendering, and key bindings for the Lite / Editor view of a
# single .tin profile.  The launcher (and the future in-game popup)
# construct an instance, push a frame, and the editor calls back via
# the EditorHost protocol when it is done.

try:
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.mouse_events import MouseButton, MouseEventType
except ImportError:
    pass  # Tests import this module; prompt_toolkit absence is OK.

import asyncio
import base64
import bisect
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from palette import (  # noqa: E402
    C_TITLE, C_ACTIVE, C_ITEM, C_BODY, C_HINT, C_ACCENT,
    C_YELLOW, C_ERR, C_DANGER, C_QUOTE, C_QUOTE_ATTR, C_HOVER, C_SELECTED,
    C_SECTION, C_DIVIDER,
    C_BUTTON, C_BUTTON_HOVER, C_BUTTON_DISABLED,
    C_BUTTON_INACTIVE, C_BUTTON_ACTIVE_UNFOCUSED, C_BUTTON_ACTIVE_FOCUSED,
    C_OK, C_CURSOR_CELL,
    C_SYN_COMMAND, C_SYN_BRACE, C_SYN_DELIM, C_SYN_VAR, C_SYN_CODE,
    C_SYN_BRACE_MATCH,
    TTPP_COLOR_STYLES, TTPP_COLOR_NAMES,
)
import ttpp_syntax  # noqa: E402
import macro_keys  # noqa: E402
import profile_io  # noqa: E402
from widgets.scrollbar import Scrollbar  # noqa: E402


# ---------------------------------------------------------------------------
# EditorHost protocol
# ---------------------------------------------------------------------------
class EditorHost:
    """Protocol that the hosting context (launcher or in-game popup) must
    satisfy.  ProfileEditor calls these methods instead of touching launcher
    globals directly."""

    @property
    def app(self):
        """The running prompt_toolkit Application, or None."""
        raise NotImplementedError

    @property
    def app_loop(self):
        """The running asyncio event loop, or None."""
        raise NotImplementedError

    @property
    def terminal_bg(self):
        """Detected terminal background hex string (#rrggbb) or None."""
        raise NotImplementedError

    def term_cols(self) -> int:
        raise NotImplementedError

    def term_rows(self) -> int:
        raise NotImplementedError

    def title_blank_above(self) -> int:
        """Leading blank rows above the editor's title row.

        Surface-specific to match the host's own menu chrome: the
        launcher uses two leading blanks, the in-game popup uses one
        (ADR 0085)."""
        raise NotImplementedError

    def push_overlay_frame(self):
        """Push the macro-keybind overlay frame onto the host's frame stack."""
        raise NotImplementedError

    def pop_overlay_frame(self):
        """Pop the macro-keybind overlay frame."""
        raise NotImplementedError

    def focus_current_frame(self):
        """Ask the host to re-focus the current-frame window."""
        raise NotImplementedError

    def is_active(self) -> bool:
        """True when the profile_editor frame is the current frame."""
        raise NotImplementedError

    def is_overlay_active(self) -> bool:
        """True when the profile_editor_macro_keybind frame is current."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Module-level helpers and constants (copied/adapted from launcher.py)
# ---------------------------------------------------------------------------

# Undo/redo max stack depth
_EDITOR_UNDO_MAX_DEPTH = 200

# Click-count window (seconds) for double/triple-click detection
_EDITOR_CLICK_WINDOW = 0.4

# Scrollbar auto-scroll timing
_AUTOSCROLL_INITIAL_DELAY   = 0.30
_AUTOSCROLL_REPEAT_INTERVAL = 0.10


def _make_window(text_fn, *, focusable=False):
    return Window(
        content=FormattedTextControl(text=text_fn, focusable=focusable),
        wrap_lines=False,
        always_hide_cursor=True,
    )


def _pad_centre(text, cols=None):
    if cols is None:
        return ""
    pad = max(0, (cols - len(text)) // 2)
    return " " * pad


def _interpolate_hex(base_hex: str, target_hex: str, t: float) -> str:
    """Per-channel linear interpolation between two `#rrggbb` colours.
    `t=0` returns base, `t=1` returns target; intermediate values are
    clamped to the byte range. Foundation for `_credits_brightness_to_hex`
    (target = white) and the editor-mode focused current-line band
    (target = black or white depending on terminal-bg brightness)."""
    br = int(base_hex[1:3], 16)
    bg = int(base_hex[3:5], 16)
    bb = int(base_hex[5:7], 16)
    tr = int(target_hex[1:3], 16)
    tg = int(target_hex[3:5], 16)
    tb = int(target_hex[5:7], 16)
    r  = max(0, min(255, int(round(br + (tr - br) * t))))
    g  = max(0, min(255, int(round(bg + (tg - bg) * t))))
    bl = max(0, min(255, int(round(bb + (tb - bb) * t))))
    return f"#{r:02x}{g:02x}{bl:02x}"



# ---------------------------------------------------------------------------
# Module-level constants and pure helpers (extracted from launcher.py)
# ---------------------------------------------------------------------------
_PROFILE_EDITOR_TABS = [
    ("Actions",     "action"),
    ("Aliases",     "alias"),
    ("Highlights",  "highlight"),
    ("Macros",      "macro"),
    ("Substitutes", "substitute"),
]

_EDITOR_PATTERN_COL_W = 8       # Pattern column inside the list panel
_EDITOR_KIND_W        = 13      # Each kind-button cell width (wide enough
                                # for "SUBSTITUTES" + centring)
_EDITOR_KIND_GAP      = 3       # Cells between kind buttons in the row
_EDITOR_KIND_ROW_H    = 3       # Kind-button row height (3-row blocks)
_EDITOR_LIST_W        = 38      # List panel content (scrollbar is +1 column)
_EDITOR_GAP           = 3       # Cells between list+scrollbar and detail
_EDITOR_DETAIL_W      = 35      # Detail panel width

# Number of buttons in the kind row — derived for layout math.
_EDITOR_KIND_COUNT    = len(_PROFILE_EDITOR_TABS)

# Detail-panel chrome surrounding the lite-mode Commands / New-text body box,
# counted in rows. The body box's visible-row budget is `_editor_body_h()`
# minus this chrome (see `_editor_body_budget`), so the box fills the space the
# panel actually has rather than stopping at a fixed ceiling. Bodies longer
# than the budget scroll within the field via an inline scrollbar.
#
# Shared trailing block reserved by every kind, unconditionally so the layout
# is height-stable whether or not a validation error shows: error/blank row +
# blank + "─── Hint ───" + 2 hint lines + trailing blank.
_EDITOR_DETAIL_TRAILING_ROWS = 6
# Text-bodied kinds (alias/action/substitute): Pattern label+box (4) + Body
# label (1) + body top/bottom borders (2) + trailing block.
_EDITOR_TEXT_BODY_CHROME  = 4 + 1 + 2 + _EDITOR_DETAIL_TRAILING_ROWS
# Macro: Key label (1) + Key cell (1) + blank (1) + Body label (1) + body
# top/bottom borders (2) + trailing block.
_EDITOR_MACRO_BODY_CHROME = 1 + 1 + 1 + 1 + 2 + _EDITOR_DETAIL_TRAILING_ROWS
# Smallest usable body box, even on very short terminals.
_EDITOR_BODY_MIN_ROWS = 3

# Per-kind detail-panel field labels — `(pattern_label, body_label)`. Used by
# both the detail panel (renamed `Body` slot) and the list panel header.
DETAIL_LABELS = {
    "alias":      ("Pattern", "Commands"),
    "action":     ("Pattern", "Commands"),
    "macro":      ("Key",     "Commands"),    # Key cell pushes a capture overlay
    "highlight":  ("Pattern", "Color"),       # body slot becomes the palette grid
    "substitute": ("Text",    "New text"),
}

# Per-kind detail-panel builder. The renderer dispatches on the active kind:
# text-bodied kinds reuse the Pattern + Body chain; `highlight` swaps the
# Body field for a 2-D color-palette grid; `macro` swaps Pattern for a
# "press to bind" button that pushes the key-capture overlay.
DETAIL_NEW_DEFAULTS = {
    "alias":      ("", ""),
    "action":     ("", ""),
    "macro":      ("", ""),
    "highlight":  ("", "light yellow"),
    "substitute": ("", ""),
}


# Highlight palette — 7 rows × 2 cols, dark-on-left, light-on-right.
# Dark column uses lowercase tt++ names (`red`, `green`, …); light column
# uses the capitalised forms (`Red`, `Green`, …) — both render through
# `TTPP_COLOR_STYLES` via `_HL_DICT_KEY` since the dict is keyed on the
# `light <colour>` form for the bright variants. Two parallel palettes
# share this geometry: text colour (left half of the detail panel) and
# background colour (right half + a `(None)` cell on top).
_HL_PALETTE = [
    ("red",     "Red"),
    ("green",   "Green"),
    ("yellow",  "Yellow"),
    ("blue",    "Blue"),
    ("magenta", "Magenta"),
    ("cyan",    "Cyan"),
    ("white",   "White"),
]
_HL_PALETTE_ROWS = len(_HL_PALETTE)
_HL_PALETTE_COLS = 2

# Display name → TTPP_COLOR_STYLES key. Accepts the dark form, the
# capitalised light form, and the `light <colour>` long form so on-disk
# bodies in any of the three conventions resolve to the right swatch.
_HL_DICT_KEY = {
    "red":     "red",
    "green":   "green",
    "yellow":  "yellow",
    "blue":    "blue",
    "magenta": "magenta",
    "cyan":    "cyan",
    "white":   "white",
    "gray":    "gray",
    "Red":          "light red",
    "Green":        "light green",
    "Yellow":       "light yellow",
    "Blue":         "light blue",
    "Magenta":      "light magenta",
    "Cyan":         "light cyan",
    "White":        "gray",     # closest light-white swatch in the palette dict
    "light red":     "light red",
    "light green":   "light green",
    "light yellow":  "light yellow",
    "light blue":    "light blue",
    "light magenta": "light magenta",
    "light cyan":    "light cyan",
}

# Style toggles surfaced in the Style row. tt++ accepts `underscore`,
# `blink`, and `reverse` directly in `#highlight {pattern} {<modifiers>
# <colour>}`. Phase 6.3: `bold` was removed — tt++ doesn't list it as a
# `#highlight` modifier, and surfacing it produced bodies tt++ would
# reject or silently drop. An on-disk `bold` token in a highlight body
# parses unchanged into the Custom slot (no `_raw` clobber) since the
# palette parser rejects it as unknown.
_HL_STYLE_TOKENS = ("underscore", "blink", "reverse")
_HL_STYLE_LABELS = {
    "underscore": "Undersc.",
    "blink":      "Blink",
    "reverse":    "Reverse",
}


def _hl_color_style(name):
    """Resolve a display name to a TTPP_COLOR_STYLES style string, or
    None if the name isn't in the palette. Accepts any of the three
    on-disk conventions (lowercase, capitalised, `light <colour>`)."""
    key = _HL_DICT_KEY.get(name)
    if key is None:
        return None
    return TTPP_COLOR_STYLES.get(key)


def _hl_parse_body(body):
    """Parse a `#highlight` body into `(styles, text_color, bg_color)`.

    Token grammar:
      - `<style>` tokens from `_HL_STYLE_TOKENS` add to the styles set.
      - `b` marks the next colour-context as background.
      - `light <name>` resolves to the capitalised light variant.
      - A bare colour token is either dark (lowercase) or light
        (capitalised) — looked up directly in `_HL_DICT_KEY`.

    Returns the parsed triple on success, or None when any token is
    unknown or the body is empty — the caller preserves the original
    body byte-exact in the Custom slot."""
    tokens = body.split()
    if not tokens:
        return None
    styles = set()
    text_color = None
    bg_color = None
    in_bg = False
    light_pending = False
    for tok in tokens:
        if tok in _HL_STYLE_TOKENS and not light_pending:
            if tok in styles:
                return None
            styles.add(tok)
            continue
        if tok == "b" and not light_pending:
            if in_bg or bg_color is not None:
                return None
            in_bg = True
            continue
        if tok == "light" and not light_pending:
            light_pending = True
            continue
        # Colour token — combine with a pending `light` prefix.
        if light_pending:
            cap = tok[:1].upper() + tok[1:].lower()
            if cap not in _HL_DICT_KEY:
                return None
            color = cap
            light_pending = False
        elif tok in _HL_DICT_KEY:
            color = tok
        else:
            return None
        if in_bg:
            bg_color = color
            in_bg = False
        else:
            if text_color is not None:
                return None
            text_color = color
    if in_bg or light_pending:
        return None
    if not styles and text_color is None and bg_color is None:
        return None
    return (styles, text_color, bg_color)


def _hl_serialize(styles, text_color, bg_color):
    """Compose a `#highlight` body from the editor's three palettes.
    Style tokens are emitted in `_HL_STYLE_TOKENS` order; the `b`
    clause is omitted when no background is selected."""
    parts = []
    for s in _HL_STYLE_TOKENS:
        if s in styles:
            parts.append(s)
    if text_color is not None:
        parts.append(text_color)
    if bg_color is not None:
        parts.append("b")
        parts.append(bg_color)
    return " ".join(parts)


def _hl_palette_position_for_color(name):
    """Return `(row, col)` of the `_HL_PALETTE` cell whose label equals
    `name`, or None when the name isn't on the grid. The check resolves
    both the lowercase dark form (`red`) and the capitalised light form
    (`Red`); `light red` is normalised to `Red` for the lookup so the
    cursor lands on the right swatch."""
    if name is None:
        return None
    # Normalise `light foo` → `Foo` for palette lookup.
    if name.startswith("light "):
        rest = name[6:]
        name = rest[:1].upper() + rest[1:].lower()
    elif name == "gray":
        name = "White"
    for r, (dark, light) in enumerate(_HL_PALETTE):
        if dark == name:
            return (r, 0)
        if light == name:
            return (r, 1)
    return None


def _hl_palette_color_at(row, col):
    """Return the `_HL_PALETTE` cell label at `(row, col)`, or None when
    the coordinate is out of range."""
    if 0 <= row < _HL_PALETTE_ROWS and 0 <= col < _HL_PALETTE_COLS:
        return _HL_PALETTE[row][col]
    return None




def _braces_balanced(s):
    """Return True when every unescaped `{` in `s` has a matching `}`
    later and no stray `}` appears first. `\\X` for any X is treated
    as escaped (the X — including `{` and `}` — does not count toward
    depth). Used by the editor's brace-balance validation to flag
    profiles that tt++ would reject on next load."""
    depth = 0
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


_EDITOR_HINTS = {
    "alias": (
        "%1 %2 capture words · ; chains",
        "gv %1  →  get %1;value %1",
    ),
    "action": (
        "%1 %2 match text · ^ anchors line",
        "^%1 raises %2 hand  →  group %1",
    ),
    "highlight": (
        "%1 matches text · ^ anchors line",
        "^%1 enters  colours whole line",
    ),
    "substitute": (
        "%1 %2 capture & reuse in New text",
        "%1 massacres %2 → %1 MASSACRES %2",
    ),
    "macro": (
        "Enter on Key cell to bind a key",
        "$var inserts variable · ; chains",
    ),
}

# Kind labels surfaced in user-facing hints. Singular form for in-flight
# create prompts; plural form for the empty-state message.
_EDITOR_KIND_LABELS = {
    "alias":      ("alias",      "aliases"),
    "action":     ("action",     "actions"),
    "macro":      ("macro",      "macros"),
    "highlight":  ("highlight",  "highlights"),
    "substitute": ("substitute", "substitutes"),
}


def _editor_sb_thumb_geom_generic(total, visible, height, offset):
    """Generic thumb geometry — same math as `self._editor_sb_thumb_geom`
    but parameterised by the scroll offset so it works for the body
    field's local viewport (the entry-list helper hardcodes
    `self._editor_list_scroll`)."""
    if total <= 0 or total <= visible or height <= 0:
        return 0, 0
    ratio   = visible / total
    thumb_h = max(1, round(ratio * height))
    thumb_h = min(thumb_h, height)
    max_top = height - thumb_h
    mx_scroll = max(0, total - visible)
    if max_top <= 0 or mx_scroll <= 0:
        return 0, thumb_h
    top = round(offset / mx_scroll * max_top)
    top = max(0, min(max_top, top))
    return top, thumb_h


def _editor_pad_full(style, text, handler=None):
    """Build a single-fragment row of width `_EDITOR_DETAIL_W` from a
    single style + text. Pads with empty-style spaces or truncates.

    When `handler` is supplied, every fragment carries it so the whole
    row reacts to mouse clicks — used by the label, border, and gap
    rows of editable detail fields so clicking on the field's chrome
    focuses it (rather than just clicks on the content row)."""
    w = _EDITOR_DETAIL_W
    if handler is None:
        if len(text) > w:
            return [(style, text[:w])]
        if len(text) == w:
            return [(style, text)]
        return [(style, text), ("", " " * (w - len(text)))]
    if len(text) > w:
        return [(style, text[:w], handler)]
    if len(text) == w:
        return [(style, text, handler)]
    return [(style, text, handler),
            ("", " " * (w - len(text)), handler)]


def _editor_box_top(width):
    return "┌" + "─" * (width - 2) + "┐"


def _editor_box_bot(width):
    return "└" + "─" * (width - 2) + "┘"


def _editor_field_border_style(focused):
    """Subtle visual indicator for which detail field has focus.
    Unfocused: dim grey (`C_HINT`). Focused: amber (`C_ACCENT`) — a
    shift up the same warm family the launcher uses elsewhere, so it
    reads as "active" without leaving the vintage-amber palette."""
    return C_ACCENT if focused else C_HINT


def _editor_centered_row(style, text):
    """Build a row that centres `text` in the detail-panel width."""
    w = _EDITOR_DETAIL_W
    if len(text) > w:
        return [(style, text[:w])]
    pad_l = max(0, (w - len(text)) // 2)
    pad_r = max(0, w - pad_l - len(text))
    return [
        ("", " " * pad_l),
        (style, text),
        ("", " " * pad_r),
    ]


def _editor_macro_key_cell_text(entry):
    """The rendered text + style for the macro Key cell, given an entry.

    Three states (mirrors phase 5 spec):
      • Empty pattern (pre-capture)  → "[ Press to bind… ]" in C_HINT.
      • Known escape → "[ <display name> ]" in C_ITEM.
      • Unknown escape → "[ Custom: <raw> ]" in C_HINT (same convention as
        the highlights Custom slot).
    """
    raw = entry.pattern or ""
    if raw == "":
        return "[ Press to bind… ]", C_HINT, "placeholder"
    name = macro_keys.escape_to_name(raw)
    if name is not None:
        return f"[ {name} ]", C_ITEM, "known"
    return f"[ Custom: {raw} ]", C_HINT, "custom"


def format_entry_pattern(entry, max_len=40):
    """Readable pattern for an Entry, suitable for confirm dialogs.

    `macro` entries resolve through `escape_to_name`, falling back to
    `Custom: <raw>` for unknown escape sequences. All other kinds return
    the raw pattern, truncated with `…` when longer than `max_len`."""
    raw = entry.pattern or ""
    if entry.kind == "macro":
        name = macro_keys.escape_to_name(raw)
        return name if name is not None else f"Custom: {raw}"
    if len(raw) > max_len:
        return raw[: max(0, max_len - 1)] + "…"
    return raw




# Phase 6.2 palette geometry. Inner content spans 28 cells: 6+6 Text
# swatches + 3-cell gap + 6+6 BG swatches + 1 trailing space. Each
# swatch column is 6 cells wide; the swatch itself is `[X]██` (5 chars)
# + 1 trailing space. The whole row is centred within `_EDITOR_DETAIL_W`.
_HL_SWATCH_COL_W   = 6
_HL_GRID_GAP       = 3
_HL_GRID_W         = (_HL_SWATCH_COL_W * 4 + _HL_GRID_GAP)   # 27
_HL_HEADER_HALF_W  = _HL_SWATCH_COL_W * 2                     # 12


def _list_body_first_line(body):
    """Return the first non-blank line of `body` verbatim (uncapped).
    Empty string when body is empty or only blank lines. Used for the
    highlight colour-preview lookup, which must match the full token
    irrespective of column-truncation."""
    if not body:
        return ""
    for line in body.split("\n"):
        if line.strip():
            return line
    return ""


def _list_body_preview(body, body_col_w):
    """Pure helper for the list-view body cell.

    Picks the first non-blank line of `body` and returns up to
    `body_col_w` cells of preview text. Appends `…` whenever the
    rendered cell does NOT show the body in full — either the first
    line had to be truncated to fit the column, or additional non-
    blank content follows that line."""
    if not body:
        return ""
    first_line = ""
    has_more = False
    seen_first = False
    for line in body.split("\n"):
        if not line.strip():
            continue
        if not seen_first:
            first_line = line
            seen_first = True
        else:
            has_more = True
            break
    truncated = len(first_line) > body_col_w
    if truncated or (has_more and len(first_line) >= body_col_w):
        return first_line[:max(0, body_col_w - 1)] + "…"
    if has_more:
        return first_line + "…"
    return first_line


_EDITOR_TOGGLE_LABELS = ("LITE", "EDITOR")

# Fractional lift toward white (dark bg) or black (light bg) used to derive
# the focused current-line band from `host.terminal_bg`. 0.12 reproduces the
# legacy `#1f1f1f`-on-`#000000` tone (255 * 0.12 ≈ 31 = 0x1f), so the visual
# on a black terminal is unchanged. The band itself is computed lazily in
# `_editor_focused_line_hl_bg()` so it always reflects the live host bg.
_EDITOR_LINE_HL_LIFT = 0.12


_EDITOR_SYNTAX_STYLE = {
    "command": C_SYN_COMMAND,
    "brace":   C_SYN_BRACE,
    "delim":   C_SYN_DELIM,
    "var":     C_SYN_VAR,
    "code":    C_SYN_CODE,
}


def _editor_word_class(ch):
    """Three-way classification used by double-click word selection.
    `word` covers alphanumerics and `_`; `ws` covers space and tab;
    everything else (punctuation, symbols, non-latin printables) is
    `other`. Word selection walks a same-class run in both directions."""
    if ch.isalnum() or ch == "_":
        return "word"
    if ch in (" ", "\t"):
        return "ws"
    return "other"


def _editor_word_bounds(line_text, col):
    """Return `(start, end)` of the same-class run that contains the
    character at `col` (end-exclusive — `line_text[start:end]` is the
    word). Returns None for a click at or past end-of-line: word
    selection never crosses a line boundary, and there is nothing to
    extend over past the last character."""
    if col < 0 or col >= len(line_text):
        return None
    cls = _editor_word_class(line_text[col])
    s = col
    while s > 0 and _editor_word_class(line_text[s - 1]) == cls:
        s -= 1
    e = col
    while e < len(line_text) and _editor_word_class(line_text[e]) == cls:
        e += 1
    return (s, e)




def _wrap_text(text, width):
    """Word-wrap `text` to `width` columns.  Returns a list of strings."""
    out = []
    line = ""
    for raw in text.splitlines():
        if not raw.strip():
            if line:
                out.append(line); line = ""
            out.append("")
            continue
        if raw[:1].isspace():
            if line:
                out.append(line); line = ""
            out.append(raw)
            continue
        for word in raw.split():
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line += " " + word
            else:
                out.append(line)
                line = word
    if line:
        out.append(line)
    return out


def _emit_osc52_copy(text, app=None):
    """Push `text` to the system clipboard via the OSC 52 escape sequence.

    Best-effort: when the terminal doesn't support OSC 52 the sequence is
    silently discarded; the in-app register still works either way. We
    write through the prompt_toolkit output (it owns the screen) and
    guard on `app` so calls before the application boots are no-ops."""
    if app is None or not text:
        return
    try:
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        seq = f"\x1b]52;c;{payload}\x07"
        out = app.output
        out.write_raw(seq)
        out.flush()
    except Exception:
        # OSC 52 is a courtesy — never let it raise into a key handler.
        pass


def _bracketed_paste_normalise(text):
    """Normalise terminal-paste line endings to `\\n`. Bracketed paste
    delivers `\\r\\n` on Windows-clipboard sources and lone `\\r` from
    some macOS pasteboards; the editor model only understands `\\n`."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --- Editor-mode (buffer) copy / cut / paste -------------------------



# ---------------------------------------------------------------------------
# ProfileEditor
# ---------------------------------------------------------------------------
class ProfileEditor:
    """Self-contained profile editor UI widget.

    Construct one instance per edit session; discard it on exit.
    The host pushes the "profile_editor" frame *after* constructing this
    object (the constructor mirrors _enter_profile_editor except for the
    _push_frame call).
    """

    def __init__(self, *, path, profile, on_exit, host):
        """
        path     -- pathlib.Path to the .tin file being edited.
        profile  -- profile_io.Profile already loaded from path.
        on_exit  -- callable(profile) invoked when ESC/save fires; the host
                    is responsible for saving and popping the frame.
        host     -- EditorHost implementation.
        """
        self._on_exit = on_exit
        self._host = host

        # --- Instance state (mirrors the old _editor_* module globals) ---
        self._editor_profile_path = profile.path
        self._editor_data         = profile
        self._editor_active_tab   = 0
        self._editor_hover_tab    = None
        self._editor_focus        = 0
        self._editor_list_cursor  = 0
        self._editor_list_scroll  = 0
        self._editor_hover_row    = None
        self._editor_list_sb      = None
        self._editor_detail_field    = 0
        self._editor_body_line       = 0
        self._editor_body_col        = 0
        self._editor_pattern_cursor  = 0
        self._editor_pattern_touched = False
        self._editor_body_scroll     = 0
        self._editor_mode            = "lite"
        self._editor_toggle_focused  = False
        self._editor_toggle_hover    = None
        self._editor_buffer_text     = ""
        self._editor_buffer_cursor   = 0
        self._editor_buffer_scroll   = 0
        self._editor_buffer_anchor   = None
        self._editor_buffer_line_starts_cache = (None, None)
        self._editor_buffer_visual_cache      = (None, None, None)
        self._editor_buffer_syntax_cache      = (None, None)
        self._editor_pending_closers          = []
        self._editor_undo_stack               = []
        self._editor_redo_stack               = []
        self._editor_undo_open                = False
        self._editor_undo_last_kind           = None
        self._editor_clipboard                = ""
        self._editor_click_count              = 0
        self._editor_click_last_t             = 0.0
        self._editor_click_last_xy            = (-1, -1)
        self._editor_click_now                = time.monotonic
        self._editor_pattern_anchor           = None
        self._editor_body_anchor_line         = None
        self._editor_body_anchor_col          = None
        self._editor_hl_style_cursor          = 0
        self._editor_hl_text_row              = 0
        self._editor_hl_text_col              = 0
        self._editor_hl_text_sel              = None
        self._editor_hl_bg_row                = 0
        self._editor_hl_bg_col                = 0
        self._editor_hl_bg_sel                = None
        self._editor_hl_hover                 = None
        self._editor_keybind_error            = ""
        self._editor_keybind_just_created     = False
        self._editor_feedback_text            = None
        self._editor_feedback_style           = ""
        self._editor_feedback_handle          = None
        self._editor_flash_text               = None
        self._editor_flash_style              = ""
        self._editor_flash_handle             = None
        self._autoscroll_step_fn              = None
        self._autoscroll_handle               = None
        self._autoscroll_target               = None
        self._kb_cache                        = None

        # Per-instance detail builders (methods, not module-level functions)
        self._EDITOR_DETAIL_BUILDERS = {
            "alias":      self._editor_build_text_detail,
            "action":     self._editor_build_text_detail,
            "substitute": self._editor_build_text_detail,
            "highlight":  self._editor_build_palette_detail,
            "macro":      self._editor_build_macro_detail,
        }

        # Build scrollbar and refresh
        self._editor_list_sb = Scrollbar(
            0, self._editor_list_visible(), self._editor_list_visible(),
        )
        self._editor_undo_reset()
        self._editor_clear_flash()
        self._autoscroll_disarm()
        self._editor_refresh_buffers()

        # Build the prompt_toolkit windows (created once, rendered dynamically)
        self._main_win    = _make_window(self._profile_editor_text, focusable=True)
        self._overlay_win = _make_window(self._profile_editor_keybind_text, focusable=True)
        self._footer_win  = Window(
            content=FormattedTextControl(text=self._profile_editor_footer_text,
                                         focusable=False),
            height=lambda: Dimension.exact(self._profile_editor_footer_h()),
            wrap_lines=False, always_hide_cursor=True,
        )

    # --- Public API --------------------------------------------------------

    def main_window(self):
        """The main focusable Window for the profile_editor frame."""
        return self._main_win

    def overlay_window(self):
        """The focusable Window for the profile_editor_macro_keybind overlay."""
        return self._overlay_win

    def container(self):
        """HSplit container for the profile_editor frame."""
        flex_spacer = Window()
        return HSplit([self._main_win, flex_spacer, self._footer_win])

    def overlay_container(self):
        """Container for the macro-keybind overlay frame (simple Window)."""
        return self._overlay_win

    def _save_and_close(self):
        """ESC handler: invoke on_exit. The host receives the profile object
        and is responsible for saving to disk and popping the frame."""
        if self._editor_data is not None:
            if self._editor_mode == "editor":
                new_prof = profile_io.parse_profile(self._editor_buffer_text,
                                                    self._editor_data.path)
                self._editor_data.items[:] = new_prof.items
                self._editor_data.path     = new_prof.path
        self._editor_clear_flash()
        self._autoscroll_disarm()
        self._on_exit(self._editor_data)

    def _profile_editor_save_and_close(self):
        """Alias for _save_and_close; called by the ESC key binding."""
        self._save_and_close()

    def key_bindings(self):
        """Return KeyBindings for the profile_editor frame.

        Cached on first call so DynamicKeyBindings doesn't re-register
        every handler on every keystroke."""
        if self._kb_cache is None:
            kb = KeyBindings()
            self._register_key_bindings(kb)
            self._kb_cache = kb
        return self._kb_cache


    # --- Editor methods ---

    def _editor_dispatch_detail_builder(self, kind):
        return self._EDITOR_DETAIL_BUILDERS.get(kind, self._editor_build_text_detail)
    
    
    # Body / Commands / etc. default values for `+ New entry` rows, keyed by kind.
    # Aliases / actions / substitutes start blank; highlights default to the
    # project's vintage-amber accent colour so the user sees the swatch
    # pre-selected and can re-pick from the palette. Macros start blank too,
    # but the overlay is auto-pushed so the user never sees the empty state.
    def _editor_package_w(self):
        # Body width: list + scrollbar + gap + detail. Kind buttons moved
        # to a horizontal row above the body (Phase 6.3); body math no
        # longer includes the kind column.
        return _EDITOR_LIST_W + 1 + _EDITOR_GAP + _EDITOR_DETAIL_W
    
    
    def _editor_left_pad(self):
        return max(0, (self._host.term_cols() - self._editor_package_w()) // 2)
    
    
    def _editor_kind_row_w(self):
        """Total width of the horizontal kind-button row: five 13-cell
        buttons with 3-cell gaps between, centred on the terminal."""
        return (_EDITOR_KIND_COUNT * _EDITOR_KIND_W
                + (_EDITOR_KIND_COUNT - 1) * _EDITOR_KIND_GAP)
    
    
    def _editor_kind_left_pad(self):
        return max(0, (self._host.term_cols() - self._editor_kind_row_w()) // 2)
    
    
    def _editor_body_h(self):
        """Body row height — branches on `self._editor_mode`.

        `nb` is the host-provided count of leading blank rows above the
        title (`title_blank_above`): launcher 2, popup 1. The rest of the
        chrome is fixed, so the per-mode overhead is `<fixed> + nb`.

        Lite mode budget reserves rows for the leading blanks, title
        row, blank separator, and the horizontal kind-button row + its
        blank-line separator (the footer blank + hint live in the
        dedicated footer Window, with a flex_spacer absorbing the
        remaining slack between body and footer — see
        `_build_profile_editor`). `11 + nb` rows of chrome total: the
        body chrome, 2 in the footer Window, and the spacer slack. The
        detail panel's field chain (Pattern + Commands + error + hint
        block) needs ~15 rows minimum.

        Editor mode has no kind-button row and no detail panel; only the
        leading blanks, the title row, one blank below the title, and
        the buffer. The footer blank + hint live in the footer Window
        (2 rows). Reserve `4 + nb` chrome rows total so the buffer + body
        chrome + footer Window sum to the terminal height exactly (the
        flex_spacer collapses to zero, preserving the editor-mode
        anchoring). Sync with `self._profile_editor_text`'s leading blanks —
        change them together.

        (Sanity check: launcher nb=2 → 6 / 13, identical to the historic
        two-blank layout; popup nb=1 → 5 / 12.)"""
        nb = self._host.title_blank_above()
        if self._editor_mode == "editor":
            return max(15, self._host.term_rows() - (4 + nb))
        return max(15, self._host.term_rows() - (11 + nb))
    
    
    def _editor_list_visible(self):
        """List data rows visible in the body (header sits above)."""
        return max(1, self._editor_body_h() - 1)
    
    
    def _profile_editor_set_tab(self, idx):
        """Switch to tab `idx`. Resets list cursor + scroll to 0 and
        refreshes detail-panel buffers from the new active kind's first
        entry, so cross-tab navigation always lands the cursor on a
        real row with valid in-buffer cursors."""
        n = len(_PROFILE_EDITOR_TABS)
        new_idx = max(0, min(n - 1, idx))
        if new_idx != self._editor_active_tab:
            self._editor_active_tab = new_idx
            self._editor_list_cursor = 0
            self._editor_list_scroll = 0
            self._editor_refresh_buffers()
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _profile_editor_set_hover_tab(self, idx):
        if self._editor_hover_tab != idx:
            self._editor_hover_tab = idx
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _profile_editor_set_hover_row(self, idx):
        if self._editor_hover_row != idx:
            self._editor_hover_row = idx
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _profile_editor_clear_hover(self):
        changed = False
        if self._editor_hover_tab is not None:
            self._editor_hover_tab = None
            changed = True
        if self._editor_hover_row is not None:
            self._editor_hover_row = None
            changed = True
        if self._editor_toggle_hover is not None:
            self._editor_toggle_hover = None
            changed = True
        if changed and self._host.app:
            self._host.app.invalidate()
    
    
    def _profile_editor_set_focus(self, panel, field=None):
        """Set the focus zone. Optional `field` selects the detail-panel
        field when entering panel=2. Switching panels arms the Pattern
        required-error when leaving an empty Pattern field. Any focus or
        field change clears live selections in both text fields — leaving
        the field invalidates the selection.
    
        Detail-field semantics depend on the active kind:
          - text-bodied + macro: 0 = Pattern/Key, 1 = Body
          - highlight: 0 = Pattern, 1 = Style, 2 = Text, 3 = Background
        """
        # Any explicit menu-zone focus clears the toggle row's keyboard claim.
        self._editor_unfocus_toggle()
        prev_focus = self._editor_focus
        prev_field = self._editor_detail_field
        leaving_pattern = (
            prev_focus == 2 and prev_field == 0
            and (panel != 2 or (field is not None and field != 0))
        )
        leaving_body = (
            prev_focus == 2 and prev_field == 1
            and (panel != 2 or (field is not None and field != 1))
        )
        if leaving_pattern:
            entry = self._editor_current_entry()
            if entry is not None and entry.pattern == "":
                self._editor_pattern_touched = True
            self._editor_clear_pattern_selection()
        if leaving_body:
            self._editor_clear_body_selection()
        if panel != 2:
            self._editor_clear_selections()
        if panel == 2:
            if field is None:
                field = self._editor_detail_field if prev_focus == 2 else 0
            max_field = self._editor_hl_zone_count() - 1
            self._editor_detail_field = max(0, min(max_field, field))
        if self._editor_focus == panel and (panel != 2 or self._editor_detail_field == prev_field):
            return
        self._editor_focus = panel
        self._host.focus_current_frame()
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _profile_editor_cycle_focus(self, delta):
        """Cycle the focus chain.
    
        Menu mode: toggle → kind → list → detail.Pattern → detail.Body →
        toggle. Highlight detail has four zones; macro has two; aliases /
        actions / substitutes have two. The detail zones come from
        `self._editor_hl_zone_count` so the cycle length adapts to the kind.
    
        Editor mode: toggle → buffer → toggle."""
        if self._editor_mode == "editor":
            new_focused = not self._editor_toggle_focused
            if new_focused:
                self._editor_focus_toggle()
            else:
                self._editor_unfocus_toggle()
            return
        detail_zones = self._editor_hl_zone_count()
        total = 3 + detail_zones   # toggle + kind + list + detail zones
        if self._editor_toggle_focused:
            idx = 0
        elif self._editor_focus == 0:
            idx = 1
        elif self._editor_focus == 1:
            idx = 2
        else:
            idx = 3 + min(self._editor_detail_field, detail_zones - 1)
        new_idx = (idx + delta) % total
        if new_idx == 0:
            self._editor_focus_toggle()
            return
        self._editor_unfocus_toggle()
        if new_idx == 1:
            self._profile_editor_set_focus(0)
        elif new_idx == 2:
            self._profile_editor_set_focus(1)
        else:
            self._profile_editor_set_focus(2, field=new_idx - 3)
    
    
    def _profile_editor_active_kind(self):
        _, kind = _PROFILE_EDITOR_TABS[self._editor_active_tab]
        return kind
    
    
    def _profile_editor_active_count(self):
        if self._editor_data is None:
            return 0
        return len(self._editor_data.entries_of(self._profile_editor_active_kind()))
    
    
    def _profile_editor_display_view(self):
        """Return the active tab's entries in ascending display order. The
        underlying `self._editor_data.items` is already sorted by `parse_profile`,
        but `entries_of` returns them in items-order, which a mid-session
        create can scramble (the new entry is appended to the bottom). A
        presentation-only sort keeps the list view stable until the next
        save/mode-flip re-sorts the underlying items.
    
        `macro` entries sort by their *display name* rather than the raw
        escape sequence so the list groups F-keys before numpad keys before
        Alt+letters, matching what the user sees. Unknown escapes are
        keyed on `Custom: <raw>` so they cluster together at the end."""
        if self._editor_data is None:
            return []
        kind = self._profile_editor_active_kind()
        entries = self._editor_data.entries_of(kind)
        if kind == "macro":
            def _key(e):
                name = macro_keys.escape_to_name(e.pattern)
                return name if name is not None else f"Custom: {e.pattern}"
            return sorted(entries, key=_key)
        return sorted(entries, key=lambda e: e.pattern)
    
    
    def _profile_editor_display_total(self):
        """Total displayed rows in the list: entries + 1 for the
        `+ New entry` sentinel."""
        return len(self._profile_editor_display_view()) + 1
    
    
    def _editor_current_entry(self):
        """The Entry under the list cursor in the display view, or `None`
        when the cursor sits on the `+ New entry` sentinel or the view is
        empty."""
        view = self._profile_editor_display_view()
        if 0 <= self._editor_list_cursor < len(view):
            return view[self._editor_list_cursor]
        return None
    
    
    def _editor_cursor_on_sentinel(self):
        return self._editor_list_cursor == len(self._profile_editor_display_view())
    
    
    def _editor_refresh_buffers(self):
        """Refresh transient cursors from the current entry. Pattern and
        Body are read directly from the Entry; the in-buffer cursors land
        at end-of-buffer (and end-of-last-line for Body) so subsequent
        typing appends naturally. The pattern-touched flag resets — it
        tracks "have you ever left THIS entry's Pattern field empty" — so
        navigating away and back doesn't keep a stale error visible on a
        different row.
    
        On `highlight` entries the three palette zones (Style, Text,
        Background) are re-initialised by parsing `entry.body`. A body
        that decomposes cleanly through `_hl_parse_body` sets the style
        toggles and lands the text/bg cursors on the matching swatches;
        a non-decomposable body stashes the original value in the Custom
        slot and parks the user on it."""
        entry = self._editor_current_entry()
        self._editor_body_scroll = 0
        if entry is None:
            self._editor_pattern_cursor = 0
            self._editor_body_line = 0
            self._editor_body_col = 0
            self._editor_hl_text_row = 0
            self._editor_hl_text_col = 0
            self._editor_hl_text_sel = None
            self._editor_hl_bg_row   = 0
            self._editor_hl_bg_col   = 0
            self._editor_hl_bg_sel   = None
            self._editor_hl_style_cursor = 0
        else:
            self._editor_pattern_cursor = len(entry.pattern)
            body_lines = entry.body.split("\n") if entry.body else [""]
            self._editor_body_line = max(0, len(body_lines) - 1)
            self._editor_body_col  = len(body_lines[self._editor_body_line])
            if entry.kind == "highlight":
                parsed = _hl_parse_body(entry.body)
                if parsed is not None:
                    _styles, text_color, bg_color = parsed
                    # Selection mirrors the body's text/bg colour; cursor
                    # parks on the selected swatch (or 0,0 when no selection).
                    text_pos = (_hl_palette_position_for_color(text_color)
                                if text_color else None)
                    self._editor_hl_text_sel = text_pos
                    self._editor_hl_text_row, self._editor_hl_text_col = text_pos or (0, 0)
                    bg_pos = (_hl_palette_position_for_color(bg_color)
                              if bg_color else None)
                    self._editor_hl_bg_sel = bg_pos
                    self._editor_hl_bg_row, self._editor_hl_bg_col = bg_pos or (0, 0)
                    self._editor_hl_style_cursor = 0
                else:
                    # Non-decomposable body — nothing selected on either
                    # dimension. Cursor parks at (0,0) so navigation starts
                    # somewhere visible; the original body stays in
                    # `entry.body` until the user toggles a swatch.
                    self._editor_hl_text_row, self._editor_hl_text_col = 0, 0
                    self._editor_hl_text_sel = None
                    self._editor_hl_bg_row, self._editor_hl_bg_col = 0, 0
                    self._editor_hl_bg_sel = None
                    self._editor_hl_style_cursor = 0
            else:
                self._editor_hl_text_row = 0
                self._editor_hl_text_col = 0
                self._editor_hl_text_sel = None
                self._editor_hl_bg_row   = 0
                self._editor_hl_bg_col   = 0
                self._editor_hl_bg_sel   = None
                self._editor_hl_style_cursor = 0
        self._editor_pattern_touched = False
        self._editor_hl_hover = None
        self._editor_clear_selections()
    
    
    def _editor_hl_active_styles(self):
        """Return the styles currently active on the cursor entry — by
        re-parsing the body. Returns an empty set when the body is in the
        Custom slot or doesn't parse."""
        entry = self._editor_current_entry()
        if entry is None or entry.kind != "highlight":
            return set()
        parsed = _hl_parse_body(entry.body)
        if parsed is None:
            return set()
        return parsed[0]
    
    
    def _editor_hl_compose_body(self):
        """Compose `entry.body` from the current selections + active styles.
        Phase 6.2: the SELECTION (not the cursor) drives the body — either
        selection may be `None`, meaning "no colour on this dimension".
        Writes the new body back to `entry.body` (which drops `_raw`)."""
        entry = self._editor_current_entry()
        if entry is None or entry.kind != "highlight":
            return
        text_color = (_hl_palette_color_at(*self._editor_hl_text_sel)
                      if self._editor_hl_text_sel else None)
        bg_color = (_hl_palette_color_at(*self._editor_hl_bg_sel)
                    if self._editor_hl_bg_sel else None)
        styles = self._editor_hl_active_styles()
        new_body = _hl_serialize(styles, text_color, bg_color)
        if entry.body != new_body:
            entry.body = new_body
    
    
    def _editor_hl_toggle_style(self, style):
        """Flip `style` in the active set and re-serialise the body."""
        entry = self._editor_current_entry()
        if entry is None or entry.kind != "highlight":
            return
        styles = self._editor_hl_active_styles()
        if style in styles:
            styles.remove(style)
        else:
            styles.add(style)
        text_color = (_hl_palette_color_at(*self._editor_hl_text_sel)
                      if self._editor_hl_text_sel else None)
        bg_color = (_hl_palette_color_at(*self._editor_hl_bg_sel)
                    if self._editor_hl_bg_sel else None)
        entry.body = _hl_serialize(styles, text_color, bg_color)
    
    
    def _editor_hl_toggle_text_selection_at_cursor(self):
        """Enter / click on a Text swatch: if the cursor sits on the
        currently selected swatch, clear the selection (no text colour).
        Otherwise, mark the cursor swatch as selected. Re-composes the body."""
        pos = (self._editor_hl_text_row, self._editor_hl_text_col)
        self._editor_hl_text_sel = None if self._editor_hl_text_sel == pos else pos
        self._editor_hl_compose_body()
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_hl_toggle_bg_selection_at_cursor(self):
        """Enter / click on a BG swatch: toggle the BG selection at the
        cursor and re-compose the body."""
        pos = (self._editor_hl_bg_row, self._editor_hl_bg_col)
        self._editor_hl_bg_sel = None if self._editor_hl_bg_sel == pos else pos
        self._editor_hl_compose_body()
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_hl_set_text_cursor(self, row, col):
        """Move the text-palette cursor to `(row, col)` (clamped). Cursor
        movement is decoupled from selection — see ADR 0084."""
        row = max(0, min(_HL_PALETTE_ROWS - 1, row))
        col = max(0, min(_HL_PALETTE_COLS - 1, col))
        if (row, col) == (self._editor_hl_text_row, self._editor_hl_text_col):
            return
        self._editor_hl_text_row = row
        self._editor_hl_text_col = col
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_hl_set_bg_cursor(self, row, col):
        """Move the bg-palette cursor to `(row, col)` (clamped). Cursor
        movement is decoupled from selection — see ADR 0084. The `-1`
        sentinel for "(None)" is no longer used."""
        new_row = max(0, min(_HL_PALETTE_ROWS - 1, row))
        new_col = max(0, min(_HL_PALETTE_COLS - 1, col))
        if (new_row, new_col) == (self._editor_hl_bg_row, self._editor_hl_bg_col):
            return
        self._editor_hl_bg_row = new_row
        self._editor_hl_bg_col = new_col
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_hl_set_style_cursor(self, idx):
        """Move the style-toggle cursor to `idx` (clamped). Does NOT toggle
        the style — pressing Enter or clicking the toggle does that."""
        n = len(_HL_STYLE_TOKENS)
        idx = max(0, min(n - 1, idx))
        if idx == self._editor_hl_style_cursor:
            return
        self._editor_hl_style_cursor = idx
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_lines(self):
        """The current entry's body split on `\\n`. `["" ]` when no entry or
        empty body, so the renderer always has at least one row to draw."""
        entry = self._editor_current_entry()
        if entry is None or entry.body == "":
            return [""]
        return entry.body.split("\n")
    
    
    def _editor_body_set_lines(self, lines):
        """Write `lines` back into the current entry's `body`. Joining with
        `\\n` round-trips the multi-line representation; `entry.body = ...`
        goes through `__setattr__` and clears `_raw`."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        entry.body = "\n".join(lines)
    
    
    def _editor_body_clamp_cursor(self):
        """Defensively clamp `self._editor_body_line` / `self._editor_body_col` into
        the current body's shape. Called from edit and nav paths that may
        have advanced past the trailing edge."""
        lines = self._editor_body_lines()
        self._editor_body_line = max(0, min(len(lines) - 1, self._editor_body_line))
        self._editor_body_col  = max(0, min(len(lines[self._editor_body_line]),
                                       self._editor_body_col))
    
    
    def _editor_body_insert_char(self, ch):
        """Insert `ch` at the current (line, col) cursor and advance the
        column by one. Splits and joins use `\\n` so the Entry's body
        string mirrors the visual line break exactly. Replaces the live
        selection (if any) before inserting."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        self._editor_body_delete_selection()
        lines = self._editor_body_lines()
        if not lines:
            lines = [""]
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        lines[line] = lines[line][:col] + ch + lines[line][col:]
        self._editor_body_set_lines(lines)
        self._editor_body_col = col + 1
    
    
    def _editor_body_insert_newline(self):
        """Split the current line at the cursor column and place the cursor
        at the start of the new line. Replaces the live selection (if any)
        before splitting."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        self._editor_body_delete_selection()
        lines = self._editor_body_lines()
        if not lines:
            lines = [""]
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        head, tail = lines[line][:col], lines[line][col:]
        lines[line] = head
        lines.insert(line + 1, tail)
        self._editor_body_set_lines(lines)
        self._editor_body_line = line + 1
        self._editor_body_col  = 0
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_backspace(self):
        """Delete the character before the cursor. At the start of a line
        (col == 0) join with the previous line instead, placing the cursor
        at the join point — standard text-editor backspace semantics. With
        a live selection, delete the selection instead."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        if self._editor_body_delete_selection():
            if self._host.app:
                self._host.app.invalidate()
            return
        lines = self._editor_body_lines()
        if not lines:
            return
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        if col > 0:
            lines[line] = lines[line][:col - 1] + lines[line][col:]
            self._editor_body_set_lines(lines)
            self._editor_body_col = col - 1
        elif line > 0:
            prev_len = len(lines[line - 1])
            lines[line - 1] = lines[line - 1] + lines[line]
            del lines[line]
            self._editor_body_set_lines(lines)
            self._editor_body_line = line - 1
            self._editor_body_col  = prev_len
        # else: top-left corner of an empty buffer — nothing to delete.
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_move_left(self):
        """← within Body. Wraps from start-of-line to end-of-previous-line.
        No-op at the top-left corner."""
        lines = self._editor_body_lines()
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        if col > 0:
            self._editor_body_col = col - 1
        elif line > 0:
            self._editor_body_line = line - 1
            self._editor_body_col  = len(lines[line - 1])
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_move_right(self):
        """→ within Body. Wraps from end-of-line to start-of-next-line.
        No-op at the bottom-right corner."""
        lines = self._editor_body_lines()
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        if col < len(lines[line]):
            self._editor_body_col = col + 1
        elif line < len(lines) - 1:
            self._editor_body_line = line + 1
            self._editor_body_col  = 0
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_move_line(self, delta):
        """Up / Down within Body — preserve the column as far as the new
        line allows. Returns True when the cursor actually moved, so the
        `↑/↓` keybind can fall through to inter-zone nav at the edges."""
        lines = self._editor_body_lines()
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        new_line = line + delta
        if new_line < 0 or new_line >= len(lines):
            return False
        self._editor_body_line = new_line
        self._editor_body_col  = min(self._editor_body_col, len(lines[new_line]))
        if self._host.app:
            self._host.app.invalidate()
        return True
    
    
    def _editor_set_pattern(self, text):
        """Update the current entry's pattern, re-sort the display view,
        and re-anchor the list cursor onto the same entry."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        entry.pattern = text
        # Re-sort and re-anchor.
        view_after = self._profile_editor_display_view()
        try:
            self._editor_list_cursor = view_after.index(entry)
        except ValueError:
            self._editor_list_cursor = 0
        self._profile_editor_scroll_into_view()
    
    
    def _editor_clear_pattern_selection(self):
        self._editor_pattern_anchor = None
    
    
    def _editor_clear_body_selection(self):
        self._editor_body_anchor_line = None
        self._editor_body_anchor_col  = None
    
    
    def _editor_clear_selections(self):
        """Clear both Pattern and Body selection anchors."""
        self._editor_clear_pattern_selection()
        self._editor_clear_body_selection()
    
    
    def _editor_pattern_set_anchor_if_none(self):
        """Arm the Pattern selection anchor at the current cursor. Called
        from shift-arrow handlers so a fresh shift-move starts a selection
        rooted at the current cursor."""
        if self._editor_pattern_anchor is None:
            self._editor_pattern_anchor = self._editor_pattern_cursor
    
    
    def _editor_body_set_anchor_if_none(self):
        """Arm the Body selection anchor at the current cursor."""
        if self._editor_body_anchor_line is None:
            self._editor_body_anchor_line = self._editor_body_line
            self._editor_body_anchor_col  = self._editor_body_col
    
    
    def _editor_pattern_selection(self):
        """Return `(start, end)` in Pattern (inclusive, exclusive) or None
        when no live selection. `start == end` is treated as no selection."""
        if self._editor_pattern_anchor is None:
            return None
        a = self._editor_pattern_anchor
        c = self._editor_pattern_cursor
        if a == c:
            return None
        return (min(a, c), max(a, c))
    
    
    def _editor_body_selection(self):
        """Return `((s_line, s_col), (e_line, e_col))` for the Body
        selection, or None. Ordering normalised so start ≤ end in document
        order (line first, then column)."""
        if self._editor_body_anchor_line is None:
            return None
        a = (self._editor_body_anchor_line, self._editor_body_anchor_col)
        c = (self._editor_body_line, self._editor_body_col)
        if a == c:
            return None
        return (min(a, c), max(a, c))
    
    
    def _editor_body_line_selection_range(self, line_idx):
        """The per-line selection slice `(start_col, end_col)` for `line_idx`,
        or None when the selection doesn't touch this line. Used by the
        renderer to paint the C_SELECTED band per visible line."""
        sel = self._editor_body_selection()
        if sel is None:
            return None
        (sl, sc), (el, ec) = sel
        if line_idx < sl or line_idx > el:
            return None
        lines = self._editor_body_lines()
        line_len = len(lines[line_idx]) if 0 <= line_idx < len(lines) else 0
        start_col = sc if line_idx == sl else 0
        # End-of-line lines (anywhere except the last line of the selection)
        # paint one past the visible content so the selection reads as
        # continuous — the renderer treats `line_len + 1` as "include the
        # trailing space cell".
        end_col = ec if line_idx == el else line_len + 1
        return (start_col, end_col)
    
    
    def _editor_pattern_delete_selection(self):
        """When a Pattern selection exists, delete it and place the cursor
        at the selection start. Returns True iff a deletion happened."""
        sel = self._editor_pattern_selection()
        if sel is None:
            return False
        entry = self._editor_current_entry()
        if entry is None:
            return False
        s, e = sel
        pat = entry.pattern
        self._editor_set_pattern(pat[:s] + pat[e:])
        self._editor_pattern_cursor = s
        self._editor_pattern_anchor = None
        return True
    
    
    def _editor_body_delete_selection(self):
        """When a Body selection exists, delete it and place the cursor at
        the selection start. Returns True iff a deletion happened."""
        sel = self._editor_body_selection()
        if sel is None:
            return False
        (sl, sc), (el, ec) = sel
        lines = self._editor_body_lines()
        if not lines:
            return False
        sl = max(0, min(len(lines) - 1, sl))
        el = max(0, min(len(lines) - 1, el))
        sc = max(0, min(len(lines[sl]), sc))
        ec = max(0, min(len(lines[el]), ec))
        head = lines[sl][:sc]
        tail = lines[el][ec:]
        new_lines = lines[:sl] + [head + tail] + lines[el + 1:]
        self._editor_body_set_lines(new_lines)
        self._editor_body_line = sl
        self._editor_body_col  = sc
        self._editor_body_anchor_line = None
        self._editor_body_anchor_col  = None
        return True
    
    
    def _editor_pattern_insert_char(self, ch):
        """Insert `ch` at the pattern cursor and advance the cursor. Replaces
        the live selection (if any) before inserting."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        self._editor_pattern_delete_selection()
        pat = entry.pattern
        col = max(0, min(len(pat), self._editor_pattern_cursor))
        self._editor_set_pattern(pat[:col] + ch + pat[col:])
        self._editor_pattern_cursor = col + 1
    
    
    def _editor_pattern_backspace(self):
        """Delete the character before the pattern cursor. With a live
        selection, delete the selection instead."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        if self._editor_pattern_delete_selection():
            return
        pat = entry.pattern
        col = max(0, min(len(pat), self._editor_pattern_cursor))
        if col == 0:
            return
        self._editor_set_pattern(pat[:col - 1] + pat[col:])
        self._editor_pattern_cursor = col - 1
    
    
    def _editor_pattern_forward_delete(self):
        """Delete the character *at* the pattern cursor (the cell under the
        cursor). With a live selection, delete the selection instead."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        if self._editor_pattern_delete_selection():
            return
        pat = entry.pattern
        col = max(0, min(len(pat), self._editor_pattern_cursor))
        if col >= len(pat):
            return
        self._editor_set_pattern(pat[:col] + pat[col + 1:])
    
    
    def _editor_pattern_move_left(self):
        entry = self._editor_current_entry()
        if entry is None:
            return
        if self._editor_pattern_cursor > 0:
            self._editor_pattern_cursor -= 1
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_pattern_move_right(self):
        entry = self._editor_current_entry()
        if entry is None:
            return
        if self._editor_pattern_cursor < len(entry.pattern):
            self._editor_pattern_cursor += 1
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_pattern_move_home(self):
        """Pattern is single-line — Home goes to col 0."""
        if self._editor_current_entry() is None:
            return
        self._editor_pattern_cursor = 0
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_pattern_move_end(self):
        """Pattern is single-line — End goes to len(pattern)."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        self._editor_pattern_cursor = len(entry.pattern)
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_move_home(self):
        """Home in Body — start of the current logical line."""
        if self._editor_current_entry() is None:
            return
        self._editor_body_col = 0
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_move_end(self):
        """End in Body — end of the current logical line."""
        if self._editor_current_entry() is None:
            return
        lines = self._editor_body_lines()
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        self._editor_body_col = len(lines[line])
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_body_forward_delete(self):
        """Delete the character at the cursor in Body. At end-of-line, join
        with the next line. With a live selection, delete the selection."""
        entry = self._editor_current_entry()
        if entry is None:
            return
        if self._editor_body_delete_selection():
            return
        lines = self._editor_body_lines()
        if not lines:
            return
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        if col < len(lines[line]):
            lines[line] = lines[line][:col] + lines[line][col + 1:]
            self._editor_body_set_lines(lines)
        elif line < len(lines) - 1:
            lines[line] = lines[line] + lines[line + 1]
            del lines[line + 1]
            self._editor_body_set_lines(lines)
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_validation_error(self):
        """Inline validation error text or None. Precedence — highest first:
    
          1. `Pattern is required.` — empty pattern, but only once the user
             has left the field at least once (touched flag).
          2. `Unbalanced braces in <pattern-label>.` — Pattern has mismatched
             braces; tt++ would reject the line on next load. Live, not
             gated by touched.
          3. `Unbalanced braces in <body-label>.` — same for Body.
    
        Save is **never** blocked by these. The user sees them while
        editing and is expected to fix them; if they ESC anyway, tt++
        will surface the error on next session load."""
        entry = self._editor_current_entry()
        if entry is None:
            return None
        if self._editor_pattern_touched and entry.pattern == "":
            return "Pattern is required."
        kind = entry.kind
        pat_lbl, body_lbl = DETAIL_LABELS.get(kind, ("Pattern", "Body"))
        if not _braces_balanced(entry.pattern):
            return f"Unbalanced braces in {pat_lbl}."
        if not _braces_balanced(entry.body):
            return f"Unbalanced braces in {body_lbl}."
        return None
    
    
    def _editor_create_new_entry(self):
        """Append a blank Entry of the active kind to `Profile.items`, move
        the list cursor onto it in the sorted view, and focus the detail
        panel's Pattern field. Per-kind defaults come from
        `DETAIL_NEW_DEFAULTS`; abandoning a create is harmless because
        `save_profile` drops empty-pattern entries before write.
    
        Macros are special: the new entry's Key cell is left empty and the
        key-capture overlay is auto-pushed so the user never sees a
        "[ Press to bind… ]" placeholder in the wild. ESC on that overlay
        removes the unfilled Entry."""
        if self._editor_data is None:
            return
        kind = self._profile_editor_active_kind()
        pat_default, body_default = DETAIL_NEW_DEFAULTS.get(kind, ("", ""))
        entry = profile_io.Entry(
            kind=kind, pattern=pat_default, body=body_default,
            priority=None, _raw=None)
        self._editor_data.items.append(entry)
        view_after = self._profile_editor_display_view()
        try:
            self._editor_list_cursor = view_after.index(entry)
        except ValueError:
            self._editor_list_cursor = 0
        self._profile_editor_scroll_into_view()
        self._editor_refresh_buffers()
        self._profile_editor_set_focus(2, field=0)
        if kind == "macro":
            self._editor_push_keybind_overlay(just_created=True)
    
    
    def _profile_editor_scroll_into_view(self):
        """Adjust `self._editor_list_scroll` so the cursor row is visible."""
        visible = self._editor_list_visible()
        if self._editor_list_cursor < self._editor_list_scroll:
            self._editor_list_scroll = self._editor_list_cursor
        elif self._editor_list_cursor >= self._editor_list_scroll + visible:
            self._editor_list_scroll = self._editor_list_cursor - visible + 1
        # Include the sentinel row in the scroll bounds so the cursor can
        # land on it.
        total = self._profile_editor_display_total()
        max_scroll = max(0, total - visible)
        self._editor_list_scroll = max(0, min(max_scroll, self._editor_list_scroll))
    
    
    def _profile_editor_move_cursor(self, delta):
        """Move the list cursor by `delta`. Includes the "+ New entry"
        sentinel in the navigable range so users can reach it with ↓ at
        the end. Refreshes detail-panel buffers when the cursor lands on
        a different entry."""
        total = self._profile_editor_display_total()
        if total <= 0:
            return
        new_cursor = max(0, min(total - 1, self._editor_list_cursor + delta))
        if new_cursor != self._editor_list_cursor:
            self._editor_list_cursor = new_cursor
            self._profile_editor_scroll_into_view()
            self._editor_refresh_buffers()
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _profile_editor_jump_cursor(self, target):
        total = self._profile_editor_display_total()
        if total <= 0:
            return
        new_cursor = max(0, min(total - 1, target))
        if new_cursor != self._editor_list_cursor:
            self._editor_list_cursor = new_cursor
            self._profile_editor_scroll_into_view()
            self._editor_refresh_buffers()
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _profile_editor_scroll_list(self, delta):
        """Wheel scroll on the list — moves the viewport without moving the
        cursor."""
        visible = self._editor_list_visible()
        total = self._profile_editor_display_total()
        mx = max(0, total - visible)
        self._editor_list_scroll = max(0, min(mx, self._editor_list_scroll + delta))
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_list_wheel(self, delta):
        """Mouse-wheel scroll on the lite-mode entry list: shifts the
        viewport by `delta` rows through the Scrollbar widget so its
        internal offset stays the authoritative one; read it back into
        `self._editor_list_scroll`. The list cursor stays put."""
        if self._editor_list_sb is None:
            self._profile_editor_scroll_list(delta)
            return
        visible = self._editor_list_visible()
        total   = self._profile_editor_display_total()
        self._editor_list_sb.update(total, visible, height=visible)
        self._editor_list_sb.scroll_to(self._editor_list_scroll)
        self._editor_list_sb.scroll_by(delta)
        self._editor_list_scroll = self._editor_list_sb.scroll_offset
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _profile_editor_request_delete(self):
        """`Del` handler: remove the cursor Entry from `Profile.items`,
        clamp the cursor, and re-render. No confirmation — the friction-
        reduction trade-off is accepted (Del is far harder to press
        accidentally than a letter key). No-op when the cursor is on the
        `+ New entry` sentinel — there is nothing to delete.
    
        After delete, prefer keeping the cursor on a real entry rather
        than falling onto the sentinel — only land on the sentinel when
        there are no entries left."""
        view = self._profile_editor_display_view()
        if not view or not (0 <= self._editor_list_cursor < len(view)):
            return
        target = view[self._editor_list_cursor]
        if self._editor_data is not None:
            try:
                self._editor_data.items.remove(target)
            except ValueError:
                pass
        entries_total = self._profile_editor_active_count()
        if entries_total == 0:
            self._editor_list_cursor = 0   # the sentinel — only row left
        else:
            self._editor_list_cursor = max(
                0, min(entries_total - 1, self._editor_list_cursor))
        self._profile_editor_scroll_into_view()
        self._editor_refresh_buffers()
        if self._host.app:
            self._host.app.invalidate()
    
    
    # Scrollbar geometry used by the inline list/scrollbar render. Mirrors the
    # math in widgets/scrollbar.py so the editor's single-window layout can
    # emit one cell per body row without instantiating a separate column.
    def _editor_sb_thumb_geom(self, total, visible, height):
        if total <= 0 or total <= visible or height <= 0:
            return 0, 0
        ratio   = visible / total
        thumb_h = max(1, round(ratio * height))
        thumb_h = min(thumb_h, height)
        max_top = height - thumb_h
        mx_scroll = max(0, total - visible)
        if max_top <= 0 or mx_scroll <= 0:
            return 0, thumb_h
        top = round(self._editor_list_scroll / mx_scroll * max_top)
        top = max(0, min(max_top, top))
        return top, thumb_h
    
    
    def _editor_sb_click_to_offset(self, cell_row, total, visible, height):
        """Page-step click: clicks above/below the thumb scroll by one
        viewport; clicks on the thumb are a no-op. Mirrors the widget's
        Scrollbar.render() handler so the inline-rendered entry-list bar
        behaves identically. Returns the new `self._editor_list_scroll` value."""
        mx_scroll = max(0, total - visible)
        if mx_scroll <= 0:
            return self._editor_list_scroll
        top, thumb_h = self._editor_sb_thumb_geom(total, visible, height)
        if cell_row < top:
            return max(0, self._editor_list_scroll - visible)
        if cell_row >= top + thumb_h:
            return min(mx_scroll, self._editor_list_scroll + visible)
        return self._editor_list_scroll
    
    
    # ----- Rendering helpers --------------------------------------------------
    # Per-kind two-line hint shown under the `─── Hint ───` divider in the
    # detail panel. Phrased for lite-mode input (pattern + body cells, not
    # the full `#command` line); `→` separates the pattern side from the
    # command side. Each line must fit `_EDITOR_DETAIL_W - 2` (~33 cells)
    # without wrapping.
    def _editor_body_lines_for_entry(self, entry):
        """Split an entry's body on literal `\\n` so multi-line entries render
        each physical line in the bordered body field."""
        if entry is None:
            return [""]
        return entry.body.split("\n") if entry.body else [""]
    
    
    def _editor_body_budget(self):
        """Visible-row budget for the lite-mode Commands / New-text body box.

        Derived from `_editor_body_h()` minus the rows the rest of the active
        kind's detail chain consumes (`_EDITOR_TEXT_BODY_CHROME` /
        `_EDITOR_MACRO_BODY_CHROME`), so the box fills the panel's available
        height instead of stopping at a fixed ceiling. Floored at
        `_EDITOR_BODY_MIN_ROWS` so the box stays usable on very short
        terminals. The chrome reserves the trailing hint block
        unconditionally, so the budget — and the overall layout — is
        height-stable whether or not a validation error shows."""
        if self._profile_editor_active_kind() == "macro":
            chrome = _EDITOR_MACRO_BODY_CHROME
        else:
            chrome = _EDITOR_TEXT_BODY_CHROME
        return max(_EDITOR_BODY_MIN_ROWS, self._editor_body_h() - chrome)


    def _editor_body_wheel(self, delta):
        """Mouse-wheel scroll on the lite-mode Body field. No-op when the
        body fits inside the visible budget; otherwise adjusts
        `self._editor_body_scroll` by `delta` lines, clamped. The body cursor
        stays put — the next cursor-moving keystroke pulls the viewport
        back via `self._editor_body_viewport`."""
        cap = self._editor_body_budget()
        line_count = len(self._editor_body_lines())
        if line_count <= cap:
            return
        mx = max(0, line_count - cap)
        new_scroll = max(0, min(mx, self._editor_body_scroll + delta))
        if new_scroll != self._editor_body_scroll:
            self._editor_body_scroll = new_scroll
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_body_scroll_cursor_into_view(self):
        """Pull the Commands viewport so the cursor's line is visible. Called
        from every Body cursor-mutating action (keystrokes, arrow nav, content
        clicks, shift-selection moves, insert/Backspace/Delete). Mirrors
        `_editor_buffer_scroll_cursor_into_view` for the editor-mode buffer.

        Per ADR 0083 the render path (`_editor_body_viewport`) no longer
        scrolls to the cursor; the viewport sits wherever the most recent
        cursor-mutating action (or wheel) put it."""
        cap = self._editor_body_budget()
        line_count = len(self._editor_body_lines())
        if line_count <= cap:
            self._editor_body_scroll = 0
            return
        cur = max(0, min(line_count - 1, self._editor_body_line))
        if cur < self._editor_body_scroll:
            self._editor_body_scroll = cur
        elif cur >= self._editor_body_scroll + cap:
            self._editor_body_scroll = cur - cap + 1
        self._editor_body_scroll = max(0, min(line_count - cap, self._editor_body_scroll))


    def _editor_body_viewport(self, line_count):
        """Return `(scroll, visible_count, overflow)` for the Commands viewport.

        Per ADR 0083 the render path must not scroll to the cursor — that
        re-clamp would fight wheel scrolling every frame. The cursor-into-view
        clamp lives in `_editor_body_scroll_cursor_into_view`, called from
        cursor-mutating actions. Here `_editor_body_scroll` is authoritative
        and is only clamped to bounds.

        `overflow` is True when `line_count` exceeds the budget — used to decide
        whether the body box needs an inline scrollbar column."""
        cap = self._editor_body_budget()
        if line_count <= cap:
            self._editor_body_scroll = 0
            return 0, line_count, False
        self._editor_body_scroll = max(0, min(line_count - cap, self._editor_body_scroll))
        return self._editor_body_scroll, cap, True
    
    
    def _editor_body_scrollbar_cell(self, visible_row, scroll, total, visible, focused):
        """Build the scrollbar cell for a body-box visible row when content
        overflows the cap. Mirrors the entry-list scrollbar glyphs: bright
        block thumb + dim track. Click handler is page-step (matching the
        Scrollbar widget contract)."""
        cap = self._editor_body_budget()
        top, thumb_h = _editor_sb_thumb_geom_generic(total, visible, cap, scroll)
        if top <= visible_row < top + thumb_h:
            style, glyph = "bold fg:#ffffff", "█"
        else:
            style, glyph = "fg:#585858", "░"
    
        def _handler(ev, row=visible_row, t=top, h=thumb_h):
            if ev.event_type == MouseEventType.SCROLL_UP:
                self._editor_body_wheel(-3)
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                self._editor_body_wheel(3)
                return None
            if ev.event_type == MouseEventType.MOUSE_UP:
                self._autoscroll_disarm()
                return None
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                self._autoscroll_set_target(row)
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            mx = max(0, total - visible)
            if row < t:
                self._editor_body_scroll = max(0, self._editor_body_scroll - visible)
            elif row >= t + h:
                self._editor_body_scroll = min(mx, self._editor_body_scroll + visible)
            else:
                return None
            # Keep the cursor inside the viewport — clamp to the new window
            # so subsequent typing happens where the user is looking.
            if self._editor_body_line < self._editor_body_scroll:
                self._editor_body_line = self._editor_body_scroll
            elif self._editor_body_line >= self._editor_body_scroll + visible:
                self._editor_body_line = self._editor_body_scroll + visible - 1
            self._autoscroll_arm(self._editor_body_autoscroll_step, row)
            if self._host.app:
                self._host.app.invalidate()
            return None
        return (style, glyph, _handler)
    
    
    def _editor_build_body_box(self, entry, body_focused, body_lbl, body_border,
                               body_focus_h):
        """Build the label + bordered Commands / New-text box for the body
        field. Visible content is sized to `_editor_body_budget()`; bodies
        longer than the budget render with an inline scrollbar in the right
        edge of the box and the viewport tracks the cursor.
    
        Returns the list of detail rows for the field (label + top border +
        visible content rows + bottom border)."""
        rows = []
        rows.append(_editor_pad_full(C_HINT, body_lbl, body_focus_h))
        rows.append(_editor_pad_full(body_border, _editor_box_top(_EDITOR_DETAIL_W),
                                     body_focus_h))
        body_lines  = self._editor_body_lines_for_entry(entry)
        cursor_line = max(0, min(len(body_lines) - 1, self._editor_body_line))
        scroll, visible, overflow = self._editor_body_viewport(len(body_lines))
        end = min(scroll + visible, len(body_lines))
        for vrow, i in enumerate(range(scroll, end)):
            line = body_lines[i]
            is_cursor_line = body_focused and i == cursor_line
            col = (self._editor_body_col if is_cursor_line else None)
            sel = (self._editor_body_line_selection_range(i)
                   if body_focused else None)
            sb_cell = None
            if overflow:
                sb_cell = self._editor_body_scrollbar_cell(
                    vrow, scroll, len(body_lines), visible, body_focused)
            rows.append(self._editor_box_content_row(
                line, body_focused, cursor_col=col,
                sel_range=sel,
                field_id="body", line_idx=i,
                scrollbar_cell=sb_cell))
        rows.append(_editor_pad_full(body_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                     body_focus_h))
        return rows
    
    
    def _editor_box_content_row(self, text, border_focused, cursor_col=None,
                                sel_range=None,
                                field_id=None, line_idx=None,
                                scrollbar_cell=None):
        """Render `│ <text> │` for a wide field. Splits the inner area
        into per-cell fragments so a click on any column can position the
        cursor there.
    
        `border_focused` controls the `│` border-character style; pass the
        field-level focus state so every row of a focused multi-line field
        draws consistent borders (the cursor line and the non-cursor lines
        look the same).
    
        `cursor_col`, when not None, marks the absolute column on this line
        where the in-buffer cursor sits — that cell paints `C_SELECTED`.
        Pass None on non-cursor lines.
    
        `sel_range`, when not None, is `(start_col, end_col)` of the live
        selection that touches this line (absolute columns, end-exclusive);
        every cell in `[start_col, end_col)` paints `C_SELECTED`.
    
        `field_id` is `"pattern"` or `"body"` and gates the per-cell click
        handler; `line_idx` (Body only) tells the handler which line within
        the body the click maps to.
    
        `scrollbar_cell`, when not None, is a `(style, glyph[, handler])`
        fragment that replaces the rightmost inner cell — used by the body
        field when its content overflows the visible-row budget. Effective
        content width drops by one in that case.
    
        Returns a list of `(style, text[, handler])` fragments summing to
        `_EDITOR_DETAIL_W` cells."""
        w = _EDITOR_DETAIL_W
        border_style = _editor_field_border_style(border_focused)
        if scrollbar_cell is None:
            inner = w - 4
        else:
            # Reserve the rightmost inner cell for the scrollbar; content
            # cells fill the remaining w-5 columns.
            inner = w - 5
    
        # Compute the visible view of the buffer + the cursor's visible col.
        # When the buffer fits in `inner`, show it fully. When it overflows,
        # scroll so the cursor stays visible — try to keep at least one
        # cell of context on each side.
        if cursor_col is None:
            cur_for_scroll = len(text)
        else:
            cur_for_scroll = max(0, min(len(text), cursor_col))
    
        if len(text) <= inner:
            view_text  = text + " " * (inner - len(text))
            start_col  = 0
        else:
            half = inner // 2
            start_col = max(0, min(len(text) - inner + 1, cur_for_scroll - half))
            view_text = text[start_col:start_col + inner]
            if len(view_text) < inner:
                view_text = view_text + " " * (inner - len(view_text))
    
        view_cursor = (cur_for_scroll - start_col) if cursor_col is not None else None
    
        # Body borders carry the body's focus handler so wheel events landing
        # on the vertical bars scroll the body viewport (when overflow). Other
        # fields keep the default `None` handler — there is nothing to scroll.
        border_h = (self._editor_make_field_focus_handler("body")
                    if field_id == "body" else None)
        frags = [(border_style, "│ ", border_h)]
    
        for i in range(inner):
            ch = view_text[i] if i < len(view_text) else " "
            abs_col = start_col + i
            in_sel = (sel_range is not None
                      and sel_range[0] <= abs_col < sel_range[1])
            is_cursor = (view_cursor is not None and i == view_cursor)
            # When a selection is active, the cursor sits at one boundary —
            # for a forward run that boundary is `sel_range[1]`, i.e. the
            # first cell *outside* the selection. Painting that cell as
            # C_SELECTED visually extended the highlight by one (e.g.
            # double-click in `{word}` looked like `word}`). Suppress the
            # cursor paint when a selection covers the run; the selection
            # cells themselves convey the extent.
            if in_sel or (is_cursor and sel_range is None):
                style = C_SELECTED
            else:
                style = C_ITEM if ch != " " else ""
            if field_id is None:
                frags.append((style, ch, None))
            else:
                # Per-cell click handler — focuses the field and positions
                # the cursor at this visible column. Body handlers also
                # capture the line index so multi-line clicks land
                # correctly.
                frags.append((style, ch,
                              self._editor_make_field_click_handler(
                                  field_id, i, line_idx, start=start_col)))
    
        if scrollbar_cell is not None:
            # `scrollbar_cell` may be a 2- or 3-tuple; normalise either way.
            frags.append(scrollbar_cell if len(scrollbar_cell) == 3
                         else (scrollbar_cell[0], scrollbar_cell[1], None))
    
        frags.append((border_style, " │", border_h))
        return frags
    
    
    def _editor_make_field_click_handler(self, field_id, visible_col, line_idx,
                                         start=0):
        """Build a `MOUSE_DOWN` handler that focuses the named detail
        field and positions the in-buffer cursor at the clicked column.
        `start` is the scroll offset of the visible view into the buffer
        so the click maps back to the right absolute column.
    
        A count-1 click clears any live selection on that field. A count-2
        click selects the word at the clicked position. A count-3 click
        selects the whole logical line in Body (incl. trailing `\\n` when
        present) or the entire single-line Pattern field."""
        def _handler(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                return None
            if ev.event_type == MouseEventType.SCROLL_UP:
                if field_id == "body":
                    self._editor_body_wheel(-3)
                    return None
                return NotImplemented
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                if field_id == "body":
                    self._editor_body_wheel(3)
                    return None
                return NotImplemented
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            target_col = max(0, start + visible_col)
            count = self._editor_click_tick(ev)
            if field_id == "pattern":
                entry = self._editor_current_entry()
                if entry is None:
                    return None
                self._profile_editor_set_focus(2, field=0)
                pat = entry.pattern
                if count == 2:
                    bounds = _editor_word_bounds(pat, target_col)
                    if bounds is None:
                        self._editor_pattern_cursor = len(pat)
                        self._editor_clear_pattern_selection()
                    else:
                        s, e = bounds
                        self._editor_pattern_anchor = s
                        self._editor_pattern_cursor = e
                elif count == 3:
                    self._editor_pattern_anchor = 0
                    self._editor_pattern_cursor = len(pat)
                else:
                    self._editor_pattern_cursor = max(0, min(len(pat), target_col))
                    self._editor_clear_pattern_selection()
            elif field_id == "body":
                entry = self._editor_current_entry()
                if entry is None:
                    return None
                self._profile_editor_set_focus(2, field=1)
                lines = self._editor_body_lines()
                line = max(0, min(len(lines) - 1,
                                  line_idx if line_idx is not None else 0))
                if count == 2:
                    bounds = _editor_word_bounds(lines[line], target_col)
                    if bounds is None:
                        self._editor_body_line = line
                        self._editor_body_col  = len(lines[line])
                        self._editor_clear_body_selection()
                    else:
                        s, e = bounds
                        self._editor_body_anchor_line = line
                        self._editor_body_anchor_col  = s
                        self._editor_body_line = line
                        self._editor_body_col  = e
                elif count == 3:
                    # End the selection at the line's last text character;
                    # excluding the trailing `\n` keeps the highlight off
                    # the next line's first cell.
                    self._editor_body_anchor_line = line
                    self._editor_body_anchor_col  = 0
                    self._editor_body_line = line
                    self._editor_body_col  = len(lines[line])
                else:
                    self._editor_body_line = line
                    self._editor_body_col  = max(0, min(len(lines[line]),
                                                   target_col))
                    self._editor_clear_body_selection()
                self._editor_body_scroll_cursor_into_view()
            if self._host.app:
                self._host.app.invalidate()
            return None
        return _handler
    
    
    def _editor_make_field_focus_handler(self, field_id):
        """A MOUSE_DOWN handler that focuses the named detail field without
        repositioning the in-buffer cursor at a column. Used by the label
        row, the top/bottom border rows, and the side-padding cells so a
        click anywhere on a field's outer bounding box brings it into
        focus. Wheel events on the body's chrome (label/borders) scroll the
        body viewport when it overflows the 10-row cap; pattern chrome
        ignores wheel."""
        def _handler(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                return None
            if ev.event_type == MouseEventType.SCROLL_UP:
                if field_id == "body":
                    self._editor_body_wheel(-3)
                    return None
                return NotImplemented
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                if field_id == "body":
                    self._editor_body_wheel(3)
                    return None
                return NotImplemented
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            entry = self._editor_current_entry()
            if entry is None:
                return None
            if field_id == "pattern":
                self._profile_editor_set_focus(2, field=0)
                self._editor_clear_pattern_selection()
            elif field_id == "body":
                self._profile_editor_set_focus(2, field=1)
                self._editor_clear_body_selection()
            if self._host.app:
                self._host.app.invalidate()
            return None
        return _handler
    
    
    def _editor_detail_lines(self, entry, total_lines):
        """Build the right-side detail rows. Returns a list of length
        `total_lines`; each element is itself a list of fragments summing
        to `_EDITOR_DETAIL_W` cells. Fragments are 2-tuples `(style, text)`
        or 3-tuples `(style, text, handler)` — both forms survive the
        outer compositor.
    
        Dispatches the body of the panel through
        `self._editor_dispatch_detail_builder`: text-bodied kinds reuse the
        Pattern + Body chain, `highlight` swaps Body for a palette grid,
        `macro` swaps Pattern for the press-to-bind Key cell.
    
        The wrapper handles the no-entry branch:
          • cursor on the `+ New entry` sentinel → centred prompt;
          • list empty *and* no entry under the cursor → empty-state hint.
        """
        kind = self._profile_editor_active_kind()
        _kind_sing, kind_plural = _EDITOR_KIND_LABELS.get(kind, (kind, kind))
    
        rows = []
        view = self._profile_editor_display_view()
    
        if entry is None:
            if len(view) == 0:
                msg = f"No {kind_plural} yet. Press n to add one."
            else:
                msg = f"Press Enter to create a new {_kind_sing}."
            wrapped = _wrap_text(msg, _EDITOR_DETAIL_W) or [""]
            top_blank = max(0, (total_lines - len(wrapped)) // 2)
            for _ in range(top_blank):
                rows.append(_editor_pad_full(C_HINT, ""))
            for line in wrapped:
                rows.append(_editor_centered_row(C_HINT, line))
            while len(rows) < total_lines:
                rows.append(_editor_pad_full(C_HINT, ""))
            return rows[:total_lines]
    
        builder = self._editor_dispatch_detail_builder(kind)
        return builder(entry, total_lines)
    
    
    def _editor_build_text_detail(self, entry, total_lines):
        """Pattern + Body editor for `alias`, `action`, `substitute`. Both
        fields are text inputs with the in-buffer cursor model + focused-
        border accent shared with the alias editor."""
        detail_focused = (self._editor_focus == 2)
        pat_lbl, body_lbl = DETAIL_LABELS.get(entry.kind, ("Pattern", "Body"))
        pattern_focused = detail_focused and self._editor_detail_field == 0
        body_focused    = detail_focused and self._editor_detail_field == 1
        pat_border  = _editor_field_border_style(pattern_focused)
        body_border = _editor_field_border_style(body_focused)
        pat_focus_h  = self._editor_make_field_focus_handler("pattern")
        body_focus_h = self._editor_make_field_focus_handler("body")
        pat_sel = self._editor_pattern_selection() if pattern_focused else None
    
        rows = []
    
        rows.append(_editor_pad_full(C_HINT, pat_lbl, pat_focus_h))
        rows.append(_editor_pad_full(pat_border, _editor_box_top(_EDITOR_DETAIL_W),
                                     pat_focus_h))
        rows.append(self._editor_box_content_row(
            entry.pattern, pattern_focused,
            cursor_col=self._editor_pattern_cursor if pattern_focused else None,
            sel_range=pat_sel,
            field_id="pattern"))
        rows.append(_editor_pad_full(pat_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                     pat_focus_h))
    
        rows.extend(self._editor_build_body_box(
            entry, body_focused, body_lbl, body_border, body_focus_h))
    
        err = self._editor_validation_error()
        if err:
            rows.append(_editor_pad_full(C_DANGER, err))
        else:
            rows.append(_editor_pad_full(C_HINT, ""))
    
        rows.append(_editor_pad_full(C_HINT, ""))
        rows.append(_editor_centered_row(C_HINT, "─── Hint ───"))
        for line in _EDITOR_HINTS.get(entry.kind, ("", "")):
            rows.append(_editor_pad_full(C_HINT, line))
        rows.append(_editor_pad_full(C_HINT, ""))
    
        while len(rows) < total_lines:
            rows.append(_editor_pad_full(C_HINT, ""))
        return rows[:total_lines]
    
    
    def _editor_build_palette_detail(self, entry, total_lines):
        """Highlight detail panel — Phase 6.4 layout.
    
        Rows (top → bottom), all centred within the detail panel:
    
            Pattern
            ┌────────────────────────────┐
            │ <pattern text>             │
            └────────────────────────────┘
            <blank>
            [ ]Undersc. [ ]Blink [ ]Reverse
            <blank>
            ── Text ──        ── BG ──
            [ ]██  [ ]██     [ ]██  [ ]██   ← row 0
            ...
            [ ]██  [ ]██     [ ]██  [ ]██   ← row 6
    
        Swatch toggle (`[X]`) reflects whether THAT swatch is the
        currently-selected text/bg colour (Phase 6.2: selection decoupled
        from cursor — see ADR 0084). Enter or click on a swatch toggles
        selection; mouse hover paints a hover highlight.
        """
        detail_focused = (self._editor_focus == 2)
        pat_lbl, _ = DETAIL_LABELS["highlight"]
        pattern_focused = detail_focused and self._editor_detail_field == 0
        style_focused   = detail_focused and self._editor_detail_field == 1
        text_focused    = detail_focused and self._editor_detail_field == 2
        bg_focused      = detail_focused and self._editor_detail_field == 3
        pat_border = _editor_field_border_style(pattern_focused)
        pat_focus_h = self._editor_make_field_focus_handler("pattern")
        pat_sel = self._editor_pattern_selection() if pattern_focused else None
    
        rows = []
    
        rows.append(_editor_pad_full(C_HINT, pat_lbl, pat_focus_h))
        rows.append(_editor_pad_full(pat_border, _editor_box_top(_EDITOR_DETAIL_W),
                                     pat_focus_h))
        rows.append(self._editor_box_content_row(
            entry.pattern, pattern_focused,
            cursor_col=self._editor_pattern_cursor if pattern_focused else None,
            sel_range=pat_sel,
            field_id="pattern"))
        rows.append(_editor_pad_full(pat_border, _editor_box_bot(_EDITOR_DETAIL_W),
                                     pat_focus_h))
    
        rows.append(_editor_pad_full(C_HINT, ""))
        rows.append(self._editor_hl_style_row(style_focused))
        rows.append(_editor_pad_full(C_HINT, ""))
        rows.append(self._editor_hl_section_headers_row())
        for r in range(_HL_PALETTE_ROWS):
            rows.append(self._editor_hl_palette_row(r, text_focused, bg_focused))
    
        err = self._editor_validation_error()
        if err:
            rows.append(_editor_pad_full(C_DANGER, err))
        else:
            rows.append(_editor_pad_full(C_HINT, ""))
    
        rows.append(_editor_pad_full(C_HINT, ""))
        rows.append(_editor_centered_row(C_HINT, "─── Hint ───"))
        for line in _EDITOR_HINTS.get("highlight", ("", "")):
            rows.append(_editor_pad_full(C_HINT, line))
        rows.append(_editor_pad_full(C_HINT, ""))
    
        while len(rows) < total_lines:
            rows.append(_editor_pad_full(C_HINT, ""))
        return rows[:total_lines]
    
    
    def _editor_build_macro_detail(self, entry, total_lines):
        """Key (press-to-bind cell) + Commands (text body) for `macro`.
    
        The Key cell is a focusable button, not a TextArea — the user can
        `Enter` or click it to push the key-capture overlay, which records
        the canonical tt++ escape into `entry.pattern`. Commands is the
        same text editor used for the other text-bodied kinds."""
        detail_focused = (self._editor_focus == 2)
        pat_lbl, body_lbl = DETAIL_LABELS["macro"]
        key_focused  = detail_focused and self._editor_detail_field == 0
        body_focused = detail_focused and self._editor_detail_field == 1
        body_border  = _editor_field_border_style(body_focused)
        body_focus_h = self._editor_make_field_focus_handler("body")
    
        rows = []
    
        rows.append(_editor_pad_full(C_HINT, pat_lbl))
        rows.append(self._editor_macro_key_cell_row(entry, key_focused))
        rows.append(_editor_pad_full(C_HINT, ""))
    
        rows.extend(self._editor_build_body_box(
            entry, body_focused, body_lbl, body_border, body_focus_h))
    
        err = self._editor_validation_error()
        if err:
            rows.append(_editor_pad_full(C_DANGER, err))
        else:
            rows.append(_editor_pad_full(C_HINT, ""))
    
        rows.append(_editor_pad_full(C_HINT, ""))
        rows.append(_editor_centered_row(C_HINT, "─── Hint ───"))
        for line in _EDITOR_HINTS.get("macro", ("", "")):
            rows.append(_editor_pad_full(C_HINT, line))
        rows.append(_editor_pad_full(C_HINT, ""))
    
        while len(rows) < total_lines:
            rows.append(_editor_pad_full(C_HINT, ""))
        return rows[:total_lines]
    
    
    def _editor_macro_key_cell_row(self, entry, focused):
        """Render the macro Key cell as a single row that fills the detail
        panel width. Focused state wraps the label in `C_BUTTON_ACTIVE_FOCUSED`
        (the same amber token the entry-list cursor row and kind buttons use);
        an accompanying click handler pushes the capture overlay."""
        label, style, _state = _editor_macro_key_cell_text(entry)
        w = _EDITOR_DETAIL_W
        indent = 0
        text = label
        if len(text) > w - indent:
            text = text[: max(0, w - indent - 1)] + "…"
        pad = max(0, w - indent - len(text))
        if focused:
            cell_style = C_BUTTON_ACTIVE_FOCUSED
        else:
            cell_style = style
    
        def _click(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            self._profile_editor_set_focus(2, field=0)
            self._editor_push_keybind_overlay(just_created=False)
            return None
    
        frags = [(cell_style, text, _click)]
        if pad > 0:
            frags.append(("", " " * pad, _click))
        return frags
    
    
    def _editor_hl_swatch_fragments(self, name, kind, is_selected, is_cursor,
                                    is_hover, row, col):
        """Build the fragments for one Text or BG swatch cell.
    
        `kind` is "text" or "bg". `[X]██` when selected, `[ ]██` otherwise.
        The `██` band is painted in the swatch's colour. Trailing space
        completes the 6-cell column.
    
        Focus + state styling: a cursor swatch (zone focused) wraps its
        checkbox in C_BUTTON_ACTIVE_FOCUSED — the same amber token the
        entry-list cursor row and kind buttons use — so the cursor reads
        against any underlying colour; hover paints C_HOVER on the
        checkbox slot. Cursor + focused wins over hover."""
        checkbox = "[X]" if is_selected else "[ ]"
        band = "██"
    
        if is_cursor:
            cb_style = C_BUTTON_ACTIVE_FOCUSED
        elif is_hover:
            cb_style = C_HOVER
        else:
            cb_style = C_ITEM
    
        style_key = _HL_DICT_KEY.get(name)
        fg = TTPP_COLOR_STYLES.get(style_key, "") if style_key else ""
        band_style = fg or C_ITEM
    
        handler = (self._editor_hl_make_text_handler(row, col)
                   if kind == "text" else self._editor_hl_make_bg_handler(row, col))
        trailing_pad = _HL_SWATCH_COL_W - len(checkbox) - len(band)
        return [
            (cb_style, checkbox, handler),
            (band_style, band, handler),
            ("", " " * trailing_pad, handler),
        ]
    
    
    def _editor_hl_make_text_handler(self, row, col):
        """MouseEvent handler for a Text swatch: hover paints C_HOVER;
        click moves the cursor to the swatch AND toggles its selection
        (Phase 6.2 — selection decoupled from cursor)."""
        def _handler(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                new_hover = ("text", row, col)
                if self._editor_hl_hover != new_hover:
                    self._editor_hl_hover = new_hover
                    if self._host.app:
                        self._host.app.invalidate()
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            self._profile_editor_set_focus(2, field=2)
            self._editor_hl_set_text_cursor(row, col)
            self._editor_hl_toggle_text_selection_at_cursor()
            return None
        return _handler
    
    
    def _editor_hl_make_bg_handler(self, row, col):
        """MouseEvent handler for a BG swatch: hover paints C_HOVER; click
        moves the cursor to the swatch AND toggles its selection."""
        def _handler(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                new_hover = ("bg", row, col)
                if self._editor_hl_hover != new_hover:
                    self._editor_hl_hover = new_hover
                    if self._host.app:
                        self._host.app.invalidate()
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            self._profile_editor_set_focus(2, field=3)
            self._editor_hl_set_bg_cursor(row, col)
            self._editor_hl_toggle_bg_selection_at_cursor()
            return None
        return _handler
    
    
    def _editor_hl_make_style_handler(self, idx):
        """Mouse handler for a Style toggle cell. Click flips the toggle
        on/off; hover paints C_HOVER."""
        def _handler(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                new_hover = ("style", 0, idx)
                if self._editor_hl_hover != new_hover:
                    self._editor_hl_hover = new_hover
                    if self._host.app:
                        self._host.app.invalidate()
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            self._profile_editor_set_focus(2, field=1)
            self._editor_hl_set_style_cursor(idx)
            self._editor_hl_toggle_style(_HL_STYLE_TOKENS[idx])
            if self._host.app:
                self._host.app.invalidate()
            return None
        return _handler
    
    
    def _editor_hl_style_row(self, focused):
        """Build the inline Style toggle row:
        `[X]Undersc. [X]Blink [X]Reverse` (Phase 6.3).
    
        Each toggle's on/off state is conveyed solely by the `[X]` / `[ ]`
        checkbox glyph — colour is a pure cursor/focus indicator, never
        keyed off `is_active`. Palette zones are amber-or-nothing: a
        cursor position inside a multi-cell zone is not a persistent
        selection (unlike the kind buttons or the entry-list cursor row),
        so when the Style zone loses focus the cursor simply disappears
        — no grey "out of focus" carry-over. The cursor cell paints
        `C_BUTTON_ACTIVE_FOCUSED` (amber) when the Style zone is focused;
        hover paints `C_HOVER`; everything else paints `C_HINT`.
        Precedence, highest first: cursor + focused > hover > default.
        Cells are centred within the detail panel width."""
        tokens = _HL_STYLE_TOKENS
        active = self._editor_hl_active_styles()
        cell_labels = [_HL_STYLE_LABELS[t] for t in tokens]
        cells = [f"[{'X' if t in active else ' '}]{lbl}"
                 for t, lbl in zip(tokens, cell_labels)]
        total_w = sum(len(c) for c in cells) + (len(cells) - 1)  # 1-space gaps
        pad_l = max(0, (_EDITOR_DETAIL_W - total_w) // 2)
        pad_r = max(0, _EDITOR_DETAIL_W - pad_l - total_w)
        frags = [("", " " * pad_l)]
        for i, (tok, lbl) in enumerate(zip(tokens, cell_labels)):
            is_cursor = focused and (i == self._editor_hl_style_cursor)
            is_hover  = (self._editor_hl_hover == ("style", 0, i)
                         and not is_cursor)
            checkbox = f"[{'X' if tok in active else ' '}]"
            if is_cursor:
                cell_style = C_BUTTON_ACTIVE_FOCUSED
            elif is_hover:
                cell_style = C_HOVER
            else:
                cell_style = C_HINT
            cb_style  = cell_style
            lbl_style = cell_style
            h = self._editor_hl_make_style_handler(i)
            frags.append((cb_style, checkbox, h))
            frags.append((lbl_style, lbl, h))
            if i < len(tokens) - 1:
                frags.append(("", " "))
        if pad_r > 0:
            frags.append(("", " " * pad_r))
        return frags
    
    
    def _editor_hl_section_headers_row(self):
        """Phase 6.4: `── Text ──` over the Text grid and `── BG ──` over
        the BG grid (U+2500 box-drawing glyphs, matching the `─── Hint ───`
        and frame divider styling). Each header is centred within its
        12-cell column area (two swatch columns wide). The whole row is
        itself centred within the detail panel."""
        text_hdr = "── Text ──"
        bg_hdr   = "── BG ──"
        text_pad_l = max(0, (_HL_HEADER_HALF_W - len(text_hdr)) // 2)
        text_pad_r = max(0, _HL_HEADER_HALF_W - text_pad_l - len(text_hdr))
        bg_pad_l   = max(0, (_HL_HEADER_HALF_W - len(bg_hdr))   // 2)
        bg_pad_r   = max(0, _HL_HEADER_HALF_W - bg_pad_l - len(bg_hdr))
        inner_w = _HL_GRID_W
        panel_pad_l = max(0, (_EDITOR_DETAIL_W - inner_w) // 2)
        panel_pad_r = max(0, _EDITOR_DETAIL_W - panel_pad_l - inner_w)
        return [
            ("", " " * panel_pad_l),
            ("", " " * text_pad_l),
            (C_HINT, text_hdr),
            ("", " " * text_pad_r),
            ("", " " * _HL_GRID_GAP),
            ("", " " * bg_pad_l),
            (C_HINT, bg_hdr),
            ("", " " * bg_pad_r),
            ("", " " * panel_pad_r),
        ]
    
    
    def _editor_hl_palette_row(self, r, text_focused, bg_focused):
        """Build one row of the swatch grid: two Text swatches, gap, two BG
        swatches. The whole row is centred within the detail panel.
    
        Each swatch is rendered as `[X]██` or `[ ]██` per its own selection
        state; the cursor (zone focused) draws as `C_BUTTON_ACTIVE_FOCUSED`
        (amber) on the checkbox slot."""
        text_dark, text_light = _HL_PALETTE[r]
        bg_dark, bg_light     = _HL_PALETTE[r]
    
        tdc = (text_focused and r == self._editor_hl_text_row
               and self._editor_hl_text_col == 0)
        tlc = (text_focused and r == self._editor_hl_text_row
               and self._editor_hl_text_col == 1)
        bdc = (bg_focused and r == self._editor_hl_bg_row
               and self._editor_hl_bg_col == 0)
        blc = (bg_focused and r == self._editor_hl_bg_row
               and self._editor_hl_bg_col == 1)
        tdh = (self._editor_hl_hover == ("text", r, 0) and not tdc)
        tlh = (self._editor_hl_hover == ("text", r, 1) and not tlc)
        bdh = (self._editor_hl_hover == ("bg",   r, 0) and not bdc)
        blh = (self._editor_hl_hover == ("bg",   r, 1) and not blc)
    
        td_sel = self._editor_hl_text_sel == (r, 0)
        tl_sel = self._editor_hl_text_sel == (r, 1)
        bd_sel = self._editor_hl_bg_sel   == (r, 0)
        bl_sel = self._editor_hl_bg_sel   == (r, 1)
    
        inner_w = _HL_GRID_W
        panel_pad_l = max(0, (_EDITOR_DETAIL_W - inner_w) // 2)
        panel_pad_r = max(0, _EDITOR_DETAIL_W - panel_pad_l - inner_w)
        frags = [("", " " * panel_pad_l)]
        frags.extend(self._editor_hl_swatch_fragments(text_dark,  "text", td_sel,
                                                 tdc, tdh, r, 0))
        frags.extend(self._editor_hl_swatch_fragments(text_light, "text", tl_sel,
                                                 tlc, tlh, r, 1))
        frags.append(("", " " * _HL_GRID_GAP))
        frags.extend(self._editor_hl_swatch_fragments(bg_dark,    "bg", bd_sel,
                                                 bdc, bdh, r, 0))
        frags.extend(self._editor_hl_swatch_fragments(bg_light,   "bg", bl_sel,
                                                 blc, blh, r, 1))
        if panel_pad_r > 0:
            frags.append(("", " " * panel_pad_r))
        return frags
    
    
    def _editor_list_row_text(self, entry, is_cursor, is_hover):
        """Render one list row as a list of `(style, text)` fragments
        summing to `_EDITOR_LIST_W` cells.
    
        Pattern column is fixed at `_EDITOR_PATTERN_COL_W` chars; remainder
        is the body column with `…` truncation. For `highlight` entries
        whose body resolves to a known palette colour, the body cell is
        rendered *in that colour* — so the list doubles as a colour
        preview. Custom (non-palette) values render in default text colour.
    
        `macro` entries show the readable key name (`Numpad 0`, `F1`,
        `Alt+a`) in place of the raw escape sequence — `escape_to_name`
        resolves the on-disk value; unknown escapes fall back to
        `Custom: <raw>` in `C_HINT`, the same convention as the
        highlights Custom slot.
    
        The cursor row uses a single `C_BUTTON_ACTIVE_FOCUSED` (amber) or
        `C_BUTTON_ACTIVE_UNFOCUSED` (grey) fragment for the whole row so
        the selection band reads as one element."""
        w = _EDITOR_LIST_W
        pat = entry.pattern
        pat_custom = False
        if entry.kind == "macro":
            name = macro_keys.escape_to_name(pat)
            if name is not None:
                pat = name
            else:
                pat = f"Custom: {pat}"
                pat_custom = True
        if len(pat) > _EDITOR_PATTERN_COL_W:
            pat = pat[:max(0, _EDITOR_PATTERN_COL_W - 1)] + "…"
        pat_cell = pat.ljust(_EDITOR_PATTERN_COL_W)
        body_col_w = w - _EDITOR_PATTERN_COL_W - 2
        # Phase 6.2: skip leading blank/whitespace-only lines so a body whose
        # first real content sits below empty lines still previews here. The
        # detail panel keeps the body verbatim — this only affects the list
        # preview cell.
        body_full = _list_body_first_line(entry.body)
        body_one_line = _list_body_preview(entry.body, body_col_w)
        body_cell = body_one_line.ljust(body_col_w)
        full_text = (pat_cell + "  " + body_cell)[:w].ljust(w)
    
        if is_cursor:
            cursor_style = (C_BUTTON_ACTIVE_FOCUSED if self._editor_focus == 1
                            else C_BUTTON_ACTIVE_UNFOCUSED)
            return [(cursor_style, full_text)]
        if is_hover:
            return [(C_HOVER, full_text)]
        if entry.kind == "highlight":
            # Color preview: render the swatch name in its own text-colour
            # when the body parses (using the *full* body — truncation in
            # the visible cell shouldn't disable the colour preview). Direct
            # single-colour bodies fall through the legacy lookup for
            # back-compat with pre-section-C profiles.
            if body_full in TTPP_COLOR_NAMES:
                return [
                    (C_ITEM, pat_cell + "  "),
                    (TTPP_COLOR_STYLES[body_full], body_cell),
                ]
            parsed = _hl_parse_body(body_full)
            if parsed is not None:
                _styles, text_color, _bg = parsed
                tc_style = _hl_color_style(text_color) if text_color else None
                if tc_style:
                    return [
                        (C_ITEM, pat_cell + "  "),
                        (tc_style, body_cell),
                    ]
        if entry.kind == "macro" and pat_custom:
            # Mirror the highlights Custom slot — dim the unknown-key cell so
            # it reads as "needs attention" without breaking column alignment.
            return [
                (C_HINT, pat_cell + "  "),
                (C_ITEM, body_cell),
            ]
        return [(C_ITEM, full_text)]
    
    
    def _editor_list_header_frag(self, visible_rows):
        """Build the list header fragments — `<pattern_label>  <body_label>`
        plus padding. Labels come from `DETAIL_LABELS[active_kind]` so the
        Highlights tab shows `Pattern + Color`, Substitutes shows
        `Text + New text`, etc.
    
        Returns a list of fragments that fills `_EDITOR_LIST_W` cells. The
        header stays in muted grey (`C_HINT`) regardless of focus — the
        three-state colour grammar reserves the focus signal for the cursor
        row inside the list and for the kind/mode buttons. The header is
        non-interactive in Phase 6.2; the underlying data is always sorted
        ascending so the click-to-toggle affordance was retired."""
        w = _EDITOR_LIST_W
        base_style = C_HINT
        kind = self._profile_editor_active_kind()
        pat_lbl, body_lbl = DETAIL_LABELS.get(kind, ("Pattern", "Body"))
        pat_col_w = _EDITOR_PATTERN_COL_W
        pat_label = pat_lbl[:pat_col_w].ljust(pat_col_w)
        body_label = body_lbl[: w - pat_col_w - 2].ljust(w - pat_col_w - 2)
        gap = "  "
    
        def _clear(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                self._profile_editor_set_hover_row(None)
                return None
            return NotImplemented
    
        return [
            (base_style, pat_label, _clear),
            (base_style, gap, _clear),
            (base_style, body_label, _clear),
        ]
    
    
    def _editor_clear_outer_hover(self, ev):
        """Outer fragment hover handler — clears every hover index inside the
        editor when MOUSE_MOVE lands in chrome (padding, blanks, etc.)."""
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            self._profile_editor_clear_hover()
            return None
        return NotImplemented
    
    
    # ---------------------------------------------------------------------------
    # Mode toggle (LITE / EDITOR)
    # ---------------------------------------------------------------------------
    def _editor_focused_line_hl_bg(self, terminal_bg):
        """Buffer-focused current-line band, derived from `terminal_bg`. Lifts
        the host bg toward white when it is dark, toward black when it is
        light, by `_EDITOR_LINE_HL_LIFT` — a small fixed offset that reads as
        a subtle band rather than a hard stripe. Reuses `_interpolate_hex`
        from the credits fade. Falls back to `bg:#1f1f1f` when `terminal_bg`
        is None so the legacy near-black behaviour is preserved."""
        if not terminal_bg:
            return "bg:#1f1f1f"
        r = int(terminal_bg[1:3], 16)
        g = int(terminal_bg[3:5], 16)
        b = int(terminal_bg[5:7], 16)
        target = "#000000" if (r + g + b) >= 384 else "#ffffff"
        return f"bg:{_interpolate_hex(terminal_bg, target, _EDITOR_LINE_HL_LIFT)}"
    
    
    def _editor_toggle_block(self, label):
        """Return the rendered text for a toggle block. Each block is the label
        wrapped in one cell of padding on each side, per the spec."""
        return f" {label} "
    
    
    def _editor_toggle_widget_w(self):
        """Total width of the LITE/EDITOR toggle including the single-space gap
        between the blocks."""
        return sum(len(self._editor_toggle_block(s)) for s in _EDITOR_TOGGLE_LABELS) + 1
    
    
    def _editor_toggle_button_style(self, label_lower):
        """Three-state colour for a toggle block. `label_lower` is "lite" or
        "editor". Active = matches `self._editor_mode`. Zone focus = the toggle row
        has keyboard focus. Hover on the inactive block previews active-
        unfocused (matches the kind-button convention)."""
        is_active = (label_lower == self._editor_mode)
        is_hover  = (self._editor_toggle_hover == label_lower and not is_active)
        if is_active and self._editor_toggle_focused:
            return C_BUTTON_ACTIVE_FOCUSED
        if is_active or is_hover:
            return C_BUTTON_ACTIVE_UNFOCUSED
        return C_BUTTON_INACTIVE
    
    
    def _editor_set_toggle_hover(self, label_lower):
        """Update the toggle-row hover state and invalidate. `label_lower` is
        "lite", "editor", or None."""
        if self._editor_toggle_hover != label_lower:
            self._editor_toggle_hover = label_lower
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_toggle_button_handler(self, label_lower):
        """Mouse handler for a toggle block."""
        def _h(ev, lbl=label_lower):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                self._editor_set_toggle_hover(lbl)
                return None
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                # Click on the active block is a no-op; click on the
                # inactive block flips mode. Either way, focus the toggle.
                self._editor_focus_toggle()
                if lbl != self._editor_mode:
                    self._editor_flip_mode()
                return None
            return NotImplemented
        return _h
    
    
    def _editor_focus_toggle(self):
        """Move keyboard focus to the toggle row."""
        if not self._editor_toggle_focused:
            self._editor_toggle_focused = True
            self._host.focus_current_frame()
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_unfocus_toggle(self):
        """Clear toggle focus — used when a non-toggle zone takes focus."""
        if self._editor_toggle_focused:
            self._editor_toggle_focused = False
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_toggle_descend(self):
        """Drop from the LITE/EDITOR toggle into the current mode's first
        zone: lite → focus 0; editor → just unfocus the toggle, which drops
        straight into the buffer (the only other zone). Shared by ↓ and
        Enter/Space so they behave identically — none of them flip the mode."""
        self._editor_unfocus_toggle()
        if self._editor_mode == "lite":
            self._profile_editor_set_focus(0)
        # In editor mode the buffer is the only other zone — clearing the
        # toggle focus drops us straight into it.


    def _editor_flip_mode(self):
        """Toggle between lite and editor mode. Edits in either mode survive
        the flip:
          • lite → editor — serialise the in-memory Profile into the text
            buffer; place the cursor at offset 0.
          • editor → lite — parse the buffer back into the existing Profile;
            re-anchor the lite-mode cursors via `self._editor_refresh_buffers`.
    
        The lenient parser surfaces unrecognised lines as Passthrough so
        user-edited text never throws — the worst case is a previously-known
        entry becoming a Passthrough until reformatted."""
        if self._editor_data is None:
            return
        self._editor_clear_pending_closers()
        self._editor_clear_flash()
        self._autoscroll_disarm()
        self._editor_undo_reset()
        if self._editor_mode == "lite":
            self._editor_buffer_text   = profile_io.serialize_profile(self._editor_data)
            self._editor_buffer_cursor = 0
            self._editor_buffer_scroll = 0
            self._editor_buffer_anchor = None
            self._editor_mode          = "editor"
        else:
            path = self._editor_data.path
            new_prof = profile_io.parse_profile(self._editor_buffer_text, path)
            self._editor_data.items[:] = new_prof.items
            self._editor_data.path     = new_prof.path
            # Reset list cursor onto a real row of the current kind so the
            # detail panel re-binds cleanly.
            self._editor_list_cursor = 0
            self._editor_list_scroll = 0
            self._editor_refresh_buffers()
            self._editor_mode = "lite"
        if self._host.app:
            self._host.app.invalidate()
    
    
    # ---------------------------------------------------------------------------
    # Editor-mode buffer helpers
    # ---------------------------------------------------------------------------
    def _editor_buffer_line_starts(self):
        """Return a list of buffer offsets where each logical line starts.
        Always has at least one entry (`[0]`); ends BEFORE the trailing `\\n`
        of the buffer so the cursor at end-of-buffer maps to a valid line.
    
        Cached against the buffer text reference: Python strings are
        immutable, so an `is` match guarantees identical content. Every
        mutator allocates a fresh string, which invalidates the cache."""
        text = self._editor_buffer_text
        cached_text, cached_starts = self._editor_buffer_line_starts_cache
        if cached_text is text and cached_starts is not None:
            return cached_starts
        starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                starts.append(i + 1)
        self._editor_buffer_line_starts_cache = (text, starts)
        return starts
    
    
    def _editor_buffer_syntax_spans(self):
        """Return the lexical token spans for the current buffer text — list
        of `(start, end, kind)` tuples in ascending, non-overlapping order.
        Wraps `ttpp_syntax.tokenize()` with an identity-keyed cache so
        tokenisation runs once per buffer mutation, not once per render
        frame."""
        text = self._editor_buffer_text
        cached_text, cached_spans = self._editor_buffer_syntax_cache
        if cached_text is text and cached_spans is not None:
            return cached_spans
        spans = ttpp_syntax.tokenize(text)
        self._editor_buffer_syntax_cache = (text, spans)
        return spans
    
    
    # Map from tokeniser kind → palette fg style. Kept module-local so the
    # renderer can do a single dict lookup per token span without re-computing.
    def _editor_buffer_brace_offsets(self):
        """List of absolute offsets of `"brace"`-kind spans, in ascending
        order. Used by the matching-brace highlight and the balance
        indicator. Braces consumed inside `${...}` or `\\{` are NOT
        structural — the tokeniser already excludes them, so this list
        contains only matchable braces."""
        return [s[0] for s in self._editor_buffer_syntax_spans() if s[2] == "brace"]
    
    
    def _editor_brace_match_positions(self):
        """If the cursor is adjacent to a structural `{`/`}`, return a
        `(pos, partner_pos)` tuple in ascending order. Otherwise return
        None — including the unbalanced case, where the brace has no
        partner. Prefers the brace at `cursor - 1` (most recently typed)
        when both sides are matchable."""
        text   = self._editor_buffer_text
        cur    = self._editor_buffer_cursor
        braces = self._editor_buffer_brace_offsets()
        if not braces:
            return None
        brace_set = set(braces)
        candidates = []
        if cur - 1 >= 0 and (cur - 1) in brace_set:
            candidates.append(cur - 1)
        if cur < len(text) and cur in brace_set:
            candidates.append(cur)
        for pos in candidates:
            ch = text[pos]
            if ch == "{":
                depth = 1
                for off in braces:
                    if off <= pos:
                        continue
                    depth += 1 if text[off] == "{" else -1
                    if depth == 0:
                        return (pos, off) if pos < off else (off, pos)
            elif ch == "}":
                depth = 1
                for off in reversed(braces):
                    if off >= pos:
                        continue
                    depth += 1 if text[off] == "}" else -1
                    if depth == 0:
                        return (off, pos) if off < pos else (pos, off)
        return None
    
    
    def _editor_buffer_brace_balance(self):
        """Return `(unclosed, stray)` — the number of unmatched opening `{`
        and unmatched closing `}` among the buffer's structural braces.
        `unclosed > 0` means the final depth is positive; `stray > 0` means
        the depth went negative at some point and never recovered. Both can
        be non-zero for a buffer like `} {`. Drives the footer indicator."""
        text     = self._editor_buffer_text
        braces   = self._editor_buffer_brace_offsets()
        depth    = 0
        stray    = 0
        for off in braces:
            if text[off] == "{":
                depth += 1
            else:
                if depth == 0:
                    stray += 1
                else:
                    depth -= 1
        return depth, stray
    
    
    def _editor_brace_balance_text(self):
        """Footer indicator string for the current buffer. Empty when
        balanced, `"N unclosed {"`, `"N stray }"`, or both joined by `  ·  `
        when both are non-zero."""
        unclosed, stray = self._editor_buffer_brace_balance()
        parts = []
        if unclosed:
            parts.append(f"{unclosed} unclosed {{")
        if stray:
            parts.append(f"{stray} stray }}")
        return "  ·  ".join(parts)
    
    
    def _editor_line_col_text(self):
        """Always-on footer indicator for the editor cursor's 1-indexed
        line and column. `self._editor_buffer_cursor_to_line_col` is 0-indexed."""
        line, col = self._editor_buffer_cursor_to_line_col()
        return f"Ln {line + 1}, Col {col + 1}"
    
    
    def _editor_buffer_line_count(self):
        """Number of logical lines in the buffer.
    
        Trailing `\\n` creates a phantom empty line so the cursor at end-of-
        buffer has a real `(line, col)` mapping. Empty buffer → 1 line."""
        text = self._editor_buffer_text
        if text == "":
            return 1
        return text.count("\n") + (0 if text.endswith("\n") else 1) \
            + (1 if text.endswith("\n") else 0)
    
    
    def _editor_buffer_cursor_to_line_col(self):
        """Convert `self._editor_buffer_cursor` (absolute offset) to a
        `(line, col)` pair (both 0-indexed). Walks the line-starts table."""
        text = self._editor_buffer_text
        starts = self._editor_buffer_line_starts()
        cur = max(0, min(len(text), self._editor_buffer_cursor))
        line = 0
        for i, s in enumerate(starts):
            if s <= cur:
                line = i
            else:
                break
        col = cur - starts[line]
        return line, col
    
    
    def _editor_buffer_line_text(self, line_idx):
        """Return the text of logical line `line_idx` (without trailing \\n)."""
        text = self._editor_buffer_text
        starts = self._editor_buffer_line_starts()
        if not (0 <= line_idx < len(starts)):
            return ""
        start = starts[line_idx]
        end = starts[line_idx + 1] - 1 if line_idx + 1 < len(starts) else len(text)
        return text[start:end]
    
    
    def _editor_buffer_set_cursor_from_line_col(self, line, col):
        """Move the buffer cursor to `(line, col)`. Clamps to valid range."""
        starts = self._editor_buffer_line_starts()
        line = max(0, min(len(starts) - 1, line))
        line_len = len(self._editor_buffer_line_text(line))
        col = max(0, min(line_len, col))
        self._editor_buffer_cursor = starts[line] + col
    
    
    def _editor_click_tick(self, ev):
        """Update click-count tracking for `ev` and return the new count
        (1, 2, or 3). Within `_EDITOR_CLICK_WINDOW` seconds of the previous
        click at the same `(x, y)` the count cycles 1 → 2 → 3 → 1; outside
        the window or at a different `(x, y)` it resets to 1. prompt_toolkit
        only delivers single MOUSE_DOWN events, so the count is rebuilt on
        each click — there is no timer or debounce."""
        now = self._editor_click_now()
        xy = (ev.position.x, ev.position.y)
        same_spot = (xy == self._editor_click_last_xy)
        in_window = (now - self._editor_click_last_t) <= _EDITOR_CLICK_WINDOW
        if same_spot and in_window and self._editor_click_count > 0:
            self._editor_click_count = (self._editor_click_count % 3) + 1
        else:
            self._editor_click_count = 1
        self._editor_click_last_t  = now
        self._editor_click_last_xy = xy
        return self._editor_click_count
    
    
    def _editor_buffer_select_word_at(self, logical_line, col):
        """Editor-buffer double-click target. Set the buffer selection to
        the same-class run at `(logical_line, col)`. A click at or past
        end-of-line clears the selection and places the cursor at line-end
        instead."""
        line_text = self._editor_buffer_line_text(logical_line)
        bounds = _editor_word_bounds(line_text, col)
        if bounds is None:
            self._editor_buffer_set_cursor_from_line_col(logical_line, len(line_text))
            self._editor_buffer_anchor = None
            return
        s, e = bounds
        starts = self._editor_buffer_line_starts()
        base = starts[logical_line]
        self._editor_buffer_anchor = base + s
        self._editor_buffer_cursor = base + e
    
    
    def _editor_buffer_select_logical_line(self, logical_line):
        """Editor-buffer triple-click target. Select the text of
        `logical_line` only — the trailing `\\n` is excluded so the
        rendered highlight stops at end-of-line instead of bleeding onto
        the first cell of the next line. The last line (no trailing
        newline) selects through end-of-buffer."""
        text = self._editor_buffer_text
        starts = self._editor_buffer_line_starts()
        line = max(0, min(len(starts) - 1, logical_line))
        start = starts[line]
        end = starts[line + 1] - 1 if line + 1 < len(starts) else len(text)
        self._editor_buffer_anchor = start
        self._editor_buffer_cursor = end
    
    
    def _editor_buffer_consume_selection(self):
        """If an editor-mode selection is active, delete the selected range
        and place the cursor at its low end. Returns True if a selection
        was consumed (so callers can skip an additional character delete)."""
        if self._editor_buffer_anchor is None:
            return False
        cur = max(0, min(len(self._editor_buffer_text), self._editor_buffer_cursor))
        anchor = max(0, min(len(self._editor_buffer_text), self._editor_buffer_anchor))
        lo, hi = (anchor, cur) if anchor <= cur else (cur, anchor)
        if lo == hi:
            self._editor_buffer_anchor = None
            return False
        self._editor_buffer_text = self._editor_buffer_text[:lo] + self._editor_buffer_text[hi:]
        self._editor_buffer_cursor = lo
        self._editor_buffer_anchor = None
        self._editor_shift_pending_closers_on_delete(lo, hi - lo)
        return True
    
    
    def _editor_buffer_insert(self, text_to_insert):
        """Insert `text_to_insert` at the cursor and advance the cursor.
        If a selection is active, replace it."""
        self._editor_buffer_consume_selection()
        cur = max(0, min(len(self._editor_buffer_text), self._editor_buffer_cursor))
        self._editor_buffer_text = (
            self._editor_buffer_text[:cur] + text_to_insert
            + self._editor_buffer_text[cur:])
        self._editor_buffer_cursor = cur + len(text_to_insert)
        self._editor_shift_pending_closers_on_insert(cur, len(text_to_insert))
    
    
    def _editor_buffer_backspace(self):
        """Delete the character before the cursor — or the active selection
        if one is set (the selection-delete is the entire operation)."""
        if self._editor_buffer_consume_selection():
            return
        cur = max(0, min(len(self._editor_buffer_text), self._editor_buffer_cursor))
        if cur <= 0:
            return
        self._editor_buffer_text = (
            self._editor_buffer_text[:cur - 1] + self._editor_buffer_text[cur:])
        self._editor_buffer_cursor = cur - 1
        self._editor_shift_pending_closers_on_delete(cur - 1, 1)
    
    
    def _editor_buffer_delete(self):
        """Forward-delete: drop the character after the cursor — or the
        active selection if one is set."""
        if self._editor_buffer_consume_selection():
            return
        cur = max(0, min(len(self._editor_buffer_text), self._editor_buffer_cursor))
        if cur >= len(self._editor_buffer_text):
            return
        self._editor_buffer_text = (
            self._editor_buffer_text[:cur] + self._editor_buffer_text[cur + 1:])
        self._editor_shift_pending_closers_on_delete(cur, 1)
    
    
    def _editor_buffer_clear_selection(self):
        """Drop any active shift-arrow selection anchor."""
        self._editor_buffer_anchor = None
    
    
    def _editor_clear_pending_closers(self):
        """Drop the auto-close tracking list. Called by every editor action
        other than a printable insert, backspace/delete, the `}` overtype,
        and `right` — stepping away from a tentative `}` ends its
        tracking."""
        if self._editor_pending_closers:
            self._editor_pending_closers = []
    
    
    def _editor_shift_pending_closers_on_insert(self, start, length):
        """Inserts shift every offset `>= start` right by `length`. Called
        from `self._editor_buffer_insert` after the buffer mutates so the offsets
        keep pointing at the same characters."""
        if not self._editor_pending_closers or length <= 0:
            return
        self._editor_pending_closers = [
            off + length if off >= start else off
            for off in self._editor_pending_closers
        ]
    
    
    def _editor_shift_pending_closers_on_delete(self, start, length):
        """Deletes drop any offset pointing INTO the removed range
        `[start, start+length)` and shift offsets `>= start+length` left by
        `length`. Used by backspace, forward-delete, and selection
        consumption."""
        if not self._editor_pending_closers or length <= 0:
            return
        end = start + length
        self._editor_pending_closers = [
            (off - length if off >= end else off)
            for off in self._editor_pending_closers
            if off < start or off >= end
        ]
    
    
    def _editor_buffer_open_brace(self):
        """Handle a `{` key press in editor mode. Auto-close when the next
        character is end-of-buffer, whitespace, or `}` — otherwise insert a
        bare `{`. See docs/launcher.md → profile_editor → Editor mode →
        Brace assistance. Kept distinct from `self._editor_buffer_insert` so a
        future paste path can never trigger auto-close."""
        has_selection = self._editor_buffer_anchor is not None
        cur = self._editor_buffer_cursor
        text = self._editor_buffer_text
        nxt = text[cur] if cur < len(text) else ""
        will_auto_close = nxt == "" or nxt in (" ", "\t", "\n", "}")
        # Selection-replace and auto-close are atomic units; a plain literal
        # `{` insert coalesces with surrounding typing.
        self._editor_undo_record(None if (has_selection or will_auto_close) else "insert")
        self._editor_buffer_consume_selection()
        cur = self._editor_buffer_cursor
        text = self._editor_buffer_text
        nxt = text[cur] if cur < len(text) else ""
        if nxt == "" or nxt in (" ", "\t", "\n", "}"):
            self._editor_buffer_insert("{}")
            # `self._editor_buffer_insert` shifted the existing list across the
            # 2-char insert at `cur`; the new closer sits at `cur + 1`.
            self._editor_pending_closers.append(cur + 1)
            self._editor_pending_closers.sort()
            self._editor_buffer_cursor = cur + 1
        else:
            self._editor_buffer_insert("{")
    
    
    def _editor_buffer_close_brace(self):
        """Handle a `}` key press in editor mode. Overtype an auto-inserted
        `}` at the cursor (move right, drop the offset); otherwise insert a
        literal `}`."""
        cur = self._editor_buffer_cursor
        text = self._editor_buffer_text
        if (self._editor_buffer_anchor is None
                and cur < len(text)
                and text[cur] == "}"
                and cur in self._editor_pending_closers):
            # Overtype is atomic — the buffer text doesn't change, but the
            # cursor move is still a transaction boundary that ends any
            # in-progress typing run. We record so a c-z right after the
            # overtype rewinds to before this `{}` pair was finalised.
            self._editor_undo_record(None)
            self._editor_buffer_cursor = cur + 1
            self._editor_pending_closers = [
                off for off in self._editor_pending_closers if off != cur
            ]
            return
        # Literal `}` insert coalesces with surrounding typing; selection
        # replace is atomic.
        has_selection = self._editor_buffer_anchor is not None
        self._editor_undo_record(None if has_selection else "insert")
        self._editor_buffer_insert("}")
    
    
    def _editor_buffer_backspace_pair(self):
        """Backspace with auto-close pair-delete. If the cursor sits between
        `{` and a tentative `}`, delete both as one operation; otherwise
        normal backspace."""
        cur = self._editor_buffer_cursor
        text = self._editor_buffer_text
        has_selection = self._editor_buffer_anchor is not None
        is_pair = (not has_selection
                   and 0 < cur < len(text)
                   and text[cur - 1] == "{"
                   and text[cur] == "}"
                   and cur in self._editor_pending_closers)
        # Pair-delete and selection-consume are atomic; a normal backspace
        # coalesces with neighbouring backspaces/deletes into one "delete" run.
        self._editor_undo_record(None if (is_pair or has_selection) else "delete")
        if is_pair:
            self._editor_buffer_delete()       # drop the `}` at cursor
            self._editor_buffer_backspace()    # drop the `{` before cursor
            return
        self._editor_buffer_backspace()
    
    
    def _editor_buffer_step_over_pending_closer(self):
        """Drop pending-closer offsets now strictly behind the cursor. The
        `→` handler calls this after the cursor moves — stepping over a
        tentative `}` ends its tracking without flushing the rest of the
        list."""
        if not self._editor_pending_closers:
            return
        cur = self._editor_buffer_cursor
        self._editor_pending_closers = [
            off for off in self._editor_pending_closers if off >= cur
        ]
    
    
    def _editor_buffer_begin_selection_if_needed(self):
        """Plant the selection anchor at the current cursor if no selection
        is active yet. Called before any shift-arrow movement."""
        if self._editor_buffer_anchor is None:
            self._editor_buffer_anchor = max(
                0, min(len(self._editor_buffer_text), self._editor_buffer_cursor))
    
    
    def _editor_buffer_move_line(self, direction):
        """Swap the cursor's logical line with the one above (`-1`) or below
        (`+1`). The cursor follows the moved line with its column preserved
        (clamped to the new line's length). Returns True if the buffer
        mutated; False (with no undo entry, no closer reset) at the buffer
        ends.
    
        Newline structure is preserved by swapping only the line bodies in
        place — newline positions don't move. This makes the last-line-
        without-trailing-newline edge a no-op for line structure.
    
        Recorded as a single atomic undo transaction; clears any pending
        auto-close offsets (a move is a structural mutation, like cut/paste).
        Any active selection is dropped — multi-line block move is out of
        scope per Phase E."""
        if direction not in (-1, +1):
            return False
        line, col = self._editor_buffer_cursor_to_line_col()
        last = self._editor_buffer_line_count() - 1
        if direction == -1 and line == 0:
            return False
        if direction == +1 and line >= last:
            return False
    
        self._editor_clear_pending_closers()
        self._editor_buffer_clear_selection()
        self._editor_undo_record(None)
    
        top_line = line - 1 if direction == -1 else line
        bot_line = top_line + 1
        new_line = top_line if direction == -1 else bot_line
    
        starts = self._editor_buffer_line_starts()
        text = self._editor_buffer_text
        top_start = starts[top_line]
        bot_start = starts[bot_line]
        bot_end = (starts[bot_line + 1]
                   if bot_line + 1 < len(starts) else len(text))
        top_seg = text[top_start:bot_start]
        bot_seg = text[bot_start:bot_end]
        top_has_nl = top_seg.endswith("\n")
        bot_has_nl = bot_seg.endswith("\n")
        top_body = top_seg[:-1] if top_has_nl else top_seg
        bot_body = bot_seg[:-1] if bot_has_nl else bot_seg
        new_middle = (bot_body + ("\n" if top_has_nl else "")
                      + top_body + ("\n" if bot_has_nl else ""))
        self._editor_buffer_text = text[:top_start] + new_middle + text[bot_end:]
        self._editor_buffer_set_cursor_from_line_col(new_line, col)
        return True
    
    
    # ---------------------------------------------------------------------------
    # Editor-mode undo / redo
    # ---------------------------------------------------------------------------
    # Snapshot-based: each stack entry is `(text, cursor, anchor)`. Strings are
    # immutable, so a snapshot holds references — no copy needed. The
    # `self._editor_undo_record(kind)` helper is called BEFORE a mutating
    # transaction commits; runs of single-character `kind="insert"` typing
    # (or `kind="delete"` backspace/delete) coalesce so a word's worth of
    # typing is one undoable unit. Paste, cut, auto-close, overtype, and
    # pair-delete pass `kind=None` for an atomic unit that does not coalesce.
    # See docs/launcher.md and docs/decisions/0091-profile-editor-undo-coalescing.md.
    
    def _editor_undo_snapshot(self):
        return (self._editor_buffer_text, self._editor_buffer_cursor, self._editor_buffer_anchor)
    
    
    def _editor_undo_reset(self):
        """Drop both stacks and close any open coalescing run. Called from
        `_enter_profile_editor` and on every lite↔editor flip — undo state
        never survives leaving the editor or a mode flip."""
        self._editor_undo_stack[:] = []
        self._editor_redo_stack[:] = []
        self._editor_undo_open      = False
        self._editor_undo_last_kind = None
    
    
    def _editor_undo_close(self):
        """Force a coalescing boundary without pushing a snapshot. The next
        mutating transaction starts a fresh undo entry. Called from every
        cursor-move / focus-change / mouse-click handler so a follow-up edit
        can't coalesce across the move."""
        self._editor_undo_open      = False
        self._editor_undo_last_kind = None
    
    
    def _editor_undo_record(self, kind):
        """Begin a transaction. Push the current `(text, cursor, anchor)`
        snapshot onto the undo stack unless we're inside an open coalescing
        run of the same kind (in which case the pre-edit snapshot is already
        at the top of the stack). Any push also clears the redo stack — a
        fresh edit after some undos invalidates the future.
    
        `kind ∈ {"insert", "delete", None}`. `"insert"` and `"delete"` open a
        coalescing run; `None` is atomic (paste, cut, auto-close, overtype,
        pair-delete, newline insert — each its own undoable unit, never
        coalesced with neighbours).
    
        Call this BEFORE mutating buffer state."""
        if kind in ("insert", "delete") \
                and self._editor_undo_open and self._editor_undo_last_kind == kind:
            # Continuing an open run — pre-edit snapshot already recorded.
            # Any new edit still invalidates the redo future.
            self._editor_redo_stack[:] = []
            return
        self._editor_undo_stack.append(self._editor_undo_snapshot())
        if len(self._editor_undo_stack) > _EDITOR_UNDO_MAX_DEPTH:
            self._editor_undo_stack.pop(0)
        self._editor_redo_stack[:] = []
        if kind in ("insert", "delete"):
            self._editor_undo_open      = True
            self._editor_undo_last_kind = kind
        else:
            self._editor_undo_open      = False
            self._editor_undo_last_kind = None
    
    
    def _editor_undo(self):
        """c-z. Restore the most recent pre-edit snapshot. Pushes the current
        state onto the redo stack first so c-y can step forward again.
        Clears `self._editor_pending_closers` (offsets aren't valid against the
        restored text) and scrolls the cursor into view."""
        if not self._editor_undo_stack:
            return
        self._editor_undo_close()
        self._editor_redo_stack.append(self._editor_undo_snapshot())
        text, cursor, anchor = self._editor_undo_stack.pop()
        self._editor_buffer_text   = text
        self._editor_buffer_cursor = cursor
        self._editor_buffer_anchor = anchor
        self._editor_clear_pending_closers()
        self._editor_buffer_scroll_cursor_into_view()
    
    
    def _editor_redo(self):
        """c-y. Symmetric to undo — pop from redo, push current to undo,
        restore. Same post-conditions (closers cleared, cursor in view)."""
        if not self._editor_redo_stack:
            return
        self._editor_undo_close()
        self._editor_undo_stack.append(self._editor_undo_snapshot())
        if len(self._editor_undo_stack) > _EDITOR_UNDO_MAX_DEPTH:
            self._editor_undo_stack.pop(0)
        text, cursor, anchor = self._editor_redo_stack.pop()
        self._editor_buffer_text   = text
        self._editor_buffer_cursor = cursor
        self._editor_buffer_anchor = anchor
        self._editor_clear_pending_closers()
        self._editor_buffer_scroll_cursor_into_view()
    
    
    # ---------------------------------------------------------------------------
    # Clipboard — shared register + OSC 52 system-clipboard write
    # ---------------------------------------------------------------------------
    # Editor mode and the Lite Pattern / Body fields share `self._editor_clipboard`
    # as an in-app register. Copy and cut also emit an OSC 52 sequence so the
    # system clipboard receives the same text on terminals that implement it
    # (most modern ones do). Paste reads only from the in-app register —
    # bringing text in from another application uses the terminal's own
    # bracketed-paste shortcut. See docs/decisions/0090-osc52-write-not-read.md.
    
    def _clipboard_write(self, text):
        """Place `text` into the in-app register and best-effort onto the
        system clipboard via OSC 52."""
        self._editor_clipboard = text
        _emit_osc52_copy(text, self._host.app)
    
    
    def _editor_buffer_selection_range(self):
        """`(lo, hi)` for the live editor-mode selection, or None when no
        selection is set or the anchor coincides with the cursor."""
        if self._editor_buffer_anchor is None:
            return None
        cur = max(0, min(len(self._editor_buffer_text), self._editor_buffer_cursor))
        anchor = max(0, min(len(self._editor_buffer_text), self._editor_buffer_anchor))
        if cur == anchor:
            return None
        return (min(cur, anchor), max(cur, anchor))
    
    
    def _editor_buffer_current_line_span(self):
        """Return `(start, end)` covering the current line PLUS its trailing
        `\\n` (when present). Used by the no-selection copy/cut path."""
        text = self._editor_buffer_text
        starts = self._editor_buffer_line_starts()
        line, _col = self._editor_buffer_cursor_to_line_col()
        start = starts[line]
        end = starts[line + 1] if line + 1 < len(starts) else len(text)
        return start, end
    
    
    def _editor_buffer_copy(self):
        """Copy selection — or the current line + its `\\n` — into the shared
        register and out via OSC 52. Cursor and buffer unchanged."""
        sel = self._editor_buffer_selection_range()
        if sel is not None:
            lo, hi = sel
            self._clipboard_write(self._editor_buffer_text[lo:hi])
            return
        lo, hi = self._editor_buffer_current_line_span()
        if lo == hi:
            return
        text = self._editor_buffer_text[lo:hi]
        if not text.endswith("\n"):
            text = text + "\n"
        self._clipboard_write(text)
    
    
    def _editor_buffer_cut(self):
        """Cut selection — or the current line — into the shared register.
        With no selection, removes one adjacent newline so no blank line is
        left behind. Clears `self._editor_pending_closers` like any other
        structural mutation."""
        sel = self._editor_buffer_selection_range()
        if sel is not None:
            lo, hi = sel
            # Atomic transaction — cut never coalesces with surrounding edits.
            self._editor_undo_record(None)
            self._clipboard_write(self._editor_buffer_text[lo:hi])
            self._editor_buffer_consume_selection()
            self._editor_clear_pending_closers()
            return
        lo, hi = self._editor_buffer_current_line_span()
        text = self._editor_buffer_text[lo:hi]
        if not text:
            return
        self._editor_undo_record(None)
        copied = text if text.endswith("\n") else text + "\n"
        self._clipboard_write(copied)
        # Drop the line. If the line has a trailing `\n`, that's already in
        # [lo, hi); otherwise (last line, no trailing `\n`) eat the preceding
        # `\n` instead, so the previous line isn't left dangling.
        if text.endswith("\n"):
            new_lo, new_hi = lo, hi
        elif lo > 0 and self._editor_buffer_text[lo - 1] == "\n":
            new_lo, new_hi = lo - 1, hi
        else:
            new_lo, new_hi = lo, hi
        self._editor_buffer_text = (
            self._editor_buffer_text[:new_lo] + self._editor_buffer_text[new_hi:])
        self._editor_buffer_cursor = min(new_lo, len(self._editor_buffer_text))
        self._editor_shift_pending_closers_on_delete(new_lo, new_hi - new_lo)
        self._editor_clear_pending_closers()
    
    
    def _editor_buffer_paste(self):
        """Paste the shared register at the cursor. Replaces any live
        selection. Clears `self._editor_pending_closers` so a tentative `}`
        cannot survive a paste."""
        if not self._editor_clipboard:
            return
        # Atomic transaction — paste is a single undoable unit.
        self._editor_undo_record(None)
        self._editor_buffer_insert(self._editor_clipboard)
        self._editor_clear_pending_closers()
    
    
    def _editor_buffer_bracketed_paste(self, text):
        """Insert pasted `text` at the cursor — used by the terminal's
        bracketed-paste path. Normalises CRLF / lone CR first; replaces any
        live selection; deliberately does NOT route through the `{` key
        handler so auto-close never fires on pasted text."""
        text = _bracketed_paste_normalise(text)
        if not text:
            return
        self._editor_undo_record(None)
        self._editor_buffer_insert(text)
        self._editor_clear_pending_closers()
    
    
    # --- Lite Pattern field — copy / cut / paste / bracketed paste -------
    
    def _editor_pattern_selected_text(self):
        """Substring covered by the live Pattern selection, or empty."""
        entry = self._editor_current_entry()
        sel = self._editor_pattern_selection()
        if entry is None or sel is None:
            return ""
        s, e = sel
        return entry.pattern[s:e]
    
    
    def _editor_pattern_copy(self):
        entry = self._editor_current_entry()
        if entry is None:
            return
        sel_text = self._editor_pattern_selected_text()
        if sel_text:
            self._clipboard_write(sel_text)
            return
        # No selection → copy the whole pattern + trailing newline so the
        # line-copy semantics match the editor-mode and Body behaviour.
        if entry.pattern == "":
            return
        self._clipboard_write(entry.pattern + "\n")
    
    
    def _editor_pattern_cut(self):
        entry = self._editor_current_entry()
        if entry is None:
            return
        sel_text = self._editor_pattern_selected_text()
        if sel_text:
            self._clipboard_write(sel_text)
            self._editor_pattern_delete_selection()
            return
        if entry.pattern == "":
            return
        self._clipboard_write(entry.pattern + "\n")
        self._editor_set_pattern("")
        self._editor_pattern_cursor = 0
    
    
    def _editor_pattern_paste(self):
        """Paste the shared register into Pattern at the cursor. Pattern is
        single-line — flatten any newlines to spaces first."""
        if not self._editor_clipboard:
            return
        text = self._editor_clipboard.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\n", " ")
        self._editor_pattern_insert_text(text)
    
    
    def _editor_pattern_bracketed_paste(self, text):
        """Insert pasted `text` into the Pattern field. Normalised newlines
        are flattened to spaces because Pattern is single-line."""
        text = _bracketed_paste_normalise(text).replace("\n", " ")
        if not text:
            return
        self._editor_pattern_insert_text(text)
    
    
    def _editor_pattern_insert_text(self, text):
        """Insert a multi-character string at the Pattern cursor. Replaces
        any live selection first."""
        entry = self._editor_current_entry()
        if entry is None or not text:
            return
        self._editor_pattern_delete_selection()
        pat = entry.pattern
        col = max(0, min(len(pat), self._editor_pattern_cursor))
        self._editor_set_pattern(pat[:col] + text + pat[col:])
        self._editor_pattern_cursor = col + len(text)
    
    
    # --- Lite Body field — copy / cut / paste / bracketed paste ----------
    
    def _editor_body_selected_text(self):
        """Substring covered by the live Body selection, or empty."""
        sel = self._editor_body_selection()
        if sel is None:
            return ""
        (sl, sc), (el, ec) = sel
        lines = self._editor_body_lines()
        if not lines:
            return ""
        sl = max(0, min(len(lines) - 1, sl))
        el = max(0, min(len(lines) - 1, el))
        sc = max(0, min(len(lines[sl]), sc))
        ec = max(0, min(len(lines[el]), ec))
        if sl == el:
            return lines[sl][sc:ec]
        parts = [lines[sl][sc:]]
        parts.extend(lines[sl + 1:el])
        parts.append(lines[el][:ec])
        return "\n".join(parts)
    
    
    def _editor_body_current_line_text(self):
        """The text of the current Body line, without trailing newline."""
        lines = self._editor_body_lines()
        if not lines:
            return ""
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        return lines[line]
    
    
    def _editor_body_copy(self):
        sel_text = self._editor_body_selected_text()
        if sel_text:
            self._clipboard_write(sel_text)
            return
        line_text = self._editor_body_current_line_text()
        if line_text == "" and len(self._editor_body_lines()) <= 1:
            return
        self._clipboard_write(line_text + "\n")
    
    
    def _editor_body_cut(self):
        sel_text = self._editor_body_selected_text()
        if sel_text:
            self._clipboard_write(sel_text)
            self._editor_body_delete_selection()
            self._editor_body_scroll_cursor_into_view()
            return
        lines = self._editor_body_lines()
        if not lines:
            return
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        if lines[line] == "" and len(lines) == 1:
            return
        self._clipboard_write(lines[line] + "\n")
        # Remove the line; if it was the only one, leave a single empty
        # line so the body model stays well-formed.
        if len(lines) == 1:
            new_lines = [""]
            self._editor_body_line = 0
        else:
            new_lines = lines[:line] + lines[line + 1:]
            if line >= len(new_lines):
                self._editor_body_line = len(new_lines) - 1
        self._editor_body_col = 0
        self._editor_body_set_lines(new_lines)
        self._editor_body_scroll_cursor_into_view()
    
    
    def _editor_body_paste(self):
        if not self._editor_clipboard:
            return
        self._editor_body_insert_text(self._editor_clipboard)
    
    
    def _editor_body_bracketed_paste(self, text):
        text = _bracketed_paste_normalise(text)
        if not text:
            return
        self._editor_body_insert_text(text)
    
    
    def _editor_body_insert_text(self, text):
        """Insert a (possibly multi-line) string at the Body cursor.
        Replaces any live selection first. Splits on `\\n`."""
        entry = self._editor_current_entry()
        if entry is None or not text:
            return
        self._editor_body_delete_selection()
        lines = self._editor_body_lines()
        if not lines:
            lines = [""]
        line = max(0, min(len(lines) - 1, self._editor_body_line))
        col  = max(0, min(len(lines[line]), self._editor_body_col))
        head = lines[line][:col]
        tail = lines[line][col:]
        pieces = text.split("\n")
        if len(pieces) == 1:
            lines[line] = head + pieces[0] + tail
            new_line = line
            new_col  = col + len(pieces[0])
        else:
            new_block = [head + pieces[0]] + list(pieces[1:-1]) + [pieces[-1] + tail]
            lines = lines[:line] + new_block + lines[line + 1:]
            new_line = line + len(pieces) - 1
            new_col  = len(pieces[-1])
        self._editor_body_set_lines(lines)
        self._editor_body_line = new_line
        self._editor_body_col  = new_col
        self._editor_body_scroll_cursor_into_view()


    def _editor_buffer_content_width(self, cols):
        """Width of the visible text-buffer region in editor mode. Equals the
        terminal width minus the line-number column and the right-edge
        scrollbar slot. Floors at 1 cell so the renderer never divides by
        zero on a pathologically narrow terminal."""
        return max(1, cols - self._editor_line_num_w() - 1)
    
    
    def _editor_line_num_w(self):
        """Width of the line-number column. Default 4 cells (3 digits + 1-cell
        gap); widens by one cell per extra digit when the file is longer
        than 999 lines."""
        n = self._editor_buffer_line_count()
        digits = max(3, len(str(max(1, n))))
        return digits + 1
    
    
    def _editor_buffer_visual_layout(self, cols):
        """Compute the visual layout of the buffer for the current viewport:
    
        - `wrap_w`: content-cell width per visual row.
        - `visual_rows`: total visual rows after soft wrap.
        - `line_to_visual`: list of (start_visual, wrap_count) per logical
          line — `start_visual[i]` is the first visual row index of logical
          line `i`, `wrap_count[i]` is how many visual rows it occupies.
    
        Empty logical lines still occupy one visual row.
    
        Cached per `(text_ref, cols)` — `is`-matching the buffer reference
        invalidates on any mutation (which allocates a fresh string). One
        render frame triggers up to three calls (direct + two via
        `self._editor_buffer_cursor_visual_row`); only the first does work."""
        text = self._editor_buffer_text
        cached_text, cached_cols, cached_val = self._editor_buffer_visual_cache
        if (cached_text is text
                and cached_cols == cols
                and cached_val is not None):
            return cached_val
        wrap_w = self._editor_buffer_content_width(cols)
        starts = self._editor_buffer_line_starts()
        text_len = len(text)
        line_to_visual = []
        total = 0
        for line_idx in range(len(starts)):
            start = starts[line_idx]
            end = (starts[line_idx + 1] - 1
                   if line_idx + 1 < len(starts) else text_len)
            line_len = end - start
            n = max(1, (line_len + wrap_w - 1) // wrap_w) if line_len else 1
            line_to_visual.append((total, n))
            total += n
        out = (wrap_w, total, line_to_visual)
        self._editor_buffer_visual_cache = (text, cols, out)
        return out
    
    
    def _editor_buffer_cursor_visual_row(self, cols):
        """Return the visual row index where the cursor sits, for current
        viewport `cols`."""
        wrap_w, _total, l2v = self._editor_buffer_visual_layout(cols)
        line, col = self._editor_buffer_cursor_to_line_col()
        start, _n = l2v[line]
        return start + (col // wrap_w)
    
    
    def _editor_buffer_scroll_into_view(self, cols, viewport_h):
        """Clamp `self._editor_buffer_scroll` so the cursor row stays inside the
        viewport. Adjusts in the smallest delta needed."""
        _wrap_w, total, _l2v = self._editor_buffer_visual_layout(cols)
        cur_row = self._editor_buffer_cursor_visual_row(cols)
        if cur_row < self._editor_buffer_scroll:
            self._editor_buffer_scroll = cur_row
        elif cur_row >= self._editor_buffer_scroll + viewport_h:
            self._editor_buffer_scroll = cur_row - viewport_h + 1
        max_scroll = max(0, total - viewport_h)
        self._editor_buffer_scroll = max(0, min(max_scroll, self._editor_buffer_scroll))
    
    
    def _editor_buffer_wheel(self, delta):
        """Mouse-wheel scroll on the editor-mode buffer: shift the viewport
        by `delta` visual rows, clamped. The buffer cursor stays put — the
        next cursor-moving keystroke pulls the viewport back. Mirrors the
        decoupling that scrollbar clicks already implement."""
        cols = self._host.term_cols()
        _wrap_w, total, _l2v = self._editor_buffer_visual_layout(cols)
        viewport_h = self._editor_body_h()
        max_scroll = max(0, total - viewport_h)
        new_scroll = max(0, min(max_scroll, self._editor_buffer_scroll + delta))
        if new_scroll != self._editor_buffer_scroll:
            self._editor_buffer_scroll = new_scroll
            if self._host.app:
                self._host.app.invalidate()
    
    
    def _editor_buffer_chrome_wheel_handler(self, ev):
        """Handler for editor-mode buffer chrome cells (line-number column)
        that need to clear outer hover on MOUSE_MOVE and forward wheel
        events to the buffer viewport."""
        if ev.event_type == MouseEventType.MOUSE_MOVE:
            self._profile_editor_clear_hover()
            return None
        if ev.event_type == MouseEventType.SCROLL_UP:
            self._editor_buffer_wheel(-3)
            return None
        if ev.event_type == MouseEventType.SCROLL_DOWN:
            self._editor_buffer_wheel(3)
            return None
        return NotImplemented
    
    
    def _editor_kind_button_style(self, idx):
        """Return the three-state colour token for the kind button at index
        `idx` (0..len(_PROFILE_EDITOR_TABS)-1). Hover on an inactive button
        previews the active-unfocused state.
    
        The kind-button row counts as focused only when `self._editor_focus == 0`
        AND the toggle row does not hold the keyboard claim — moving focus
        up to the LITE | EDITOR toggle leaves `self._editor_focus` at 0, so the
        toggle-focused flag must be checked explicitly to keep amber from
        leaking outside the focused zone."""
        is_active    = (idx == self._editor_active_tab)
        is_hover     = (self._editor_hover_tab == idx and not is_active)
        zone_focused = (self._editor_focus == 0 and not self._editor_toggle_focused)
        if is_active and zone_focused:
            return C_BUTTON_ACTIVE_FOCUSED
        if is_active or is_hover:
            return C_BUTTON_ACTIVE_UNFOCUSED
        return C_BUTTON_INACTIVE
    
    
    def _editor_kind_button_handler(self, idx):
        """Mouse handler for any cell inside the kind button at index `idx`.
        Hovering sets `self._editor_hover_tab`; clicking focuses the kind-button
        row and switches to that kind."""
        def _h(ev, i=idx):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                self._profile_editor_set_hover_tab(i)
                return None
            if ev.event_type == MouseEventType.MOUSE_DOWN:
                self._profile_editor_set_focus(0)
                self._profile_editor_set_tab(i)
                return None
            return NotImplemented
        return _h
    
    
    def _editor_append_kind_button_row(self, frags, cols):
        """Append the horizontal kind-button row (3 rows tall) to `frags`.
        Five 13-cell BG-filled blocks separated by 3-cell gaps, the whole
        group centred on the terminal. Each button paints per the
        three-state colour grammar; the label sits centred on the middle
        row. Phase 6.3 replaced the vertical kind column with this row.
    
        Each rendered cell carries the button's mouse handler so hover and
        click work on any cell within the block, mirroring the column-era
        behaviour."""
        left_pad  = self._editor_kind_left_pad()
        row_w     = self._editor_kind_row_w()
        right_pad = max(0, cols - left_pad - row_w)
        n         = _EDITOR_KIND_COUNT
        for within_btn in range(_EDITOR_KIND_ROW_H):
            if left_pad > 0:
                frags.append(("", " " * left_pad, self._editor_clear_outer_hover))
            for idx in range(n):
                label_upper = _PROFILE_EDITOR_TABS[idx][0].upper()
                style       = self._editor_kind_button_style(idx)
                if within_btn == 1:
                    text = label_upper.center(_EDITOR_KIND_W)
                else:
                    text = " " * _EDITOR_KIND_W
                frags.append((style, text, self._editor_kind_button_handler(idx)))
                if idx < n - 1:
                    frags.append(("", " " * _EDITOR_KIND_GAP,
                                  self._editor_clear_outer_hover))
            if right_pad > 0:
                frags.append(("", " " * right_pad, self._editor_clear_outer_hover))
            frags.append(("", "\n", self._editor_clear_outer_hover))
    
    
    def _profile_editor_text(self):
        """Render the editor frame as a single fragment list.
    
        Layout (top to bottom, lite mode — Phase 6.3):
    
            ─── Profile Editor: <name> ───                  LITE EDITOR
            <blank>
            ┌───────────┐  ┌───────────┐  ...  ┌───────────┐
            │  ACTIONS  │  │  ALIASES  │       │SUBSTITUTES│
            └───────────┘  └───────────┘       └───────────┘
            <blank>
            Pattern        Body                Pattern
            <pattern>      <body…>             ┌─────────────────┐
            + New entry                        │ <pattern>       │
            ...                                 ...
    
        Editor mode replaces steps 2-5 with the full-height text buffer.
        Both modes emit the host-provided number of leading blank rows
        above the title row (`title_blank_above`: launcher 2, popup 1).
    
        The five 13-cell kind buttons sit in a horizontal row, BG-filled,
        centred on the terminal. The colour grammar (`C_BUTTON_*`) carries
        focus + active state. Headers and field labels stay in muted grey
        at all times. Phase 6.3 replaced the vertical kind column with this
        row, widened the entry list (23 → 38) and detail panel (30 → 35),
        and bumped the inter-panel gap (2 → 3)."""
        cols = self._host.term_cols()
        name = (self._editor_profile_path.stem
                if self._editor_profile_path is not None else "")
        title  = f"─── Profile Editor: {name} ───"
    
        frags = []
        # Both modes emit the host-provided number of leading blank rows
        # explicitly (launcher 2, popup 1): the frame uses
        # `HSplit([body, flex_spacer, footer])` (no vertical centering), so
        # the body anchors to the top of the available space. Editor mode's
        # body fills the terminal exactly so there is no slack; lite mode's
        # spacer absorbs the slack between body and footer. The chrome
        # budgets in `self._editor_body_h` count these blanks — change them
        # together.
        for _ in range(self._host.title_blank_above()):
            frags.append(("", "\n", self._editor_clear_outer_hover))
        self._editor_append_title_row(frags, title, cols)
        frags.append(("", "\n", self._editor_clear_outer_hover))
    
        if self._editor_mode == "editor":
            self._editor_append_editor_body(frags, cols)
            return frags
    
        # Lite mode: kind-button row (3 rows) + blank separator, then body.
        self._editor_append_kind_button_row(frags, cols)
        frags.append(("", "\n", self._editor_clear_outer_hover))
    
        # ----- Body region (master/detail) --------------------------------
        body_h    = self._editor_body_h()
        visible   = self._editor_list_visible()
        view      = self._profile_editor_display_view()
        entries_total = len(view)
        sentinel_idx  = entries_total            # index of the "+ New entry" row
        total         = entries_total + 1        # entries + sentinel
        if self._editor_list_sb is not None:
            self._editor_list_sb.update(total, visible, height=visible)
            self._editor_list_sb.scroll_to(self._editor_list_scroll)
    
        # Clamp cursor and scroll defensively (tab switches, deletions, etc.).
        # Per ADR 0083 the render path must not scroll the viewport to the
        # cursor — that re-clamp would fight wheel scrolling every frame.
        # Cursor-into-view happens only on cursor-mutating actions; here we
        # clamp `_editor_list_scroll` to bounds only and treat it as
        # authoritative.
        if self._editor_list_cursor < 0:
            self._editor_list_cursor = 0
        elif self._editor_list_cursor >= total:
            self._editor_list_cursor = total - 1
        max_scroll = max(0, total - visible)
        self._editor_list_scroll = max(0, min(max_scroll, self._editor_list_scroll))
    
        # Detail panel content (length == body_h). Sentinel cursor → no
        # entry; `self._editor_detail_lines` produces the centred "press Enter"
        # prompt or the empty-state hint.
        cur_entry = (view[self._editor_list_cursor]
                     if 0 <= self._editor_list_cursor < entries_total else None)
        detail_rows = self._editor_detail_lines(cur_entry, body_h)
    
        # Scrollbar geometry for the data rows (visible cells under header).
        sb_top, sb_thumb_h = self._editor_sb_thumb_geom(total, visible, visible)
        sb_visible = total > visible
    
        left_pad  = self._editor_left_pad()
        gap_str   = " " * _EDITOR_GAP
        right_pad = max(0, cols - left_pad - self._editor_package_w())
    
        for body_row in range(body_h):
            # ----- Left column: header (row 0) or data rows (1..body_h-1) -----
            if body_row == 0:
                left_frags = self._editor_list_header_frag(visible)
            else:
                data_idx = body_row - 1   # 0..body_h-2 visible data rows index
                if data_idx < visible:
                    abs_idx = self._editor_list_scroll + data_idx
                    is_cursor = (abs_idx == self._editor_list_cursor)
                    if 0 <= abs_idx < entries_total:
                        is_hover  = (self._editor_hover_row == abs_idx and not is_cursor)
                        row_frags = self._editor_list_row_text(
                            view[abs_idx], is_cursor, is_hover)
    
                        def _row_handler(ev, row=abs_idx):
                            if ev.event_type == MouseEventType.MOUSE_MOVE:
                                self._profile_editor_set_hover_row(row)
                                return None
                            if ev.event_type == MouseEventType.MOUSE_DOWN:
                                self._profile_editor_set_focus(1)
                                self._editor_list_cursor = row
                                self._profile_editor_scroll_into_view()
                                self._editor_refresh_buffers()
                                if self._host.app:
                                    self._host.app.invalidate()
                                return None
                            if ev.event_type == MouseEventType.SCROLL_UP:
                                self._editor_list_wheel(-3)
                                return None
                            if ev.event_type == MouseEventType.SCROLL_DOWN:
                                self._editor_list_wheel(3)
                                return None
                            return NotImplemented
    
                        left_frags = [
                            (s, t, _row_handler) for (s, t) in row_frags
                        ]
                    elif abs_idx == sentinel_idx:
                        # "+ New entry" sentinel row — selectable like any
                        # row; Enter / click creates a fresh blank Entry.
                        is_hover = (self._editor_hover_row == abs_idx and not is_cursor)
                        label = "+ New entry"
                        text = label.ljust(_EDITOR_LIST_W)[:_EDITOR_LIST_W]
                        if is_cursor:
                            style = (C_BUTTON_ACTIVE_FOCUSED if self._editor_focus == 1
                                     else C_BUTTON_ACTIVE_UNFOCUSED)
                        elif is_hover:
                            style = C_HOVER
                        else:
                            style = C_HINT
    
                        def _sentinel_handler(ev, row=abs_idx):
                            if ev.event_type == MouseEventType.MOUSE_MOVE:
                                self._profile_editor_set_hover_row(row)
                                return None
                            if ev.event_type == MouseEventType.MOUSE_DOWN:
                                # Click on "+ New entry" acts as a button —
                                # create the entry immediately. Focus moves
                                # to the list briefly so the cursor anchors,
                                # then `self._editor_create_new_entry` moves
                                # focus to the detail panel's Pattern field.
                                self._profile_editor_set_focus(1)
                                self._editor_list_cursor = row
                                self._profile_editor_scroll_into_view()
                                self._editor_create_new_entry()
                                if self._host.app:
                                    self._host.app.invalidate()
                                return None
                            if ev.event_type == MouseEventType.SCROLL_UP:
                                self._editor_list_wheel(-3)
                                return None
                            if ev.event_type == MouseEventType.SCROLL_DOWN:
                                self._editor_list_wheel(3)
                                return None
                            return NotImplemented
    
                        left_frags = [(style, text, _sentinel_handler)]
                    else:
                        # Blank row inside the list panel — wheel still scrolls.
                        def _blank_row_handler(ev):
                            if ev.event_type == MouseEventType.MOUSE_MOVE:
                                self._profile_editor_set_hover_row(None)
                                return None
                            if ev.event_type == MouseEventType.SCROLL_UP:
                                self._editor_list_wheel(-3)
                                return None
                            if ev.event_type == MouseEventType.SCROLL_DOWN:
                                self._editor_list_wheel(3)
                                return None
                            return NotImplemented
                        left_frags = [("", " " * _EDITOR_LIST_W,
                                       _blank_row_handler)]
                else:
                    left_frags = [("", " " * _EDITOR_LIST_W,
                                   self._editor_clear_outer_hover)]
    
            # ----- Scrollbar cell -----
            if body_row == 0:
                sb_frag = ("", " ", self._editor_clear_outer_hover)
            else:
                sb_row = body_row - 1
                if sb_visible and sb_row < visible:
                    if sb_top <= sb_row < sb_top + sb_thumb_h:
                        sb_style = "bold fg:#ffffff"
                        sb_ch    = "█"
                    else:
                        sb_style = "fg:#585858"
                        sb_ch    = "░"
    
                    def _sb_handler(ev, row=sb_row,
                                    t=total, v=visible):
                        if ev.event_type == MouseEventType.MOUSE_DOWN:
                            top, thumb_h = self._editor_sb_thumb_geom(t, v, v)
                            on_thumb = (top <= row < top + thumb_h)
                            off = self._editor_sb_click_to_offset(
                                row, t, v, v)
                            self._editor_list_scroll = off
                            if self._editor_list_sb is not None:
                                self._editor_list_sb.scroll_to(off)
                            if not on_thumb:
                                self._autoscroll_arm(
                                    self._editor_list_autoscroll_step, row)
                            if self._host.app:
                                self._host.app.invalidate()
                            return None
                        if ev.event_type == MouseEventType.MOUSE_UP:
                            self._autoscroll_disarm()
                            return None
                        if ev.event_type == MouseEventType.MOUSE_MOVE:
                            self._profile_editor_set_hover_row(None)
                            self._autoscroll_set_target(row)
                            return None
                        if ev.event_type == MouseEventType.SCROLL_UP:
                            self._editor_list_wheel(-3)
                            return None
                        if ev.event_type == MouseEventType.SCROLL_DOWN:
                            self._editor_list_wheel(3)
                            return None
                        return NotImplemented
    
                    sb_frag = (sb_style, sb_ch, _sb_handler)
                else:
                    sb_frag = ("", " ", self._editor_clear_outer_hover)
    
            # ----- Detail cell -----
            detail_row = detail_rows[body_row]
    
            # ----- Compose the row -----
            # Phase 6.3: no kind column — buttons live in a horizontal row
            # above the body. Body starts with list + scrollbar + detail.
            frags.append(("", " " * left_pad, self._editor_clear_outer_hover))
            for f in left_frags:
                frags.append(f)
            frags.append(sb_frag)
            frags.append(("", gap_str, self._editor_clear_outer_hover))
            # Detail rows mix 2-tuples (plain text) and 3-tuples (per-cell
            # mouse handlers in the editable field areas). Both shapes
            # need to land in the FormattedText stream with a hover-clear
            # fallback for cells that don't carry their own handler.
            for f in detail_row:
                if len(f) == 3 and f[2] is not None:
                    frags.append(f)
                else:
                    style, text = f[0], f[1]
                    frags.append((style, text, self._editor_clear_outer_hover))
            if right_pad > 0:
                frags.append(("", " " * right_pad, self._editor_clear_outer_hover))
            frags.append(("", "\n", self._editor_clear_outer_hover))
    
        return frags
    
    
    def _profile_editor_footer_text(self):
        """Footer-hint row + optional feedback flash, rendered into the
        dedicated footer Window so a flex_spacer between body and footer
        pins the hint to the final terminal row in both modes (matches the
        `profile` / `history` footer-anchoring contract)."""
        frags = []
        self._editor_append_footer(frags, self._host.term_cols())
        return frags
    
    
    def _profile_editor_footer_h(self):
        """Height of the footer Window: 2 rows (blank + hint) normally,
        grows to 4 (blank + hint + blank + feedback) while a key-capture
        feedback flash is live. Keeps the hint on the bottom row whenever
        no feedback is showing."""
        return 4 if self._editor_feedback_text else 2
    
    
    def _editor_append_title_row(self, frags, title, cols):
        """Render the title-row with the LITE/EDITOR toggle right-aligned so
        the `R` in EDITOR sits above the right `┐` of the detail panel's
        Pattern frame in lite mode. Narrow terminals truncate the title's
        right-side decorative dashes; the toggle is never sacrificed."""
        package_w = self._editor_package_w()
        left_pad  = self._editor_left_pad()
        toggle_w  = self._editor_toggle_widget_w()
        # The R in EDITOR must sit at the column of the detail panel's `┐`
        # (i.e. the last column of the package). Right-aligning the toggle's
        # offset-13 cell to that column means the toggle starts 14 cells
        # before. The trailing space of " EDITOR " hangs one cell past the
        # package right edge — invisible on a black background.
        r_col       = left_pad + package_w - 1
        toggle_start = r_col - 13
    
        # Centre the title on the terminal, then truncate from the right so it
        # never overlaps the toggle.
        title_start = (cols - len(title)) // 2
        title_max_end = toggle_start - 1   # one cell of gap
        if title_start + len(title) > title_max_end:
            max_len = max(0, title_max_end - title_start)
            title = title[:max_len].rstrip("─ ")
        title_start = (cols - len(title)) // 2 if title else 0
        # Re-clamp after possible truncation so the title still fits.
        if title_start + len(title) > title_max_end:
            title_start = max(0, title_max_end - len(title))
    
        # Emit: leading padding, title, padding to toggle, toggle, trailing pad.
        if title_start > 0:
            frags.append(("", " " * title_start, self._editor_clear_outer_hover))
        if title:
            frags.append((C_SECTION, title, self._editor_clear_outer_hover))
        pad_to_toggle = max(0, toggle_start - (title_start + len(title)))
        if pad_to_toggle > 0:
            frags.append(("", " " * pad_to_toggle, self._editor_clear_outer_hover))
    
        for i, label_upper in enumerate(_EDITOR_TOGGLE_LABELS):
            label_lower = label_upper.lower()
            block = self._editor_toggle_block(label_upper)
            style = self._editor_toggle_button_style(label_lower)
            frags.append((style, block,
                          self._editor_toggle_button_handler(label_lower)))
            if i == 0:
                frags.append(("", " ", self._editor_clear_outer_hover))
    
        tail_pad = max(0, cols - toggle_start - toggle_w)
        if tail_pad > 0:
            frags.append(("", " " * tail_pad, self._editor_clear_outer_hover))
        frags.append(("", "\n", self._editor_clear_outer_hover))
    
    
    def _editor_append_footer(self, frags, cols):
        """Footer hints + the macro key-capture feedback flash. Hint text
        depends on the current focus zone and the active mode.
    
        Phase 6.2: arrow-key and Enter tokens are removed from all editor
        footers — they're intuitive enough from layout to skip the hint.
        The Tab token is uniformly `Tab Cycle` everywhere — it describes
        what the key does, not the size of the focus chain. Kept tokens:
        `Tab Cycle` / `Shift+Tab`, `n New`, `Del Delete`, `ESC Save & back`.
    
        Called from the footer-Window text fn; the leading `\\n` produces
        the blank separator row above the hint within that Window."""
        frags.append(("", "\n", self._editor_clear_outer_hover))
        if self._editor_toggle_focused:
            footer = "Tab Cycle · ESC Save & back"
        elif self._editor_mode == "editor":
            footer = "Tab Cycle · ESC Save & back"
        elif self._editor_focus == 0:
            footer = "Tab Cycle · ESC Save & back"
        elif self._editor_focus == 1:
            footer = ("n New · Del Delete · Tab Cycle · "
                      "ESC Save & back")
        else:
            footer = "Tab Cycle · ESC Save & back"
        # A live c-c / c-x flash takes over the centred message slot. The
        # editor-mode Ln/Col indicator stays pinned to the right edge in
        # both branches; the brace-balance segment only joins it on the
        # static-hint branch (the flash branch keeps the row uncluttered).
        if self._editor_flash_text:
            flash = self._editor_flash_text
            leading_pad = _pad_centre(flash, cols)
            frags.append(("", leading_pad, self._editor_clear_outer_hover))
            frags.append((self._editor_flash_style, flash, self._editor_clear_outer_hover))
            if self._editor_mode == "editor":
                lc_text = self._editor_line_col_text()
                used = len(leading_pad) + len(flash)
                pad = max(1, cols - used - len(lc_text))
                frags.append(("", " " * pad, self._editor_clear_outer_hover))
                frags.append((C_HINT, lc_text, self._editor_clear_outer_hover))
        else:
            leading_pad = _pad_centre(footer, cols)
            frags.append(("", leading_pad, self._editor_clear_outer_hover))
            frags.append((C_HINT, footer, self._editor_clear_outer_hover))
            # Right-aligned: brace-balance (C_DANGER, when unbalanced) sits
            # immediately left of the always-on Ln/Col, joined by `  ·  `.
            # Ln/Col stays at column (cols - len(lc_text)) regardless of
            # whether the brace segment is present. See docs/launcher.md →
            # profile_editor → Editor mode.
            if self._editor_mode == "editor":
                lc_text = self._editor_line_col_text()
                balance_text = self._editor_brace_balance_text()
                sep = "  ·  "
                used = len(leading_pad) + len(footer)
                right_w = len(lc_text)
                if balance_text:
                    right_w += len(balance_text) + len(sep)
                pad = max(1, cols - used - right_w)
                frags.append(("", " " * pad, self._editor_clear_outer_hover))
                if balance_text:
                    frags.append((C_DANGER, balance_text,
                                  self._editor_clear_outer_hover))
                    frags.append((C_HINT, sep, self._editor_clear_outer_hover))
                frags.append((C_HINT, lc_text, self._editor_clear_outer_hover))
        if self._editor_feedback_text:
            frags.append(("", "\n", self._editor_clear_outer_hover))
            frags.append((
                "", _pad_centre(self._editor_feedback_text, cols),
                self._editor_clear_outer_hover,
            ))
            frags.append((
                self._editor_feedback_style, self._editor_feedback_text,
                self._editor_clear_outer_hover,
            ))
    
    
    def _editor_buffer_scroll_cursor_into_view(self):
        """Pull the viewport so the cursor's visual row is visible. Called
        from every cursor-mutating action (keystrokes, content clicks,
        selection-extending shift+arrows). Scrollbar clicks deliberately do
        NOT call this so the user's scroll survives until the cursor moves.
    
        The render path no longer calls scroll_into_view; the viewport sits
        wherever the most recent cursor-mutating action put it."""
        self._editor_buffer_scroll_into_view(self._host.term_cols(), self._editor_body_h())
    
    
    def _editor_append_editor_body(self, frags, cols):
        """Render the editor-mode body: full-width text buffer with line
        numbers on the left, an inline scrollbar on the right, and a
        current-line highlight tracking the cursor.
    
        Per-row composition. Each row is emitted as ~3-6 style runs (line-
        number cell, 1-5 content runs, scrollbar, newline) with a single
        per-row mouse handler that interprets `ev.position.x`. The previous
        per-cell layout allocated ~83 fragments and closures per row × 24
        rows per frame — measurable lag on files of ~20+ lines."""
        body_h = self._editor_body_h()
        wrap_w, total_visual, l2v = self._editor_buffer_visual_layout(cols)
        scroll = self._editor_buffer_scroll
        cursor_line, cursor_col = self._editor_buffer_cursor_to_line_col()
        cursor_wrap_idx = cursor_col // wrap_w
        ln_w = self._editor_line_num_w()
        starts = self._editor_buffer_line_starts()
        text = self._editor_buffer_text
        text_len = len(text)
    
        overflow = total_visual > body_h
        sb_top, sb_thumb_h = _editor_sb_thumb_geom_generic(
            total_visual, body_h, body_h, scroll)
        sb_visible = overflow
    
        # Syntax-highlight spans for the whole buffer (identity-cached, so
        # cheap on every frame after the first post-mutation tokenisation).
        # `syn_cursor` walks forward through `syn_spans` across all visible
        # rows; it never rewinds because visible rows iterate in ascending
        # absolute-offset order.
        syn_spans  = self._editor_buffer_syntax_spans()
        syn_n      = len(syn_spans)
        syn_cursor = 0
    
        # Pre-compute (logical_line, wrap_idx) for each visible visual row.
        # `l2v[line_idx] = (start_visual, wrap_count)`; we walk forward from
        # the line that contains the first visible visual row.
        visible_rows = []
        line_idx = 0
        consumed = 0
        for i, (s, n) in enumerate(l2v):
            if s + n > scroll:
                line_idx = i
                consumed = scroll - s
                break
        for _ in range(body_h):
            if line_idx < len(l2v):
                _start, n = l2v[line_idx]
                visible_rows.append((line_idx, consumed))
                consumed += 1
                if consumed >= n:
                    line_idx += 1
                    consumed = 0
            else:
                visible_rows.append(None)
    
        buffer_focused = (not self._editor_toggle_focused)
        # Focused: subtle band derived from the host terminal bg. Unfocused
        # (toggle has focus): no `bg:` override so the row blends into the
        # surrounding canvas — `row_bg = ""` propagates through the per-cell
        # style composition below without painting a band.
        hl_bg          = (self._editor_focused_line_hl_bg(self._host.terminal_bg)
                          if buffer_focused else "")
    
        # Active selection range in absolute char offsets, or None.
        sel_lo = sel_hi = None
        if self._editor_buffer_anchor is not None:
            a = max(0, min(text_len, self._editor_buffer_anchor))
            c = max(0, min(text_len, self._editor_buffer_cursor))
            if a != c:
                sel_lo, sel_hi = (a, c) if a < c else (c, a)
    
        # Matching-brace highlight: the brace adjacent to the cursor and
        # its partner. `None` when the cursor is not next to a brace or
        # when the partner can't be found (unbalanced). The renderer
        # checks `abs_off in match_offsets` per cell — constant-time even
        # though the helper itself scans the brace list.
        bm = self._editor_brace_match_positions()
        match_offsets = (bm[0], bm[1]) if bm is not None else ()
    
        for vrow in range(body_h):
            info = visible_rows[vrow]
            is_cursor_line = (info is not None and info[0] == cursor_line)
            row_bg = hl_bg if is_cursor_line else ""
    
            # ----- Line-number cell -----
            if info is None or info[1] != 0:
                ln_text = " " * ln_w
            else:
                ln_text = (str(info[0] + 1).rjust(ln_w - 1) + " ")
            ln_style = f"fg:#585858 {row_bg}".strip()
            frags.append((ln_style, ln_text,
                          self._editor_buffer_chrome_wheel_handler))
    
            # ----- Content cells (one row = 1-5 style runs) -----
            if info is None:
                frags.append((row_bg, " " * wrap_w,
                              self._editor_buffer_chrome_wheel_handler))
            else:
                logical_line, wrap_idx = info
                line_start_abs = starts[logical_line]
                line_end_abs   = (starts[logical_line + 1] - 1
                                  if logical_line + 1 < len(starts) else text_len)
                line_len = line_end_abs - line_start_abs
    
                wrap_start = wrap_idx * wrap_w
                chunk_lo   = line_start_abs + wrap_start
                chunk_hi   = line_start_abs + min(line_len, wrap_start + wrap_w)
                chunk      = text[chunk_lo:chunk_hi]
                chunk_len  = len(chunk)
    
                is_cursor_visual_row = (
                    is_cursor_line and wrap_idx == cursor_wrap_idx)
                cursor_cell = (cursor_col - wrap_start
                               if is_cursor_visual_row else -1)
    
                content_text_style = f"{C_ITEM} {row_bg}".strip()
                row_handler = self._editor_buffer_row_click_handler(
                    logical_line, wrap_start, ln_w, line_len)
    
                # Build per-cell style + char arrays, then collapse runs.
                cell_styles = [None] * wrap_w
                cell_chars  = [" "] * wrap_w
                for ccol in range(wrap_w):
                    token_fg = None
                    is_brace_match = False
                    if ccol < chunk_len:
                        ch = chunk[ccol]
                        cell_chars[ccol] = ch
                        abs_off = chunk_lo + ccol
                        in_sel = (sel_lo is not None
                                  and sel_lo <= abs_off < sel_hi)
                        # Skip spans that end at/before this cell, then peek
                        # at the next span — if it starts at/before us we're
                        # inside it. Monotonic across the whole frame.
                        while (syn_cursor < syn_n
                               and syn_spans[syn_cursor][1] <= abs_off):
                            syn_cursor += 1
                        if (syn_cursor < syn_n
                                and syn_spans[syn_cursor][0] <= abs_off):
                            token_fg = _EDITOR_SYNTAX_STYLE[
                                syn_spans[syn_cursor][2]]
                        is_brace_match = abs_off in match_offsets
                    else:
                        ch = " "
                        in_sel = False
                    is_cursor_cell = (ccol == cursor_cell)
                    # See `self._editor_box_content_row`: when a selection is
                    # active the cursor sits at the run boundary, so painting
                    # its cell would visually extend the highlight by one
                    # (e.g. double-click `{word}` looked like `word}`).
                    if in_sel or (is_cursor_cell and buffer_focused
                                  and sel_lo is None):
                        cell_styles[ccol] = C_SELECTED
                    elif is_brace_match:
                        cell_styles[ccol] = C_SYN_BRACE_MATCH
                    elif token_fg is not None:
                        cell_styles[ccol] = (
                            f"{token_fg} {row_bg}".strip() if row_bg
                            else token_fg)
                    elif ch != " ":
                        cell_styles[ccol] = content_text_style
                    else:
                        cell_styles[ccol] = row_bg
    
                i = 0
                while i < wrap_w:
                    j = i + 1
                    while j < wrap_w and cell_styles[j] == cell_styles[i]:
                        j += 1
                    frags.append((cell_styles[i],
                                  "".join(cell_chars[i:j]),
                                  row_handler))
                    i = j
    
            # ----- Scrollbar cell -----
            if sb_visible and sb_top <= vrow < sb_top + sb_thumb_h:
                sb_style, sb_glyph = "bold fg:#ffffff", "█"
            elif sb_visible:
                sb_style, sb_glyph = "fg:#585858", "░"
            else:
                sb_style, sb_glyph = "", " "
            frags.append((sb_style, sb_glyph,
                          self._editor_buffer_scrollbar_click_handler(vrow, sb_top,
                                                                 sb_thumb_h,
                                                                 total_visual,
                                                                 body_h)))
            frags.append(("", "\n", self._editor_clear_outer_hover))
    
    
    def _editor_buffer_row_click_handler(self, logical_line, wrap_start,
                                         content_x_offset, line_len):
        """One mouse handler per visible row. A count-1 click lands the
        cursor on the `(logical_line, col)` derived from `ev.position.x`
        and clears any selection. A count-2 click selects the word at that
        position; a count-3 click selects the whole logical line (incl. its
        trailing `\\n`, when present). Move events are silent (no per-row
        hover in editor mode).
    
        Pre-Phase-6.1 this was one closure per cell — ~80×24 closures per
        frame. Now one closure per visible row, interpreting the column at
        click time."""
        def _h(ev):
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                return None
            if ev.event_type == MouseEventType.SCROLL_UP:
                self._editor_buffer_wheel(-3)
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                self._editor_buffer_wheel(3)
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            col_in_content = ev.position.x - content_x_offset
            if col_in_content < 0:
                col_in_content = 0
            abs_col = min(line_len, wrap_start + col_in_content)
            count = self._editor_click_tick(ev)
            self._editor_unfocus_toggle()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            if count == 2:
                self._editor_buffer_select_word_at(logical_line, abs_col)
            elif count == 3:
                self._editor_buffer_select_logical_line(logical_line)
            else:
                self._editor_buffer_set_cursor_from_line_col(logical_line, abs_col)
                self._editor_buffer_clear_selection()
            self._editor_buffer_scroll_cursor_into_view()
            if self._host.app:
                self._host.app.invalidate()
            return None
        return _h
    
    
    def _editor_buffer_scrollbar_click_handler(self, vrow, sb_top, sb_thumb_h,
                                               total, viewport_h):
        """Page-step click on the editor-mode scrollbar. Clicks above the
        thumb page up by one viewport, clicks below page down. Holding the
        button on a track row arms `_autoscroll_*` to repeat the page-step
        toward the held row until the thumb covers it (see ADR 0092)."""
        def _h(ev, row=vrow, top=sb_top, h=sb_thumb_h, t=total, v=viewport_h):
            if ev.event_type == MouseEventType.SCROLL_UP:
                self._editor_buffer_wheel(-3)
                return None
            if ev.event_type == MouseEventType.SCROLL_DOWN:
                self._editor_buffer_wheel(3)
                return None
            if ev.event_type == MouseEventType.MOUSE_UP:
                self._autoscroll_disarm()
                return None
            if ev.event_type == MouseEventType.MOUSE_MOVE:
                self._autoscroll_set_target(row)
                return None
            if ev.event_type != MouseEventType.MOUSE_DOWN:
                return NotImplemented
            max_scroll = max(0, t - v)
            on_thumb = (top <= row < top + h)
            if row < top:
                self._editor_buffer_scroll = max(0, self._editor_buffer_scroll - v)
            elif row >= top + h:
                self._editor_buffer_scroll = min(max_scroll,
                                            self._editor_buffer_scroll + v)
            if not on_thumb:
                self._autoscroll_arm(self._editor_buffer_autoscroll_step, row)
            if self._host.app:
                self._host.app.invalidate()
            return None
        return _h
    
    
    # --- Profile editor — feedback flash --------------------------------------
    def _editor_set_feedback(self, text, style, ttl_seconds=2.0):
        """Flash an inline feedback message below the editor footer. Used
        for "Bound to <key>." after a successful key capture."""
        self._editor_feedback_text  = text
        self._editor_feedback_style = style
        if self._editor_feedback_handle is not None:
            try:
                self._editor_feedback_handle.cancel()
            except Exception:
                pass
            self._editor_feedback_handle = None
        if self._host.app_loop is not None:
            self._editor_feedback_handle = self._host.app_loop.call_later(
                ttl_seconds, self._editor_clear_feedback)
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_clear_feedback(self):
        self._editor_feedback_text  = None
        self._editor_feedback_style = ""
        self._editor_feedback_handle = None
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_flash(self, text, style=C_ACCENT, ttl_seconds=1.5):
        """Flash a short confirmation in the editor footer's message slot —
        e.g. "Copied" / "Cut" after a successful c-c / c-x. While the flash
        is live the centred hint text is replaced and the editor-mode brace
        indicator yields; both return on the next render after auto-clear."""
        self._editor_flash_text  = text
        self._editor_flash_style = style
        if self._editor_flash_handle is not None:
            try:
                self._editor_flash_handle.cancel()
            except Exception:
                pass
            self._editor_flash_handle = None
        if self._host.app_loop is not None:
            self._editor_flash_handle = self._host.app_loop.call_later(
                ttl_seconds, self._editor_clear_flash)
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _editor_clear_flash(self):
        self._editor_flash_text  = None
        self._editor_flash_style = ""
        if self._editor_flash_handle is not None:
            try:
                self._editor_flash_handle.cancel()
            except Exception:
                pass
            self._editor_flash_handle = None
        if self._host.app:
            self._host.app.invalidate()
    
    
    # --- Profile editor — scrollbar click-and-hold auto-scroll ----------------
    # prompt_toolkit delivers no "button held" event stream between MOUSE_DOWN
    # and MOUSE_UP, and MOUSE_UP reaches only the fragment under the pointer
    # at release — so it cannot be the sole stop signal. Auto-scroll is
    # bounded by a TARGET (the held track row) and self-terminates once the
    # thumb covers that row, or the scroll clamps. MOUSE_UP, when received,
    # disarms early. See ADR 0092.
    def _autoscroll_arm(self, step_fn, target_row):
        """Disarm any existing auto-scroll, then schedule the first tick
        after `_AUTOSCROLL_INITIAL_DELAY`. `step_fn` performs one page-step
        toward `self._autoscroll_target` and returns True to keep going, False to
        stop. The target lives in module state so MOUSE_MOVE handlers can
        update it without re-arming."""
        self._autoscroll_disarm()
        self._autoscroll_step_fn = step_fn
        self._autoscroll_target  = target_row
        if self._host.app_loop is not None:
            self._autoscroll_handle = self._host.app_loop.call_later(
                _AUTOSCROLL_INITIAL_DELAY, self._autoscroll_tick)
    
    
    def _autoscroll_tick(self):
        """One auto-scroll step: invoke `step_fn`, invalidate the app, then
        either reschedule (continue) or disarm (target reached / clamped).
        Exposed at module scope so tests can drive it directly without
        sleeping for the timer."""
        self._autoscroll_handle = None
        if self._autoscroll_step_fn is None:
            return
        try:
            keep_going = bool(self._autoscroll_step_fn())
        except Exception:
            keep_going = False
        if self._host.app:
            self._host.app.invalidate()
        if not keep_going:
            self._autoscroll_disarm()
            return
        if self._host.app_loop is not None:
            self._autoscroll_handle = self._host.app_loop.call_later(
                _AUTOSCROLL_REPEAT_INTERVAL, self._autoscroll_tick)
    
    
    def _autoscroll_set_target(self, target_row):
        """Best-effort target-follows-pointer update for MOUSE_MOVE while a
        button is held. No-op when auto-scroll is not armed."""
        if self._autoscroll_step_fn is not None:
            self._autoscroll_target = target_row
    
    
    def _autoscroll_disarm(self):
        """Cancel any pending tick and clear auto-scroll state. Safe to call
        multiple times; safe to call when nothing is armed."""
        self._autoscroll_step_fn = None
        self._autoscroll_target  = None
        if self._autoscroll_handle is not None:
            try:
                self._autoscroll_handle.cancel()
            except Exception:
                pass
            self._autoscroll_handle = None
    
    
    def _autoscroll_armed(self):
        """True while a scrollbar auto-scroll is armed — for tests."""
        return self._autoscroll_step_fn is not None
    
    
    # Per-scrollbar step functions. Each re-reads the CURRENT thumb geometry
    # against `self._autoscroll_target` and pages one viewport toward it; returns
    # False once the thumb covers the target row or no further scroll is
    # possible. The step function captures NO geometry — captured thumb_top
    # values go stale as the thumb moves.
    def _editor_buffer_autoscroll_step(self):
        target = self._autoscroll_target
        if target is None:
            return False
        cols = self._host.term_cols()
        body_h = self._editor_body_h()
        _wrap_w, total_visual, _l2v = self._editor_buffer_visual_layout(cols)
        if total_visual <= body_h:
            return False
        max_scroll = max(0, total_visual - body_h)
        top, thumb_h = _editor_sb_thumb_geom_generic(
            total_visual, body_h, body_h, self._editor_buffer_scroll)
        if top <= target < top + thumb_h:
            return False
        if target < top:
            new_scroll = max(0, self._editor_buffer_scroll - body_h)
        else:
            new_scroll = min(max_scroll, self._editor_buffer_scroll + body_h)
        if new_scroll == self._editor_buffer_scroll:
            return False
        self._editor_buffer_scroll = new_scroll
        return True
    
    
    def _editor_list_autoscroll_step(self):
        target = self._autoscroll_target
        if target is None:
            return False
        visible = self._editor_list_visible()
        total = self._profile_editor_display_total()
        if total <= visible:
            return False
        max_scroll = max(0, total - visible)
        top, thumb_h = self._editor_sb_thumb_geom(total, visible, visible)
        if top <= target < top + thumb_h:
            return False
        if target < top:
            new_scroll = max(0, self._editor_list_scroll - visible)
        else:
            new_scroll = min(max_scroll, self._editor_list_scroll + visible)
        if new_scroll == self._editor_list_scroll:
            return False
        self._editor_list_scroll = new_scroll
        if self._editor_list_sb is not None:
            self._editor_list_sb.scroll_to(new_scroll)
        return True
    
    
    def _editor_body_autoscroll_step(self):
        target = self._autoscroll_target
        if target is None:
            return False
        cap = self._editor_body_budget()
        line_count = len(self._editor_body_lines())
        if line_count <= cap:
            return False
        max_scroll = max(0, line_count - cap)
        top, thumb_h = _editor_sb_thumb_geom_generic(
            line_count, cap, cap, self._editor_body_scroll)
        if top <= target < top + thumb_h:
            return False
        if target < top:
            new_scroll = max(0, self._editor_body_scroll - cap)
        else:
            new_scroll = min(max_scroll, self._editor_body_scroll + cap)
        if new_scroll == self._editor_body_scroll:
            return False
        self._editor_body_scroll = new_scroll
        return True
    
    
    # --- Profile editor — macro key-capture overlay ---------------------------
    def _editor_push_keybind_overlay(self, just_created):
        """Push the `profile_editor_macro_keybind` frame. `just_created` is
        True when the overlay was auto-opened by `+ New entry`; on ESC the
        handler then removes the unfilled Entry."""
        self._editor_keybind_error        = ""
        self._editor_keybind_just_created = just_created
        self._host.push_overlay_frame()
    
    
    def _editor_keybind_cancel(self):
        """ESC handler. When the overlay was auto-pushed by `+ New entry`,
        remove the unfilled Entry so the list stays visually consistent."""
        if self._editor_keybind_just_created and self._editor_data is not None:
            # The just-created entry is the most recent Entry of kind=macro
            # with an empty pattern. There is at most one such entry by
            # construction — `self._editor_create_new_entry` appends it last and
            # immediately pushes the overlay before the user can edit.
            for i in range(len(self._editor_data.items) - 1, -1, -1):
                it = self._editor_data.items[i]
                if (isinstance(it, profile_io.Entry)
                        and it.kind == "macro" and it.pattern == ""):
                    del self._editor_data.items[i]
                    break
            # Re-anchor the cursor — prefer falling onto the sentinel only
            # when no entries remain.
            entries_total = self._profile_editor_active_count()
            if entries_total == 0:
                self._editor_list_cursor = 0
            else:
                self._editor_list_cursor = min(self._editor_list_cursor, entries_total)
            self._profile_editor_scroll_into_view()
            self._editor_refresh_buffers()
        self._editor_keybind_just_created = False
        self._host.pop_overlay_frame()
        self._profile_editor_set_focus(2, field=0)
    
    
    def _editor_keybind_accept(self, match):
        """Match handler: write `match.tin_escape` into the current entry's
        pattern, flash the success line, pop the overlay, and move focus to
        Commands so the user can keep typing."""
        entry = self._editor_current_entry()
        if entry is None:
            # Defensive — the overlay shouldn't be reachable without an
            # entry under the cursor.
            self._editor_keybind_just_created = False
            self._host.pop_overlay_frame()
            return
        entry.pattern = match.tin_escape
        # Re-sort + re-anchor so the entry's new place in the list lands
        # under the cursor.
        view_after = self._profile_editor_display_view()
        try:
            self._editor_list_cursor = view_after.index(entry)
            self._profile_editor_scroll_into_view()
        except ValueError:
            pass
        auto_opened = self._editor_keybind_just_created
        self._editor_keybind_just_created = False
        self._host.pop_overlay_frame()
        if auto_opened:
            self._profile_editor_set_focus(2, field=1)
        else:
            self._profile_editor_set_focus(2, field=0)
        self._editor_set_feedback(f"Bound to {match.display_name}.", C_ACCENT)
    
    
    def _editor_keybind_set_error(self, msg):
        self._editor_keybind_error = msg
        if self._host.app:
            self._host.app.invalidate()
    
    
    def _profile_editor_keybind_text(self):
        """Render the key-capture overlay — a centred modal panel.
    
        Layout:
            ─── Bind key ───
            <blank>
            Press the key to bind…
            <blank>
               <error line — only when an attempt failed>
            <blank>
               ESC Cancel
        """
        cols = self._host.term_cols()
        title  = "─── Bind key ───"
        prompt = "Press the key to bind…"
        footer = "ESC Cancel"
        frags = []
        frags.append(("", "\n\n"))
        frags.append(("", _pad_centre(title, cols)))
        frags.append((C_SECTION, title))
        frags.append(("", "\n\n\n"))
        frags.append(("", _pad_centre(prompt, cols)))
        frags.append((C_ITEM, prompt))
        frags.append(("", "\n\n"))
        if self._editor_keybind_error:
            frags.append(("", _pad_centre(self._editor_keybind_error, cols)))
            frags.append((C_DANGER, self._editor_keybind_error))
            frags.append(("", "\n\n"))
        else:
            frags.append(("", "\n\n"))
        frags.append(("", _pad_centre(footer, cols)))
        frags.append((C_HINT, footer))
        return frags
    

    def _editor_in_palette_focus(self):
        """True when the detail panel's currently-focused field is any of
        the highlight palette zones (Style, Text, Background). Used by the
        text-editing keybindings (Backspace, character input, Home/End,
        arrow keys) to skip the text-body code paths."""
        return (self._editor_focus == 2
                and self._profile_editor_active_kind() == "highlight"
                and self._editor_detail_field in (1, 2, 3))

    def _editor_hl_zone_count(self):
        """Number of focusable zones inside the detail panel for the
        current kind. 4 for highlights (Pattern, Style, Text, BG); 2 for
        everything else (Pattern, Body)."""
        if self._profile_editor_active_kind() == "highlight":
            return 4
        return 2

    def _editor_in_macro_key_focus(self):
        """True when the detail panel's Pattern slot is showing the macro
        Key cell (Macros tab + detail field 0)."""
        return (self._editor_focus == 2
                and self._editor_detail_field == 0
                and self._profile_editor_active_kind() == "macro")

    def _kb_peditor_palette_right(self):
        """Right within the highlight palette zones — see docs/launcher.md
        'Focus model'. Phase 6.2 chain:
        Style rightmost (Reverse) → Text (0, 0);
        Text col 0 → Text col 1;
        Text col 1 → BG col 0 (same row);
        BG col 0 → BG col 1;
        BG col 1 → no-op (rightmost zone)."""
        field = self._editor_detail_field
        if field == 1:
            if self._editor_hl_style_cursor >= len(_HL_STYLE_TOKENS) - 1:
                # Reverse (rightmost) → Text (0, 0).
                self._profile_editor_set_focus(2, field=2)
                self._editor_hl_set_text_cursor(0, 0)
            else:
                self._editor_hl_set_style_cursor(self._editor_hl_style_cursor + 1)
            return
        if field == 2:
            if self._editor_hl_text_col == 0:
                self._editor_hl_set_text_cursor(self._editor_hl_text_row, 1)
            else:
                self._profile_editor_set_focus(2, field=3)
                self._editor_hl_set_bg_cursor(self._editor_hl_text_row, 0)
            return
        if field == 3:
            if self._editor_hl_bg_col == 0:
                self._editor_hl_set_bg_cursor(self._editor_hl_bg_row, 1)

    def _kb_peditor_palette_left(self):
        """Left within the highlight palette. Phase 6.3 fall-through chain
        (leftmost Style toggle is now Undersc. after Bold was dropped):
        Style.Undersc. (leftmost toggle) → Pattern (cursor at end);
        Text col 0 → Style.Reverse (rightmost toggle);
        BG col 0 → Text col 1 (same row).
        All other moves are intra-zone."""
        field = self._editor_detail_field
        if field == 1:
            if self._editor_hl_style_cursor <= 0:
                entry = self._editor_current_entry()
                self._profile_editor_set_focus(2, field=0)
                self._editor_pattern_cursor = len(entry.pattern) if entry else 0
            else:
                self._editor_hl_set_style_cursor(self._editor_hl_style_cursor - 1)
            return
        if field == 2:
            if self._editor_hl_text_col == 1:
                self._editor_hl_set_text_cursor(self._editor_hl_text_row, 0)
            else:
                self._profile_editor_set_focus(2, field=1)
                self._editor_hl_set_style_cursor(len(_HL_STYLE_TOKENS) - 1)
            return
        if field == 3:
            if self._editor_hl_bg_col == 1:
                self._editor_hl_set_bg_cursor(self._editor_hl_bg_row, 0)
            else:
                self._profile_editor_set_focus(2, field=2)
                self._editor_hl_set_text_cursor(self._editor_hl_bg_row, 1)

    def _kb_peditor_palette_up(self):
        """Up within the highlight palette: Style ↑ → Pattern;
        Text / BG row 0 ↑ → Style; otherwise row-1."""
        field = self._editor_detail_field
        if field == 1:
            self._profile_editor_set_focus(2, field=0)
            return
        if field == 2:
            if self._editor_hl_text_row == 0:
                self._profile_editor_set_focus(2, field=1)
            else:
                self._editor_hl_set_text_cursor(self._editor_hl_text_row - 1,
                                           self._editor_hl_text_col)
            return
        if field == 3:
            if self._editor_hl_bg_row == 0:
                self._profile_editor_set_focus(2, field=1)
            else:
                self._editor_hl_set_bg_cursor(self._editor_hl_bg_row - 1,
                                         self._editor_hl_bg_col)

    def _kb_peditor_palette_down(self):
        """Down within the highlight palette: Style ↓ → Text col 0;
        Text / BG bottom row ↓ → no-op; otherwise row+1."""
        field = self._editor_detail_field
        if field == 1:
            self._profile_editor_set_focus(2, field=2)
            return
        if field == 2:
            if self._editor_hl_text_row < _HL_PALETTE_ROWS - 1:
                self._editor_hl_set_text_cursor(self._editor_hl_text_row + 1,
                                           self._editor_hl_text_col)
            return
        if field == 3:
            if self._editor_hl_bg_row < _HL_PALETTE_ROWS - 1:
                self._editor_hl_set_bg_cursor(self._editor_hl_bg_row + 1,
                                         self._editor_hl_bg_col)

    def _kb_peditor_lite_dispatch(self, pattern_fn, body_fn):
        if self._editor_focus != 2:
            return False
        if self._editor_in_palette_focus():
            return False
        if self._editor_in_macro_key_focus():
            return False
        ran = False
        if self._editor_detail_field == 0:
            pattern_fn()
            ran = True
        elif self._editor_detail_field == 1:
            body_fn()
            ran = True
        if self._host.app:
            self._host.app.invalidate()
        return ran

    def _kb_peditor_buffer_move_cursor(self, delta_line, delta_col=0):
        """Move the buffer cursor by line/column. Preserves the column when
        moving vertically (clamps to the destination line's length)."""
        line, col = self._editor_buffer_cursor_to_line_col()
        if delta_line:
            new_line = line + delta_line
            starts = self._editor_buffer_line_starts()
            if new_line < 0:
                return False
            if new_line >= len(starts):
                return False
            new_line_len = len(self._editor_buffer_line_text(new_line))
            new_col = min(col, new_line_len)
            self._editor_buffer_set_cursor_from_line_col(new_line, new_col)
            return True
        if delta_col:
            self._editor_buffer_cursor = max(0, min(len(self._editor_buffer_text),
                                               self._editor_buffer_cursor + delta_col))
        return True


    # --- Plain (unshifted) cursor moves: clear selection, then move ------
    # Every cursor-move handler also closes any open coalescing run — a
    # move forces the next insert/delete to start a fresh undo transaction.

    def _kb_peditor_lite_copy(self, event=None):
        """Lite-mode C-c: copy pattern or body text."""
        if self._kb_peditor_lite_dispatch(self._editor_pattern_copy,
                                           self._editor_body_copy):
            self._editor_flash("Copied")

    def _kb_peditor_lite_cut(self, event=None):
        """Lite-mode C-x: cut pattern or body text."""
        if self._kb_peditor_lite_dispatch(self._editor_pattern_cut,
                                           self._editor_body_cut):
            self._editor_flash("Cut")

    def _kb_peditor_lite_paste(self, event=None):
        """Lite-mode C-v: paste into pattern or body."""
        self._kb_peditor_lite_dispatch(self._editor_pattern_paste,
                                        self._editor_body_paste)

    def _kb_peditor_buffer_copy(self, event=None):
        """Editor-mode C-c: copy buffer selection."""
        self._editor_buffer_copy()
        self._editor_flash("Copied")

    def _kb_peditor_buffer_cut(self, event=None):
        """Editor-mode C-x: cut buffer selection."""
        self._editor_buffer_cut()
        self._editor_buffer_scroll_cursor_into_view()
        self._editor_flash("Cut")

    def _kb_peditor_buffer_paste(self, event=None):
        """Editor-mode C-v: paste into buffer."""
        self._editor_buffer_paste()
        self._editor_buffer_scroll_cursor_into_view()

    def _kb_peditor_buffer_bracketed_paste(self, event_or_data=None):
        """Editor-mode bracketed paste into buffer.

        Accepts either a prompt_toolkit event (with .data) or a raw string."""
        if hasattr(event_or_data, 'data'):
            data = event_or_data.data or ""
        elif isinstance(event_or_data, str):
            data = event_or_data
        else:
            data = ""
        self._editor_buffer_bracketed_paste(data)
        self._editor_buffer_scroll_cursor_into_view()

    def _editor_word_bounds(self, line_text, col):
        """Instance proxy for the module-level _editor_word_bounds."""
        return _editor_word_bounds(line_text, col)

    def _register_key_bindings(self, kb):
        """Register all profile_editor key bindings onto `kb`."""
        from prompt_toolkit.filters import Condition

        # Sub-state filters (these replace the module-level _in_pe_* functions)
        def _in_pe_lite():
            return Condition(lambda: self._host.is_active()
                             and self._editor_mode == 'lite'
                             and not self._editor_toggle_focused)

        def _in_pe_editor():
            return Condition(lambda: self._host.is_active()
                             and self._editor_mode == 'editor'
                             and not self._editor_toggle_focused)

        def _in_pe_toggle():
            return Condition(lambda: self._host.is_active()
                             and self._editor_toggle_focused)

        def _in_frame_peditor():
            return Condition(lambda: self._host.is_active())

        def _in_frame_keybind():
            return Condition(lambda: self._host.is_overlay_active())

        # Profile editor — Tab / Shift+Tab cycle the 4-stop focus chain
        # (tabs → list → detail.Pattern → detail.Body → tabs). Arrows and
        # printable input route through one handler per key, gated on the
        # current focus zone + active detail field.
        @kb.add("tab", filter=_in_pe_lite())
        def _kb_peditor_tab(event):
            self._profile_editor_cycle_focus(1)
        
        
        @kb.add("s-tab", filter=_in_pe_lite())
        def _kb_peditor_stab(event):
            self._profile_editor_cycle_focus(-1)
        
        
        @kb.add("right", filter=_in_pe_lite())
        def _kb_peditor_right(event):
            if self._editor_focus == 0:
                # Kind buttons row (Phase 6.3): Right moves to the next button.
                # No wrap — Right on the last button (SUBSTITUTES) is a no-op.
                if self._editor_active_tab < len(_PROFILE_EDITOR_TABS) - 1:
                    self._profile_editor_set_tab(self._editor_active_tab + 1)
                return
            elif self._editor_focus == 1:
                self._profile_editor_set_focus(2, field=0)
            elif self._editor_focus == 2:
                if self._editor_in_macro_key_focus():
                    return   # Key cell is a button — no horizontal cursor
                if self._editor_in_palette_focus():
                    self._kb_peditor_palette_right()
                elif self._editor_detail_field == 0:
                    self._editor_clear_pattern_selection()
                    self._editor_pattern_move_right()
                else:
                    self._editor_clear_body_selection()
                    self._editor_body_move_right()
                    self._editor_body_scroll_cursor_into_view()


        @kb.add("left", filter=_in_pe_lite())
        def _kb_peditor_left(event):
            """Stepwise Left within the lite mode. Each detail-panel zone, when
            its cursor sits at position 0, falls through one zone to the left:
            Body → Pattern (or Key for macros), Pattern / Key → entry list,
            list → kind buttons. On the kind-buttons row (Phase 6.3 — buttons
            now sit horizontally), Left moves to the previous button (no wrap)
            instead of falling through. Within highlight palette zones the
            fall-through chain is Style.Undersc. → Pattern, Text first col →
            Style.Reverse, BG first col → Text last col — see
            `self._kb_peditor_palette_left`. Fall-through clears the active text
            selection so the new zone starts fresh."""
            if self._editor_focus == 0:
                # Kind buttons row: Left moves to the previous button. No wrap
                # — Left on the first button (ACTIONS) is a no-op.
                if self._editor_active_tab > 0:
                    self._profile_editor_set_tab(self._editor_active_tab - 1)
                return
            if self._editor_focus == 1:
                self._profile_editor_set_focus(0)
                return
            if self._editor_focus == 2:
                if self._editor_in_macro_key_focus():
                    # Macro Key cell is a button (no horizontal cursor) — Left
                    # falls through to the entry list.
                    self._profile_editor_set_focus(1)
                    return
                if self._editor_in_palette_focus():
                    self._kb_peditor_palette_left()
                    return
                if self._editor_detail_field == 0:
                    # Text-bodied Pattern: at pos 0 → entry list.
                    if self._editor_pattern_cursor <= 0:
                        self._editor_clear_pattern_selection()
                        self._profile_editor_set_focus(1)
                    else:
                        self._editor_clear_pattern_selection()
                        self._editor_pattern_move_left()
                    return
                # Body at line 0 col 0: fall through to the previous zone.
                # Text-bodied kinds → Pattern (cursor at end). Macros → Key cell.
                if self._editor_body_line == 0 and self._editor_body_col == 0:
                    self._editor_clear_body_selection()
                    entry = self._editor_current_entry()
                    if self._profile_editor_active_kind() == "macro":
                        self._profile_editor_set_focus(2, field=0)
                    else:
                        self._profile_editor_set_focus(2, field=0)
                        self._editor_pattern_cursor = len(entry.pattern) if entry else 0
                    return
                self._editor_clear_body_selection()
                self._editor_body_move_left()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("up", filter=_in_pe_lite())
        def _kb_peditor_up(event):
            if self._editor_focus == 0:
                # Kind buttons row (Phase 6.3): Up always falls through to the
                # LITE/EDITOR toggle — the buttons are now a single horizontal
                # row, not a vertical column.
                self._editor_focus_toggle()
                return
            if self._editor_focus == 1:
                if self._editor_list_cursor == 0:
                    # Top of entry list → kind buttons (which sit between the
                    # list and the toggle in the new physical stacking).
                    self._profile_editor_set_focus(0)
                else:
                    self._profile_editor_move_cursor(-1)
                return
            if self._editor_detail_field == 0:
                # Detail Pattern → kind buttons (was: → toggle).
                self._profile_editor_set_focus(0)
                return
            if self._editor_in_palette_focus():
                self._kb_peditor_palette_up()
                return
            # Text body ↑: inter-line first; at top edge of buffer → Pattern.
            self._editor_clear_body_selection()
            if not self._editor_body_move_line(-1):
                self._profile_editor_set_focus(2, field=0)
            else:
                self._editor_body_scroll_cursor_into_view()


        @kb.add("down", filter=_in_pe_lite())
        def _kb_peditor_down(event):
            if self._editor_focus == 0:
                # Kind buttons row (Phase 6.3): Down always falls through to
                # the entry list, since the buttons sit horizontally above it.
                self._profile_editor_set_focus(1)
                self._profile_editor_jump_cursor(0)
                return
            if self._editor_focus == 1:
                self._profile_editor_move_cursor(1)
                return
            if self._editor_detail_field == 0:
                # Pattern ↓ → first palette zone (Style on highlights, Body
                # otherwise).
                self._profile_editor_set_focus(2, field=1)
                return
            if self._editor_in_palette_focus():
                self._kb_peditor_palette_down()
                return
            self._editor_clear_body_selection()
            self._editor_body_move_line(1)
            self._editor_body_scroll_cursor_into_view()


        # Shift-arrow selection. Each handler arms the anchor (if not already
        # set) and reuses the regular movement primitive. The selection cell-
        # range is computed at render time from (anchor, cursor).
        @kb.add("s-right", filter=_in_pe_lite())
        def _kb_peditor_s_right(event):
            if self._editor_focus != 2:
                return
            if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                return
            if self._editor_detail_field == 0:
                self._editor_pattern_set_anchor_if_none()
                self._editor_pattern_move_right()
            else:
                self._editor_body_set_anchor_if_none()
                self._editor_body_move_right()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("s-left", filter=_in_pe_lite())
        def _kb_peditor_s_left(event):
            if self._editor_focus != 2:
                return
            if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                return
            if self._editor_detail_field == 0:
                self._editor_pattern_set_anchor_if_none()
                self._editor_pattern_move_left()
            else:
                self._editor_body_set_anchor_if_none()
                self._editor_body_move_left()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("s-up", filter=_in_pe_lite())
        def _kb_peditor_s_up(event):
            if self._editor_focus != 2:
                return
            if (self._editor_in_macro_key_focus() or self._editor_in_palette_focus()
                    or self._editor_detail_field == 0):
                return   # Pattern is single-line — s-up is a no-op
            self._editor_body_set_anchor_if_none()
            self._editor_body_move_line(-1)
            self._editor_body_scroll_cursor_into_view()


        @kb.add("s-down", filter=_in_pe_lite())
        def _kb_peditor_s_down(event):
            if self._editor_focus != 2:
                return
            if (self._editor_in_macro_key_focus() or self._editor_in_palette_focus()
                    or self._editor_detail_field == 0):
                return
            self._editor_body_set_anchor_if_none()
            self._editor_body_move_line(1)
            self._editor_body_scroll_cursor_into_view()


        @kb.add("s-home", filter=_in_pe_lite())
        def _kb_peditor_s_home(event):
            if self._editor_focus != 2:
                return
            if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                return
            if self._editor_detail_field == 0:
                self._editor_pattern_set_anchor_if_none()
                self._editor_pattern_move_home()
            else:
                self._editor_body_set_anchor_if_none()
                self._editor_body_move_home()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("s-end", filter=_in_pe_lite())
        def _kb_peditor_s_end(event):
            if self._editor_focus != 2:
                return
            if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                return
            if self._editor_detail_field == 0:
                self._editor_pattern_set_anchor_if_none()
                self._editor_pattern_move_end()
            else:
                self._editor_body_set_anchor_if_none()
                self._editor_body_move_end()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("pageup", filter=_in_pe_lite())
        def _kb_peditor_pgup(event):
            if self._editor_focus == 1:
                self._profile_editor_move_cursor(-self._editor_list_visible())
        
        
        @kb.add("pagedown", filter=_in_pe_lite())
        def _kb_peditor_pgdn(event):
            if self._editor_focus == 1:
                self._profile_editor_move_cursor(self._editor_list_visible())
        
        
        @kb.add("home", filter=_in_pe_lite())
        def _kb_peditor_home(event):
            if self._editor_focus == 1:
                self._profile_editor_jump_cursor(0)
                return
            if self._editor_focus == 2:
                if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                    return
                if self._editor_detail_field == 0:
                    self._editor_clear_pattern_selection()
                    self._editor_pattern_move_home()
                else:
                    self._editor_clear_body_selection()
                    self._editor_body_move_home()
                    self._editor_body_scroll_cursor_into_view()


        @kb.add("end", filter=_in_pe_lite())
        def _kb_peditor_end(event):
            if self._editor_focus == 1:
                # End jumps to the sentinel row — the last selectable position.
                self._profile_editor_jump_cursor(self._profile_editor_display_total() - 1)
                return
            if self._editor_focus == 2:
                if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                    return
                if self._editor_detail_field == 0:
                    self._editor_clear_pattern_selection()
                    self._editor_pattern_move_end()
                else:
                    self._editor_clear_body_selection()
                    self._editor_body_move_end()
                    self._editor_body_scroll_cursor_into_view()


        @kb.add("delete", filter=_in_pe_lite())
        def _kb_peditor_kdelete(event):
            """`Del` semantics depend on focus zone:
            - List focus → delete the cursor entry immediately (no confirm).
            - Pattern / Body focus → forward-delete the character at the cursor.
            - Palette or macro Key cell → no-op (selection-only zones).
            """
            if self._editor_focus == 1:
                self._profile_editor_request_delete()
                return
            if self._editor_focus != 2:
                return
            if self._editor_in_macro_key_focus() or self._editor_in_palette_focus():
                return
            if self._editor_detail_field == 0:
                self._editor_pattern_forward_delete()
                if self._host.app:
                    self._host.app.invalidate()
            else:
                self._editor_body_forward_delete()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("n", filter=_in_pe_lite())
        @kb.add("N", filter=_in_pe_lite())
        def _kb_peditor_n(event):
            if self._editor_focus == 1:
                self._editor_create_new_entry()
            elif self._editor_focus == 2:
                _kb_peditor_any(event)
        
        
        @kb.add("enter", filter=_in_pe_lite())
        def _kb_peditor_enter(event):
            if self._editor_focus == 0:
                # Kind buttons row: Enter activates the focused button by
                # dropping into the entry list, cursor on row 0. Mirrors
                # ↓ so the row stops feeling dead.
                self._profile_editor_set_focus(1)
                self._profile_editor_jump_cursor(0)
                return
            if self._editor_focus == 1:
                if self._editor_cursor_on_sentinel():
                    self._editor_create_new_entry()
                    return
                entry = self._editor_current_entry()
                if entry is None:
                    return
                self._profile_editor_set_focus(2, field=0)
                return
            if self._editor_focus == 2:
                if self._editor_in_macro_key_focus():
                    # Key cell is a button — Enter pushes the capture overlay.
                    self._editor_push_keybind_overlay(just_created=False)
                    return
                if self._editor_in_palette_focus():
                    # Style zone: Enter toggles the current style. Text / BG:
                    # Enter toggles the selection at the cursor swatch.
                    if self._editor_detail_field == 1:
                        self._editor_hl_toggle_style(
                            _HL_STYLE_TOKENS[self._editor_hl_style_cursor])
                        if self._host.app:
                            self._host.app.invalidate()
                    elif self._editor_detail_field == 2:
                        self._editor_hl_toggle_text_selection_at_cursor()
                    elif self._editor_detail_field == 3:
                        self._editor_hl_toggle_bg_selection_at_cursor()
                    return
                if self._editor_detail_field == 1:
                    self._editor_body_insert_newline()
                    self._editor_body_scroll_cursor_into_view()
                # Pattern: Enter is a no-op (use Tab / ↓ to advance).


        @kb.add("space", filter=_in_pe_lite())
        def _kb_peditor_space(event):
            if self._editor_focus == 0:
                # Kind buttons row: Space mirrors Enter — drop into the
                # entry list, cursor on row 0.
                self._profile_editor_set_focus(1)
                self._profile_editor_jump_cursor(0)
                return
            if self._editor_focus == 2:
                # Detail panel: route to the printable-char handler so
                # Pattern and Body keep inserting a literal space. The
                # palette zones and the macro Key cell are no-ops there
                # already (the <any> handler swallows them).
                _kb_peditor_any(event)
            # focus 1 (entry list): Space is a no-op — Enter still owns
            # list activation.


        @kb.add("backspace", filter=_in_pe_lite())
        def _kb_peditor_backspace(event):
            if self._editor_focus != 2:
                return
            if self._editor_in_macro_key_focus():
                return   # Key cell is a button — backspace is a no-op
            if self._editor_detail_field == 0:
                self._editor_pattern_backspace()
                if self._host.app:
                    self._host.app.invalidate()
            elif self._editor_in_palette_focus():
                return   # palette is selection-only
            else:
                self._editor_body_backspace()
                self._editor_body_scroll_cursor_into_view()


        @kb.add("<any>", filter=_in_pe_lite())
        def _kb_peditor_any(event):
            """Printable-char input on the detail panel. Pattern and Body
            accept any printable character; insertion happens at the in-buffer
            cursor. The palette field and the macro Key cell are
            selection-only and swallow everything."""
            if self._editor_focus != 2:
                return
            if self._editor_in_palette_focus():
                return
            if self._editor_in_macro_key_focus():
                return
            data = event.data or ""
            if len(data) != 1 or not data.isprintable():
                return
            if self._editor_detail_field == 0:
                self._editor_pattern_insert_char(data)
                if self._host.app:
                    self._host.app.invalidate()
            elif self._editor_detail_field == 1:
                self._editor_body_insert_char(data)
                self._editor_body_scroll_cursor_into_view()
                if self._host.app:
                    self._host.app.invalidate()
        
        
        # --- Lite-mode clipboard (copy / cut / paste) ------------------------
        # Dispatch mirrors `_kb_peditor_any`: only the Pattern (detail_field 0)
        # and Body (detail_field 1, non-palette, non-macro-Key) text fields
        # respond. Tab buttons, the list, the palette zones and the macro Key
        # cell are all no-ops. Returns True when one of the fns ran — callers
        # use this to gate the c-c / c-x confirmation flash to text contexts.
        @kb.add("c-c", filter=_in_pe_lite())
        def _kb_peditor_lite_copy(event):
            self._kb_peditor_lite_copy(event)
        
        
        @kb.add("c-x", filter=_in_pe_lite())
        def _kb_peditor_lite_cut(event):
            self._kb_peditor_lite_cut(event)
        
        
        @kb.add("c-v", filter=_in_pe_lite())
        def _kb_peditor_lite_paste(event):
            self._kb_peditor_lite_paste(event)
        
        
        @kb.add(Keys.BracketedPaste, filter=_in_pe_lite())
        def _kb_peditor_lite_bracketed_paste(event):
            data = event.data or ""
            self._kb_peditor_lite_dispatch(
                lambda: self._editor_pattern_bracketed_paste(data),
                lambda: self._editor_body_bracketed_paste(data),
            )
        
        
        # `eager=True` is deliberately omitted: the Alt+↑/↓ line-move bindings
        # arrive as the escape-prefix chords `("escape", "up")` / `("escape",
        # "down")`. prompt_toolkit needs the brief follow-key wait to choose
        # between a bare ESC and a chord; an eager bare ESC would fire before
        # the arrow could disambiguate. The only user-visible cost is a short
        # delay before ESC save-and-close. See also the same trade-off on the
        # macro-keybind overlay's ESC binding.
        @kb.add("escape", filter=_in_frame_peditor())
        def _kb_peditor_escape(event):
            self._profile_editor_save_and_close()
        
        
        # ---------------------------------------------------------------------------
        # Profile editor — LITE/EDITOR toggle key handlers
        # ---------------------------------------------------------------------------
        # Phase 6.2: Left/Right select LITE/EDITOR respectively (two-button row;
        # no-op when the requested mode is already active). Enter and Space no
        # longer activate the toggle — those keys are free for other zones.
        
        @kb.add("up", filter=_in_pe_toggle())
        def _kb_peditor_toggle_up(event):
            # Nothing above the toggle.
            return
        
        
        @kb.add("down", filter=_in_pe_toggle())
        def _kb_peditor_toggle_down(event):
            self._editor_toggle_descend()


        @kb.add("enter", filter=_in_pe_toggle())
        def _kb_peditor_toggle_enter(event):
            # Enter descends like ↓ — it does NOT flip the mode (Left/Right/
            # click remain the only mode-flip affordances).
            self._editor_toggle_descend()


        @kb.add("space", filter=_in_pe_toggle())
        def _kb_peditor_toggle_space(event):
            # Space descends like ↓ — it does NOT flip the mode.
            self._editor_toggle_descend()


        @kb.add("left", filter=_in_pe_toggle())
        def _kb_peditor_toggle_left(event):
            # Left selects LITE. No-op when LITE is already active.
            if self._editor_mode != "lite":
                self._editor_flip_mode()
        
        
        @kb.add("right", filter=_in_pe_toggle())
        def _kb_peditor_toggle_right(event):
            # Right selects EDITOR. No-op when EDITOR is already active.
            if self._editor_mode != "editor":
                self._editor_flip_mode()
        
        
        @kb.add("tab",   filter=_in_pe_toggle())
        def _kb_peditor_toggle_tab(event):
            self._profile_editor_cycle_focus(1)
        
        
        @kb.add("s-tab", filter=_in_pe_toggle())
        def _kb_peditor_toggle_stab(event):
            self._profile_editor_cycle_focus(-1)
        
        
        # ---------------------------------------------------------------------------
        # Profile editor — editor-mode buffer key handlers
        # ---------------------------------------------------------------------------
        @kb.add("left",  filter=_in_pe_editor())
        def _kb_peditor_buffer_left(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(0, -1)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("right", filter=_in_pe_editor())
        def _kb_peditor_buffer_right(event):
            self._editor_buffer_clear_selection()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(0, +1)
            self._editor_buffer_step_over_pending_closer()
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("up", filter=_in_pe_editor())
        def _kb_peditor_buffer_up(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            if not self._kb_peditor_buffer_move_cursor(-1):
                self._editor_focus_toggle()
            else:
                self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("down", filter=_in_pe_editor())
        def _kb_peditor_buffer_down(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(+1)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        # Alt+↑ / Alt+↓ move the cursor's logical line up or down. prompt_toolkit
        # delivers Alt+arrow as the escape-prefix chord (`escape`, then `up` /
        # `down`), so the bare ESC binding above must NOT be `eager=True` — see
        # the comment there. `self._editor_buffer_move_line` records the move as a
        # single atomic undo transaction and clears pending closers; no-op at
        # the buffer ends does not push an undo entry.
        @kb.add("escape", "up", filter=_in_pe_editor())
        def _kb_peditor_buffer_alt_up(event):
            if self._editor_buffer_move_line(-1):
                self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("escape", "down", filter=_in_pe_editor())
        def _kb_peditor_buffer_alt_down(event):
            if self._editor_buffer_move_line(+1):
                self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("home", filter=_in_pe_editor())
        def _kb_peditor_buffer_home(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            line, _col = self._editor_buffer_cursor_to_line_col()
            self._editor_buffer_set_cursor_from_line_col(line, 0)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("end", filter=_in_pe_editor())
        def _kb_peditor_buffer_end(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            line, _col = self._editor_buffer_cursor_to_line_col()
            self._editor_buffer_set_cursor_from_line_col(
                line, len(self._editor_buffer_line_text(line)))
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("pageup", filter=_in_pe_editor())
        def _kb_peditor_buffer_pgup(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            line, col = self._editor_buffer_cursor_to_line_col()
            step = max(1, self._editor_body_h())
            target_line = max(0, line - step)
            target_col = 0 if target_line == 0 else col
            self._editor_buffer_set_cursor_from_line_col(target_line, target_col)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("pagedown", filter=_in_pe_editor())
        def _kb_peditor_buffer_pgdn(event):
            self._editor_buffer_clear_selection()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            line, col = self._editor_buffer_cursor_to_line_col()
            step = max(1, self._editor_body_h())
            last = self._editor_buffer_line_count() - 1
            target_line = min(last, line + step)
            if target_line == last:
                last_len = len(self._editor_buffer_line_text(last))
                target_col = 0 if col < (last_len - col) else last_len
            else:
                target_col = col
            self._editor_buffer_set_cursor_from_line_col(target_line, target_col)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        # --- Shift+arrow / Shift+Home / Shift+End: extend selection ----------
        # Each plants an anchor at the current cursor (if not already set),
        # then performs the same cursor move as the unshifted variant. The
        # selection is the [min(anchor, cursor), max(anchor, cursor)) range.
        @kb.add("s-left",  filter=_in_pe_editor())
        def _kb_peditor_buffer_s_left(event):
            self._editor_buffer_begin_selection_if_needed()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(0, -1)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("s-right", filter=_in_pe_editor())
        def _kb_peditor_buffer_s_right(event):
            self._editor_buffer_begin_selection_if_needed()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(0, +1)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("s-up", filter=_in_pe_editor())
        def _kb_peditor_buffer_s_up(event):
            self._editor_buffer_begin_selection_if_needed()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(-1)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("s-down", filter=_in_pe_editor())
        def _kb_peditor_buffer_s_down(event):
            self._editor_buffer_begin_selection_if_needed()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._kb_peditor_buffer_move_cursor(+1)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("s-home", filter=_in_pe_editor())
        def _kb_peditor_buffer_s_home(event):
            self._editor_buffer_begin_selection_if_needed()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            line, _col = self._editor_buffer_cursor_to_line_col()
            self._editor_buffer_set_cursor_from_line_col(line, 0)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("s-end", filter=_in_pe_editor())
        def _kb_peditor_buffer_s_end(event):
            self._editor_buffer_begin_selection_if_needed()
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            line, _col = self._editor_buffer_cursor_to_line_col()
            self._editor_buffer_set_cursor_from_line_col(
                line, len(self._editor_buffer_line_text(line)))
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("backspace", filter=_in_pe_editor())
        def _kb_peditor_buffer_backspace(event):
            # `self._editor_buffer_backspace_pair` records the transaction (pair vs.
            # normal) before mutating.
            self._editor_buffer_backspace_pair()
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("delete", filter=_in_pe_editor())
        def _kb_peditor_buffer_delete(event):
            # Forward-delete coalesces with neighbouring delete keystrokes; a
            # live selection makes it an atomic selection-replace.
            has_selection = self._editor_buffer_anchor is not None
            self._editor_undo_record(None if has_selection else "delete")
            self._editor_buffer_delete()
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("enter", filter=_in_pe_editor())
        def _kb_peditor_buffer_enter(event):
            self._editor_clear_pending_closers()
            # Newline is its own undoable unit — never coalesces with surrounding
            # typing.
            self._editor_undo_record(None)
            self._editor_buffer_insert("\n")
            self._editor_buffer_scroll_cursor_into_view()
        
        
        # --- Brace assistance ------------------------------------------------
        # Auto-close `{` to `{}` (cursor between), with `}` overtype, `→`
        # step-over, and Backspace pair-delete. State lives in
        # `self._editor_pending_closers`. See docs/launcher.md → profile_editor →
        # Editor mode → Brace assistance for the full lifetime rules. The
        # logic deliberately sits in the key-bound helpers (not in
        # `self._editor_buffer_insert`) so a future paste path inserts text
        # verbatim without ever auto-closing.
        @kb.add("{", filter=_in_pe_editor())
        def _kb_peditor_buffer_open_brace(event):
            self._editor_buffer_open_brace()
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("}", filter=_in_pe_editor())
        def _kb_peditor_buffer_close_brace(event):
            self._editor_buffer_close_brace()
            self._editor_buffer_scroll_cursor_into_view()
        
        
        @kb.add("tab", filter=_in_pe_editor())
        def _kb_peditor_buffer_tab(event):
            self._editor_clear_pending_closers()
            # Focus change forces a coalescing boundary so a follow-up edit in
            # another zone (or back in the buffer) starts a fresh undo entry.
            self._editor_undo_close()
            self._profile_editor_cycle_focus(1)
        
        
        @kb.add("s-tab", filter=_in_pe_editor())
        def _kb_peditor_buffer_stab(event):
            self._editor_clear_pending_closers()
            self._editor_undo_close()
            self._profile_editor_cycle_focus(-1)
        
        
        @kb.add("c-c", filter=_in_pe_editor())
        def _kb_peditor_buffer_copy(event):
            self._kb_peditor_buffer_copy(event)
        
        
        @kb.add("c-x", filter=_in_pe_editor())
        def _kb_peditor_buffer_cut(event):
            self._kb_peditor_buffer_cut(event)
        
        
        @kb.add("c-v", filter=_in_pe_editor())
        def _kb_peditor_buffer_paste(event):
            self._kb_peditor_buffer_paste(event)
        
        
        @kb.add(Keys.BracketedPaste, filter=_in_pe_editor())
        def _kb_peditor_buffer_bracketed_paste(event):
            self._kb_peditor_buffer_bracketed_paste(event)
        
        
        @kb.add("c-z", filter=_in_pe_editor())
        def _kb_peditor_buffer_undo(event):
            self._editor_undo()
            if self._host.app:
                self._host.app.invalidate()
        
        
        @kb.add("c-y", filter=_in_pe_editor())
        def _kb_peditor_buffer_redo(event):
            self._editor_redo()
            if self._host.app:
                self._host.app.invalidate()
        
        
        @kb.add("<any>", filter=_in_pe_editor())
        def _kb_peditor_buffer_any(event):
            data = event.data or ""
            if len(data) != 1 or not data.isprintable():
                return
            # Single printable char: part of a coalescing "insert" run; a live
            # selection makes the type-over an atomic selection-replace.
            has_selection = self._editor_buffer_anchor is not None
            self._editor_undo_record(None if has_selection else "insert")
            self._editor_buffer_insert(data)
            self._editor_buffer_scroll_cursor_into_view()
        
        
        # Profile editor — macro key-capture overlay
        # `eager=True` is intentionally omitted on the ESC binding so
        # prompt_toolkit waits briefly for a follower key — without that
        # disambiguation, Alt+letter (delivered as `escape`, then letter)
        # fires Cancel before the letter arrives.
        @kb.add("escape", filter=_in_frame_keybind())
        def _kb_peditor_keybind_escape(event):
            self._editor_keybind_cancel()
        
        
        # Explicit binding per KNOWN_KEYS entry. Required so prompt_toolkit
        # matches chord forms (("escape", "a") for Alt+a, ("escape", "O", "p")
        # for Numpad 0) before the bare `escape` Cancel — and so the chord
        # doesn't fall through to the wildcard `<any>` on the parent list.
        def _register_overlay_keybinds():
            for mk in macro_keys.KNOWN_KEYS:
                keys = mk.pk_keys if isinstance(mk.pk_keys, tuple) else (mk.pk_keys,)
                def _handler(event, _mk=mk):
                    self._editor_keybind_accept(_mk)
                kb.add(*keys,
                       filter=_in_frame_keybind())(_handler)
        _register_overlay_keybinds()
        
        
        @kb.add("<any>", filter=_in_frame_keybind())
        def _kb_peditor_keybind_any(event):
            """Wildcard fallback for keys outside KNOWN_KEYS — show the standard
            rejection message. (Known keys are handled by the explicit bindings
            registered above, which take precedence over this wildcard.)"""
            match = macro_keys.match_pressed(event)
            if match is not None:
                # Defensive — explicit bindings above should have caught this.
                self._editor_keybind_accept(match)
            else:
                self._editor_keybind_set_error(macro_keys.rejection_reason(event))
        

