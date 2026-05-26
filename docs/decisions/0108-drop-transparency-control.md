# 0108 — Terminal Settings: drop the transparency control

Status: Accepted. Supersedes the transparency decision in ADR 0107.

## Context

ADR 0107 exposed background transparency (foot's `[colors] alpha`) as a
Terminal Settings control, as a calculated risk: it was unknown whether
WSLg's compositor renders a transparent foot surface, and the default of
1.0 (fully opaque) meant a non-compositing host would simply ignore the
setting.

Real-machine testing on Windows 11 confirmed that WSLg does not composite
the alpha — a sub-1.0 `alpha` has no visible effect. The control is dead on
the only platform the foot deployment targets.

## Decision

Remove the transparency control entirely:

- the Transparency row and its stepper are removed from the launcher
  Terminal Settings page;
- `alpha` is dropped from `foot_config.py`'s managed key set, and the
  `alpha` field is removed from `TerminalConfig`;
- the `alpha` line is removed from the shipped `install/examples/foot.ini`.

An `alpha` line already present in an installed user's foot.ini is left
untouched — once `alpha` is unmanaged, the writer preserves it verbatim as
an ordinary unmanaged line. At its default of 1.0 it is a harmless no-op.

## Consequences

- No transparency setting. foot still reads `[colors] alpha` if a user
  hand-edits it, but the cockpit neither sets nor relies on it.
- Should a future, non-WSLg foot deployment composite alpha,
  re-introducing the control is a small, well-understood change.

## Supersedes

The transparency portion of ADR 0107. ADR 0107 otherwise stands.
