# bridge/launcher/profile_io.py — parser / serializer for tt++ profile files.
#
# Recognises the five GUI-editable command kinds (#alias, #action, #macro,
# #highlight, #substitute / #sub) in the canonical two- or three-brace-arg
# form. Command names are matched case-insensitively, and brace-arg groups
# may be separated by any whitespace including newlines (tt++ treats
# newlines outside braces as whitespace). Everything else (#var, #event,
# blank lines, malformed entries) is preserved one physical line at a time
# as a Passthrough. #nop lines are dropped (matching #class write semantics
# — see docs/decisions/0042-blank-profile-template.md).
#
# Used by the launcher's profile editor frame; see docs/launcher.md.

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

KINDS = ("alias", "action", "macro", "highlight", "substitute")

# Canonical command names tt++ accepts in profile files for the five
# GUI-editable kinds. Order is irrelevant — `resolve_kind` checks all.
CANONICAL_KINDS = ("alias", "action", "macro", "highlight", "substitute")

_NOP = "#nop"


def resolve_kind(token):
    """Resolve a command-name token (the letters after `#`, any case) to
    a canonical kind, mirroring tt++'s unambiguous-prefix rule.

    Returns the canonical kind on an unambiguous case-insensitive prefix
    match of length ≥ 2 (e.g. `mac` → `macro`, `Hi` → `highlight`,
    `SUB` → `substitute`). Returns None for single-char tokens
    (ambiguous), for tokens longer than the canonical name (plurals
    like `macros`), and — defensively — for prefixes that would match
    more than one canonical kind.
    """
    t = token.lower()
    if len(t) < 2:
        return None
    matches = [k for k in CANONICAL_KINDS
               if k.startswith(t) and len(t) <= len(k)]
    return matches[0] if len(matches) == 1 else None


@dataclass
class Entry:
    kind: str                       # 'alias' | 'action' | 'macro' | 'highlight' | 'substitute'
    pattern: str
    body: str
    priority: Optional[int] = None
    _raw: Optional[str] = None      # original source span (without the trailing \n)


@dataclass
class Passthrough:
    raw: str                        # verbatim source line (without trailing newline)


@dataclass
class Profile:
    path: Path
    items: List[Union[Entry, Passthrough]] = field(default_factory=list)

    def entries_of(self, kind: str) -> List[Entry]:
        return [it for it in self.items
                if isinstance(it, Entry) and it.kind == kind]


# ---------------------------------------------------------------------------
# Brace tokeniser
# ---------------------------------------------------------------------------
def _read_brace_group(src, i, n):
    """Read a single `{...}` group starting at `src[i]`. Returns
    `(body, end)` where `body` is the text strictly between the matched
    outer braces and `end` is the index just past the closing `}`. Tracks
    nesting; `\\` escapes the next character (so `\\}` does not close a
    group). Returns `None` if `src[i] != '{'` or the group is
    unterminated."""
    if i >= n or src[i] != "{":
        return None
    j = i + 1
    start = j
    depth = 1
    while j < n:
        c = src[j]
        if c == "\\" and j + 1 < n:
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:j], j + 1
        j += 1
    return None


def _split_brace_args(s):
    """Split a tail like ` {arg1} {arg2} [{arg3}]` into raw arg strings.
    Inter-arg whitespace may include newlines, matching tt++ semantics
    where newlines outside braces are treated as whitespace.

    Returns the list of args on success, or `None` if malformed or if
    the input contains trailing non-whitespace after the last `}`.
    """
    args = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in (" ", "\t", "\n", "\r"):
            i += 1
        if i >= n:
            break
        if s[i] != "{":
            return None
        result = _read_brace_group(s, i, n)
        if result is None:
            return None
        body, i = result
        args.append(body)
    return args


def _read_command_name(src, i, n):
    """If `src[i:]` starts with `<spaces/tabs>#<letters>`, return the
    lower-cased `#<letters>` token (including the `#`); otherwise return
    `None`. Used for case-insensitive command-name dispatch. Does not
    consume newlines from any caller pointer."""
    j = i
    while j < n and src[j] in (" ", "\t"):
        j += 1
    if j >= n or src[j] != "#":
        return None
    k = j + 1
    while k < n and src[k].isalpha():
        k += 1
    return src[j:k].lower()


def _try_parse_entry_at(src, i, n):
    """Try to parse one Entry beginning at logical-line position `i`.

    Returns `(Entry, end_pos)` on success, where `end_pos` is the index
    just past the closing `}` of the last consumed brace group. The
    Entry's `_raw` captures the full byte span from `i` through
    `end_pos` (exclusive) so unmodified entries round-trip byte-exact.

    Returns `None` if no known command name matches, if the brace
    grouping is malformed, or if there is trailing non-whitespace on
    the entry's last physical line (which makes the line ambiguous and
    is safer to surface as a Passthrough).
    """
    # Skip optional leading horizontal whitespace on the logical line.
    j = i
    while j < n and src[j] in (" ", "\t"):
        j += 1
    if j >= n or src[j] != "#":
        return None
    # `cmd_start` is the position of `#`; letters follow immediately.
    cmd_start = j
    k = j + 1
    while k < n and src[k].isalpha():
        k += 1
    kind = resolve_kind(src[cmd_start + 1:k])
    if kind is None:
        return None

    # The command token must be followed by EOF, whitespace (incl. \n),
    # or an opening brace — anything else (e.g. `#aliasfoo`) is not us.
    if k < n and src[k] not in (" ", "\t", "\n", "\r", "{"):
        return None
    j = k

    # Consume up to 3 brace groups, with arbitrary whitespace between
    # (including newlines — tt++ treats newlines outside braces as ws).
    # `end_after_last_brace` tracks the position right after the last
    # `}` so trailing whitespace (which the inner loop may consume while
    # searching for the next `{`) is NOT folded into the entry's _raw.
    args = []
    end_after_last_brace = j
    while len(args) < 3:
        while j < n and src[j] in (" ", "\t", "\n", "\r"):
            j += 1
        if j >= n or src[j] != "{":
            break
        result = _read_brace_group(src, j, n)
        if result is None:
            return None
        body_text, j = result
        end_after_last_brace = j
        args.append(body_text)

    if not (2 <= len(args) <= 3):
        return None
    pattern = args[0]
    body    = args[1]
    priority = None
    if len(args) == 3:
        try:
            priority = int(args[2])
        except ValueError:
            return None

    # Guard against trailing non-whitespace on the entry's last physical
    # line. If present, surface as Passthrough so the bytes survive
    # untouched on save (the simpler regenerator can't reproduce them).
    m = end_after_last_brace
    while m < n and src[m] != "\n":
        if src[m] not in (" ", "\t", "\r"):
            return None
        m += 1

    raw = src[i:end_after_last_brace]
    return Entry(kind=kind, pattern=pattern, body=body,
                 priority=priority, _raw=raw), end_after_last_brace


def _parse_line(raw_line):
    """Single-line parse wrapper kept for unit tests. Returns Entry,
    Passthrough, or None (for `#nop`). `load_profile` uses the multi-
    line tokeniser directly and does not go through this helper."""
    line = raw_line.rstrip("\n").rstrip("\r")
    n = len(line)
    cmd = _read_command_name(line, 0, n)
    if cmd == _NOP:
        return None
    if cmd is not None and resolve_kind(cmd[1:]) is not None:
        result = _try_parse_entry_at(line, 0, n)
        if result is not None:
            entry, _end = result
            return entry
    return Passthrough(raw=line)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
_KIND_TO_CMD = {
    "alias":      "#alias",
    "action":     "#action",
    "macro":      "#macro",
    "highlight":  "#highlight",
    "substitute": "#substitute",
}


def _serialize_entry(entry):
    """Regenerate a canonical `#<kind> {pattern} {body}[ {priority}]` line."""
    cmd = _KIND_TO_CMD[entry.kind]
    out = f"{cmd} {{{entry.pattern}}} {{{entry.body}}}"
    if entry.priority is not None:
        out += f" {{{entry.priority}}}"
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_profile(path):
    """Parse `path` (a `pathlib.Path` or `str`) into a `Profile`.

    Walks the source as a stream, not line by line, so multi-line entry
    forms (brace groups separated by newlines) are recognised. Lines
    that don't start a known command fall through to Passthrough one
    physical line at a time."""
    p = Path(path)
    with open(p, "r") as fh:
        src = fh.read()

    items = []
    i = 0
    n = len(src)
    while i < n:
        cmd = _read_command_name(src, i, n)
        if cmd == _NOP:
            # Drop one physical line. Multi-line `#nop {...}` blocks
            # are not consumed wholesale; their brace lines become
            # Passthrough, which still byte-round-trips.
            nl = src.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if cmd is not None and resolve_kind(cmd[1:]) is not None:
            result = _try_parse_entry_at(src, i, n)
            if result is not None:
                entry, end_pos = result
                items.append(entry)
                nl = src.find("\n", end_pos)
                i = n if nl == -1 else nl + 1
                continue
        # Fallback: one physical line as Passthrough.
        nl = src.find("\n", i)
        if nl == -1:
            items.append(Passthrough(raw=src[i:].rstrip("\r")))
            i = n
        else:
            items.append(Passthrough(raw=src[i:nl].rstrip("\r")))
            i = nl + 1

    return Profile(path=p, items=items)


def save_profile(profile):
    """Write `profile` back to its `path` via a temp-file + rename.

    Entry items with `_raw` still attached emit that verbatim (lossless
    round-trip for unmodified entries, including multi-line forms).
    Entries with `_raw=None` are regenerated canonically. `Passthrough`
    items emit their raw text.
    """
    p = Path(profile.path)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w") as fh:
        for item in profile.items:
            if isinstance(item, Passthrough):
                fh.write(item.raw + "\n")
            elif isinstance(item, Entry):
                if item._raw is not None:
                    fh.write(item._raw + "\n")
                else:
                    fh.write(_serialize_entry(item) + "\n")
    os.replace(tmp, p)
