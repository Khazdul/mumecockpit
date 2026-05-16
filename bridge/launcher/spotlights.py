# bridge/launcher/spotlights.py — cross-character spotlight reel.
#
# Pure library: walks every character's sealed runs, extracts the four
# tracked event types (char_death, level_up, pkill, achievement), merges
# neighbouring events within a single run into multi-event spotlights,
# interleaves spotlights across characters via a "no two adjacent from
# the same character" rotation, and (lazily) slices each spotlight's
# `.log` to a [pre-roll, post-roll] window. See docs/runs.md for the
# JSONL/log schema, ADR 0065 for the aggregator pattern, and
# docs/launcher.md for how the launcher consumes this.

from __future__ import annotations

import bisect
import json
import os
from collections import deque
from dataclasses import dataclass, field

import log_player

_BRIDGE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR   = os.path.dirname(_BRIDGE_DIR)
_DATA_RUNS_DIR = os.path.join(_PROJECT_DIR, "data", "runs")

# Window around a spotlight, in seconds. Multi-event spotlights anchor
# pre-roll on the first event and post-roll on the last.
_PRE_ROLL_S  = 10
_POST_ROLL_S = 5
# Two events merge into a single spotlight if the gap between them is
# <= this many seconds (i.e. the next event falls within the previous
# event's post-roll).
_MERGE_GAP_S = _POST_ROLL_S


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SpotlightEvent:
    kind: str                          # "death" | "level_up" | "pkill" | "achievement"
    ts: int                            # epoch seconds (JSONL `ts`)
    label: str                         # pre-rendered display string
    extra: dict = field(default_factory=dict)


@dataclass
class Spotlight:
    character: str
    run_id: str
    log_path: str
    events: list                       # list[SpotlightEvent], chronological
    window_start_us: int               # nominal at aggregate time, clamped on lazy load
    window_end_us: int
    log_events: list = field(default_factory=list)  # populated lazily
    event_offsets_us: list = field(default_factory=list)  # parallel to events
    _loaded: bool = False              # private: idempotency flag


@dataclass
class SpotlightReel:
    spotlights: list                   # list[Spotlight]
    total_count: int


# ---------------------------------------------------------------------------
# JSONL row → event-kind dispatch
# ---------------------------------------------------------------------------

def _label_death(row: dict) -> tuple[str, dict]:
    level = row.get("level")
    if isinstance(level, int):
        return f"Death (level {level})", {"level": level}
    return "Death", {}


def _label_level_up(row: dict) -> tuple[str, dict]:
    level = row.get("level")
    if isinstance(level, int):
        return f"Reached level {level}", {"level": level}
    # Defensive: level_up rows always carry a level, but tolerate gracefully.
    return "Level up", {}


def _label_pkill(row: dict) -> tuple[str, dict]:
    name = row.get("name") if isinstance(row.get("name"), str) else ""
    race = row.get("race") if isinstance(row.get("race"), str) else ""
    if name and race:
        target = f"{name} {race}"
    else:
        target = name or "an unknown foe"
    return f"PvP kill: {target}", {"name": name, "race": race}


def _label_achievement(row: dict) -> tuple[str, dict]:
    name = row.get("name") if isinstance(row.get("name"), str) else ""
    if not name:
        return "Achievement", {}
    return f"Achievement: {name}", {"name": name}


# JSONL event → (kind, label_fn)
_TRACKED = {
    "char_death":  ("death",       _label_death),
    "level_up":    ("level_up",    _label_level_up),
    "pkill":       ("pkill",       _label_pkill),
    "achievement": ("achievement", _label_achievement),
}


# ---------------------------------------------------------------------------
# JSONL reading (tolerant of malformed/partial lines)
# ---------------------------------------------------------------------------

def _iter_rows(path: str):
    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def _extract_events(path: str) -> list:
    """Return the spotlight-eligible events in a sealed JSONL, in file order."""
    out: list = []
    for row in _iter_rows(path):
        ev = row.get("event")
        spec = _TRACKED.get(ev)
        if spec is None:
            continue
        ts = row.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        kind, label_fn = spec
        label, extra = label_fn(row)
        out.append(SpotlightEvent(kind=kind, ts=int(ts), label=label, extra=extra))
    return out


# ---------------------------------------------------------------------------
# Spotlight building (merge within a single run)
# ---------------------------------------------------------------------------

def _build_spotlights_for_run(
    character: str,
    run_id: str,
    log_path: str,
    events: list,
) -> list:
    """Group events from one run into spotlights, merging neighbours
    within `_MERGE_GAP_S`."""
    if not events:
        return []
    events = sorted(events, key=lambda e: e.ts)
    groups: list = [[events[0]]]
    for ev in events[1:]:
        prev = groups[-1][-1]
        if ev.ts - prev.ts <= _MERGE_GAP_S:
            groups[-1].append(ev)
        else:
            groups.append([ev])

    spotlights: list = []
    for group in groups:
        first_ts = group[0].ts
        last_ts  = group[-1].ts
        spotlights.append(Spotlight(
            character=character,
            run_id=run_id,
            log_path=log_path,
            events=group,
            window_start_us=(first_ts - _PRE_ROLL_S) * 1_000_000,
            window_end_us=(last_ts + _POST_ROLL_S) * 1_000_000,
        ))
    return spotlights


# ---------------------------------------------------------------------------
# Rotation: interleave spotlights so two adjacent never share a character
# unless that's all that's left.
# ---------------------------------------------------------------------------

def _rotate(per_char_groups: dict) -> list:
    """Interleave per-character spotlight queues. Each queue is sorted
    newest-first (descending by first-event ts) by the caller. At each
    step picks the queue whose head spotlight has the most recent
    timestamp, skipping the just-picked character when an alternative
    exists."""
    queues: dict = {ch: deque(spots) for ch, spots in per_char_groups.items() if spots}
    reel: list = []
    last_char = None
    while queues:
        candidates = list(queues.keys())
        if last_char in candidates and len(candidates) > 1:
            candidates = [c for c in candidates if c != last_char]
        pick = max(candidates, key=lambda c: queues[c][0].events[0].ts)
        reel.append(queues[pick].popleft())
        last_char = pick
        if not queues[pick]:
            del queues[pick]
    return reel


# ---------------------------------------------------------------------------
# Aggregation entry point
# ---------------------------------------------------------------------------

def aggregate_spotlights(runs_dir: str | None = None) -> SpotlightReel:
    """Walk every character directory, extract tracked events from sealed
    runs that have a paired .log, build merged spotlights per run, and
    interleave them into a SpotlightReel."""
    base = runs_dir if runs_dir is not None else _DATA_RUNS_DIR
    if not os.path.isdir(base):
        return SpotlightReel(spotlights=[], total_count=0)

    try:
        char_names = sorted(os.listdir(base))
    except OSError:
        return SpotlightReel(spotlights=[], total_count=0)

    per_char: dict = {}
    for char in char_names:
        char_dir = os.path.join(base, char)
        if not os.path.isdir(char_dir):
            continue
        try:
            entries = os.listdir(char_dir)
        except OSError:
            continue

        char_spotlights: list = []
        for fn in entries:
            if not fn.endswith(".jsonl") or fn == "current.jsonl":
                continue
            run_id = fn[:-len(".jsonl")]
            log_path = os.path.join(char_dir, run_id + ".log")
            if not os.path.exists(log_path):
                continue
            jsonl_path = os.path.join(char_dir, fn)
            events = _extract_events(jsonl_path)
            if not events:
                continue
            char_spotlights.extend(_build_spotlights_for_run(
                char, run_id, log_path, events,
            ))

        if not char_spotlights:
            continue
        # Newest-first within a character.
        char_spotlights.sort(key=lambda s: s.events[0].ts, reverse=True)
        per_char[char] = char_spotlights

    reel = _rotate(per_char)
    return SpotlightReel(spotlights=reel, total_count=len(reel))


# ---------------------------------------------------------------------------
# Lazy .log loading + window clamping
# ---------------------------------------------------------------------------

def _parse_full_log(path: str) -> list:
    """Wrapper around log_player._parse_log_file that returns the full
    event list for `path` (run_id field is unused at the spotlight layer,
    but populated for parity)."""
    events: list = []
    run_id = os.path.basename(path)
    if run_id.endswith(".log"):
        run_id = run_id[:-len(".log")]
    log_player._parse_log_file(path, run_id, events)
    return events


def load_spotlight_log_events(spotlight: Spotlight, cache: dict) -> None:
    """Populate `spotlight.log_events` (sliced to `[window_start_us,
    window_end_us]`), clamping the window to the actual `.log` range and
    populating `spotlight.event_offsets_us`. Idempotent — safe to call
    multiple times. Parsed files are cached in `cache` keyed by log_path
    so a chain of spotlights sharing a `.log` parses it exactly once.

    If clamping leaves an empty window (event timestamps fall outside
    the log range — corruption or clock skew), `spotlight.log_events`
    stays empty and the caller is expected to drop the spotlight."""
    if spotlight._loaded:
        return

    parsed = cache.get(spotlight.log_path)
    if parsed is None:
        parsed = _parse_full_log(spotlight.log_path)
        cache[spotlight.log_path] = parsed

    if not parsed:
        spotlight.log_events = []
        spotlight.event_offsets_us = [0] * len(spotlight.events)
        spotlight._loaded = True
        return

    log_min_us = parsed[0].ts_us
    log_max_us = parsed[-1].ts_us

    win_start = max(spotlight.window_start_us, log_min_us)
    win_end   = min(spotlight.window_end_us, log_max_us)

    if win_start >= win_end:
        spotlight.window_start_us = win_start
        spotlight.window_end_us   = win_start
        spotlight.log_events = []
        spotlight.event_offsets_us = [0] * len(spotlight.events)
        spotlight._loaded = True
        return

    spotlight.window_start_us = win_start
    spotlight.window_end_us   = win_end

    # parsed is sorted ascending by ts_us (log files are monotonic).
    ts_us_list = [ev.ts_us for ev in parsed]
    lo = bisect.bisect_left(ts_us_list, win_start)
    hi = bisect.bisect_right(ts_us_list, win_end)
    spotlight.log_events = parsed[lo:hi]

    offsets: list = []
    for ev in spotlight.events:
        off = ev.ts * 1_000_000 - win_start
        if off < 0:
            off = 0
        offsets.append(off)
    spotlight.event_offsets_us = offsets
    spotlight._loaded = True


# ---------------------------------------------------------------------------
# Playback adapter — LogPlayback-shaped wrapper over a reel
# ---------------------------------------------------------------------------

class SpotlightPlayback:
    """LogPlayback-compatible wrapper over a list of (loaded) spotlights.

    The playback consumer (launcher's log_view frame) only requires
    `events`, `playback_offset_us`, `total_duration_us`, `loaded_run_ids`,
    and `run_at(idx)`. Spotlights are stitched into a single timeline
    with zero gap between them: spotlight N+1's first event sits at
    playback offset (sum of spotlight 0..N durations).

    Additional spotlight-specific accessors:
      `spotlight_of_event_idx(i)` — which spotlight an event belongs to.
      `spotlight_at_offset(us)`   — bisect lookup by playback offset.
      `spotlight_start_offsets_us`— per-spotlight playback offset.
      `event_progress(spot, off)` — (active_event_idx, seconds_to_next).
    """

    def __init__(self, spotlights: list):
        self.spotlights: list = list(spotlights)
        self.character: str = ""

        events: list = []
        playback_offset_us: list = []
        spotlight_of_event_idx: list = []
        spotlight_start_offsets_us: list = []
        loaded_run_ids: list = []

        cursor_us = 0
        for spot_idx, spot in enumerate(self.spotlights):
            spotlight_start_offsets_us.append(cursor_us)
            if spot.run_id not in loaded_run_ids:
                loaded_run_ids.append(spot.run_id)
            for ev in spot.log_events:
                events.append(ev)
                rel = ev.ts_us - spot.window_start_us
                if rel < 0:
                    rel = 0
                playback_offset_us.append(cursor_us + rel)
                spotlight_of_event_idx.append(spot_idx)
            dur = spot.window_end_us - spot.window_start_us
            if dur < 0:
                dur = 0
            cursor_us += dur

        self.events = events
        self.playback_offset_us = playback_offset_us
        self.total_duration_us = cursor_us
        self.spotlight_of_event_idx = spotlight_of_event_idx
        self.spotlight_start_offsets_us = spotlight_start_offsets_us
        self.loaded_run_ids = loaded_run_ids
        self.run_ids = list(loaded_run_ids)

    def __bool__(self):
        return bool(self.events)

    def __len__(self):
        return len(self.events)

    def run_at(self, event_index: int):
        """Return (spotlight, spotlight_ordinal, total) at the given
        event index. Spotlight ordinal is 1-based to match the
        LogPlayback.run_at contract used by the header renderer."""
        if event_index < 0 or event_index >= len(self.events):
            raise IndexError(event_index)
        spot_idx = self.spotlight_of_event_idx[event_index]
        spot = self.spotlights[spot_idx]
        return (spot, spot_idx + 1, len(self.spotlights))

    def run_info(self, run_id: str) -> dict:
        # SpotlightPlayback doesn't use the LogPlayback.run_info() path —
        # the launcher's spotlight-mode header reads fields off the
        # active Spotlight directly. This stub exists for parity.
        return {}

    def spotlight_at_offset(self, offset_us: int) -> int:
        """Return the index of the spotlight playing at `offset_us`."""
        if not self.spotlight_start_offsets_us:
            return 0
        i = bisect.bisect_right(self.spotlight_start_offsets_us, offset_us) - 1
        if i < 0:
            i = 0
        if i >= len(self.spotlights):
            i = len(self.spotlights) - 1
        return i

    def event_progress(self, spotlight: Spotlight, offset_within_spotlight_us: int):
        """Drive the countdown overlay: returns
        (active_event_index, seconds_to_next_event_or_None).

        `active_event_index` is the index of the most recent event that
        has fired (== -1 if none have yet). `seconds_to_next` is the
        non-negative float gap to the next pending event; None when no
        further events remain in this spotlight."""
        offsets = spotlight.event_offsets_us
        if not offsets:
            return (-1, None)
        cur = max(0, int(offset_within_spotlight_us))
        # active: largest i with offsets[i] <= cur (or -1 if none yet).
        active = bisect.bisect_right(offsets, cur) - 1
        if active >= len(offsets) - 1:
            return (active, None)
        next_off = offsets[active + 1]
        seconds = max(0.0, (next_off - cur) / 1_000_000.0)
        return (active, seconds)


# ---------------------------------------------------------------------------
# Smoke entry point
# ---------------------------------------------------------------------------

def _smoke_main() -> None:
    reel = aggregate_spotlights()
    print(f"reel: {reel.total_count} spotlights")
    cache: dict = {}
    for i, spot in enumerate(reel.spotlights):
        load_spotlight_log_events(spot, cache)
        kinds = ",".join(e.kind for e in spot.events)
        dropped = "" if spot.log_events else "  (dropped: empty window)"
        print(f"  {i+1:3d}. {spot.character:12s} {spot.run_id}  "
              f"events={len(spot.events)} [{kinds}]  "
              f"log_events={len(spot.log_events)}{dropped}")


if __name__ == "__main__":
    _smoke_main()
