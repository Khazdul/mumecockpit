# ADR 0036 — Drag-end sweeps stuck copy-mode panes; plain click does not

## Status

Accepted

## Context

tmux fires drag-end events on the **release** surface, not the drag-start surface.
When a pane enters copy-mode via auto-drag-start and the pointer is released outside
that pane (on another pane, a border, or the status bar), the originating pane is
left in copy-mode with an active selection and tmux focus does not return to the
input pane. The user is stuck until they start a new drag inside the original pane.

Independently, prompt_toolkit panes (comm, buffs) have `mouse_support=True` and
handle mouse events internally via `send-keys -M`. They never enter tmux copy-mode,
so the existing copy-mode `MouseDragEnd1Pane` binding never fires for drags that
start and end within them. After such a drag, tmux focus stays on the comm or buffs
pane rather than returning to input.

The existing pane-mode-changed hook (which refocuses input on copy-mode exit) and
the copy-mode `MouseDragEnd1Pane` binding are not enough: both require that the
event fires on the same pane that entered copy-mode. When the release surface differs,
neither path fires for the stuck pane.

## Decision

Add `focus_input.sh --sweep`. When called with `--sweep`, the script iterates all
panes in `mume:cockpit` and calls `send-keys -X copy-pipe-and-cancel` on every
non-input pane where `pane_in_mode == 1`. `copy-pipe-and-cancel` is safe in both
states: with a selection it copies via OSC 52 and exits; without a selection it
just exits.

Bind `--sweep` to every drag-end surface that is not already covered by the
copy-mode binding:

- **`MouseDragEnd1Pane` (root table)** — fires for drag-end in prompt_toolkit panes
  (comm, buffs) and for any drag-end where the release pane did not traverse copy-mode.
  Gated on `pane_title != input`.
- **`MouseDragEnd1Border`** — chains `--sweep` after `on_pane_resize.sh` (order does
  not matter; the two scripts are independent).
- **`MouseDragEnd1Status`, `MouseDragEnd1StatusLeft`, `MouseDragEnd1StatusRight`** —
  cover the matrix where a drag started in a pane (entering copy-mode) and the release
  landed on the tmux status bar.

`MouseUp1Pane` (plain click) is deliberately **not** changed to use `--sweep`.
Sweeping on click would cancel copy-mode in the main pane if the user clicks another
pane while browsing scrollback — a clear regression.

## Consequences

- After any drag-end, the input pane has tmux focus and no other pane is stuck in
  copy-mode with a stale selection.
- Selections from out-of-pane releases are still preserved: `copy-pipe-and-cancel`
  copies before exiting.
- The (drag-start × drag-end) surface matrix is uniformly handled. Future panes added
  to the cockpit need no new bindings as long as their `pane_title` is not `input`.
- prompt_toolkit panes (comm, buffs) get correct refocus after drag without losing
  their internal mouse handling.
- Plain-click scrollback navigation in the main pane is unaffected.

## Alternatives considered

- **Sweep on every mouse-up (`MouseUp1Pane`).** Rejected — cancels scrollback on
  plain click, a clear regression for scrollback navigation.
- **Per-pane drag-end bindings keyed on pane title.** Rejected — the pane-title guard
  (`pane_title != input`) scales to future panes without new bindings; a per-title
  approach would require maintenance for each new pane added.
- **Separate handler for comm/buffs by title.** Rejected — same reason; the unified
  sweep path is simpler and forward-compatible.

## References

- `docs/tmux-bindings.md` — binding inventory and drag-end matrix rationale.
- `docs/input-pane.md` — `setup_mouse_binding()` lifecycle.
- ADR 0024 — why mouse bindings can be registered once for the lifetime of the session.
- ADR 0025 — copy-mode-as-canonical-scrollback model that sweep semantics compose with.

## Update 2026-05-03

The `pane_title != input` gate was removed from the root-table `MouseDragEnd1Pane` binding. The gate was incorrect: drag-end fires on the **release** pane, not the drag-start pane. When a drag starts in main, char, ui, or dev (entering copy-mode) and is released on the input pane, the release pane is input — not in copy-mode — so the copy-mode binding does not fire. The root binding's gate then suppressed sweep, leaving the drag-source stuck in copy-mode with a stale selection. Sweep is always the correct response: drag-end on input necessarily originated in another pane. `MouseUp1Pane` retains its gate — a plain click on input is a local typing action and must not trigger tmux logic.
