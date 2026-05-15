# bridge/launcher/palette.py — shared prompt_toolkit colour palette.
# Single source of truth for cockpit chrome colours used by the in-game
# popup (ingame_menu.py) and the launcher rewrite. The C_* names mirror
# the _MR_* ANSI roles defined in menu_render.sh; see docs/launcher.md.

__all__ = [
    "C_TITLE", "C_ACTIVE", "C_ITEM", "C_BODY", "C_HINT", "C_ACCENT",
    "C_YELLOW", "C_ERR",
    "C_QUOTE", "C_QUOTE_ATTR", "C_HOVER", "C_SELECTED",
    "C_HEADER", "C_SECTION", "C_DIVIDER",
    "C_BUTTON", "C_BUTTON_HOVER", "C_BUTTON_DISABLED",
    "C_LOG_PLAYER_INPUT", "C_LOG_CURSOR",
    "C_LOG_OVERLAY_BG", "C_LOG_OVERLAY_FG", "C_LOG_OVERLAY_HINT",
    "C_LOG_SCRUBBER_FILLED", "C_LOG_SCRUBBER_EMPTY", "C_LOG_SCRUBBER_THUMB",
    "C_LOG_BUTTON_IDLE", "C_LOG_BUTTON_HOVER",
    "_S_VALUE", "_S_LABEL", "_S_GAINED", "_S_LOSS", "_S_TP_BAR",
    "_S_TRACK", "_S_MARKER", "_S_THUMB", "_S_TOTAL", "_S_ARROW",
    "_S_HINT", "_S_PVP", "_S_ALLY", "_S_STAR",
    "PANE_COLORS", "PANE_COLOR_ORDER", "pane_color_hex",
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
C_BUTTON_DISABLED = "fg:#585858 bg:#0f0f0f"   # disabled — dim grey on near-bg

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

# log_view floating overlays (top header + bottom controls). Dark
# translucent-feeling fill so the underlying log dims without losing
# context; ESC hint is dimmer than the regular foreground.
C_LOG_OVERLAY_BG     = "bg:#101418"
C_LOG_OVERLAY_FG     = "fg:#dadada bg:#101418"
C_LOG_OVERLAY_HINT   = "fg:#6c6c6c bg:#101418"

# Scrubber: filled stretch before the playhead, single-cell thumb at the
# playhead, empty stretch after. All share the overlay bg so the bar
# blends into the controls row.
C_LOG_SCRUBBER_FILLED = "fg:#ffaf00 bg:#101418"
C_LOG_SCRUBBER_EMPTY  = "fg:#3a3a3a bg:#101418"
C_LOG_SCRUBBER_THUMB  = "bold fg:#ffffff bg:#101418"

# Rewind / play-pause buttons.
C_LOG_BUTTON_IDLE  = "fg:#dadada bg:#101418"
C_LOG_BUTTON_HOVER = "bold fg:#ffffff bg:#1c2228"

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
