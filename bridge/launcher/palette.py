# bridge/launcher/palette.py — shared prompt_toolkit colour palette.
# Single source of truth for cockpit chrome colours used by the in-game
# popup (ingame_menu.py) and the launcher rewrite. The C_* names mirror
# the _MR_* ANSI roles defined in menu_render.sh; see docs/launcher.md.

__all__ = [
    "C_TITLE", "C_ACTIVE", "C_ITEM", "C_BODY", "C_HINT", "C_ACCENT",
    "C_YELLOW", "C_ERR",
    "C_QUOTE", "C_QUOTE_ATTR", "C_HOVER", "C_HOVER_TITLE",
    "C_HEADER", "C_SECTION", "C_DIVIDER",
    "_S_VALUE", "_S_LABEL", "_S_GAINED", "_S_LOSS", "_S_TP_BAR",
    "_S_TRACK", "_S_MARKER", "_S_THUMB", "_S_TOTAL", "_S_ARROW",
    "_S_HINT", "_S_PVP", "_S_ALLY", "_S_STAR",
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
C_HOVER_TITLE = "bold fg:#5fffff"   # between C_TITLE and C_ACTIVE
                                    # — hover variant for title/section cells

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
