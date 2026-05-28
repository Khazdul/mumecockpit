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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

KINDS = ("alias", "action", "macro", "highlight", "substitute")

# Canonical command names tt++ accepts in profile files for the five
# GUI-editable kinds. Order is irrelevant — `resolve_kind` checks all.
CANONICAL_KINDS = ("alias", "action", "macro", "highlight", "substitute")

# Kinds whose bodies tt++ rewrites on `#write` (logout) into an indented
# multi-line block. We normalise these back to flat form at parse time so
# the editor's Commands field renders cleanly. Highlights and substitutes
# are left untouched — tt++ does not reformat them and their bodies may
# contain intentional whitespace.
_NORMALISE_BODY_KINDS = frozenset(("action", "alias", "macro"))

# Per-kind brace-arg arity: (min_args, max_args). tt++ accepts an optional
# third arg as priority on every GUI-editable kind except `#macro`.
_KIND_ARITY = {
    "alias":      (2, 3),
    "action":     (2, 3),
    "macro":      (2, 2),
    "highlight":  (2, 3),
    "substitute": (2, 3),
}

_NOP = "#nop"

_CLASS_OPEN_CLOSE = re.compile(
    r'^\s*#class\s+\{[^}]+\}\s+\{?(open|close)\}?\s*$',
    re.IGNORECASE,
)


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

    def __setattr__(self, name, value):
        # Mutating any GUI-editable field drops `_raw` so `save_profile`
        # regenerates the entry canonically. The dataclass-generated
        # __init__ assigns fields in declaration order — `_raw` is last,
        # so the initial parse-time assignment lands after the field
        # writes that would otherwise clear it. See ADR 0081-adjacent
        # round-trip contract in docs/launcher.md.
        if name in ("pattern", "body", "priority"):
            current = self.__dict__.get(name, _MISSING)
            if current != value:
                object.__setattr__(self, "_raw", None)
        object.__setattr__(self, name, value)


_MISSING = object()


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

    # Consume up to `max_args` brace groups, with arbitrary whitespace
    # between (including newlines — tt++ treats newlines outside braces
    # as ws). `end_after_last_brace` tracks the position right after
    # the last `}` so trailing whitespace (which the inner loop may
    # consume while searching for the next `{`) is NOT folded into the
    # entry's _raw. `max_args` comes from `_KIND_ARITY`: `#macro`
    # accepts exactly 2; the other four kinds accept 2 or 3.
    min_args, max_args = _KIND_ARITY[kind]
    args = []
    end_after_last_brace = j
    while len(args) < max_args:
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

    if not (min_args <= len(args) <= max_args):
        return None
    pattern = args[0]
    body    = args[1]
    priority = None
    if len(args) == 3:
        # Only reachable for kinds whose max_args == 3 (alias/action/
        # highlight/substitute). Non-integer priority surfaces the line
        # as Passthrough so we never reinterpret an unknown form.
        try:
            priority = int(args[2].strip())
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
    """Regenerate a canonical `#<kind> {pattern} {body}[ {priority}]` line.

    `#macro` never accepts a third brace-arg, so a stray `priority` on a
    macro Entry is dropped defensively (the GUI never sets it, but the
    serializer guards anyway)."""
    cmd = _KIND_TO_CMD[entry.kind]
    out = f"{cmd} {{{entry.pattern}}} {{{entry.body}}}"
    _min, max_args = _KIND_ARITY[entry.kind]
    if entry.priority is not None and max_args >= 3:
        out += f" {{{entry.priority}}}"
    return out


# ---------------------------------------------------------------------------
# Sort + group helpers
# ---------------------------------------------------------------------------
def _classify_passthrough(pt):
    """Return `(command_name, first_arg)` for a Passthrough whose raw
    text starts with `#<cmd> {arg1}`, or `None` for blank lines, free
    text, and malformed forms — those are dropped on sort.

    `command_name` is the lower-cased `#<token>` (e.g. `#var`).
    `first_arg` is the text strictly between the first `{...}` group;
    it becomes the sort key within the command group.

    Multi-line passthrough forms (a `#class {x} { ... \\n ... }` block
    whose closing `}` lives on a later physical line) become per-line
    Passthroughs in `parse_profile`; only the first line classifies and
    the continuation lines drop on sort. This is a known limitation —
    see the Phase 6.2 ADR."""
    raw = pt.raw
    n = len(raw)
    cmd = _read_command_name(raw, 0, n)
    if cmd is None:
        return None
    # Advance past leading horizontal whitespace then the `#<letters>` token.
    j = 0
    while j < n and raw[j] in (" ", "\t"):
        j += 1
    j += len(cmd)
    while j < n and raw[j] in (" ", "\t"):
        j += 1
    if j >= n or raw[j] != "{":
        return None
    result = _read_brace_group(raw, j, n)
    if result is None:
        return None
    first_arg, _end = result
    return (cmd, first_arg)


def _item_classify(item):
    """Return `(command_name, sort_key)` for an Entry or Passthrough, or
    `None` for items that should be dropped on sort.

    Empty-pattern Entries (the editor's abandoned create attempts) are
    also dropped — `serialize_profile` already had this rule; surfacing
    it here keeps `parse_profile` and `serialize_profile` symmetric."""
    if isinstance(item, Entry):
        if item.pattern.strip() == "":
            return None
        return (_KIND_TO_CMD[item.kind], item.pattern)
    if isinstance(item, Passthrough):
        return _classify_passthrough(item)
    return None


def _normalise_body(body):
    """Reformat a tt++-rewritten multi-line body back to flat form.

    tt++ rewrites multi-statement bodies on `#write` (logout) into an
    indented block: the text right after the opening `{` and right
    before the closing `}` becomes a blank-edge line, and every
    in-between line is prefixed with four spaces. We undo both:

      1. Strip leading and trailing blank/whitespace-only lines.
      2. For every remaining line that begins with at least four
         spaces, remove the leading four spaces.

    Newlines following `;` survive — the result reads as one statement
    per line, un-indented, no blank edge rows. Idempotent (a body
    already in flat form returns equal). The caller is expected to
    apply this only to kinds in `_NORMALISE_BODY_KINDS`."""
    lines = body.split("\n")
    # Strip leading whitespace-only lines.
    while lines and lines[0].strip() == "":
        lines.pop(0)
    # Strip trailing whitespace-only lines.
    while lines and lines[-1].strip() == "":
        lines.pop()
    # De-indent any line that starts with at least four spaces.
    out = []
    for line in lines:
        if line.startswith("    "):
            out.append(line[4:])
        else:
            out.append(line)
    return "\n".join(out)


def _sorted_items(items):
    """Sort `items` into command groups. Returns a list of
    `(command_name, item)` tuples in render order: groups sorted
    alphabetically by `command_name`, items within each group sorted
    case-insensitively by `sort_key`. Stable sort preserves source order
    on ties."""
    classified = []
    for item in items:
        key = _item_classify(item)
        if key is None:
            continue
        cmd, sort_key = key
        classified.append((cmd, sort_key, item))
    classified.sort(key=lambda t: (t[0].lower(), t[1].lower()))
    return [(cmd, item) for cmd, _key, item in classified]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def parse_profile(src, path):
    """Parse `src` (a string) into a `Profile`, attaching `path` (a
    `pathlib.Path` or `str`) as the resulting profile's path.

    Walks the source as a stream, not line by line, so multi-line entry
    forms (brace groups separated by newlines) are recognised. Lines
    that don't start a known command fall through to Passthrough one
    physical line at a time. `#nop` lines are dropped (ADR 0042).

    The returned `Profile.items` is sorted into command groups —
    alphabetical by command name, alphabetical within each group by
    first brace-arg (case-insensitive). Blank lines, free text, and
    malformed Passthroughs are dropped during the sort pass. This
    matches the order `serialize_profile` would emit, so a parse →
    serialize round-trip is idempotent."""
    items = []
    i = 0
    n = len(src)
    while i < n:
        cmd = _read_command_name(src, i, n)
        if cmd == _NOP:
            # Drop one physical line. Multi-line `#nop {...}` blocks
            # are not consumed wholesale; their brace lines become
            # Passthrough, which the sort pass drops anyway.
            nl = src.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        # Drop #class {…} {open|close} — mirrors sanitize_profile.sh.
        nl = src.find("\n", i)
        phys_end = n if nl == -1 else nl
        if _CLASS_OPEN_CLOSE.match(src[i:phys_end]):
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

    # Per-entry post-parse: normalise tt++-rewritten multi-line bodies
    # back to flat form for action / alias / macro. Routes the new value
    # through `Entry.__setattr__`, which only clears `_raw` when the
    # string actually changes — so a flat-form entry round-trips
    # byte-exact, while a multi-line one regenerates canonically on
    # save. Structural (operates on `entry.body`, not the raw source),
    # so a legitimate nested `{` inside a body is unaffected.
    for item in items:
        if isinstance(item, Entry) and item.kind in _NORMALISE_BODY_KINDS:
            item.body = _normalise_body(item.body)

    sorted_items = [item for _cmd, item in _sorted_items(items)]
    return Profile(path=Path(path), items=sorted_items)


def serialize_profile(profile):
    """Render `profile.items` as the full file content (a string).

    Items are grouped by `#<command>` (Entry kinds plus any
    classifiable Passthrough) and sorted alphabetically within each
    group; groups are sorted alphabetically by command name and emitted
    with a single blank line between them. Blank lines, free text, and
    malformed Passthroughs in the input are dropped — see the Phase 6.2
    ADR for the rationale.

    Entry items with `_raw` still attached emit that verbatim (lossless
    round-trip for unmodified entries, including multi-line forms).
    Entries with `_raw=None` are regenerated canonically. `Passthrough`
    items emit their raw text.

    Entries whose `pattern.strip()` is empty are dropped entirely —
    these are abandoned create attempts surfaced by the editor's
    "+ New entry" sentinel. Other "soft-invalid" states (empty body,
    etc.) are written as-is.

    Each item is followed by a newline; the result therefore always
    ends with `\\n` when non-empty."""
    out = []
    prev_cmd = None
    for cmd, item in _sorted_items(profile.items):
        if prev_cmd is not None and prev_cmd != cmd:
            out.append("\n")
        if isinstance(item, Passthrough):
            out.append(item.raw + "\n")
        else:
            if item._raw is not None:
                out.append(item._raw + "\n")
            else:
                out.append(_serialize_entry(item) + "\n")
        prev_cmd = cmd
    return "".join(out)


def load_profile(path):
    """Read `path` (a `pathlib.Path` or `str`) and return the parsed
    `Profile`. Thin wrapper around `parse_profile`."""
    p = Path(path)
    with open(p, "r") as fh:
        src = fh.read()
    return parse_profile(src, p)


def save_profile(profile):
    """Serialise `profile` and write it to `profile.path` via a
    temp-file + rename.

    Before serialising, strips any `#alias` Entry whose pattern matches a
    name in `bridge/runtime/core_aliases.list` (ADR 0115 follow-up). The
    removed names are written to `profile.dropped_collisions` (always a
    fresh list, even when empty) so the caller can surface a message.
    See `_filter_core_collisions` for details."""
    _filter_core_collisions(profile)
    p = Path(profile.path)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w") as fh:
        fh.write(serialize_profile(profile))
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Core-alias collision filter (ADR 0115 follow-up)
# ---------------------------------------------------------------------------
# The runtime list is generated at launcher startup by
# bridge/launcher/core_aliases.py. We read it lazily on first save and
# cache the resulting set for the process lifetime — both the launcher
# and the in-game popup are short-lived enough that re-reading per call
# would only add I/O without changing behaviour.

_CORE_ALIASES_LIST_PATH = (
    Path(__file__).resolve().parents[2] / "bridge" / "runtime" / "core_aliases.list"
)
_CORE_ALIASES_CACHE = None  # set[str] once loaded; None = not yet loaded.


def _load_core_aliases():
    """Read the runtime list, caching for the process. Missing or empty
    file → empty set, which disables filtering (fail open)."""
    global _CORE_ALIASES_CACHE
    if _CORE_ALIASES_CACHE is not None:
        return _CORE_ALIASES_CACHE
    names = set()
    try:
        with open(_CORE_ALIASES_LIST_PATH, "r") as fh:
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                if line:
                    names.add(line)
    except OSError:
        pass
    _CORE_ALIASES_CACHE = names
    return names


def _reset_core_aliases_cache():
    """Test-only: clear the process-level cache so the next
    `_load_core_aliases` call re-reads the file. Tests that monkey-patch
    `_CORE_ALIASES_LIST_PATH` must call this to take effect."""
    global _CORE_ALIASES_CACHE
    _CORE_ALIASES_CACHE = None


def _filter_core_collisions(profile):
    """Strip `#alias` entries whose pattern matches a core-registered
    alias from `profile.items`, in place. Always resets
    `profile.dropped_collisions` to a fresh list (empty if no filter ran
    or no entries matched).

    Only `kind == "alias"` is filtered — actions, highlights, etc. are
    untouched. Non-Entry items (Passthroughs) pass through unchanged."""
    profile.dropped_collisions = []
    names = _load_core_aliases()
    if not names:
        return
    kept = []
    for item in profile.items:
        if (isinstance(item, Entry)
                and item.kind == "alias"
                and item.pattern in names):
            profile.dropped_collisions.append(item.pattern)
        else:
            kept.append(item)
    profile.items[:] = kept


def profile_has_core_collisions(profile):
    """Return True iff `profile.items` contains any `#alias` Entry that
    would be removed by `_filter_core_collisions`. Read-only — does not
    mutate the profile or its `dropped_collisions` attribute.

    Hosts that skip `save_profile` on a non-dirty profile use this to
    detect a pre-existing hand-edit collision and force a save anyway,
    so the file is cleaned and the user is notified."""
    names = _load_core_aliases()
    if not names:
        return False
    for item in profile.items:
        if (isinstance(item, Entry)
                and item.kind == "alias"
                and item.pattern in names):
            return True
    return False
