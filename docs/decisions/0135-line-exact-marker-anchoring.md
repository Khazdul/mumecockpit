# 0135 — line-exact pkill/char_death markers via .log content-match

**Status:** Accepted
**Date:** 2026-06-14

## Context

Chain and spotlight markers were placed by snapping the run event's
whole-second fold-time `ts` to the nearest `.log` line by time (ADR 0121
point 6 for chain; the equivalent `ev.ts*1e6 - window_start` arithmetic
for spotlight). In bursty combat (many lines per second) that lands
several lines off the real event line. The marker click-to-seek
affordance surfaced it: clicking K►/D► landed the cursor 4–5 lines from
the R.I.P. / "You are dead" line.

## Decision

Anchor pkill and char_death to their actual `.log` event line. The
precise line already exists in the `.log` at microsecond `ts_us` (tt++
`%U` capture). At marker-build time a shared pure helper,
`match_event_line_ts_us` (log_player.py), content-matches it on the
line's PLAIN text (pkill → "R.I.P.", char_death/"death" → "You are
dead"), within a ±1 s window, name-disambiguated, and returns that
line's ts_us; callers convert to their offset coordinate. Used by both
chain (`_snap_marker_offset`) and spotlight
(`load_spotlight_log_events`) so the two modes agree. On no match it
falls back to the prior whole-second time-snap (never worse).
achievement/level_up keep the time-snap — they are GMCP-sourced with no
reliable `.log` text line.

## Alternatives considered

- **Record a precise microsecond timestamp (or line reference) for the
  event in the JSONL at write time.** Rejected because it is multi-layer
  (Lua run_log + JSONL schema + reader + docs), only helps future runs
  (historical logs keep second resolution), and — decisively — the Lua
  recorder writes JSONL `ts` via `os.time()` (whole seconds) while the
  `.log` is timestamped separately by tt++ `%U`; the Lua side has no
  microsecond wall-clock tied to that `%U` epoch, so a recorder-written
  "precise" ts would not snap exactly to the `.log` line anyway. The
  player-side content-match fixes all logs in one layer because the
  precise line is already captured.

## Relationships

Shares the `log_view` playback engine with spotlight mode (ADR
0077–0080); builds on the per-run `.log` capture. Revises ADR 0121 (see
its 2026-06-14 addendum) on both marker placement and the
marker-layer-does-not-seek stance.
