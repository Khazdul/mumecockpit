# ADR 0113 — Too-small gate: in-gate terminal reset hatch (foot-managed)

**Status:** accepted

## Context

The launcher's Options → Terminal page exposes a user-selectable window mode
and font size (ADR 0107). A user can pick a combination — typically
`initial-window-mode=windowed` with a large font — that, on the next
relaunch, drops the foot window below the launcher's `MIN_COLS=60` /
`MIN_ROWS=18` minimum-size gate. The gate then takes over the root layout
and swallows every key except Ctrl-C / Ctrl-Q.

That state is a lockout. The only in-product UI for changing the font and
window mode is Options → Terminal, which is unreachable because the gate
sits in front of it. The exits Ctrl-C / Ctrl-Q quit the cockpit but do not
fix the underlying foot.ini — the next launch returns straight to the
gate. Recovery without a hatch requires editing foot.ini by hand from
outside the cockpit, which neither the launcher nor the Windows
installer's user-facing documentation covers.

Only the foot/WSLg managed-terminal deployment (`MUME_TERMINAL=foot-managed`,
ADR 0104) owns foot.ini and the supervisor relaunch loop, so only it can
self-heal. On every other terminal the cockpit doesn't own the host
window's dimensions and has nothing safe to rewrite.

## Decision

Bind R / Shift+R inside the too-small gate, gated on
`MUME_TERMINAL=foot-managed`, to an in-gate reset that:

1. Reads the current foot.ini through `bridge/launcher/foot_config.py`.
2. Replaces the `initial-window-mode` field with `fullscreen` and the
   font `size=` attribute with `15`. Every other managed key — family,
   pad, background, cursor style, cursor blink, window pixel size — is
   preserved verbatim, as are all unmanaged lines.
3. Writes the file via `foot_config.write_settings` (the managed-keys
   atomic writer from ADR 0107).
4. Drops the relaunch sentinel + `.launcher_resume` hint and exits,
   reusing the Options → Terminal Apply relaunch tail so the supervisor
   brings foot back at safe defaults.

The gate prints a `"Press R to reset terminal settings to defaults"` hint
under the "Terminal too small" line only when the foot-managed filter
matches. The explicit R binding beats the gate's `<any>` swallow only
when the same filter matches; on every other terminal R is swallowed
exactly as before — fail-closed.

Both window mode **and** font size are rewritten. Fullscreen alone is not
a safe fallback: at maximum font size on a low-resolution monitor, even a
fullscreen window can still fall below the 60×18 gate. Resetting the
font size to a value known to clear the gate on any reasonable display is
required for the hatch to actually rescue the user.

## Consequences

- The lockout failure mode has an in-product, single-keystroke recovery
  path under the deployment that owns foot.ini.
- The reset never makes a working install worse: it preserves family,
  colours, cursor, pad, and pixel size, and only touches two fields that
  the user has demonstrably set wrong. A user who deliberately wants
  `windowed` + a large font can pick those again from Options → Terminal
  after the relaunch.
- An R keypress in any non-foot-managed terminal that falls below the
  gate is still swallowed, matching pre-existing behaviour. There is no
  surprise rewrite of an unmanaged terminal config.
- If the write fails (permissions, disk full), the handler returns
  silently and the gate stays up — Ctrl-C / Ctrl-Q still exit. The user
  is no worse off than before the hatch existed.

## Rejected alternatives

- **Pre-flight validation at Apply.** Refuse or clamp `windowed` +
  large-font combinations from inside Options → Terminal so the user can
  never produce a too-small foot. Rejected: the unsafe threshold depends
  on the host monitor resolution and DPI, which the launcher cannot
  reliably query under WSLg (the resolution-detection limitation already
  documented in ADR 0107). A pre-flight check would either be too
  conservative (blocking legitimate setups) or too permissive (still
  letting the lockout happen). Recovery on the gate is robust regardless
  of which dimensions broke.

- **External CLI reset path.** A `mume-cockpit --reset-terminal` flag,
  or a separate `bridge/launcher/reset_terminal.py` invoked from
  outside foot. Rejected: it pushes recovery off the surface where the
  user is actually stuck (the running foot window) and into a place they
  cannot reach without instructions. The whole point of the lockout is
  that the cockpit's UI is the only thing the user knows how to drive;
  asking them to open a Windows shell, find a WSL command, and type a
  flag is a worse experience than a single keystroke on the screen
  already in front of them.

## See also

- [ADR 0104](0104-windows-deployment-foot-wslg.md) — the foot/WSLg
  deployment, `MUME_TERMINAL=foot-managed`, the supervisor relaunch
  loop, and the `.relaunch_terminal` sentinel.
- [ADR 0107](0107-terminal-settings-managed-keys.md) — Options →
  Terminal as the user-facing surface that can produce the lockout, and
  the managed-keys foot.ini writer the reset reuses.
