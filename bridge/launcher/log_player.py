# bridge/launcher/log_player.py — chain log loading + ANSI parsing.
#
# Pure logic module for the launcher's log_view frame. No prompt_toolkit
# Application or rendering — just data model, .log parsing, and
# run-boundary tracking. See docs/runs.md for the .log format and
# docs/launcher.md "log_view" for the consumer contract.

from __future__ import annotations

import bisect
import json
import os
import re
from dataclasses import dataclass, field

from palette import C_LOG_PLAYER_INPUT

# Tracked-event kind → strip letter. Shared by both playback modes:
# chain mode keys off the raw run-archive JSONL `event` names, spotlight
# mode off `SpotlightEvent.kind` (which normalises char_death to "death").
# Both "char_death" and "death" map to D so the contract is mode-agnostic.
MARKER_KIND_TO_LETTER = {
    "pkill":      "K",
    "char_death": "D",
    "death":      "D",
    "achievement": "A",
    "level_up":   "L",
}

_BRIDGE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR   = os.path.dirname(_BRIDGE_DIR)
_DATA_RUNS_DIR = os.path.join(_PROJECT_DIR, "data", "runs")


# ---------------------------------------------------------------------------
# ANSI SGR parser — 16-colour + bright, plus bold/underline. Bold brightens
# the foreground (terminal convention) rather than being an orthogonal font
# attribute: a bold base colour (30..37) resolves to its bright variant, and
# bold with no explicit fg renders bright white. "bold" is still emitted as a
# font weight alongside the brightened colour.
# Unknown codes (256-colour, truecolour, italic, etc.) are silently
# dropped per spec: the affected text renders uncoloured rather than
# crashing the player.
# ---------------------------------------------------------------------------
_ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")

_FG_BASE = {
    30: "#000000", 31: "#cd0000", 32: "#00cd00", 33: "#cdcd00",
    34: "#0000ee", 35: "#cd00cd", 36: "#00cdcd", 37: "#e5e5e5",
    90: "#7f7f7f", 91: "#ff0000", 92: "#00ff00", 93: "#ffff00",
    94: "#5c5cff", 95: "#ff00ff", 96: "#00ffff", 97: "#ffffff",
}
_BG_BASE = {
    40: "#000000", 41: "#cd0000", 42: "#00cd00", 43: "#cdcd00",
    44: "#0000ee", 45: "#cd00cd", 46: "#00cdcd", 47: "#e5e5e5",
    100: "#7f7f7f", 101: "#ff0000", 102: "#00ff00", 103: "#ffff00",
    104: "#5c5cff", 105: "#ff00ff", 106: "#00ffff", 107: "#ffffff",
}


class _SGRState:
    __slots__ = ("fg", "bg", "bold", "underline")

    def __init__(self):
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False

    def reset(self):
        self.fg = None
        self.bg = None
        self.bold = False
        self.underline = False

    def apply(self, codes):
        i = 0
        n = len(codes)
        while i < n:
            c = codes[i]
            if c == 0:
                self.reset()
            elif c == 1:
                self.bold = True
            elif c == 22:
                self.bold = False
            elif c == 4:
                self.underline = True
            elif c == 24:
                self.underline = False
            elif c == 39:
                self.fg = None
            elif c == 49:
                self.bg = None
            elif c in _FG_BASE:
                # Store the raw SGR code; style() resolves it against `bold`.
                self.fg = c
            elif c in _BG_BASE:
                self.bg = _BG_BASE[c]
            elif c == 38 and i + 1 < n:
                # 256-colour / truecolour foreground: skip params, leave fg unset.
                if codes[i + 1] == 5 and i + 2 < n:
                    self.fg = None
                    i += 2
                elif codes[i + 1] == 2 and i + 4 < n:
                    self.fg = None
                    i += 4
            elif c == 48 and i + 1 < n:
                if codes[i + 1] == 5 and i + 2 < n:
                    self.bg = None
                    i += 2
                elif codes[i + 1] == 2 and i + 4 < n:
                    self.bg = None
                    i += 4
            # Any other code is silently ignored.
            i += 1

    def _effective_fg(self):
        """Resolve the stored fg SGR code into a hex colour, applying bold-as-
        brightness. Returns None when no foreground should be emitted."""
        if self.fg is None:
            # Bold with no explicit colour renders bright white (terminal
            # convention); otherwise leave the default grey foreground.
            return "#ffffff" if self.bold else None
        if 30 <= self.fg <= 37 and self.bold:
            return _FG_BASE[self.fg + 60]
        return _FG_BASE[self.fg]

    def style(self):
        parts = []
        if self.bold:
            parts.append("bold")
        if self.underline:
            parts.append("underline")
        fg = self._effective_fg()
        if fg is not None:
            parts.append(f"fg:{fg}")
        if self.bg is not None:
            parts.append(f"bg:{self.bg}")
        return " ".join(parts)


def parse_ansi(text):
    """Split `text` into a list of `(style, run)` prompt_toolkit fragments,
    interpreting embedded ANSI SGR sequences. Unrecognised sequences are
    consumed; the text after them renders with whatever style state survived."""
    if "\x1b" not in text:
        return [("", text)] if text else []
    state = _SGRState()
    fragments = []
    pos = 0
    for m in _ANSI_RE.finditer(text):
        if m.start() > pos:
            fragments.append((state.style(), text[pos:m.start()]))
        params = m.group(1)
        if params:
            codes = []
            for p in params.split(";"):
                if p.isdigit():
                    codes.append(int(p))
            if codes:
                state.apply(codes)
            else:
                state.apply([0])
        else:
            state.apply([0])
        pos = m.end()
    if pos < len(text):
        fragments.append((state.style(), text[pos:]))
    return fragments


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------
@dataclass
class LogEvent:
    ts_us: int
    direction: str            # "in" or "out"
    text: str                 # raw line body, prefix and "> " stripped, CR stripped
    run_id: str
    fragments: list = field(default_factory=list)  # [(style, run), ...]


# Line format per docs/runs.md:
#   <microseconds> <raw_line>           # inbound (any non-"> " prefix)
#   <microseconds> > <command>          # outbound
_LINE_RE = re.compile(r"^(\d+) (.*)$")


def _log_path(character: str, run_id: str) -> str:
    return os.path.join(_DATA_RUNS_DIR, character, run_id + ".log")


def _parse_log_file(path: str, run_id: str, out_events: list):
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line:
                continue
            m = _LINE_RE.match(line)
            if not m:
                continue
            try:
                ts_us = int(m.group(1))
            except ValueError:
                continue
            rest = m.group(2)
            if rest.startswith("> "):
                cmd = rest[2:].rstrip("\r")
                ev = LogEvent(
                    ts_us=ts_us, direction="out", text=cmd, run_id=run_id,
                    fragments=[(C_LOG_PLAYER_INPUT, cmd)] if cmd else [],
                )
            else:
                ev = LogEvent(
                    ts_us=ts_us, direction="in", text=rest, run_id=run_id,
                    fragments=parse_ansi(rest),
                )
            out_events.append(ev)


# Inter-event gaps longer than this collapse to 0 during playback — keeps
# multi-day chain replays watchable while still respecting natural pacing.
_PLAYBACK_GAP_CAP_US = 10_000_000


class LogPlayback:
    """Loaded chain log: events from all runs in `run_ids` merged in
    microsecond order. Runs whose `.log` file is missing are silently
    skipped — `run_ids` retains the original chain ordering for
    `run_at()` ordinals.
    """

    def __init__(self, character: str, run_ids: list, runs_dir: str | None = None):
        self.character = character
        self.run_ids = list(run_ids)
        self._runs_dir = runs_dir if runs_dir is not None else _DATA_RUNS_DIR
        self._ordinal = {rid: i + 1 for i, rid in enumerate(self.run_ids)}
        self._run_info_cache: dict = {}  # run_id -> dict | None (None = missing)
        self.loaded_run_ids: list = []  # subset that actually had a .log
        self.events: list = []
        for rid in self.run_ids:
            path = (os.path.join(self._runs_dir, character, rid + ".log")
                    if runs_dir is not None else _log_path(character, rid))
            if not os.path.exists(path):
                continue
            self.loaded_run_ids.append(rid)
            _parse_log_file(path, rid, self.events)
        # Stable sort by ts_us; events within a single file are already
        # monotonic, this only matters across files when clocks shift.
        self.events.sort(key=lambda e: e.ts_us)

        # Per-event playback offset (microseconds from event 0). Gaps over
        # _PLAYBACK_GAP_CAP_US are clamped to 0 so an overnight pause in a
        # chain doesn't make the player sit silent for hours.
        self.playback_offset_us: list = []
        offset = 0
        prev_ts = None
        for ev in self.events:
            if prev_ts is not None:
                gap = ev.ts_us - prev_ts
                if 0 < gap <= _PLAYBACK_GAP_CAP_US:
                    offset += gap
            self.playback_offset_us.append(offset)
            prev_ts = ev.ts_us
        self.total_duration_us = self.playback_offset_us[-1] if self.playback_offset_us else 0

        # Tracked-event strip markers, computed once by set_marker_events().
        self._marker_offsets: list = []

    def __bool__(self):
        return bool(self.events)

    def __len__(self):
        return len(self.events)

    def offset_for_ts_us(self, ts_us: int) -> int:
        """Map a wall-clock timestamp (microseconds since epoch) onto a
        playback offset by snapping to the nearest log line by ts_us, then
        returning that line's `playback_offset_us`. Handles stitched runs
        and the chain's gap clamping transparently. Result is clamped to
        `[0, total_duration_us]`. Returns 0 when there are no events."""
        if not self.events:
            return 0
        ts_list = [ev.ts_us for ev in self.events]
        i = bisect.bisect_left(ts_list, ts_us)
        # Pick whichever neighbour is closest in wall-clock time.
        if i <= 0:
            idx = 0
        elif i >= len(ts_list):
            idx = len(ts_list) - 1
        else:
            before = ts_list[i - 1]
            after  = ts_list[i]
            idx = i if (after - ts_us) < (ts_us - before) else i - 1
        off = self.playback_offset_us[idx]
        if off < 0:
            return 0
        if off > self.total_duration_us:
            return self.total_duration_us
        return off

    def _snap_marker_offset(self, kind: str, ts_seconds: int, ident: str) -> int:
        """Return a playback offset (us) for a marker. For pkill / char_death,
        find the matching .log line near the fold second and return its
        `playback_offset_us`. Otherwise (or if no line matches) fall back to
        `offset_for_ts_us(ts_seconds * 1e6)`.

        The marker carries only the whole-second fold time, so snapping by
        time lands several bursty-combat lines off the real event line. The
        precise line is in the .log (microsecond ts_us); we content-match it:
            pkill      -> plain text contains "R.I.P."
            char_death -> plain text contains "You are dead"
        Matching uses each event's PLAIN text (ANSI stripped by joining the
        fragment texts), not the raw `ev.text`."""
        ts_us = ts_seconds * 1_000_000
        if kind not in ("pkill", "char_death"):
            return self.offset_for_ts_us(ts_us)
        if not self.events:
            return self.offset_for_ts_us(ts_us)

        needle = "R.I.P." if kind == "pkill" else "You are dead"

        # Bound the candidate window [ts_seconds - 1, ts_seconds + 1] by
        # ts_us, then scan that slice. The R.I.P. line is expected at or
        # before the fold second; the ±1 s slop covers second-flooring and
        # the ~500 ms fold delay.
        ts_list = [ev.ts_us for ev in self.events]
        lo = bisect.bisect_left(ts_list, (ts_seconds - 1) * 1_000_000)
        hi = bisect.bisect_right(ts_list, (ts_seconds + 2) * 1_000_000 - 1)

        matches: list[int] = []  # indices into self.events
        for i in range(lo, hi):
            ev = self.events[i]
            if ev.direction != "in":
                continue
            sec = ev.ts_us // 1_000_000
            if sec < ts_seconds - 1 or sec > ts_seconds + 1:
                continue
            plain = "".join(t for _, t in ev.fragments)
            if needle in plain:
                matches.append(i)

        if not matches:
            return self.offset_for_ts_us(ts_us)

        chosen: int | None = None
        # 1. Prefer a matching line whose plain text contains the ident.
        if ident:
            for i in matches:
                plain = "".join(t for _, t in self.events[i].fragments)
                if ident in plain:
                    chosen = i
                    break
        # 2. Else the latest matching line at or before the fold second.
        if chosen is None:
            at_or_before = [i for i in matches if self.events[i].ts_us <= ts_us]
            if at_or_before:
                chosen = at_or_before[-1]
        # 3. Else the matching line nearest the fold second by ts_us.
        if chosen is None:
            chosen = min(matches, key=lambda i: abs(self.events[i].ts_us - ts_us))

        return self.playback_offset_us[chosen]

    def set_marker_events(self, events: list) -> None:
        """Build the strip-marker list from `(kind, ts_seconds, ident)` tuples
        (as produced by `run_stats.marker_events`). Each kind is mapped to
        a strip letter via `MARKER_KIND_TO_LETTER` (unknown kinds skipped)
        and its wall-clock ts resolved to a playback offset via
        `_snap_marker_offset` (content-match for pkill / char_death, else the
        time-snap). Computed once and cached for `event_markers()`."""
        out: list = []
        for kind, ts, ident in events:
            letter = MARKER_KIND_TO_LETTER.get(kind)
            if letter is None:
                continue
            off = self._snap_marker_offset(kind, int(ts), ident)
            out.append((letter, off))
        self._marker_offsets = out

    def event_markers(self):
        """(letter, offset_us) for each tracked event, offset within
        [0, total_duration_us]. letter ∈ {'K','D','A','L'}.

        Mode-agnostic contract read by the launcher's right-edge playback
        strip (mirrors `SpotlightPlayback.event_markers`). Populated by
        `set_marker_events()` from the chain's run-archive JSONL; defaults
        to `[]` until then."""
        return self._marker_offsets

    def run_at(self, event_index: int):
        """Return (run_id, run_ordinal, total_runs) for an event index.

        `run_ordinal` is the original 1-based position in `run_ids`,
        NOT renumbered for skipped (missing-log) runs.
        """
        if event_index < 0 or event_index >= len(self.events):
            raise IndexError(event_index)
        ev = self.events[event_index]
        return (ev.run_id, self._ordinal[ev.run_id], len(self.run_ids))

    def run_info(self, run_id: str) -> dict:
        """Return `{character, start_level, start_ts}` for a run, parsed
        from the sealed `<run_id>.jsonl`'s first `run_start` row.

        Cached on first access. Missing or unreadable files cache an
        empty dict so subsequent calls don't re-touch the disk. Returned
        dict keys may be absent when the source row lacked them.
        """
        cached = self._run_info_cache.get(run_id)
        if cached is not None:
            return cached
        info: dict = {}
        path = os.path.join(self._runs_dir, self.character, run_id + ".jsonl")
        try:
            f = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            self._run_info_cache[run_id] = info
            return info
        with f:
            first = f.readline()
        if first:
            try:
                row = json.loads(first)
            except ValueError:
                row = None
            if isinstance(row, dict) and row.get("event") == "run_start":
                if isinstance(row.get("character"), str):
                    info["character"] = row["character"]
                if isinstance(row.get("level"), int):
                    info["start_level"] = row["level"]
                if isinstance(row.get("ts"), (int, float)):
                    info["start_ts"] = int(row["ts"])
        self._run_info_cache[run_id] = info
        return info
