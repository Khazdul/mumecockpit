# 0104 — Windows deployment: foot under WSLg, fullscreen, supervisor-owned

**Status:** Accepted
**Date:** 2026-05-26

## Context

ADR 0103 decided that the Windows deployment must run the cockpit's terminal as
a Linux GUI application under WSLg, to keep ConPTY out of the render path. This
ADR selects the terminal emulator and the launch and lifecycle architecture
that realise that decision.

Scope is Windows-only. Native Linux and macOS deployments are unchanged.

## Decision

### Terminal: foot

The Windows deployment's terminal is **foot**. It is Wayland-native (WSLg
provides a Wayland display), CPU-rendered with no GPU/EGL dependency, modern,
truecolor, and has full block / box-drawing glyph coverage — which the cockpit
panes require.

### Fullscreen-only

foot runs with `initial-window-mode=fullscreen` — true fullscreen, not
`maximized`. A dedicated game client owns the screen; it does not tile beside
other windows. True fullscreen has no decorations to render, which dissolves
the titlebar, interactive-resize, and "two windows" problems by design. foot's
fullscreen-toggle keybinding is kept as a harmless escape hatch.

### Direct launch via a WSLg .desktop entry

The installer ships `mume-cockpit.desktop` (with an icon) into WSL. WSLg
surfaces Linux `.desktop` files in the Windows Start Menu as a core feature, so
the cockpit gets a Start Menu entry with no intermediate terminal window and no
console flash — unlike invoking `wsl.exe` from a Windows `.lnk`.

### Supervisor-owned foot lifecycle

A process cannot cleanly restart its own terminal, and the terminal font is a
property of foot (foot.ini). A small bash **supervisor** (`bridge/supervisor.sh`)
therefore owns foot's lifecycle and is the entry point the `.desktop` launches:

- It loops: launch foot running the cockpit entry, wait for foot to exit, check
  for a relaunch **sentinel file**; if present, remove it and loop (the fresh
  foot reads an edited foot.ini); if absent, exit.
- It exports `MUME_TERMINAL=foot-managed`, which foot passes through to the
  cockpit, signalling the managed-foot deployment.
- It clears any stale sentinel at its own startup, so a crash mid-relaunch
  cannot mis-route a subsequent cold start.

### Relaunch IPC: a sentinel file

Relaunch is triggered by a sentinel file (`bridge/runtime/.relaunch_terminal`),
not by foot exit-code propagation — the sentinel does not depend on foot's
exit-code behaviour, and it matches the existing `bridge/runtime/` sentinel
convention.

## Consequences

- Decoupling foot's lifecycle from the cockpit process is what makes a
  font-change relaunch possible (the launcher exits, the supervisor brings up a
  fresh foot). It also leaves room for free crash-restart behaviour later.
- `MUME_TERMINAL` is the single signal that deployment-aware UI grinds on — the
  Terminal Settings submenu appears only under the managed-foot deployment. The
  launcher fail-closes: an absent or unknown value means no managed-terminal UI.
- Accepted trade-off: WSLg is a compatibility layer, not a polished desktop.
  Its minimal Weston compositor produces cosmetic warts in any terminal.
  Fullscreen-only neutralises nearly all of them — no decorations, no
  interactive resize. The one residual is the WSLg cursor-offset bug
  (microsoft/wslg #1290 and #935), which fullscreen does not address; it is
  manageable because the launcher's hover-highlight gives visual feedback
  before any click.

## Alternatives considered

**Linux-Alacritty under WSLg.** Rejected: Alacritty needs OpenGL/EGL and WSLg's
GPU stack fails it. GPU acceleration is in any case a liability rather than a
benefit for a tiny-trickle MUD workload.

**xterm (X11) under WSLg.** Rejected: it gets real window decorations, but is
dated-looking, has laggy interactive resize, and the cockpit panes did not
render correctly.

**Launcher detach-respawns foot itself** (`setsid foot &`, then exit).
Rejected: relies on fragile session/teardown timing. A dedicated supervisor
owns the lifecycle cleanly.

**foot exit-code propagation for relaunch.** Rejected: depends on foot's
exit-code behaviour. A sentinel file does not.

## Relation to other ADRs

- Builds on **ADR 0103** — the decision to move the Windows terminal off the
  ConPTY path.
- The WSLg `.desktop` → supervisor → cockpit entry path supersedes the Windows
  `.lnk` delegation of **ADR 0028** for the Windows deployment. The argv-mangling
  concern that motivated ADR 0028 no longer applies — there is no
  alacritty → wsl → bash chain.
- **ADR 0015** (Windows installer supports 22H2+ only) still applies unchanged.
