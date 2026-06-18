# 0143 — Terminal colour palette separate from the pane palette; foreground as a managed foot.ini key

**Status:** Accepted
**Date:** 2026-06-19

## Context

ADR 0107 expanded Terminal Settings and gave its Background control a
fixed-value cycle that reused `PANE_COLOR_ORDER` / `PANE_COLORS` — the same
palette the per-pane background grid draws from. Two changes broke that
reuse:

- **More terminal backgrounds.** Beyond the existing pane tints we wanted
  Teal / Sepia / Slate / Paper as terminal-only options. These are not pane
  tints and have no place in the Panes grid.
- **A foreground control.** Terminal Settings gained a Font color row, so
  the terminal now needs a foreground palette as well as a background one.

That forced a choice: extend `PANE_COLORS` to carry the new terminal
colours, or give terminal colours their own dedicated palette.

## Decision

Terminal colours get a **dedicated palette** in `bridge/launcher/palette.py`,
kept separate from `PANE_COLORS`:

- `TERMINAL_BG_ORDER` lists the eleven background names; `TERMINAL_BG_EXTRA`
  holds the four terminal-only extras (teal / sepia / slate / paper).
- `TERMINAL_FG` / `TERMINAL_FG_ORDER` is a short foreground ramp (sage →
  silver → ash → stone → shadow → ink).

The seven pane-tint names are **referenced, not copied**:
`terminal_bg_hex(name)` resolves shared labels through `pane_color_hex`,
so a user who matched their terminal to a pane tint sees the same label.
Because a terminal background is always a concrete colour (unlike a pane
tint, where the `black → None` sentinel means "no bg override"), the
sentinel resolves to literal `#000000` here.

Foreground is added to `foot_config`'s managed key set following ADR 0107's
managed-keys pattern, default `dcdccc` (foot's own default, so an absent
key is a no-op). The shipped `install/examples/foot.ini` template keeps its
DOS-palette `foreground=C0C0C0`, and `silver` is `#C0C0C0` so that shipped
value snaps onto a named swatch on a clean install rather than rendering as
a raw hex. `paper` is a deliberate off-white (`#F4ECD8`), not pure
`#FFFFFF`, because pure white did not render correctly with chrome that
assumes a dark background.

## Consequences

- The Panes grid is untouched — no non-pane columns leak into it.
- No new sync burden on `open_pane.sh` or `pane_frame.py`: the terminal
  palette stays out of the pane layer, preserving ADR 0126's separation.
- The Background cycle no longer reuses `PANE_COLOR_ORDER`; it reads the
  dedicated terminal palette.
- Foreground and background are chosen independently — no locked pairings.
- Off-palette on-disk colours (hand-edited foot.ini) survive a no-op Apply:
  both cycles prepend an unmatched on-disk value, labelled by its hex.

## Alternatives considered

**Fold terminal colours into `PANE_COLORS`.** Rejected: it pollutes the
Panes grid with non-pane columns (teal / sepia / slate / paper / the
foreground ramp) and drags pane-layer files (`open_pane.sh`,
`pane_frame.py`) into terminal-only changes, against ADR 0126's separation
of the pane layer from the launcher.

**A locked light/dark theme pairing foreground with background.** Rejected:
free combination of any foreground with any background was the requirement;
a fixed pairing would have removed exactly the flexibility the foreground
control was added to provide.

## Relation to other ADRs

- Builds on [ADR 0107](0107-terminal-settings-managed-keys.md) (managed-keys
  foot.ini editing) — extends its managed set with `foreground`; does not
  supersede it.
- Relates to [ADR 0126](0126-timers-layout-menu.md): the terminal palette
  stays out of the pane layer for the same separation reason (the pane
  packages must not import from `bridge/launcher`).
