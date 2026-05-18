# bridge/launcher/macro_keys.py — bidirectional macro-key map.
#
# Single source of truth for the launcher's profile editor view of the
# `#macro` key set: the tt++ escape sequence stored on disk, the
# prompt_toolkit key event that produces it from the input pane, and
# the human-readable name shown in the editor.
#
# CONTRACT: every entry here must be a key that bridge/panes/input_pane.py
# forwards to tt++. Bind a key here that input_pane does NOT forward and
# the editor will happily set the pattern but the macro will never fire
# in-game. When you add a key to input_pane's forwarded sets, mirror it
# here; when you add one here, mirror it there.
#
# A future refactor can hoist the shared list into one place; see the
# ADR alongside this module for the trade-off.

from dataclasses import dataclass
from typing import Any, Optional, Tuple, Union

try:
    from prompt_toolkit.keys import Keys
except ImportError:   # tolerate import-time absence for unit tests
    Keys = None       # type: ignore


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MacroKey:
    pk_keys: Any           # prompt_toolkit Keys.* constant or a tuple of
                           # escape characters matching input_pane's bindings
    tin_escape: str        # canonical on-disk form, e.g. r"\eOp"
    display_name: str      # "Numpad 0", "F1", "Alt+a", "Ctrl+g"


# Numpad SS3 sequences. tt++ writes them as `\eOp`, `\eOq`, … on disk.
# Order mirrors a physical numpad layout (0..9, . , Enter, *, +, -, /).
_NUMPAD = [
    ("p", "0", "Numpad 0"),
    ("q", "1", "Numpad 1"),
    ("r", "2", "Numpad 2"),
    ("s", "3", "Numpad 3"),
    ("t", "4", "Numpad 4"),
    ("u", "5", "Numpad 5"),
    ("v", "6", "Numpad 6"),
    ("w", "7", "Numpad 7"),
    ("x", "8", "Numpad 8"),
    ("y", "9", "Numpad 9"),
    ("n", ".", "Numpad ."),
    ("M", "Enter", "Numpad Enter"),
    ("j", "*", "Numpad *"),
    ("k", "+", "Numpad +"),
    ("m", "-", "Numpad -"),
    ("o", "/", "Numpad /"),
]


def _build_known_keys():
    keys = []
    # F-keys F1..F12. tt++ accepts the prompt_toolkit Keys.F* names directly
    # via #macro {\eOP} on most terminals, but the user-facing canonical
    # form on disk varies; we emit Keys.F* tokens for the capture path and
    # store the standard xterm escape on disk.
    f_escapes = {
        1:  r"\eOP",   2:  r"\eOQ",   3:  r"\eOR",   4:  r"\eOS",
        5:  r"\e[15~", 6:  r"\e[17~", 7:  r"\e[18~", 8:  r"\e[19~",
        9:  r"\e[20~", 10: r"\e[21~", 11: r"\e[23~", 12: r"\e[24~",
    }
    if Keys is not None:
        for n in range(1, 13):
            keys.append(MacroKey(
                pk_keys=getattr(Keys, f"F{n}"),
                tin_escape=f_escapes[n],
                display_name=f"F{n}",
            ))
    # Numpad keys — multi-key tuple form (matches input_pane bindings).
    for letter, label, name in _NUMPAD:
        keys.append(MacroKey(
            pk_keys=("escape", "O", letter),
            tin_escape=fr"\eO{letter}",
            display_name=name,
        ))
    # Alt+letter — escape prefix + letter, mirrors input_pane.ALT_FORWARDED_LETTERS.
    # Skips b, d, f (reserved for word ops) and o (parser collision with
    # numpad-division SS3 sequence \eOo).
    alt_letters = [
        "a", "c", "e", "g", "h", "i", "j", "k", "l", "m",
        "n", "p", "q", "r", "s", "t", "u", "v", "w",
        "x", "y", "z",
    ]
    for letter in alt_letters:
        keys.append(MacroKey(
            pk_keys=("escape", letter),
            tin_escape=fr"\e{letter}",
            display_name=f"Alt+{letter}",
        ))
    # Ctrl+letter — mirrors input_pane FORWARDED_KEYS' Ctrl subset (g, l, o).
    ctrl_letters = ["g", "l", "o"]
    if Keys is not None:
        for letter in ctrl_letters:
            keys.append(MacroKey(
                pk_keys=getattr(Keys, f"Control{letter.upper()}"),
                # tt++ writes Ctrl+letter as the literal control byte (e.g.
                # Ctrl+G == 0x07). The xterm-style notation `^G` is the
                # closest user-readable canonical form most tt++ profiles use.
                tin_escape=f"^{letter.upper()}",
                display_name=f"Ctrl+{letter}",
            ))
    return keys


KNOWN_KEYS = _build_known_keys()


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------
def _normalise_escape(raw):
    """Normalise common escape forms so an existing macro authored in
    another client still resolves to a readable name.

    Accepts `\\e`, `\\x1b`, `\\033`, and a literal ESC byte; returns the
    canonical `\\e<rest>` form. Trailing characters are passed through
    unchanged."""
    if not raw:
        return raw
    s = raw
    # Literal ESC byte → "\\e" prefix.
    if s and s[0] == "\x1b":
        s = "\\e" + s[1:]
    # `\x1b` / `\X1B` hex escape → `\e`.
    elif s.startswith("\\x1b") or s.startswith("\\X1b") or s.startswith("\\x1B") or s.startswith("\\X1B"):
        s = "\\e" + s[4:]
    # `\033` octal escape → `\e`.
    elif s.startswith("\\033"):
        s = "\\e" + s[4:]
    return s


_ESCAPE_TO_NAME = {}
_NAME_TO_ESCAPE = {}
for _mk in KNOWN_KEYS:
    _ESCAPE_TO_NAME[_mk.tin_escape] = _mk.display_name
    _NAME_TO_ESCAPE[_mk.display_name] = _mk.tin_escape


def escape_to_name(esc: str) -> Optional[str]:
    """Resolve a tt++ escape sequence (as written on disk) to a readable
    display name. Returns None for unknown sequences so the caller can
    render them under a `Custom: <raw>` slot."""
    if esc is None:
        return None
    canonical = _normalise_escape(esc)
    return _ESCAPE_TO_NAME.get(canonical)


def name_to_escape(name: str) -> Optional[str]:
    """Reverse of `escape_to_name`. Returns None for unknown names."""
    return _NAME_TO_ESCAPE.get(name)


# ---------------------------------------------------------------------------
# prompt_toolkit event matching
# ---------------------------------------------------------------------------
def _event_key_tuple(event):
    """Reduce a prompt_toolkit KeyPressEvent to the comparable token used
    by the lookup tables: a single `Keys.*` value, a single string key
    name, or a tuple of escape characters (matches the multi-key tuple
    form used in input_pane for SS3 / Alt sequences)."""
    seq = list(event.key_sequence)
    if not seq:
        return None
    if len(seq) == 1:
        return seq[0].key
    return tuple(kp.key for kp in seq)


# Build a lookup keyed on `pk_keys`. Tuples and single Keys.* / strings
# all hash, so a single dict suffices.
_PK_TO_MK = {mk.pk_keys: mk for mk in KNOWN_KEYS}


def match_pressed(event) -> Optional[MacroKey]:
    """Match a prompt_toolkit KeyPressEvent against the known-keys set.

    Returns the matching MacroKey, or None if the key sequence is not
    forwardable (the caller should then surface `rejection_reason`)."""
    token = _event_key_tuple(event)
    if token is None:
        return None
    return _PK_TO_MK.get(token)


def rejection_reason(event) -> str:
    """Specific reason a key was rejected — surfaced in the capture
    overlay's error slot. The generic fallback is intentionally curt; the
    overlay re-renders on every keypress so the user can iterate quickly.

    Detected forms (highest specificity first):
      • Shift+letter (single uppercase ASCII letter, no modifiers in the
        key name)        → "Shift+letter keys aren't forwarded to tt++."
      • Alt+o            → "Alt+O has a known parser limitation."
      • Bare ESC         → "Bare ESC opens the popup menu and can't be bound."
      • Plain letter / printable single char
                         → "Plain letters reach tt++ as typed input, not as macros."
    """
    seq = list(event.key_sequence)
    if not seq:
        return "Unrecognised key — please try a different one."
    # Bare ESC — also intercepted by the overlay's Cancel binding, but
    # surface a specific reason if the wildcard ever sees it.
    if len(seq) == 1 and seq[0].key in ("escape", "c-[", "\x1b"):
        return "Bare ESC opens the popup menu and can't be bound."
    # Alt+o (escape + 'o') — parser collision with numpad-division SS3.
    if (len(seq) == 2
            and seq[0].key == "escape"
            and isinstance(seq[1].key, str)
            and seq[1].key.lower() == "o"):
        return "Alt+O has a known parser limitation."
    # Shift+letter — printable uppercase ASCII letter.
    if (len(seq) == 1
            and isinstance(seq[0].key, str)
            and len(seq[0].key) == 1
            and seq[0].key.isalpha()
            and seq[0].key.isupper()):
        return "Shift+letter keys aren't forwarded to tt++."
    # Plain printable single char (lowercase letter, digit, symbol).
    if (len(seq) == 1
            and isinstance(seq[0].key, str)
            and len(seq[0].key) == 1
            and seq[0].key.isprintable()):
        return "Plain letters reach tt++ as typed input, not as macros."
    return "That key isn't forwarded to tt++. Try F1–F12, numpad, or Alt+letter."
