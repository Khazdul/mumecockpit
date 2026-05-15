# bridge/launcher/run_meta.py — read/write the per-run meta sidecar.
#
# Pure library: no UI, no tmux, no Lua. The popup writes the sidecar
# after the player rates a saved session; run_retention consults it to
# preserve saved runs past the 14-day TTL. See docs/runs.md "Meta
# sidecar" + ADR 0074 for schema and invariants.

from __future__ import annotations

import json
import os
import sys
import time

from run_stats import _character_dir


SCHEMA_VERSION = 1


def _meta_path(character: str, run_id: str) -> str:
    return os.path.join(_character_dir(character), run_id + ".meta.json")


def read_meta(character: str, run_id: str) -> dict | None:
    """Return the parsed meta dict, or None on missing/invalid."""
    try:
        with open(_meta_path(character, run_id), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_saved(character: str, run_id: str) -> bool:
    """True iff a meta file exists and contains `saved == True`."""
    data = read_meta(character, run_id)
    if data is None:
        return False
    return data.get("saved") is True


def save_run_chain(character: str, run_ids: list[str], rating: int) -> None:
    """Atomically write a `saved` meta file for every run in the chain.

    Per-file errors are swallowed (logged to stderr) so one bad write
    cannot abort the rest of the chain.
    """
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        rating = 0
    rating = max(0, min(5, rating))

    saved_ts = int(time.time())
    payload = {
        "schema":   SCHEMA_VERSION,
        "saved":    True,
        "rating":   rating,
        "saved_ts": saved_ts,
    }

    for run_id in run_ids:
        path = _meta_path(character, run_id)
        tmp  = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.rename(tmp, path)
        except OSError as exc:
            print(f"run_meta: failed to write {path}: {exc}", file=sys.stderr)
            try:
                os.remove(tmp)
            except OSError:
                pass
