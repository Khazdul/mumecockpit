# bridge/launcher/run_stats.py — JSONL run-statistics aggregator.
#
# Pure library: no UI, no tmux, no Lua. Consumed by the in-game popup
# (run summary) and a future launcher run-browser. See docs/runs.md for
# the JSONL schema and lifecycle, and lua/core/run_log.lua for the
# authoritative list of event types and field shapes.

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

_BRIDGE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR   = os.path.dirname(_BRIDGE_DIR)
_DATA_RUNS_DIR = os.path.join(_PROJECT_DIR, "data", "runs")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class KillAgg:
    count: int = 0
    total_xp: int = 0


@dataclass
class PKillAgg:
    count: int = 0
    total_xp: int = 0


@dataclass
class RunStats:
    character: str
    start_ts: int = 0
    end_ts: int = 0
    is_active: bool = False
    duration_seconds: int = 0
    min_level: int | None = None
    current_level: int | None = None
    xp_at_start: int = 0
    xp_current: int = 0
    xp_gained: int = 0
    tp_at_start: int = 0
    tp_current: int = 0
    tp_gained: int = 0
    kills: dict[str, KillAgg] = field(default_factory=dict)
    pkills: dict[str, PKillAgg] = field(default_factory=dict)
    kill_events: list[tuple[int, int]] = field(default_factory=list)
    tp_events: list[tuple[int, int]] = field(default_factory=list)
    allies: list[str] = field(default_factory=list)
    achievements: list[tuple[int, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _character_dir(character: str) -> str:
    return os.path.join(_DATA_RUNS_DIR, character)


def _current_path(character: str) -> str:
    return os.path.join(_character_dir(character), "current.jsonl")


def _run_path(character: str, run_id: str) -> str:
    return os.path.join(_character_dir(character), run_id + ".jsonl")


def _run_id_from_ts(ts: int) -> str:
    # Matches os.date("%Y-%m-%dT%H-%M-%S", ts) in lua/core/run_log.lua.
    return time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(ts))


# ---------------------------------------------------------------------------
# JSONL reading (tolerant of malformed/partial lines from mid-write files)
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


def _read_run_start(path: str) -> dict | None:
    gen = _iter_rows(path)
    first = next(gen, None)
    gen.close()
    if isinstance(first, dict) and first.get("event") == "run_start":
        return first
    return None


def _last_event_ts(path: str) -> int | None:
    last = None
    for row in _iter_rows(path):
        ts = row.get("ts")
        if isinstance(ts, (int, float)):
            last = int(ts)
    return last


def _resolve_path(character: str, run_id: str, current_run_id: str | None) -> str | None:
    if current_run_id is not None and run_id == current_run_id:
        p = _current_path(character)
        return p if os.path.exists(p) else None
    p = _run_path(character, run_id)
    return p if os.path.exists(p) else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def current_run_id_for(character: str) -> str | None:
    rs = _read_run_start(_current_path(character))
    if rs is None:
        return None
    ts = rs.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    return _run_id_from_ts(int(ts))


def previous_run_chain(
    character: str,
    start_run_id: str,
    max_gap_seconds: int = 3600,
) -> list[str]:
    cur_id = current_run_id_for(character)
    chain: list[str] = [start_run_id]

    path = _resolve_path(character, start_run_id, cur_id)
    if path is None:
        return chain
    rs = _read_run_start(path)
    if rs is None:
        return chain

    while True:
        prev_id = rs.get("previous_run_id")
        if not isinstance(prev_id, str):
            break
        prev_path = _resolve_path(character, prev_id, cur_id)
        if prev_path is None:
            break
        prev_rs = _read_run_start(prev_path)
        if prev_rs is None:
            break
        prev_last_ts = _last_event_ts(prev_path)
        next_start_ts = rs.get("ts")
        if prev_last_ts is None or not isinstance(next_start_ts, (int, float)):
            break
        if int(next_start_ts) - prev_last_ts >= max_gap_seconds:
            break
        chain.insert(0, prev_id)
        rs = prev_rs

    return chain


def aggregate(character: str, run_ids: list[str]) -> RunStats:
    stats = RunStats(character=character)
    cur_id = current_run_id_for(character)

    seen_run_start = False
    allies: set[str] = set()

    for run_id in run_ids:
        path = _resolve_path(character, run_id, cur_id)
        if path is None:
            continue
        for row in _iter_rows(path):
            if row.get("event") == "run_start":
                _apply_run_start_row(stats, row, first=not seen_run_start)
                seen_run_start = True
            else:
                _apply_row(stats, row, allies)

    stats.allies = sorted(allies)
    stats.xp_gained = stats.xp_current - stats.xp_at_start
    stats.tp_gained = stats.tp_current - stats.tp_at_start

    if cur_id is not None and run_ids and run_ids[-1] == cur_id:
        stats.is_active = True
        # For an active run, give consumers a "now"-anchored duration so
        # the popup can show elapsed time without polling the file's mtime.
        now = int(time.time())
        if now > stats.end_ts:
            stats.end_ts = now

    if stats.start_ts and stats.end_ts:
        stats.duration_seconds = max(0, stats.end_ts - stats.start_ts)

    return stats


def load_current_run_stats(character: str) -> RunStats | None:
    cur_id = current_run_id_for(character)
    if cur_id is None:
        return None
    chain = previous_run_chain(character, cur_id)
    return aggregate(character, chain)


# ---------------------------------------------------------------------------
# Per-row accumulation
# ---------------------------------------------------------------------------

def _apply_row(stats: RunStats, row: dict, allies: set[str]) -> None:
    event = row.get("event")
    ts = row.get("ts")
    if not isinstance(ts, (int, float)):
        return
    ts = int(ts)
    if ts > stats.end_ts:
        stats.end_ts = ts

    if event == "level_up":
        _bump_level(stats, row.get("level"))
    elif event == "kill":
        name = row.get("mob_name")
        delta = _as_int(row.get("xp_delta"))
        if isinstance(name, str):
            agg = stats.kills.setdefault(name, KillAgg())
            agg.count += 1
            agg.total_xp += delta
        stats.xp_current += delta
        stats.kill_events.append((ts, delta))
    elif event == "pkill":
        name = row.get("name")
        delta = _as_int(row.get("xp_delta"))
        if isinstance(name, str):
            agg = stats.pkills.setdefault(name, PKillAgg())
            agg.count += 1
            agg.total_xp += delta
        stats.xp_current += delta
        stats.kill_events.append((ts, delta))
    elif event == "tp_gained":
        delta = _as_int(row.get("tp_delta"))
        stats.tp_current += delta
        stats.tp_events.append((ts, delta))
    elif event == "group_changed":
        members = row.get("members")
        if isinstance(members, list):
            for m in members:
                if isinstance(m, str) and m != stats.character:
                    allies.add(m)
    elif event == "achievement":
        name = row.get("name")
        if isinstance(name, str):
            stats.achievements.append((ts, name))
    # Unknown event types (including orphan_close, run_end, char_death) are
    # intentionally ignored for aggregation; their ts still moved end_ts above.


def _apply_run_start_row(stats: RunStats, row: dict, first: bool) -> None:
    ts = row.get("ts")
    if not isinstance(ts, (int, float)):
        return
    ts = int(ts)
    if ts > stats.end_ts:
        stats.end_ts = ts

    xp    = _as_int_or_none(row.get("xp"))
    tp    = _as_int_or_none(row.get("tp"))
    level = _as_int_or_none(row.get("level"))

    if first:
        stats.start_ts = ts
        if xp is not None:
            stats.xp_at_start = xp
            stats.xp_current  = xp
        if tp is not None:
            stats.tp_at_start = tp
            stats.tp_current  = tp
        if level is not None:
            stats.min_level     = level
            stats.current_level = level
    else:
        # Subsequent run_start in a chained session: re-baseline current xp/tp
        # so any between-run drift (untracked spend/gain during a disconnect)
        # is reflected in xp_current/tp_current.
        if xp is not None:
            stats.xp_current = xp
        if tp is not None:
            stats.tp_current = tp
        _bump_level(stats, level)


def _bump_level(stats: RunStats, level) -> None:
    if not isinstance(level, int):
        return
    if stats.min_level is None or level < stats.min_level:
        stats.min_level = level
    if stats.current_level is None or level > stats.current_level:
        stats.current_level = level


def _as_int(v) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _as_int_or_none(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    return None
