# 0147 — Export editor: marked-up chain logs, text or HTML replay

**Status:** Accepted
**Date:** 2026-09-26

## Context

History → Export dumped the whole chain log to a `.txt`. Players want to
share a *part* of a session — a fight, not five hours of it — and share
it the way it looks in the cockpit, with some narration. A one-off
HTML replay built by hand proved the format (black canvas, cockpit
colours, the log_view strip and controls, adjustable speed); it needed
to become a launcher feature.

## Decision

- History → **Export** now pushes an `export_editor` frame instead of
  writing a file. It shows the whole log in menu chrome with a button
  column, a gutter and a 2-col overview map.
- **Exclusions are ranges opened/closed at the cursor** (`EXCLUDE FROM
  HERE` / `STOP EXCLUDING`), modelled as sorted half-open event ranges —
  the `<exclude>…</exclude>` mental model — rather than per-line toggles
  or a parity list of markers (where closing inside a range would flip
  everything after it).
- **Comments are inserted before the cursor line** and exported as
  `## ` lines. In the HTML replay they hold playback in real time for
  5–20 s by length, independent of the speed setting, so 0.25x does not
  quadruple a reading pause.
- **Edits persist** in a per-chain `<first-run-id>.export.json` sidecar,
  anchored by `.log` line timestamps so a later stitched run cannot
  shift them. History → Delete and the retention sweep remove it.
- **HTML is one self-contained file** from
  `templates/log_replay.html` plus an embedded JSON payload. Lines are
  pre-rendered through `log_player.parse_ansi`, so colours match
  `log_view` exactly; markers use `log_player.match_event_line_ts_us`.
  Cuts collapse to ≤0.5 s of playback. The font stack leads with
  Lucida Console (the cockpit's Alacritty font) and falls back to
  system monospace — it is not embedded (licence).
- Exports go to `~` and never overwrite (`-2`, `-3` suffixes), matching
  the old Export.

## Alternatives considered

- **Reuse `log_view` with edit keys.** Rejected — its play/pause model
  and auto-hiding chrome fight an editing surface; the editor needs a
  persistent button column and always-visible exclusion state.
- **Store anchors as line numbers.** Rejected — a chain grows when a
  run is stitched on within the hour, and line numbers are meaningless
  outside the merged event list.
- **Comment time inside the timeline.** Rejected — speed scaling would
  stretch reading pauses; holds are applied in real time by the player.
