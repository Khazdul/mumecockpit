# 0082 — `macro_keys.py` duplicates the input pane's forwarded-key list

**Status:** Accepted
**Date:** 2026-05-18

## Context

Phase 5 of the launcher's profile editor (Macros tab — see
`docs/launcher.md`) introduces `bridge/launcher/macro_keys.py`, a
bidirectional map between three representations of a macro key:

- the prompt_toolkit key event produced when the user presses the
  key (a `Keys.*` constant or a multi-key tuple like
  `("escape", "O", "p")`);
- the canonical tt++ escape sequence written to the profile's
  `.tin` file (`\eOp`, `\eOP`, `\ea`, …);
- the human-readable display name surfaced in the editor
  (`Numpad 0`, `F1`, `Alt+a`).

The set of forwardable keys is already defined in
`bridge/panes/input_pane.py` — the input pane forwards exactly those
keys to tt++ via `tmux send-keys`. The editor's known-keys list
must mirror input_pane's set; bind a key in the editor that
input_pane does not forward and the resulting `#macro` will never
fire in-game.

The natural refactor is to hoist the shared key list (and probably
the canonical-form mapping) into one place — either `macro_keys.py`
imported by `input_pane.py`, or a third module imported by both —
so the two cannot drift. We chose not to do this refactor in
phase 5.

## Decision

`macro_keys.py` duplicates the forwarded-key list. The two modules
are cross-referenced in docstrings:

- `macro_keys.py`'s top-of-file comment names `input_pane.py` as
  the contract.
- `input_pane.py`'s `FORWARDED_KEYS` / `ALT_FORWARDED_LETTERS` /
  `NUMPAD_FORWARDED_KEYS` blocks remain the runtime source of
  truth; their docstrings will note `macro_keys.py` next time
  they're touched.

A test (`bridge/launcher/tests/test_macro_keys.py`) asserts that
every macro in the default `blank_profile.tin` resolves to a
display name, so a real-world drift between the template and
`macro_keys.py` would fail CI before reaching a user.

## Alternatives considered

1. **Immediate unification.** Hoist the shared definitions into
   `macro_keys.py` (or a new `bridge/lib/macros.py`) and have
   `input_pane.py` import them. This is the obviously correct
   end state.

   Rejected for phase 5: `input_pane.py` is one of the two
   latency-critical modules in the codebase (the input loop runs
   per keystroke; see `architecture.md`). Adding a cross-package
   import at module load time is low-risk but non-zero, and the
   refactor would land alongside an unrelated user-facing feature.
   We prefer to ship the feature with duplicated data and unify
   in a focused follow-up.

2. **Generate `macro_keys.py` from `input_pane.py` at build
   time.** Same end result without the runtime import. Rejected
   because the project has no build step today and adding one for
   a 50-line table is disproportionate.

3. **Skip the readable-name layer entirely** and show raw
   escapes (`\eOp` etc.) in the editor. Rejected because the
   point of phase 5 is that raw escapes are meaningless to most
   players — readable names are the user-facing improvement and
   are not derivable from `input_pane.py`'s tables alone (those
   tables map to tmux names like `KP0`, not display names like
   `Numpad 0`).

## Consequences

- Adding a forwarded key to `input_pane.py` requires a parallel
  addition to `macro_keys.py`'s `KNOWN_KEYS`; the cross-reference
  docstring is the reminder. The blank-profile resolution test
  catches drift only for the keys in the template.
- The follow-up refactor remains small (~50 lines) and can land
  whenever input_pane.py is next touched for an unrelated reason.
- Users see no behavioural difference between this state and the
  unified state — the duplication is purely a maintenance cost.
