# 0119 — Fold run rating/save into the exit confirmation

**Status:** Superseded by 0130
**Date:** 2026-05-29

## Context

The popup main menu carried a standalone "Save run" row that pushed a
`rate_session` frame (0–5 stars → chain save). It was a heavy top-level slot
for an action most sessions don't want, and it sat separately from "Exit
session", which already forced an "are you sure" confirmation modal on every
exit. Run saving and exit were two unrelated steps despite exit being exactly
the moment the user knows whether a run was worth keeping.

## Decision

Remove the "Save run" main-menu row and fold its rating/save into the
`exit_confirm` frame. The frame now shows an optional 0–5 star row above the
exit warning; the rating pre-selects from the run's existing saved rating (if
saved this session) else 0. `Y` commits: if rating > 0, save the stitched
chain, then run the unchanged exit sequence (sentinel + `cp -e`); if
rating == 0, skip saving. `ESC` cancels the exit. The star widget, key grammar
(`0..5`, ←/→, click), and the `previous_run_chain` + `save_run_chain` mechanism
are reused from the former rate_session frame.

## Consequences

- One fewer top-level menu slot; the menu stays short.
- Exit is the single rating/save touchpoint; re-rating happens naturally on
  each exit (reads existing rating on push).
- Exit never un-saves: rating 0 is a no-op on the save side regardless of prior
  state. De-saving stays exclusive to the launcher history delete flow.
- Friction guard preserved: `Y` remains a deliberate commit key (not Enter), so
  the confirmation's original protective purpose survives.
- All UI-layer; one file (`ingame_menu.py`); no tt++/Lua/hot-path impact.

## Alternatives considered

**Enter as commit key.** Rejected. Smoother, but Enter as commit removes the
deliberate-keypress friction that justified the confirmation frame's existence;
`0..5` for stars also wouldn't collide with `Y`.

**Keep "Save run" as its own row.** Rejected. The whole motivation was that the
row was a misplaced, rarely-wanted top-level slot and exit was the natural
decision point.

**Let rating 0 un-save a previously saved run.** Rejected. Ambiguous and
destructive from an exit flow; de-saving belongs in history delete.
