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
    "On the {date} you persuaded {target} of the merits of lying down.",
    "On the {date} you and {target} disagreed; {target} lost, comprehensively.",
    "On the {date} {target} discovered, too late, that you had a better idea about how the day should go.",
    "On the {date} {target} found themselves, statistically speaking, no longer in possession of life.",
    "On the {date} you delivered to {target} a small, sharp, and irrefutable argument.",
    "On the {date} {target} entered the long and well-attended queue at the Halls of Mandos.",
    "On the {date} you politely escorted {target} from this realm to another, less crowded one.",
    "On the {date} {target} discovered that the word \"invincible\" had been somewhat optimistic.",
    "On the {date} you settled accounts with {target} in full, with interest.",
    "On the {date} {target} ceased, in a manner of speaking, to be a going concern.",
    "On the {date} you applied yourself energetically to the problem of {target}, and solved it.",
    "On the {date} {target} was last seen approximately where you left them.",
    "On the {date} you reminded {target} of several uncomfortable and final truths.",
    "On the {date} {target} had a sudden and very unfortunate change of plans.",
    "On the {date} you authored the closing chapter of {target}'s remarkably brief biography.",
    "On the {date} {target} discovered a new and conclusive career path.",
    "On the {date} you had words with {target}; specifically, the last ones.",
    "On the {date} {target} stopped being a problem, in the most permanent sense available.",
    "On the {date} you persuaded {target} that further argument was, on balance, unwise.",
    "On the {date} {target}, foolhardy in the manner of their kind, met you and found their thread cut short.",
    "On the {date} you proved, with admirable economy, that {target} was mortal after all.",
    "On the {date} you delivered to {target} what historians would later describe as a setback.",
    "On the {date} you and {target} crossed paths; only you crossed back.",
    "On the {date} {target} took a swing at fate and you, helpfully, returned the blow.",
]

_DEATH_TEMPLATES = [
    "On the {date} your luck ran out and you ended up in the Halls of Mandos.",
    "On the {date} you discovered, with some surprise, that the situation was in fact fatal.",
    "On the {date} you misjudged things with admirable enthusiasm and terminal consequences.",
    "On the {date} the world reminded you, firmly, of your own mortality.",
    "On the {date} you became, however briefly, very dead.",
    "On the {date} your strategy of \"they probably won't all hit me\" was conclusively disproven.",
    "On the {date} you took a swing at fate; fate, regrettably, swung back harder.",
    "On the {date} you discovered, posthumously, several things you should have done differently.",
    "On the {date} you contributed in your own small way to the kingdom's mortality statistics.",
    "On the {date} you achieved a brief but distinguished career as a corpse.",
    "On the {date} the Doomsman of the Valar, with his customary patience, added you to the list.",
    "On the {date} you tested a theory about whether you could win that fight; the theory was wrong.",
    "On the {date} you stepped, very briefly, into the next world by way of a poorly-timed exit.",
    "On the {date} something hit you, and then something else, and then everything went quiet.",
    "On the {date} you went to seek your fortune; your fortune declined the meeting.",
    "On the {date} you optimistically attempted what was, in retrospect, a bad idea.",
    "On the {date} you joined that long company who learned, the hard way, the value of running.",
    "On the {date} you became briefly philosophical, then briefly dead.",
    "On the {date} a small misunderstanding with several enemies escalated with great enthusiasm.",
    "On the {date} you reached the limits of your considerable but ultimately finite resilience.",
    "On the {date} the kindly Doomsman invited you in; you had, as it happened, little say in the matter.",
    "On the {date} you discovered, abruptly, that not everything which hits you can be safely ignored.",
    "On the {date} you applied yourself diligently to the problem of staying alive, and failed.",
    "On the {date} your remarkable streak of not being dead came, at last, to its statistical end.",
    "On the {date} you went to face the foe with great courage and considerably less success.",
    "On the {date} you found yourself, abruptly, no longer in a position to argue the point.",
    "On the {date} you discovered that an arrow had found a path through your defences that you had not.",
    "On the {date} the universe applied to you one of its less negotiable laws.",
    "On the {date} you encountered the firm and unmoveable opinion of something very sharp.",
    "On the {date} you set out to test your luck; your luck, it turned out, had limits.",
]

_LEVEL_UP_TEMPLATES = [
    "On the {date} you arrived, slightly out of breath, at level {level}.",
    "On the {date} you became measurably more dangerous, reaching level {level}.",
    "On the {date} your XP overflowed its container and you reluctantly accepted level {level}.",
    "On the {date} you achieved level {level} through the time-honoured tradition of hitting things until they stopped.",
    "On the {date} the universe acknowledged your persistence with a promotion to level {level}.",
    "On the {date} you crossed into level {level} much as one crosses a low fence.",
    "On the {date}, after considerable effort and a fair bit of luck, you graduated to level {level}.",
    "On the {date} you ascended, with a faintly audible click, to level {level}.",
    "On the {date} you reached level {level}, having put in the work and broken many things along the way.",
    "On the {date} you levelled up to {level}, an event entirely unmarked by ceremony or applause.",
    "On the {date} the gods, who keep track of such things, registered you as level {level}.",
    "On the {date} you became, by general agreement of your skills, a level {level} sort of person.",
    "On the {date} you advanced to level {level} via the well-tested route of relentless violence.",
    "On the {date} you achieved level {level}; you celebrated, briefly, before being shot at again.",
    "On the {date} you crossed the invisible line that separated you from level {level}.",
    "On the {date} the world's bookkeepers updated your file to level {level}, with a small footnote.",
    "On the {date} you became level {level}, much to your own faint surprise.",
    "On the {date} you stepped up to level {level} as if it were merely the next stair, which in a sense it was.",
    "On the {date} you graduated, with no fanfare to speak of, to level {level}.",
    "On the {date} you became measurably better at the work, and the world rewarded you with the title \"level {level}\".",
    "On the {date} you reached level {level}, much like reaching the next town: tired, pleased, and somewhat hungrier.",
    "On the {date} your reputation among your peers ticked quietly upward to level {level}.",
    "On the {date} you achieved level {level} by the simple expedient of not dying for long enough.",
    "On the {date} you arrived at level {level} via a path lined with various unpleasantnesses.",
    "On the {date} the world's invisible accountants ruled you to be of level {level}.",
    "On the {date} you became level {level}, which felt, in all honesty, surprisingly similar to the previous one.",
    "On the {date} you, slightly battered but undeterred, achieved level {level}.",
    "On the {date} you arrived at level {level} the way most adventurers do: hungry, footsore, and faintly smug.",
    "On the {date} you ticked over to level {level} like an odometer in a particularly slow cart.",
    "On the {date} you reached level {level}, accepting the title with the modesty appropriate to its mild absurdity.",
]

_ACHIEVEMENT_TEMPLATES = [
    "On the {date} the chronicler noted: \"{text}\"",
    "On the {date} a passing minstrel committed this to song: \"{text}\"",
    "On the {date} this small thing was recorded for posterity: \"{text}\"",
    "On the {date} the day yielded up its small mystery: \"{text}\"",
    "On the {date}, much to everyone's faint surprise: \"{text}\"",
    "On the {date} word reached the chronicler: \"{text}\"",
    "On the {date} a small notice was pinned to the inn's notice-board, reading: \"{text}\"",
    "On the {date}, by way of a passing rumour, the village heard: \"{text}\"",
    "On the {date} a scribe in some distant office made an entry: \"{text}\"",
    "On the {date} an itinerant minstrel composed an unremarkable verse on this theme: \"{text}\"",
    "On the {date} the day was duly marked with these words: \"{text}\"",
    "On the {date} a small triumph was recorded thus: \"{text}\"",
    "On the {date} a herald, with his usual gravity, announced: \"{text}\"",
    "On the {date} this peculiar fact was noted and filed: \"{text}\"",
    "On the {date} an entry was made in the ledger of remarkable things: \"{text}\"",
    "On the {date} the gods themselves paused, briefly, to take note: \"{text}\"",
    "On the {date} a wandering bard, in dire need of new material, chose to sing of this: \"{text}\"",
    "On the {date} the day's official record contained this single line: \"{text}\"",
    "On the {date} the world, in its quiet way, took note: \"{text}\"",
    "On the {date} something happened worth a footnote, namely: \"{text}\"",
    "On the {date} a scrap of parchment, possibly now lost, preserved the moment thus: \"{text}\"",
    "On the {date} witnesses agreed, though for once on the same point: \"{text}\"",
    "On the {date}, between the more dramatic events of the day: \"{text}\"",
    "On the {date} a small triumph briefly outshone the surrounding tedium: \"{text}\"",
    "On the {date} you briefly earned the attention of the celestial bookkeepers: \"{text}\"",
    "On the {date} this minor wonder was witnessed and approximately remembered: \"{text}\"",
    "On the {date} the inn-keeper, leaning thoughtfully over the bar, was heard to remark: \"{text}\"",
    "On the {date} a passing crow, hearing the news, expressed itself as follows: \"{text}\"",
    "On the {date} the matter was added to the long list of things worth saying once: \"{text}\"",
    "On the {date} the world's running tally of small wonders gained an entry: \"{text}\"",
]

_CHAPTER_TEMPLATES = [
    "The Adventures of {name}",
    "Concerning {name}",
    "The Chronicle of {name}",
    "On the Subject of {name}",
    "{name}: Such Deeds as Were Done",
    "The Memoirs of {name}, Such As They Are",
    "Wherein {name} Did Things of Variable Merit",
    "A Brief and Truthful Account of {name}",
    "The Saga of {name}, Lightly Edited",
    "In Which {name} Was Frequently Surprised",
    "Some Notes on the Career of {name}",
    "{name}: A Life, Mostly",
    "The Acts and Mishaps of {name}",
    "The Long Wandering of {name}",
    "{name}, As Recalled by Witnesses",
    "The Modest Legend of {name}",
    "Concerning the Deeds of {name}, in the Order They Occurred",
    "An Annotated Record of {name}",
    "{name}: The Authorised Version",
    "{name}: A Curriculum Vitae",
    "The Brief and Eventful Tale of {name}",
    "Such Adventures as Befell {name}",
    "The Quiet Triumphs of {name}",
    "Some Highlights from the Life of {name}",
    "The Reasonably Heroic Career of {name}",
    "On the Travels of {name}",
    "The Sometimes-Heroic Deeds of {name}",
    "{name}: A Partial Inventory",
    "The Adventures of {name}, Briefly Documented",
    "{name}: Their Side of the Story",
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
