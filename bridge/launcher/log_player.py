# bridge/launcher/log_player.py — chain log loading + ANSI parsing.
#
# Pure logic module for the launcher's log_view frame. No prompt_toolkit
# Application or rendering — just data model, .log parsing, and
# run-boundary tracking. See docs/runs.md for the .log format and
# docs/launcher.md "log_view" for the consumer contract.

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from palette import C_LOG_PLAYER_INPUT

_BRIDGE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR   = os.path.dirname(_BRIDGE_DIR)
_DATA_RUNS_DIR = os.path.join(_PROJECT_DIR, "data", "runs")


# ---------------------------------------------------------------------------
# ANSI SGR parser — 16-colour + bright, plus bold/underline.
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
                self.fg = _FG_BASE[c]
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

    def style(self):
        parts = []
        if self.bold:
            parts.append("bold")
        if self.underline:
            parts.append("underline")
        if self.fg is not None:
            parts.append(f"fg:{self.fg}")
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

    def __bool__(self):
        return bool(self.events)

    def __len__(self):
        return len(self.events)

    def run_at(self, event_index: int):
        """Return (run_id, run_ordinal, total_runs) for an event index.

        `run_ordinal` is the original 1-based position in `run_ids`,
        NOT renumbered for skipped (missing-log) runs.
        """
        if event_index < 0 or event_index >= len(self.events):
            raise IndexError(event_index)
        ev = self.events[event_index]
        return (ev.run_id, self._ordinal[ev.run_id], len(self.run_ids))
