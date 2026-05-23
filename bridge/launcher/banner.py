# bridge/launcher/banner.py — shared MUME Cockpit banner (starfield +
# wordmark). Rendered by both prompt_toolkit surfaces (launcher main page
# and the in-game popup). The art is FROZEN: do not generate it at runtime
# and do not tweak the glyphs or colour map here — callers centre with
# their existing _pad_centre and attach their own hover / mouse handler.
#
# Layout: 5 starfield rows + 1 blank row + 3 MUME rows + 3 COCKPIT rows,
# every row exactly BANNER_WIDTH cells wide.

from palette import (
    C_BANNER_STAR_BRIGHT,
    C_BANNER_STAR_DIM,
    C_BANNER_STAR_MID,
    C_BANNER_WORD,
    C_BANNER_WORD_DIM,
)

BANNER_WIDTH  = 45
BANNER_HEIGHT = 12

# Frozen starfield. Each row in _STAR_GLYPHS is exactly BANNER_WIDTH
# characters; _STAR_COLORS uses the same width with one letter per cell:
#   '.' empty   'D' dim   'M' mid   'B' bright.
_STAR_GLYPHS = [
    '                 ✦ ·          ◦              ',
    '  ✧     ·  ◦  ◦ ✦ ·       ·        ✧         ',
    '◦  ·           ·     ◦ ·    ◦                ',
    '     ✧ ✧   · ◦           ·            ◦      ',
    '   ·     ·  ✦     ·   ·    · ·             · ',
]
_STAR_COLORS = [
    '.................M.M..........M..............',
    '..D.....M..M..D.B.M.......D........D.........',
    'D..M...........M.....D.D....D................',
    '.....B.B...M.M...........M............M......',
    '...M.....D..M.....D...D....D.M.............D.',
]

_STAR_STYLE = {
    '.': "",
    'D': C_BANNER_STAR_DIM,
    'M': C_BANNER_STAR_MID,
    'B': C_BANNER_STAR_BRIGHT,
}

# Wordmark rows (raw — centred to BANNER_WIDTH at render time).
_MUME_WORDS = [
    '█▄ ▄█ █   █ █▄ ▄█ █▀▀▀',
    '█ █ █ █   █ █ █ █ █▀▀ ',
    '█   █ ▀▄▄▄▀ █   █ █▄▄▄',
]
_COCKPIT_WORDS = [
    '▄▀▀▀▄ ▄▀▀▀▄ ▄▀▀▀▄ █ ▄▀  █▀▀▀▄ ▀█▀ ▀▀█▀▀',
    '█     █   █ █     █▀▄   █▀▀▀   █    █  ',
    '▀▄▄▄▀ ▀▄▄▄▀ ▀▄▄▄▀ █  ▀▄ █     ▄█▄   █  ',
]


def _starfield_fragments(glyphs, colors):
    """Merge consecutive cells of equal style into one fragment."""
    fragments = []
    cur_style = None
    cur_text  = []
    for ch, code in zip(glyphs, colors):
        style = _STAR_STYLE[code]
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


def _centred(text):
    pad = max(0, (BANNER_WIDTH - len(text)) // 2)
    return " " * pad + text + " " * max(0, BANNER_WIDTH - pad - len(text))


def banner_lines():
    """Return the 12 banner rows as a list of fragment lists.

    Each entry is a list of (style, text) 2-tuples whose visible widths sum
    to BANNER_WIDTH. Callers centre the row horizontally with their existing
    _pad_centre helper and attach the per-row hover / mouse handler — the
    same shape as the old _MUME_LINES / _COCKPIT_LINES call sites.
    """
    lines = []
    for glyphs, colors in zip(_STAR_GLYPHS, _STAR_COLORS):
        lines.append(_starfield_fragments(glyphs, colors))
    lines.append([("", " " * BANNER_WIDTH)])
    for row in _MUME_WORDS:
        lines.append([(C_BANNER_WORD, _centred(row))])
    for row in _COCKPIT_WORDS:
        lines.append([(C_BANNER_WORD_DIM, _centred(row))])
    return lines
