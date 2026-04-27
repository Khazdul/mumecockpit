# 0015 — Windows installer supports Windows 11 22H2+ only

**Status:** Accepted

## Context

- The cockpit's primary value on Windows is the MMapper integration.
- MMapper runs natively on Windows and listens on `localhost`. tt++ inside
  WSL needs to reach that port, which requires WSL2's mirrored networking
  mode (`networkingMode=mirrored` in `.wslconfig`).
- Mirrored networking requires Windows 11 22H2 (build 22621) or newer.
- Earlier Windows can run the cockpit in direct mode (no MMapper) but the
  user experience is degraded enough that it is not what we want to ship as
  "the installer".
- The original install-bootstrap plan included a "slow path" for enabling WSL
  features from scratch with reboot + resume — significant complexity for a
  small audience.

## Decision

The installer rejects Windows older than build 22621 at pre-flight with a
clear, actionable error message. Slow path is removed — if WSL2 is not
already enabled on an otherwise-supported machine, the user is instructed to
run `wsl --install` manually and re-run the installer.

## Consequences

- Installer code is materially simpler. No `$useMirrored` branching, no
  marker-file resume logic, no reboot orchestration, no Windows 10 pitfalls
  section in the docs.
- Users on Windows 10 or pre-22H2 Windows 11 cannot use the installer. They
  can still run `bootstrap-linux.sh` inside their own WSL and configure the
  Windows side by hand, but the desktop shortcut and Alacritty config must
  be set up manually.
- If a future use case for direct-mode-only Windows users emerges, this
  decision can be revisited. Nothing in the codebase locks it in permanently
  — the build check is one constant.

## Alternatives considered

- **Accept Windows 11 21H2 (build 22000+).** Adds a half-supported tier where
  MMapper does not work; same problem as Windows 10, just smaller audience.
  Rejected.
- **Keep slow path as documented but unimplemented.** Documentation debt
  without user value. Rejected — better to remove cleanly.
- **Build a "direct mode only" fast-path.** Would split the installer into two
  modes; doubles surface area for a minority case. Rejected.
