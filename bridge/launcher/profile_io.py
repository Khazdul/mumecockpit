# bridge/launcher/profile_io.py — parser / serializer for tt++ profile files.
#
# Recognises the five GUI-editable command kinds (#alias, #action, #macro,
# #highlight, #substitute / #sub) in the canonical two- or three-brace-arg
# form. Everything else (#var, #event, blank lines, malformed entries) is
# preserved verbatim as a Passthrough. #nop lines are dropped (matching
# #class write semantics — see docs/decisions/0042-blank-profile-template.md).
#
# Used by the launcher's profile editor frame; see docs/launcher.md.

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

KINDS = ("alias", "action", "macro", "highlight", "substitute")

# Command token → kind. Order matters: longer tokens before shorter ones
# (#substitute before #sub) so prefix matching picks the longest form.
_CMD_TO_KIND = [
    ("#substitute", "substitute"),
    ("#highlight",  "highlight"),
    ("#alias",      "alias"),
    ("#action",     "action"),
    ("#macro",      "macro"),
    ("#sub",        "substitute"),
]

_NOP = "#nop"


@dataclass
class Entry:
    kind: str                       # 'alias' | 'action' | 'macro' | 'highlight' | 'substitute'
    pattern: str
    body: str
    priority: Optional[int] = None
    _raw: Optional[str] = None      # original source line (without trailing newline)


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
# Brace splitter
# ---------------------------------------------------------------------------
def _split_brace_args(s):
    """Split a tail of the form ` {arg1} {arg2} [{arg3}]` into raw arg
    strings. Honours `\\` as a one-character escape (so `\\}` does not
    close a brace) and tracks nesting depth.

    Returns the list of args on success, or `None` if the input is
    malformed or contains trailing non-whitespace after the last `}`.
    """
    args = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in (" ", "\t"):
            i += 1
        if i >= n:
            break
        if s[i] != "{":
            return None
        depth = 1
        i += 1
        start = i
        while i < n:
            c = s[i]
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            return None
        args.append(s[start:i])
        i += 1
    return args


def _starts_with_command(stripped, cmd):
    """True iff `stripped` begins with `cmd` followed by EOL, whitespace,
    or `{` (so `#alias_foo` is rejected, `#alias {x} {y}` is accepted)."""
    if not stripped.startswith(cmd):
        return False
    rest = stripped[len(cmd):]
    return rest == "" or rest[0] in (" ", "\t", "{")


def _parse_line(raw_line):
    """Parse one profile-file line.

    Returns:
      * `Entry`        — recognised registration in canonical form
      * `Passthrough`  — anything else, preserved verbatim
      * `None`         — `#nop` line (dropped on save, per ADR 0042)
    """
    line = raw_line.rstrip("\n").rstrip("\r")
    stripped = line.lstrip()

    if _starts_with_command(stripped, _NOP):
        return None

    for cmd, kind in _CMD_TO_KIND:
        if not _starts_with_command(stripped, cmd):
            continue
        tail = stripped[len(cmd):]
        args = _split_brace_args(tail)
        if args is None or not (2 <= len(args) <= 3):
            return Passthrough(raw=line)
        pattern, body = args[0], args[1]
        priority = None
        if len(args) == 3:
            try:
                priority = int(args[2])
            except ValueError:
                return Passthrough(raw=line)
        return Entry(kind=kind, pattern=pattern, body=body,
                     priority=priority, _raw=line)

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
    """Parse `path` (a `pathlib.Path` or `str`) into a `Profile`."""
    p = Path(path)
    items = []
    with open(p, "r") as fh:
        for raw in fh:
            parsed = _parse_line(raw)
            if parsed is None:
                continue
            items.append(parsed)
    return Profile(path=p, items=items)


def save_profile(profile):
    """Write `profile` back to its `path` via a temp-file + rename.

    Entry items with `_raw` still attached emit that verbatim (lossless
    round-trip for unmodified entries). Entries with `_raw=None` are
    regenerated canonically. `Passthrough` items emit their raw text.
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
    import os
    os.replace(tmp, p)
