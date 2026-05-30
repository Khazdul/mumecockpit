# 0120 — Unified Enter/Space grammar on launcher selector rows

**Status:** Accepted
**Date:** 2026-05-30

## Context

Several launcher rows are *selectors* whose value is driven by `←` / `→`
or by cursor movement, which left `Enter` / `Space` dead or redundant:

- The history filter pills re-applied the already-live filter on
  `Enter` / `Space` — a no-op dressed up as an action, since moving the
  pill cursor or clicking a pill already filters immediately (ADR 0088
  P4.1).
- The Terminal Settings cycle rows (Window mode, Background, Cursor
  style, Cursor blink) no-op'd on `Enter` (ADR 0107).
- The profile editor's LITE/EDITOR toggle freed both keys in Phase 6.2
  (ADR 0084 §4) when it bound mode-switching to `←` / `→`.

The profile editor's kind-buttons row had already solved exactly this
shape — `Enter` / `Space` mirror `↓` to drop into the entry list at row
0 "so the row stops feeling dead", covered by
`TestKindRowEnterSpaceActivates`. The inconsistency was that one good
pattern lived in one place while three sibling surfaces left the keys
inert.

## Decision

Adopt one grammar across the launcher. `Enter` / `Space` always perform
a *forward* action — never a dead key on a selectable element:

1. Activate an action element (button / openable row).
2. Advance a toggle or cycler one value (≡ `→`, wrapping).
3. On a live-applied selector, commit-and-descend into the governed
   content at row 0.

The single exception is a **bare numeric stepper** (Terminal Settings
Size / Width / Height / Padding), which stays `Enter`-inert because
there is no discrete target to activate and no governed content zone to
descend into.

Surfaces brought into line:

- **History filter** — `↓` and `Enter` / `Space` now focus the runs
  table at row 0. This retires the jump-to-button-column `↓` (the
  button column is now reached from the table via `←`) and the re-apply
  `Enter`. The filter still applies live on pill move / click; the
  reciprocal `↑` from table row 0 (and from the topmost options button)
  still returns to the filter row.
- **Terminal Settings cycle rows** — `Enter` / `Space` advance the
  value one step, matching `→`.
- **LITE/EDITOR toggle** — `Enter` / `Space` descend from the focused
  toggle into the current mode's first zone (lite → kind-buttons row;
  editor → buffer), mirroring `↓`. They never *flip* the mode; the
  buffer's own `Enter` = newline is a separate zone and is unaffected.

## Prior art

The profile-editor kind-buttons row is the reference implementation —
`Enter` / `Space` mirror `↓` into the entry list at row 0, guarded by
`TestKindRowEnterSpaceActivates`. The other three surfaces were aligned
to it.

## Consequences

- One predictable rule for `Enter` / `Space` across every selector
  surface; future frames inherit it rather than re-deciding per row.
- The codified grammar lives in `docs/launcher.md` ("Navigation
  grammar") as the reference for new frames.
- Lost: the one-key filter → button-column hop. The path is now filter
  → table → `←` → buttons — you pick a run first, which is the common
  flow.

## Alternatives considered

**Enter-only on history (leave `↓` jumping to the button column).**
Rejected — it leaves `↓` inconsistent with `Enter` from the same row,
which is the defect we set out to remove.

**Leave the cyclers / toggle dead.** Rejected — inert `Enter` / `Space`
on a selectable element *is* the defect; that is the whole motivation.

## Relationships

Narrows ADR 0084 §4 (see the addendum there); touches the history
filter from ADR 0088 (see its addendum) and the Terminal Settings
cyclers from ADR 0107.
