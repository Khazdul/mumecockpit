# 0005 — apply_layout.sh owns all right-column dimensions

**Status:** Superseded by 0030
**Date:** 2026-04-25

## Context

ADR 0004 made `bridge/apply_layout.sh` the sole path for restoring `status_height`.
After that fix, three related issues remained:

- **Drag with three panes open** — dragging the ui↔status or status↔dev border
  snapped status to `status_height` correctly, but rows were redistributed among
  `ui` and `dev` by tmux rather than by any authoritative target. Result: one
  pane snapped back while neighbors changed by arbitrary amounts.

- **cp -d off→on with ui+status open** — `open_pane.sh` split below the
  bottommost right pane, giving `dev` whatever rows tmux assigned. The
  subsequent `apply_layout.sh` call only re-pinned `status_height`; `ui` and
  `dev` were untargeted. On narrow windows this left `dev` with 0 rows.

- **Status-open width-floor gap** — a recent fix gated the 33-col right-column
  floor on status being open *at drag time*. If the column was narrowed while
  status was closed (valid), opening status later left the column below 33 cols.

The shared root cause: `apply_layout.sh` only owned `status_height`. Everything
else (`ui` height, `dev` height as residual, width floor when status is open)
was left to tmux or caller-local logic.

## Decision

Extend `apply_layout.sh` to own all right-column dimensions:

1. **`ui_height` (new key in `layout.conf`, default 20)** — applied top-down
   before `status_height`; clamped so `dev` keeps at least 3 rows when present.
2. **`status_height`** — unchanged from ADR 0004.
3. **`dev` as residual** — no explicit sizing; receives whatever rows remain.
4. **33-col width floor when status is open** — enforced in `apply_layout.sh`
   on every call; widens the column automatically when status is opened into a
   narrow right column. Requires main ≥ 30 cols; otherwise leaves as-is for the
   existing narrow-terminal collapse path in `on_window_resize.sh`.

`bridge/on_pane_resize.sh` is updated to detect which border moved and persist
intent rather than raw measurements:

- ui height changed → user dragged ui↔status → persist `ui_height = U`
- status height changed → user dragged status↔dev → persist
  `ui_height = U + S − status_height` (remaps the drag to a ui growth so dev
  lands at its post-drag value after status snaps back)

The inline `resize-pane` snap-back call that was in `on_pane_resize.sh` is
removed; `apply_layout.sh` handles it via the new width-floor logic.

## Consequences

- After any right-column operation, all pane heights (ui, status, dev) are
  deterministic — no tmux-assigned residuals.
- `cp -d` off→on with ui+status open: `dev` always gets a non-zero residual.
- Opening status when the column is < 33 cols: column auto-widens to 33 if
  main can stay ≥ 30; otherwise unchanged and the collapse path handles it.
- Drag detection is reliable because `apply_layout.sh` always re-establishes a
  known geometry baseline before the next drag.
- Phase-2 dynamic `status_height` continues to work: the residual is recomputed
  on every `apply_layout.sh` call.

## Alternatives considered

**Split-from-ui + swap-pane in open_pane.sh.** Fixes the dev-zero-rows toggle
case but not the drag case, and leaves layout geometry tmux-driven for all other
operations. Rejected — same fragmentation that motivated ADR 0004.

**Full pane rebuild on every operation.** Guarantees correct geometry but
destroys scrollback in `ui` and `dev` (log-tail panes). Rejected — unacceptable
UX cost.

**Enforce width floor only at drag time.** Leaves the cp -c-into-narrow-column
case broken. Rejected — the floor should be a property of "status is open", not
"a drag just occurred".
