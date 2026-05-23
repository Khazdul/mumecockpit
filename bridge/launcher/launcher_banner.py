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
# The starfield is held as data (a list of star records). `STARS` stays the
# human-editable source of truth for positions; an internal animated layer
# is derived from it at import time. Open-field stars twinkle as a pure
# function of the monotonic clock — slow, randomized periods and phases per
# star so the field shimmers asynchronously. Stars tucked inside a wordmark
# stay fully static so they never compete with the logo. The module has no
# prompt_toolkit / app dependency: it's pure data + math, and the launcher
# drives redraws separately.

import math
import random
import time

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
# A star listed inside a wordmark column span — currently only (5,28) in
# the MUME band — is an intentional "star behind the text": the position
# is verified to be a gap in the wordmark, so the star paints into a blank
# cell and never overwrites a glyph cell. Such stars are detected
# geometrically (see `_is_embedded`) and rendered static.
STARS = [
    (0,  8, "✧", "BRIGHT"), (0, 22, "✧", "MID"), (0, 35, "·", "DIM"), (0, 41, "·", "DIM"),
    (1,  3, "·", "DIM"), (1, 11, "✦", "MID"), (1, 19, "·", "DIM"), (1, 27, "◦", "MID"),
    (2,  0, "◦", "DIM"), (2, 14, "·", "MID"), (2, 33, "·", "DIM"),
    (3,  6, "·", "DIM"), (3, 17, "✧", "MID"), (3, 29, "·", "DIM"),
    (4,  9, "·", "DIM"), (4, 31, "◦", "DIM"),
    (5,  5, "·", "DIM"), (5, 28, "·", "DIM"), (5, 40, "✦", "MID"),   # MUME row 1
    (6, 42, "·", "DIM"),                                             # MUME row 2
    (7,  2, "◦", "DIM"), (7, 37, "·", "MID"),                        # MUME row 3
    (8,  1, "·", "DIM"),                                             # COCKPIT row 1
    (9, 43, "·", "DIM"),                                             # COCKPIT row 2
]

# Twinkle: open-field stars sit at their base tier most of the cycle and
# briefly pulse ±1 tier when the sine wave crosses the peak threshold.
# Slow randomized periods keep the field shimmering asynchronously.
_TWINKLE_PERIOD_MIN = 6.0
_TWINKLE_PERIOD_MAX = 16.0
_TWINKLE_PEAK       = 0.82

# Brightness tiers as ints — embedded stars hold their base tier, open-field
# stars clamp into this range after applying the wave-driven offset.
_TIER_DIM    = 0
_TIER_MID    = 1
_TIER_BRIGHT = 2

_TIER_TO_INT = {"DIM": _TIER_DIM, "MID": _TIER_MID, "BRIGHT": _TIER_BRIGHT}
_INT_TO_STYLE = (C_BANNER_STAR_DIM, C_BANNER_STAR_MID, C_BANNER_STAR_BRIGHT)

# Only four-point-star glyphs swap, and only at the bright peak. The dot
# glyphs (· ◦) hold their shape — only their brightness pulses.
_SWAP_GLYPH = {"✦": "✧", "✧": "✦"}


def _is_embedded(row, col):
    """True if (row, col) lands inside a wordmark column span — those
    stars stay static so they don't compete with the logo glyphs."""
    if 5 <= row <= 7 and 11 <= col <= 32:
        return True
    if 8 <= row <= 10 and 3 <= col <= 41:
        return True
    return False


def _build_animated_stars():
    """Derive the animation layer from STARS. Open-field stars get a
    random period and phase (no explicit seed — each launcher session
    shimmers slightly differently); embedded stars get inert values."""
    out = []
    for row, col, glyph, tier in STARS:
        base_tier = _TIER_TO_INT[tier]
        if _is_embedded(row, col):
            out.append((row, col, glyph, base_tier, True, 0.0, 0.0))
        else:
            period = random.uniform(_TWINKLE_PERIOD_MIN, _TWINKLE_PERIOD_MAX)
            phase  = random.uniform(0.0, 1.0)
            out.append((row, col, glyph, base_tier, False, period, phase))
    return out


_ANIMATED_STARS = _build_animated_stars()


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


def banner_lines(now=None):
    """Return the 11 banner rows as a list of fragment lists.

    Same output shape as `banner.banner_lines()`: each row is a list of
    (style, text) 2-tuples whose visible widths sum to `BANNER_WIDTH`.
    Callers centre the row horizontally with their existing `_pad_centre`
    helper and attach the per-row hover / mouse handler.

    `now` (monotonic seconds) drives the twinkle; defaults to
    `time.monotonic()`. Pure function of the clock — no mutable per-frame
    state, so tests can pin a specific instant by passing `now` in.
    """
    if now is None:
        now = time.monotonic()
    grid = [[(" ", "") for _ in range(BANNER_WIDTH)]
            for _ in range(BANNER_HEIGHT)]
    _paint_word(grid, _MUME_WORDS,    _MUME_ROW0,    C_BANNER_WORD)
    _paint_word(grid, _COCKPIT_WORDS, _COCKPIT_ROW0, C_BANNER_WORD_DIM)
    for row, col, glyph, base_tier, embedded, period, phase in _ANIMATED_STARS:
        if embedded:
            grid[row][col] = (glyph, _INT_TO_STYLE[base_tier])
            continue
        wave = math.sin(2.0 * math.pi * (now / period + phase))
        if wave > _TWINKLE_PEAK:
            offset = 1
        elif wave < -_TWINKLE_PEAK:
            offset = -1
        else:
            offset = 0
        tier = base_tier + offset
        if tier < 0:
            tier = 0
        elif tier > 2:
            tier = 2
        if offset > 0 and glyph in _SWAP_GLYPH:
            glyph = _SWAP_GLYPH[glyph]
        grid[row][col] = (glyph, _INT_TO_STYLE[tier])
    return [_row_fragments(row) for row in grid]
