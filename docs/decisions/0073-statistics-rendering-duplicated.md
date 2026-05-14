# 0073 — Statistics rendering is duplicated between popup and launcher History

**Status:** Accepted
**Date:** 2026-05-15

## Context

Two surfaces in the cockpit show aggregated run-statistics in the
same visual form: ALLIES + ACHIEVEMENTS, KILLS + PvPs (sortable),
XP/h + TP/h sparklines, and the XP-linjal level-span bar.

- The **in-game popup Statistics frame**
  (`bridge/launcher/ingame_menu.py`) shows the *live* run while the
  player is in-game. It runs inside `tmux display-popup` (ADR 0062),
  tick-refreshes every 60 s, and is built around popup-height
  auto-fit.

- The **launcher History detail frame** (`bridge/launcher/launcher.py`)
  shows an *archived* session selected from the History list. It
  runs in the pre-tmux launcher Application (ADR 0069), is data-fit
  rather than popup-fit, has no live tick refresh, and includes a
  WATCH LOG button + `L` shortcut anticipating Phase 3.

Both surfaces consume the same data layer
(`bridge/launcher/run_stats.py`, ADR 0065). Only the rendering is
duplicated.

Three options surfaced when designing the launcher detail view:

(a) **Extract a shared renderer module now** —
    `bridge/launcher/stats_render.py` owning the pure rendering
    helpers; both surfaces import from it. Refactor `ingame_menu.py`
    accordingly.

(b) **Build a fresh implementation in `launcher.py`** modelled after
    the popup's renderer; `ingame_menu.py` untouched.

(c) **Import directly** from `ingame_menu.py` into `launcher.py`.

## Decision

Chose (b). The launcher's `history_detail` rendering is fresh-written
in `launcher.py`, mirroring the popup's section layout, palette,
sort logic, focus cycling, and XP-linjal computation. The popup's
`ingame_menu.py` is unchanged.

## Rationale

The two surfaces serve different use cases on different hosts, and
the hosts are right for those use cases:

- The popup is an overlay during play — quick-in / quick-out access
  to current-run numbers. Its `display-popup` host is well-suited:
  it layers above the game pane, dismisses cleanly, and the
  popup-height auto-fit + 60-second live tick are the right
  behaviours for the active-run case.

- The launcher History detail is a retrospective on archived runs.
  Its full-screen launcher Application host is well-suited:
  data-fit rendering, no live refresh, click-to-jump scrollbars,
  mouse-wheel scroll, and room for adjuncts like the WATCH LOG
  button and the future Log Player frame.

Neither host is migrating. Statistics stays in `display-popup` for
the live-run case; the Phase 3 Log Player will be a new frame in
the launcher, reached from `history_detail`'s WATCH LOG button.
Tmux remains the host only of the running game session itself.

Given two stable hosts, option (a) buys consolidation at the cost
of ongoing coupling: a change wanted on only one surface (the
popup's auto-fit, the launcher's data-fit, the launcher's row hover
that the popup intentionally lacks, the launcher's WATCH LOG
button) lands harder when both are constrained by a shared module.

Option (c) was rejected because `ingame_menu.py` is not a library
— it owns module-level mutable state, signal handlers, and
sentinel-file writes, and assumes a single global `Application`;
importing into a second host application would surface all of
those as cross-process hazards.

Option (b) keeps both surfaces independently evolvable. The cost
is duplication of several hundred rendering lines, accepted
explicitly.

## Consequences

- **Gained.** Two surfaces independently evolvable. The launcher's
  `history_detail` diverges from the popup where the archived-run
  context calls for it (no live-tick refresh, no "Run ended"
  suffix, data-fit sizing instead of popup-fit, WATCH LOG button,
  `L` key binding, row hover on data tables, hidden empty Total
  rows). The popup is unchanged and battle-tested.
- **Lost.** Code duplication of several hundred lines: data-row
  formatting, sort logic, focus cycling, scrollbar wiring,
  sparkline geometry, XP-linjal computation. Two callsites for any
  future change that should apply to both.
- **Drift risk.** A bug fix or visual tweak landing on one surface
  but not the other produces a "popup shows X but launcher shows
  Y" asymmetry for the same data. Bounded mitigation: both
  surfaces are small enough that occasional sync sweeps stay
  tractable.

## When consolidation might become attractive

Not scheduled. Trigger conditions to revisit:

- **Phase 3 Log Player wants to reuse statistics rendering
  helpers.** The Log Player lives in the launcher as a new frame;
  if it wants to embed a small statistics summary or share any
  helpers, extracting `stats_render.py` at that point gives three
  consumers (popup, History detail, Log Player) one renderer.
- **A schema change to the aggregator forces visible work on both
  surfaces**, and the duplication starts to dominate the
  maintenance cost.
- **A palette or layout overhaul wants to land identically on both
  surfaces.**

Until one of those bites, the duplication stands as recorded
technical debt rather than scheduled work.

## Alternatives considered

**Extract now and refactor popup-Statistics.** Buys consolidation
at the cost of coupling two surfaces with different use cases and
hosts. Rejected.

**Import from `ingame_menu.py` directly.** Cross-process hazards
from module-level state, signal handlers, and singleton
assumptions. Rejected.

**Defer the launcher detail view until shared rendering is
extracted.** Would have blocked the History feature on unrelated
refactoring work. The data layer is already shared (ADR 0065);
rendering symmetry is the only thing missing, and it's worth
fresh-writing for one surface to unblock the feature.

## Relation to other ADRs

- **Builds on ADR 0062** (popup in prompt_toolkit) and
  **ADR 0069** (launcher in prompt_toolkit) — both surfaces use
  the same framework, palette, and scrollbar widget
  (`widgets/scrollbar.py`).
- **Builds on ADR 0065** (Python aggregator) — both surfaces
  consume `run_stats.aggregate()` for their data. The data layer
  was always shared; only the rendering is duplicated.
