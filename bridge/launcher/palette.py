# bridge/launcher/palette.py — shared prompt_toolkit colour palette.
# Single source of truth for cockpit chrome colours used by the in-game
# popup (ingame_menu.py) and the launcher rewrite. The C_* names mirror
# the _MR_* ANSI roles defined in menu_render.sh; see docs/launcher.md.

__all__ = [
    "C_TITLE", "C_ACTIVE", "C_ITEM", "C_BODY", "C_HINT", "C_ACCENT",
    "C_YELLOW", "C_ERR", "C_DANGER",
    "C_QUOTE", "C_QUOTE_ATTR", "C_HOVER", "C_SELECTED",
    "C_HEADER", "C_SECTION", "C_DIVIDER",
    "C_BUTTON", "C_BUTTON_HOVER", "C_BUTTON_DISABLED",
    "C_BUTTON_INACTIVE", "C_BUTTON_ACTIVE_UNFOCUSED",
    "C_BUTTON_ACTIVE_FOCUSED",
    "C_OK", "C_CURSOR_CELL", "C_PANE_OFF", "C_NOTE",
    "C_BANNER_WORD", "C_BANNER_WORD_DIM",
    "C_BANNER_STAR_DIM", "C_BANNER_STAR_MID", "C_BANNER_STAR_BRIGHT",
    "C_LOG_PLAYER_INPUT", "C_LOG_CURSOR",
    "C_LOG_STRIP_PLAYED", "C_LOG_STRIP_REMAINING", "C_LOG_STRIP_MARKER",
    "C_LOG_EVENT_MARK",
    "C_LOG_BOX_FRAME", "C_LOG_BOX_FG", "C_LOG_BOX_DIM", "C_LOG_BOX_BTN_HOVER",
    "C_SPOTLIGHT_BOX_FRAME", "C_SPOTLIGHT_NAME", "C_SPOTLIGHT_TYPE",
    "C_SPOTLIGHT_COUNT",
    "C_SPOTLIGHT_ARROW", "C_SPOTLIGHT_LABEL", "C_SPOTLIGHT_BAR",
    "spotlight_box_bg",
    "_S_VALUE", "_S_LABEL", "_S_GAINED", "_S_LOSS", "_S_TP_BAR",
    "_S_TRACK", "_S_MARKER", "_S_THUMB", "_S_TOTAL", "_S_ARROW",
    "_S_HINT", "_S_PVP", "_S_ALLY", "_S_STAR",
    "PANE_COLORS", "PANE_COLOR_ORDER", "pane_color_hex",
    "PANE_COLOR_LABELS", "pane_color_label",
    "TIMERS_COLOR_ORDER", "timers_color_hex", "timers_color_index",
    "TTPP_COLOR_STYLES", "TTPP_COLOR_NAMES",
    "C_SYN_COMMAND", "C_SYN_BRACE", "C_SYN_DELIM", "C_SYN_VAR", "C_SYN_CODE",
    "C_SYN_BRACE_MATCH",
]

# ---------------------------------------------------------------------------
# Colour palette (translated from menu_render.sh _MR_* ANSI constants)
# ---------------------------------------------------------------------------
C_TITLE   = "bold fg:#00d7d7"   # _MR_TITLE  — cyan
C_ACTIVE  = "bold fg:#ffffff"   # _MR_ACTIVE — bright white
C_ITEM    = "fg:#bcbcbc"        # _MR_ITEM   — colour 250
C_BODY    = "fg:#8a8a8a"        # _MR_BODY   — colour 245
C_HINT    = "fg:#585858"        # _MR_HINT   — dim, colour 240
C_ACCENT  = "bold fg:#ffaf00"   # _MR_ACCENT — colour 214, bold
C_YELLOW  = "bold fg:#ffd75f"   # _MR_YELLOW
C_ERR     = "bold fg:#ff5f5f"   # _MR_ERR
C_DANGER  = "fg:#a04030"        # muted red — inline validation errors

# Launcher-specific roles
C_QUOTE      = "italic fg:#8a8a8a"  # _MR_QUOTE      — italic, colour 245
C_QUOTE_ATTR = "fg:#87af87"         # _MR_QUOTE_ATTR — sage green, colour 108
C_HOVER      = "fg:#dadada"         # between C_ITEM and C_ACTIVE — mouse hover
C_SELECTED   = "fg:#000000 bg:#bcbcbc"   # active sidebar filter — black on light grey

# Flat-button states. Backgrounds are the distinguishing element (no border),
# matching the History → Options widget design. Kept near-black so the widget
# blends into the launcher backdrop; only the cursor state (C_SELECTED) is
# allowed to pop. Hover is a subtle lift over normal; disabled is barely
# distinguishable from the surrounding empty space.
C_BUTTON          = "fg:#bcbcbc bg:#1a1a1a"   # normal flat button
C_BUTTON_HOVER    = "fg:#bcbcbc bg:#2a2a2a"   # mouse-hover, non-cursor
C_BUTTON_DISABLED = "fg:#585858"              # disabled — dim grey, no bg block

# Three-state button colour grammar — used by the profile editor's kind
# column, the MENU/EDITOR mode toggle, the entry-list cursor row, and the
# detail-panel frame borders. A uniform background-driven indicator that
# replaces the older mix of bold/underline and reverse-band styles.
#
#   Inactive (not selected)        → C_BUTTON_INACTIVE  (no bg fill — falls
#                                    through to the terminal background,
#                                    matching C_BUTTON_DISABLED)
#   Active, owning zone unfocused  → C_BUTTON_ACTIVE_UNFOCUSED  (= C_SELECTED)
#   Active, owning zone focused    → C_BUTTON_ACTIVE_FOCUSED    (amber bg)
#
# The hover state for inactive buttons reuses C_BUTTON_ACTIVE_UNFOCUSED so
# the preview matches the unfocused-but-selected appearance — a single
# motion of attention rather than two competing styles.
C_BUTTON_INACTIVE         = "fg:#bcbcbc"
C_BUTTON_ACTIVE_UNFOCUSED = "fg:#000000 bg:#bcbcbc"
C_BUTTON_ACTIVE_FOCUSED   = "fg:#000000 bg:#ffaf00"

# Cursor grammar — two modes of "focused" indicator across menu chrome:
#
#   - Focused cursor on a filled button → gold *background*
#     (C_BUTTON_ACTIVE_FOCUSED).
#   - Focused cursor on a swatch / checkbox cell → gold *foreground*
#     (C_CURSOR_CELL) applied to the `[ ]` glyphs only; the swatch keeps
#     its own colour. Palette / swatch zones are gold-or-nothing — they
#     have no unfocused carry-over (the cursor index is per-zone scratch,
#     not a persistent selection). The same C_CURSOR_CELL token also
#     paints the gold `<<` / `>>` arrows on selected menu rows (menu_row
#     in menu_chrome.py), so the swatch brackets and the menu-row arrows
#     share one cursor-mark hue.
#   - Selected but owning zone unfocused → grey background
#     (C_BUTTON_ACTIVE_UNFOCUSED). Applies only to persistent selections
#     (active kind, active mode, edited list row); never to palette/swatch
#     cursors.
#   - Persistent "active / selected" marker → green (C_OK). Used for the
#     profile-table ✓ and similar always-on indicators; never gold.
C_OK          = "bold fg:#7ac46f"
C_CURSOR_CELL = "bold fg:#ffaf00"

# Advisory / read-only note lines (e.g. the popup Scripts view's read-only
# subtitle). Muted dark gold — clearly gold but darker than the C_CURSOR_CELL
# arrows so it reads as a note without competing with the cursor.
C_NOTE        = "fg:#b8923c"

# Panes-grid dim colour. Painted on every cell (label, checkbox, swatch) of
# a disabled pane row so the row reads as unmistakably "off" against the
# enabled rows' bright checkboxes and coloured swatches. One step darker
# than C_HINT (#585858) — the gap is the whole point.
C_PANE_OFF    = "fg:#3a3a3a"

# ---------------------------------------------------------------------------
# Banner — shared starfield + wordmark used by the launcher main page
# (launcher.py) and the in-game popup (ingame_menu.py). See launcher_banner.py.
# ---------------------------------------------------------------------------
C_BANNER_WORD        = "fg:#00d0d0"   # wordmark line 1 (MUME)
C_BANNER_WORD_DIM    = "fg:#0a9a9c"   # wordmark line 2 (COCKPIT)
C_BANNER_STAR_DIM    = "fg:#1f595b"   # distant stars
C_BANNER_STAR_MID    = "fg:#2f9092"   # mid stars
C_BANNER_STAR_BRIGHT = "fg:#74e8e8"   # bright stars

# ---------------------------------------------------------------------------
# Statistics-frame palette (mockup-driven; isolated from the other frames so
# the main/options/scripts palettes are unaffected).
# ---------------------------------------------------------------------------
C_HEADER   = "bold fg:#ffd060"  # gold ◆ STATISTICS banner only
C_SECTION  = "bold fg:#008787"  # muted cyan section titles (KILLS, PvPs, …, XP/h, TP/h)
C_DIVIDER  = C_HINT             # muted gray section rules and chart frame strokes
_S_VALUE   = "fg:#ffffff"       # data values, names
_S_LABEL   = "fg:#909090"       # axis numbers, column headers
_S_GAINED  = "fg:#6fe060"       # XP bar gained portion, XP/h bars, XP-linjal label
_S_LOSS    = "fg:#e03c3c"       # XP-linjal loss band + bracket label (negative session gain)
_S_TP_BAR  = "fg:#ffc847"       # TP/h bars
_S_TRACK   = "fg:#1f1f1f"       # scrollbar track, untraversed bar (full-block █)
_S_MARKER  = "fg:#1f1f1f bg:#1f1f1f"  # XP-linjal ▌▐ markers — bg matches row-2 fill
_S_THUMB   = "fg:#707070"       # scrollbar thumb (mid grey)
_S_TOTAL   = "bold fg:#b0b0b0"  # sticky Total rows
_S_ARROW   = "fg:#b0b0b0"       # arrow brackets around XP-gain label
_S_HINT    = "fg:#5c5c5c"       # footer hints
_S_PVP     = "fg:#ff5f5f"       # ⚔ glyph before PvPs data rows
_S_ALLY    = "fg:#00d7d7"       # ♦ glyph before ALLIES data rows
_S_STAR    = "fg:#ffd060"       # ★ glyph before ACHIEVEMENTS data rows

# log_view (chain log player) — player commands rendered in a quiet
# grey with a faint light-cyan tint so they're visually distinct from
# server output but never compete with it for attention.
C_LOG_PLAYER_INPUT = "fg:#86a0a0"

# log_view pause-mode cursor row: subtle background only, no fg. Combined
# with each fragment's existing fg in the renderer so colours survive.
C_LOG_CURSOR = "bg:#303030"

# log_view playback chrome (right-edge vertical strip + floating control
# box). De-cyaned so the chrome blends with the terminal canvas rather
# than reading as a panel: blank cells are painted in the resolved
# `_terminal_bg` (ADR 0099), the played/unplayed track is a grey ramp,
# and only the playhead + play/pause control carry the C_ACCENT gold hue.
#
# Right-edge strip. The played portion is a light-grey full block, the
# unplayed portion a dark-grey full block, and the playhead a gold
# half-block sitting precisely on the boundary (sub-row precise). The
# marker glyphs are a hair brighter than the unplayed block so the
# A/D/K/L letters + ► stay legible against it.
C_LOG_STRIP_PLAYED    = "fg:#9a9a9a"   # played portion, light-grey full block
C_LOG_STRIP_REMAINING = "fg:#242424"   # unplayed portion, dark-grey full block
C_LOG_STRIP_MARKER    = "#ffaf00"      # gold playhead (= C_ACCENT hue); half-block, bg set per side at render
C_LOG_EVENT_MARK      = "fg:#4d4d4d"   # event letters + ► (dark grey, a hair above the unplayed block for glyph legibility)

# Floating control box. The frame glyphs and labels are quiet greys; the
# box paints every cell in `_terminal_bg` (no panel tint), so only the
# gold play/pause control and the hovered-button lift stand out.
C_LOG_BOX_FRAME       = "fg:#585858"   # box ┌─┐│└┘ glyphs
C_LOG_BOX_FG          = "fg:#9a9a9a"   # box labels (Rewind / Play)
C_LOG_BOX_DIM         = "fg:#6f6f6f"   # box time field
C_LOG_BOX_BTN_HOVER   = "bold fg:#dde4e0 bg:#242a27"  # hovered button, subtle lift on a dark canvas

# Spotlight info box (log_view spotlight-mode floating overlay). A dark,
# thin-line framed box matching the playback control box (same #585858
# frame, same terminal-bg cell fill) — discreet chrome rather than a
# bright title card. Foreground roles only; the occluding background is
# composed at runtime against the resolved `_terminal_bg` via
# spotlight_box_bg() so every box cell fully covers the scrolling log:
#   • C_SPOTLIGHT_BOX_FRAME — thin-line ┌─┐│└┘ glyphs (= control box).
#   • C_SPOTLIGHT_NAME      — character name; light grey, bold — a readable
#                             context anchor, subordinate to the gold label.
#   • C_SPOTLIGHT_TYPE      — event-type line (PvP kill / Death / …); quiet
#                             metadata grey (= count), below the name.
#   • C_SPOTLIGHT_COUNT     — "N of M" counter; quiet metadata grey.
#   • C_SPOTLIGHT_ARROW     — ◄ ► nav glyphs; muted gold.
#   • C_SPOTLIGHT_LABEL     — event label; the box's primary line — muted gold
#                             (= arrows), bold.
#   • C_SPOTLIGHT_BAR       — countdown bar caps + fill; very dark grey, in
#                             the external row below the box.
C_SPOTLIGHT_BOX_FRAME = "fg:#585858"
C_SPOTLIGHT_NAME      = "bold fg:#bcbcbc"
C_SPOTLIGHT_TYPE      = "fg:#8a8a8a"   # event-type line; muted grey (= count)
C_SPOTLIGHT_COUNT     = "fg:#8a8a8a"
C_SPOTLIGHT_ARROW     = "fg:#c79a4a"
C_SPOTLIGHT_LABEL     = "bold fg:#c79a4a"
C_SPOTLIGHT_BAR       = "fg:#333333"


def spotlight_box_bg(terminal_bg):
    """Spotlight info-box cell background — the occlusion fill painted
    under every box cell (frame, text, pad, bar, blank rows) so the box
    fully covers the scrolling log behind it. `terminal_bg` is the
    detected `#rrggbb` or `None`; falls back to `#000000` when detection
    is unavailable. Composed with each foreground role at launcher
    startup. Companion to the pane_color_hex() palette helper."""
    bg = terminal_bg or "#000000"
    return f"bg:{bg}"

# ---------------------------------------------------------------------------
# Per-pane background palette
# ---------------------------------------------------------------------------
# Named tints for the cockpit's right-column panes. Selected per pane in the
# launcher Options (Panes submenu) and the in-game popup. Stored by name in
# bridge/runtime/startup.conf under pane_color_<name>. None means "no bg
# override" — the terminal default shows through.
#
# Keep this mirrored with the case statement in
# bridge/launcher/open_pane.sh `_pane_bg_for`.
PANE_COLORS = {
    "black":  None,        # terminal default, no tmux bg override
    "red":    "#1A0E0E",
    "green":  "#0E1A0E",
    "blue":   "#0E141C",
    "grey":   "#161616",
    "orange": "#1C140A",
    "purple": "#16101C",
}
# Stable presentation order for radio rows.
PANE_COLOR_ORDER = ["black", "red", "green", "blue", "grey", "orange", "purple"]


def pane_color_hex(name):
    """Resolve a pane-colour name to its hex string, or None for the terminal
    default. Unknown names fall back to black (i.e. None)."""
    return PANE_COLORS.get(name, None) if name in PANE_COLORS else None


# Display labels decoupled from the stored colour names. The "black" column is
# really "terminal default" (PANE_COLORS["black"] is None → open_pane.sh maps
# it to bg=default), so it shows the terminal background rather than literal
# black; label it "None" to match (no bg override). Names absent from this map
# fall back to their capitalised key. The stored value and startup.conf schema
# keep using the "black" key — only the presentation changes.
PANE_COLOR_LABELS = {"black": "None"}


def pane_color_label(name):
    """Display label for a pane-colour name. Falls back to the capitalised
    name for any colour without an explicit label override."""
    return PANE_COLOR_LABELS.get(name, name.capitalize())


# ---------------------------------------------------------------------------
# Timers-pane group palette
# ---------------------------------------------------------------------------
# Ordered (name, hex) swatches for the launcher / popup "Timers layout" grid.
# The first six entries are exactly the six group default colours (so every
# type's default lands on a real swatch — spell→Blue, buff→Green, debuff→Red,
# stored→Magenta, blind→Cyan, charm→Violet); the final two are additions at
# the same saturation / brightness for users who want to recolour a group.
# Stored in timers_layout.conf as raw #rrggbb under timers_<type>_color; the
# timers pane (bridge/panes/timers_pane.py) reads the hex directly.
TIMERS_COLOR_ORDER = [
    ("Blue",    "#66b2ff"),
    ("Green",   "#00d900"),
    ("Red",     "#d90000"),
    ("Magenta", "#ff66ff"),
    ("Cyan",    "#00cccc"),
    ("Violet",  "#B388FF"),
    ("Orange",  "#ff9933"),
    ("Yellow",  "#e8c84d"),
]


def timers_color_hex(index):
    """Resolve a Timers-grid colour index to its #rrggbb string. Out-of-range
    indices clamp to the first entry (the grid's default column)."""
    if 0 <= index < len(TIMERS_COLOR_ORDER):
        return TIMERS_COLOR_ORDER[index][1]
    return TIMERS_COLOR_ORDER[0][1]


def timers_color_index(hex_str):
    """Map a stored #rrggbb string back to its Timers-grid column index, case-
    insensitively. Unknown / empty values fall back to index 0, mirroring the
    panes grid's unknown-colour-to-first-column rule."""
    want = (hex_str or "").lower()
    for i, (_name, hx) in enumerate(TIMERS_COLOR_ORDER):
        if hx.lower() == want:
            return i
    return 0


# ---------------------------------------------------------------------------
# tt++ named-color palette used by the Highlights tab in the profile editor.
#
# Maps the tt++ color-name strings users write in `#highlight {pattern} {color}`
# to prompt_toolkit style strings. The named-color form (`fg:ansiwhite` etc.)
# adapts to the terminal palette so the swatches look right wherever cockpit
# runs. Skips `ebony` and `dark <colour>` — invisible on a dark terminal.
#
# The Highlights editor renders each swatch's name *in its own colour* using
# this map, and the Highlights list panel renders the `Color` column the same
# way. Custom values (anything not in this dict) round-trip through the parser
# but render in the default text colour and surface in a "Custom" slot below
# the palette grid for safe revert.
# ---------------------------------------------------------------------------
TTPP_COLOR_STYLES = {
    "white":          "fg:ansiwhite",
    "gray":           "fg:ansibrightblack",
    "red":            "fg:ansired",
    "light red":      "fg:ansibrightred",
    "yellow":         "fg:ansiyellow",
    "light yellow":   "fg:ansibrightyellow",
    "green":          "fg:ansigreen",
    "light green":    "fg:ansibrightgreen",
    "cyan":           "fg:ansicyan",
    "light cyan":     "fg:ansibrightcyan",
    "blue":           "fg:ansiblue",
    "light blue":     "fg:ansibrightblue",
    "magenta":        "fg:ansimagenta",
    "light magenta":  "fg:ansibrightmagenta",
}

# Stable lookup set — used by the editor to decide whether an entry's body
# value is "in the palette" (cursor lands on its swatch) or a custom value
# (rendered as plain text, also surfaced in the Custom slot).
TTPP_COLOR_NAMES = frozenset(TTPP_COLOR_STYLES.keys())

# ---------------------------------------------------------------------------
# tt++ syntax-highlight palette (profile editor — Editor mode).
#
# Five muted hues painted on top of the editor body's base C_ITEM, by the
# lexical tokeniser in ttpp_syntax.py. First-pass values meant to be tuned
# after live use — they read as "coloured but not loud" against the
# dark backdrop and compose cleanly with the current-line tint and the
# C_SELECTED selection band.
# ---------------------------------------------------------------------------
C_SYN_COMMAND = "fg:#5fafaf"   # `#command`           — muted teal
C_SYN_BRACE   = "fg:#8290a0"   # `{` and `}`          — slate
C_SYN_DELIM   = "fg:#c8a060"   # `;`                  — dim amber
C_SYN_VAR     = "fg:#87af87"   # `$x`, `${x}`, `&x`,
                               # `%1`, `%*`           — sage green
C_SYN_CODE    = "fg:#9b86b3"   # `<088>`, `\n`, `\xFF` — muted lavender

# Painted on the brace at the cursor and its partner when the cursor is
# adjacent to a structural `{`/`}`. A subtle background lift on both
# partner cells, composed under the selection band and over the current-
# line tint. Editor mode only; see docs/launcher.md → profile_editor.
C_SYN_BRACE_MATCH = "fg:#dadada bg:#3a3a3a"
