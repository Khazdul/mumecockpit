# 0032 — Buffs pane extracted from status pane

**Status:** Accepted
**Date:** 2026-05-01

## Context

Status pane Phase 2 was originally specified to render the affects list inside
the status pane with dynamic height driven from `state.char.affects` length.
ADR 0012 already noted that this dynamic height inside a multi-content pane
would need renderer-level mitigation — fixed height with "+N more" overflow,
or compact one-line affect rendering — to avoid layout flicker. Meanwhile the
input pane gained a BUFFS button slot ahead of any backing pane, and the
affects data layer (`lua/core/affects.lua`, persistence in
`logs/affect_times/` and `logs/affects_active/`) was completed independently
of any UI surface.

## Decision

Affects are visualised in a dedicated `buffs` pane (`bridge/buffs_pane.py`)
between `status` and `comm` in the right column, toggled via `cp -b` and the
existing BUFFS button in the input pane menu bar. The status pane no longer
renders affects, no longer carries `affects` in its JSON schema, and
`status_state.lua` no longer subscribes to `affects_changed`. The data layer
(`lua/core/affects.lua`, `state.char.affects`, both persistence files) is
unchanged.

## Consequences

- Status pane keeps a fixed content shape; future status fields don't compete
  with a variable-length affect list for vertical room.
- The buffs pane can later adopt dynamic height or fixed-height overflow
  independently, without affecting the rest of the right column or other
  content surfaces. ADR 0012's renderer-level flicker guidance applies
  *within* the buffs pane when its renderer is built.
- `C_AFFECT_SPELL` / `C_AFFECT_BUFF` / `C_AFFECT_DEBUFF` constants were
  removed from `status_pane.py` in the scaffolding commit. They will reappear
  in `buffs_pane.py` when the renderer lands; that is expected churn, not a
  regression.
- The `cp` surface gains `cp -b`, taking a previously unused short flag.
- The BUFFS button is no longer inert.

## Alternatives considered

**Keep affects inside the status pane (status quo from ADR 0012).** Workable
with renderer-level mitigations, but couples two unrelated data surfaces
(character vitals/state vs. active affects) into one pane's height budget.
Rejected.

**Affects on demand via popup only** (one of the alternatives ADR 0012 itself
mentioned). Loses at-a-glance visibility of remaining durations during play.
Rejected for the primary surface; could still exist later as a secondary view.

**Render affects in both status and buffs.** Two render paths to keep in sync
over a single state source. Rejected.

## Relation to ADR 0012

Not superseded. ADR 0012's question was whether to restructure the right
column at the tmux level versus mitigating flicker at the renderer level; it
answered "renderer level." This ADR doesn't reopen that — it relocates affects
to a different pane in the same tmux model. ADR 0012's renderer-level guidance
still applies *within* the buffs pane when its renderer is built.
