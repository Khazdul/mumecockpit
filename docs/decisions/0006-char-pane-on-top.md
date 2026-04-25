# 0006 — Char pane on top of right column

**Status:** Accepted
**Date:** 2026-04-25

## Context

ADR 0005 placed the status pane in the middle of the right column (ui → status →
dev) with `ui_height` as the sole flex parameter and dev as the residual. In
practice the natural mental model is "fixed identity panel up top, work area in
the middle, log overflow at the bottom." Phase-2 dynamic char growth also flows
down through the column more cleanly when char is the topmost pane — only ui
and dev shift; no mid-column reflow.

The old order also produced two resizable borders when all three panes were open
(char↔ui and ui↔dev), requiring an unintuitive remap (status↔dev drag was
converted to a ui_height target) to preserve intent through snap-back. With
char on top there is exactly one resizable border: ui↔dev.

## Decision

Right-column order becomes `status → ui → dev`.

`bridge/apply_layout.sh` applies `ui_height` first (clamped so dev keeps ≥ 1
row when present), then `status_height`; dev receives the residual. The
width-floor logic and the height-authority model (apply_layout.sh as sole
authority, dev as residual) are unchanged from ADR 0005.

`bridge/on_pane_resize.sh` detects border drags using S-first discrimination:

- If char height S ≠ `status_height` → top border (char↔ui) was dragged.
  Snap back only; no persistence; `ui_height` is left untouched.
- If S = `status_height` and ui height U ≠ `ui_height` → bottom border
  (ui↔dev) was dragged. Persist `ui_height = U`.

`bridge/open_pane.sh` inserts status before the topmost right pane (`-b` above)
and inserts ui below status (or before dev when status is absent).

## Consequences

- Single flex border (ui↔dev) — drag semantics are unambiguous: only one border
  persists; the other snaps back.
- Cleaner match between content-driven char height and its position at the top.
- Phase-2 dynamic `status_height` growth only affects panes below it (ui
  shrinks first, then dev).
- Launcher Options page mockups updated for every combination involving CHAR.

## Alternatives considered

**(a) Keep ui on top, swap status and dev** — produces status → dev order in the
middle and bottom. Loses the "fixed-on-top" ergonomic; dev above status is
semantically odd. Rejected.

**(b) Make char↔ui drag remap to ui_height so dev grows** — the dragged border
does not touch dev, so the remap is surprising. Rejected; snap-back-only is
simpler and matches the content-driven nature of char height.

## Note

This refines ADR 0005's apply-order. The height-authority model itself
(apply_layout.sh as sole authority, ui_height as sole flex parameter, dev as
residual) is unchanged.

## Implementation note

Apply order is ui first, then status. Rationale: `tmux resize-pane` moves a
pane's bottom border by default. Applying ui first moves ui's bottom border,
squeezing dev. Applying status next moves status's bottom border, squeezing ui.
The net propagation direction under tight heights is char → ui → dev, which
preserves char (the fixed identity panel) as long as possible. The ui floor and
dev reservation are both 1 row (down from 3), since ui in the middle may
legitimately be very small when the user drags ui↔dev upward to give dev more
space. The persistence filter in on_pane_resize.sh matches: ui drag persists
when U ≥ 1.
