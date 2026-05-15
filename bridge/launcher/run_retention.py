# bridge/launcher/run_retention.py — 14-day retention sweep for run logs.
#
# Pure library: no UI, no tmux, no Lua. The launcher calls
# prune_expired_runs() once at boot, before the main menu renders. Sealed
# runs older than the TTL are deleted unless a sidecar
# <run-id>.meta.json marks the run as saved. See docs/runs.md "Meta
# sidecar" + "Retention" sections, and
# docs/decisions/0074-run-retention-and-saved-meta.md.

from __future__ import annotations

import json
import os
import time

from run_stats import _DATA_RUNS_DIR, _character_dir, _run_id_from_ts

RETENTION_TTL_SECONDS = 14 * 86400

_RUN_ID_FMT = "%Y-%m-%dT%H-%M-%S"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prune_expired_runs(ttl_seconds: int = RETENTION_TTL_SECONDS,
                       now: float | None = None) -> None:
    """Delete sealed runs older than `ttl_seconds` that are not marked saved.

    Sweeps every character directory under `data/runs/`. For each sealed
    `<run-id>.jsonl` whose run-id parses as a timestamp older than the
    cutoff and that lacks a `<run-id>.meta.json` with `"saved": true`,
    removes the `.jsonl`, the paired `.log`, and any stray meta file.
    Orphan `<run-id>.meta.json` files (no matching `.jsonl`) are also
    removed. The active run (`current.jsonl` and the meta file for its
    computed run-id) is never touched. Errors on individual files are
    swallowed; the sweep is best-effort and silent in v1.
    """
    if not os.path.isdir(_DATA_RUNS_DIR):
        return
    if now is None:
        now = time.time()
    cutoff = now - ttl_seconds

    try:
        entries = os.listdir(_DATA_RUNS_DIR)
    except OSError:
        return

    for name in entries:
        char_dir = _character_dir(name)
        if not os.path.isdir(char_dir):
            continue
        _prune_character_dir(char_dir, cutoff)


# ---------------------------------------------------------------------------
# Per-character sweep
# ---------------------------------------------------------------------------

def _prune_character_dir(char_dir: str, cutoff: float) -> None:
    try:
        files = os.listdir(char_dir)
    except OSError:
        return

    active_run_id = _read_active_run_id(os.path.join(char_dir, "current.jsonl"))

    jsonl_runs: set[str] = set()
    meta_runs:  set[str] = set()
    for fn in files:
        if fn == "current.jsonl":
            continue
        if fn.endswith(".jsonl"):
            jsonl_runs.add(fn[:-len(".jsonl")])
        elif fn.endswith(".meta.json"):
            meta_runs.add(fn[:-len(".meta.json")])

    surviving_jsonl: set[str] = set(jsonl_runs)

    # 1) Expired unsaved sealed runs — delete .jsonl + .log + .meta.json.
    for run_id in jsonl_runs:
        if run_id == active_run_id:
            continue
        ts = _run_id_to_epoch(run_id)
        if ts is None:
            continue
        if ts >= cutoff:
            continue
        meta_path = os.path.join(char_dir, run_id + ".meta.json")
        if _is_saved(meta_path):
            continue
        _safe_remove(os.path.join(char_dir, run_id + ".jsonl"))
        _safe_remove(os.path.join(char_dir, run_id + ".log"))
        _safe_remove(meta_path)
        surviving_jsonl.discard(run_id)

    # 2) Orphan meta cleanup — meta with no surviving .jsonl, excluding
    # the active run's meta (matched by computed run-id, not filename).
    for run_id in meta_runs:
        if run_id == active_run_id:
            continue
        if run_id in surviving_jsonl:
            continue
        _safe_remove(os.path.join(char_dir, run_id + ".meta.json"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_active_run_id(current_path: str) -> str | None:
    try:
        with open(current_path, "r", encoding="utf-8", errors="replace") as f:
            line = f.readline()
    except OSError:
        return None
    if not line.strip():
        return None
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict):
        return None
    ts = row.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    return _run_id_from_ts(int(ts))


def _run_id_to_epoch(run_id: str) -> float | None:
    try:
        return time.mktime(time.strptime(run_id, _RUN_ID_FMT))
    except (ValueError, OverflowError):
        return None


def _is_saved(meta_path: str) -> bool:
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("saved") is True


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
