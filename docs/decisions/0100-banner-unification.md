# 0100 — Banner unification across launcher and popup

**Status:** Accepted
**Date:** 2026-05-24

## Context

The launcher main page and the in-game popup's `main` frame both show
a starfield + MUME / COCKPIT wordmark banner. They were not always
rendered from the same module. `launcher_banner.py` was originally
split off from a frozen `banner.py` so the launcher banner could
evolve independently — gain a twinkle animation, tweak star
positions — without churning the popup. The wordmark glyphs were
duplicated between the two modules as the accepted cost of that
decoupling.

Once the launcher banner stabilised, the popup still showing a
different, static banner became the worse outcome. The two surfaces
sit a single keystroke apart (`<Esc>` swaps a live game pane for the
popup over the launcher's chrome grammar, ADR 0085), and visual drift
between them is the kind of inconsistency that ADR 0085 was created
to eliminate elsewhere.

The tt++ welcome screen (`ttpp/core/welcome.tin`) is a different
surface: not a `prompt_toolkit` application, just `#showme` lines
emitted into the game window before connect. It carries its own
hardcoded MUME / COCKPIT wordmark art and has no starfield.

## Decision

One Python source of truth for the banner —
`bridge/launcher/launcher_banner.py` — rendered (animated) by both
`prompt_toolkit` surfaces: the launcher main page and the in-game
popup's `main` frame. The frozen `banner.py` retires; the wordmark
duplication between the two Python modules ends.

`launcher_banner.banner_lines(now=None)` is a pure function of the
monotonic clock with no per-frame mutable state. Each surface drives
its own redraw — the launcher's `_banner_tick_task` at 12 Hz, the
popup's at 6 Hz — and each invalidates only while its main frame
shows. The 11-row layout (5 starfield + 3 MUME + 3 COCKPIT, no blank
separator) is the canonical banner geometry for both.

The tt++ welcome screen deliberately does **not** share this module.
It keeps its own hand-maintained `#showme` lines and prints a static,
starless wordmark only. The welcome surface is a tt++ startup
surface, not a `prompt_toolkit` one, and the wordmark art is frozen,
so accepting a small amount of duplication there beats every
alternative for surfacing the shared module to tt++.

## Consequences

**Easier.** One Python module to edit for the launcher / popup
banner — change a star's tier or position once, both surfaces follow.
The popup's main frame gains the twinkle animation for free, paid for
by a single new main-frame-gated `_banner_tick_task`.

**Harder.** The popup now owns a second async tick loop on top of its
existing 1 Hz status-refresh `_tick`. Banner ticks invalidate only
while `_current_frame == "main"`, so a submenu or a closed popup
costs nothing — but the loop's lifecycle (start in `_run`, cancel in
the `finally` block) is one more thing to keep symmetric with the
launcher. The popup runs at 6 Hz rather than the launcher's 12 Hz:
the twinkle is discrete and slow, the popup overlays a live game,
and dropping the redraw rate halves the invalidate work for no
visible difference.

**Locked out.** The welcome wordmark and the
`launcher_banner.py` wordmark may drift over time — they are two
separate copies of frozen art, and there is no build step linking
them. That drift risk is the accepted cost of not pulling Python
rendering into tt++'s startup path.

## Alternatives considered

**Keep `banner.py` as a static popup banner.** Leave the popup on the
frozen pre-twinkle art and let the launcher's banner be the lively
one. Rejected: the popup diverging from the launcher is the bad
outcome we are trying to fix, and keeping the popup intentionally
plainer than the launcher would have read as a UI bug, not a
deliberate choice.

**Generate the welcome banner from `launcher_banner.py` via a build
step.** A precommit script or a `make`-style step could emit the
`#showme` lines from the same Python source. Rejected: the wordmark
art is frozen and the welcome screen is a static splash — paying a
build-step's complexity for two seconds of plain-white logo at
startup is the wrong trade. The duplication is small (six lines of
art) and noisy to maintain in tandem only when the wordmark itself
changes, which is rare.

**Render the welcome screen in Python.** Have `welcome.tin` shell out
to a Python helper that prints the banner. Rejected: the welcome
surface is a tt++ startup surface — adding a Python subprocess to
that path inverts the dependency direction (tt++ depending on a
Python helper for boot output) and adds startup latency for no real
gain. The hardcoded `#showme` lines are the right shape for that
surface.
