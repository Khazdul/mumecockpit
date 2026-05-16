# bridge/launcher/credits.py — end-of-reel scrolling credits content.
#
# Pure library: given the loaded spotlights of a SpotlightReel, produces
# the flat list of wrapped strings that the launcher's `credits` frame
# scrolls upward on a black canvas. One spotlight event becomes one
# narrative sentence chosen deterministically from a per-kind template
# list; events are grouped by character with a chapter header per
# character, ordered by each character's oldest event. See ADR 0080 and
# docs/launcher.md "credits frame".

from __future__ import annotations

import hashlib
import textwrap
from datetime import datetime

from spotlights import Spotlight


# ---------------------------------------------------------------------------
# Day-of-month → ordinal English word
# ---------------------------------------------------------------------------
_ORDINAL_WORDS = {
    1:  "first",        2:  "second",       3:  "third",        4:  "fourth",
    5:  "fifth",        6:  "sixth",        7:  "seventh",      8:  "eighth",
    9:  "ninth",        10: "tenth",        11: "eleventh",     12: "twelfth",
    13: "thirteenth",   14: "fourteenth",   15: "fifteenth",    16: "sixteenth",
    17: "seventeenth",  18: "eighteenth",   19: "nineteenth",   20: "twentieth",
    21: "twenty-first", 22: "twenty-second", 23: "twenty-third", 24: "twenty-fourth",
    25: "twenty-fifth", 26: "twenty-sixth", 27: "twenty-seventh", 28: "twenty-eighth",
    29: "twenty-ninth", 30: "thirtieth",    31: "thirty-first",
}


# ---------------------------------------------------------------------------
# Per-kind narrative templates
# ---------------------------------------------------------------------------
_PKILL_TEMPLATES = [
    "On the {date} you boldly slayed {target}.",
    "On the {date}, after an intense and largely accidental battle, you slayed {target}.",
    "On the {date} you reduced {target} to a thoughtful silence.",
    "On the {date} {target} learned, briefly, that you do not bluff.",
    "On the {date} you sent {target} on a long and contemplative journey.",
    "On the {date} you ended the brief but enthusiastic career of {target}.",
]

_DEATH_TEMPLATES = [
    "On the {date} your luck ran out and you ended up in the Halls of Mandos.",
    "On the {date} you discovered, with some surprise, that the situation was in fact fatal.",
    "On the {date} you misjudged things with admirable enthusiasm and terminal consequences.",
    "On the {date} the world reminded you, firmly, of your own mortality.",
    "On the {date} you became, however briefly, very dead.",
    "On the {date} your strategy of \"they probably won't all hit me\" was conclusively disproven.",
]

_LEVEL_UP_TEMPLATES = [
    "On the {date} you arrived, slightly out of breath, at level {level}.",
    "On the {date} you became measurably more dangerous, reaching level {level}.",
    "On the {date} your XP overflowed its container and you reluctantly accepted level {level}.",
    "On the {date} you achieved level {level} through the time-honoured tradition of hitting things until they stopped.",
    "On the {date} the universe acknowledged your persistence with a promotion to level {level}.",
    "On the {date} you crossed into level {level} much as one crosses a low fence.",
]

_ACHIEVEMENT_TEMPLATES = [
    "On the {date} the chronicler noted: \"{text}\"",
    "On the {date} a passing minstrel committed this to song: \"{text}\"",
    "On the {date} this small thing was recorded for posterity: \"{text}\"",
    "On the {date} the day yielded up its small mystery: \"{text}\"",
    "On the {date}, much to everyone's faint surprise: \"{text}\"",
]

_CHAPTER_TEMPLATES = [
    "The Adventures of {name}",
    "Concerning {name}",
    "The Chronicle of {name}",
    "On the Subject of {name}",
    "{name}: Such Deeds as Were Done",
]


_OPENING_LINE = "Herein are recorded the deeds of your characters."
_CLOSING_LINE = "The End."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_date(ts: int) -> str:
    """Format an epoch-seconds timestamp as `"<ordinal> of <Month>, <Year>"`
    in local time. Falls back to a numeric form if the day is outside the
    1..31 ordinal map (shouldn't happen for real calendar days)."""
    dt = datetime.fromtimestamp(ts)
    ordinal = _ORDINAL_WORDS.get(dt.day, str(dt.day))
    return f"{ordinal} of {dt.strftime('%B')}, {dt.year}"


def _stable_index(seed: str, n: int) -> int:
    """Deterministic index into a list of length `n` from a string seed.
    Uses md5 — purely for a uniform-ish spread, not cryptographic."""
    if n <= 0:
        return 0
    digest = hashlib.md5(seed.encode("utf-8", errors="replace")).digest()
    val = int.from_bytes(digest[:4], "big")
    return val % n


def _pick_template(templates: list[str], spotlight: Spotlight, kind: str, ts: int) -> str:
    """Deterministic template choice for an event. Same (character,
    run_id, ts, kind) → same template across runs of the credits."""
    seed = f"{spotlight.character}|{spotlight.run_id}|{ts}|{kind}"
    return templates[_stable_index(seed, len(templates))]


def _pkill_target(extra: dict) -> str:
    name = extra.get("name", "") if isinstance(extra, dict) else ""
    race = extra.get("race", "") if isinstance(extra, dict) else ""
    if not isinstance(name, str):
        name = ""
    if not isinstance(race, str):
        race = ""
    if name and race:
        return f"{name} {race}"
    if name:
        return name
    # Defensive: pkill rows without a name fall back to a generic phrase.
    return "an unknown foe"


def _render_event(spotlight: Spotlight, event) -> str | None:
    """Render a single spotlight event as a narrative sentence. Returns
    None if the event kind is unknown (forward-compatible — new kinds
    just don't show up in credits until a template is added)."""
    date = _format_date(event.ts)
    extra = getattr(event, "extra", {}) or {}
    kind = event.kind

    if kind == "pkill":
        tpl = _pick_template(_PKILL_TEMPLATES, spotlight, kind, event.ts)
        return tpl.format(date=date, target=_pkill_target(extra))

    if kind == "death":
        tpl = _pick_template(_DEATH_TEMPLATES, spotlight, kind, event.ts)
        return tpl.format(date=date)

    if kind == "level_up":
        level = extra.get("level")
        if not isinstance(level, int):
            return None
        tpl = _pick_template(_LEVEL_UP_TEMPLATES, spotlight, kind, event.ts)
        return tpl.format(date=date, level=level)

    if kind == "achievement":
        text = extra.get("name", "")
        if not isinstance(text, str) or not text:
            return None
        tpl = _pick_template(_ACHIEVEMENT_TEMPLATES, spotlight, kind, event.ts)
        return tpl.format(date=date, text=text)

    return None


def _chapter_header(character: str) -> str:
    """Deterministic chapter header for a character."""
    idx = _stable_index(f"chapter|{character}", len(_CHAPTER_TEMPLATES))
    return _CHAPTER_TEMPLATES[idx].format(name=character)


def _wrap(line: str, text_width: int) -> list[str]:
    """Word-wrap a single sentence to `text_width` columns, preserving
    long words rather than breaking them."""
    if not line:
        return [""]
    wrapped = textwrap.wrap(
        line,
        width=text_width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [""]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_credits_lines(
    spotlights: list[Spotlight],
    text_width: int,
) -> list[str]:
    """Build the flat scroll content for the end-of-reel credits.

    Returns a list of strings, one per wrapped line, in scroll order
    (top of the list scrolls off first; bottom appears last). Structure:

    - 5 leading blank rows
    - opening line
    - 5 blank rows
    - per character (oldest-first by first event):
        - 3 blank rows
        - chapter header
        - 2 blank rows
        - chronological event narratives, one blank row between
          consecutive events
    - 5 blank rows
    - closing line
    - trailing blank padding (caller pads further when the terminal
      height is known; we add a comfortable buffer here as a baseline)

    `text_width` is the column count used for word-wrapping. The caller
    is responsible for centring the wrapped lines at render time."""
    if text_width < 1:
        text_width = 1

    # Group events by character, dropping events that don't render.
    per_char: dict[str, list] = {}
    for spot in spotlights:
        for ev in spot.events:
            sentence = _render_event(spot, ev)
            if sentence is None:
                continue
            per_char.setdefault(spot.character, []).append((ev.ts, sentence))

    # Sort each character's events chronologically (oldest first).
    for char in per_char:
        per_char[char].sort(key=lambda pair: pair[0])

    # Order characters by oldest-event ts ascending — the character whose
    # first event is oldest opens the chronicle.
    char_order = sorted(
        per_char.keys(),
        key=lambda c: per_char[c][0][0] if per_char[c] else 0,
    )

    out: list[str] = []

    # Leading blanks + opening.
    out.extend([""] * 5)
    out.extend(_wrap(_OPENING_LINE, text_width))
    out.extend([""] * 5)

    for char in char_order:
        events = per_char[char]
        if not events:
            continue
        out.extend([""] * 3)
        out.extend(_wrap(_chapter_header(char), text_width))
        out.extend([""] * 2)
        for i, (_ts, sentence) in enumerate(events):
            out.extend(_wrap(sentence, text_width))
            if i < len(events) - 1:
                out.append("")

    # Trailing blanks + closing line + baseline trailing buffer.
    out.extend([""] * 5)
    out.extend(_wrap(_CLOSING_LINE, text_width))
    # Baseline trailing buffer; the launcher adds another `term_rows`
    # blanks worth via the scroll-past-end math so the closing line
    # exits cleanly before auto-exit fires.
    out.extend([""] * 5)

    return out
