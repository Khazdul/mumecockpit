# bridge/launcher/launcher_banner.py — dedicated launcher main-page banner.
#
# Static starfield + wordmark banner used ONLY by the launcher's main page.
# The shared `banner.py` module (used by the in-game popup and rendered in
# plain white by the tt++ welcome screen) is intentionally left alone — the
# launcher banner is decoupled so it can evolve independently. As a
# deliberate consequence, the MUME and COCKPIT wordmark strings below are
# copied verbatim from `banner.py`; the wordmark is frozen art and the
# duplication is the price of keeping the two surfaces independent.
#
# The starfield is held as data (a list of star records). The renderer here
# is static, but the structure is intentionally plain and easily iterated so
# a future animation layer can mutate each record's tier / glyph per frame.

from palette import (
    C_BANNER_STAR_BRIGHT,
    C_BANNER_STAR_DIM,
    C_BANNER_STAR_MID,
    C_BANNER_WORD,
    C_BANNER_WORD_DIM,
)

BANNER_WIDTH  = 45
BANNER_HEIGHT = 11  # 5 starfield rows + 3 MUME rows + 3 COCKPIT rows

# Wordmark rows — copied verbatim from banner.py (see module docstring).
# MUME wordmark, when centred to BANNER_WIDTH, spans cols 11-32.
_MUME_WORDS = [
    '█▄ ▄█ █   █ █▄ ▄█ █▀▀▀',
    '█ █ █ █   █ █ █ █ █▀▀ ',
    '█   █ ▀▄▄▄▀ █   █ █▄▄▄',
]
# COCKPIT wordmark, when centred to BANNER_WIDTH, spans cols 3-41.
_COCKPIT_WORDS = [
    '▄▀▀▀▄ ▄▀▀▀▄ ▄▀▀▀▄ █ ▄▀  █▀▀▀▄ ▀█▀ ▀▀█▀▀',
    '█     █   █ █     █▀▄   █▀▀▀   █    █  ',
    '▀▄▄▄▀ ▀▄▄▄▀ ▀▄▄▄▀ █  ▀▄ █     ▄█▄   █  ',
]

_MUME_ROW0    = 5  # MUME wordmark starts at row 5
_COCKPIT_ROW0 = 8  # COCKPIT wordmark starts at row 8

# Star records: (row, col, glyph, tier).
#   row    0–10     (BANNER_HEIGHT)
#   col    0–44     (BANNER_WIDTH)
#   tier   "DIM" | "MID" | "BRIGHT"  →  C_BANNER_STAR_*
#   glyph  · ◦ ✦ ✧
# Stars listed inside a wordmark column span — (5,28), (6,16) in MUME and
# (8,26), (8,32), (9,12), (10,36) in COCKPIT — are intentional "stars
# behind the text": each position is verified to be a gap in the wordmark,
# so the star paints into a blank cell and never overwrites a glyph cell.
STARS = [
    (0,  8, "✧", "BRIGHT"), (0, 22, "✧", "MID"), (0, 35, "·", "DIM"), (0, 41, "·", "DIM"),
    (1,  3, "·", "DIM"), (1, 11, "✦", "MID"), (1, 19, "·", "DIM"), (1, 27, "◦", "MID"), (1, 38, "·", "DIM"),
    (2,  0, "◦", "DIM"), (2, 14, "·", "MID"), (2, 24, "✧", "BRIGHT"), (2, 33, "·", "DIM"),
    (3,  6, "·", "DIM"), (3, 17, "✧", "MID"), (3, 29, "·", "DIM"), (3, 40, "✦", "MID"),
    (4,  9, "·", "DIM"), (4, 21, "·", "MID"), (4, 31, "◦", "DIM"), (4, 43, "·", "DIM"),
    (5,  5, "·", "DIM"), (5, 28, "·", "DIM"), (5, 40, "✦", "MID"),   # MUME row 1
    (6,  8, "✧", "MID"), (6, 16, "·", "DIM"), (6, 42, "·", "DIM"),   # MUME row 2
    (7,  2, "◦", "DIM"), (7, 37, "·", "MID"),                        # MUME row 3
    (8,  1, "·", "DIM"), (8, 26, "·", "DIM"), (8, 32, "·", "DIM"),   # COCKPIT row 1
    (9, 12, "·", "DIM"), (9, 43, "·", "DIM"),                        # COCKPIT row 2
    (10, 36, "·", "DIM"),                                            # COCKPIT row 3
]

_TIER_STYLE = {
    "DIM":    C_BANNER_STAR_DIM,
    "MID":    C_BANNER_STAR_MID,
    "BRIGHT": C_BANNER_STAR_BRIGHT,
}


def _paint_word(grid, words, row0, style):
    """Paint a centred wordmark block into the grid — non-space cells only."""
    for r, line in enumerate(words):
        pad = (BANNER_WIDTH - len(line)) // 2
        for c, ch in enumerate(line):
            if ch != " ":
                grid[row0 + r][pad + c] = (ch, style)


def _row_fragments(row):
    """Merge consecutive cells of equal style into (style, text) fragments."""
    fragments = []
    cur_style = None
    cur_text  = []
    for ch, style in row:
        if style == cur_style:
            cur_text.append(ch)
        else:
            if cur_text:
                fragments.append((cur_style, "".join(cur_text)))
            cur_style = style
            cur_text  = [ch]
    if cur_text:
        fragments.append((cur_style, "".join(cur_text)))
    return fragments


def banner_lines():
    """Return the 11 banner rows as a list of fragment lists.

    Same output shape as `banner.banner_lines()`: each row is a list of
    (style, text) 2-tuples whose visible widths sum to `BANNER_WIDTH`.
    Callers centre the row horizontally with their existing `_pad_centre`
    helper and attach the per-row hover / mouse handler.
    """
    grid = [[(" ", "") for _ in range(BANNER_WIDTH)]
            for _ in range(BANNER_HEIGHT)]
    _paint_word(grid, _MUME_WORDS,    _MUME_ROW0,    C_BANNER_WORD)
    _paint_word(grid, _COCKPIT_WORDS, _COCKPIT_ROW0, C_BANNER_WORD_DIM)
    for row, col, glyph, tier in STARS:
        grid[row][col] = (glyph, _TIER_STYLE[tier])
    return [_row_fragments(row) for row in grid]
