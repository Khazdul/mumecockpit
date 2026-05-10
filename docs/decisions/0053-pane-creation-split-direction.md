# ADR 0053 — Right-column pane creation prefers split-below over split-above

**Status:** Accepted

## Context

tmux returns a killed pane's space to its previous tree-sibling. When a pane
is created with `split-window -v -b -t <next>` ("split above next"), the new
pane becomes the previous tree-sibling of `<next>`. On kill, `<next>` absorbs
the space. The *next* creation then splits above `<next>` again, making `<next>`
shrink by one more row each cycle while an unrelated pane grows by the same
amount.

This was reproduced empirically: with status, buffs, group, and dev open and
comm closed, four `cp -u` on/off cycles drove dev from h=21 to h=1 while group
ballooned from h=1 to h=31. The fifth `cp -u` open triggered tmux's "no space
for new pane" error, and tmux's recovery placed the new pane on top of the
input row, displacing the input pane entirely.

## Decision

For every right-column pane, exhaust visual-predecessor split-below targets
before falling back to visual-successor split-above targets. Splitting below an
existing pane makes the new pane that pane's tree-successor; on kill, the space
returns to that same pane — the one the next creation will split again. The
creation/kill cycle is therefore symmetric and heights stay stable.

Visual order (top to bottom): status → buffs → group → comm → ui → dev.

`status` and `dev` are natural exceptions: status always splits above the
current top-most right pane (becoming first tree-sibling — symmetric); dev
always splits below the bottom-most (becoming last tree-sibling — symmetric).
Neither needs to change.

`buffs`, `comm`, and `ui` were updated in `bridge/launcher/open_pane.sh` to
exhaust every visual predecessor as a split-below target before attempting any
split-above. `group` already followed this rule and is left alone.

Any new right-column pane added to the cockpit must follow the same pattern:
split below the nearest visual predecessor; only fall back to split-above when
no predecessor exists in the current layout.

## Consequences

Kill-distribution now returns space to the same pane the next creation will
split. Toggle cycles of any right-column pane are stable: heights do not drift
and the input pane is never displaced regardless of how many cycles are run.

## Alternatives considered

**Pin creation height with `-l <rows>`** — would constrain each new pane's
initial size but does not fix the asymmetry: subsequent splits still target the
wrong tree-sibling, so heights continue to drift. Rejected; also conflicts with
ADR 0030 (heights are tmux-managed and user-resizable).

**Force a layout rebuild via `select-layout` after each toggle** — would
correct the tree after the fact but resets any user-adjusted heights, breaking
ADR 0030's user-resizable contract. Rejected.
