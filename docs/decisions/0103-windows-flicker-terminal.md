# 0103 — Windows inbound-burst flicker: move the terminal off the ConPTY path

**Status:** Accepted
**Date:** 2026-05-26

## Context

A visual flicker was observed on inbound text bursts under the Windows
deployment. On a room-description burst the green room-name line is briefly
visible scrolling through an intermediate position before settling into place.
It reproduced reliably against the live MUD with the full app configuration,
and was absent when running bare tt++.

A long investigation ruled out, in turn:

- the async Lua relay,
- tmux compositing,
- monitor refresh rate / vsync,
- producer/consumer wire-spread.

The confirmed root cause is the **WSL2 ↔ Windows-terminal interop path** — the
WSL relay / ConPTY layer that sits between a Linux process and a Windows
terminal emulator.

Mechanism. A burst is emitted by tt++ as roughly nine per-line `write()` calls.
The WSL relay coalesces writes within a small time window and adds per-transfer
latency across the VM boundary. Bare tt++'s burst spans about 0.2 ms — it fits
inside the coalescing window, crosses the boundary as a single atomic transfer,
and does not flicker. The full app's burst spans about 0.8 ms: it is stretched
by roughly 150 `#action` / `#event` handlers processed interleaved between the
per-line writes. That exceeds the window, so the burst crosses as multiple
transfers smeared across display frames, and the terminal renders it
progressively.

The decisive proof: running tt++ with the full app configuration in a Linux
terminal under **WSLg** eliminates the flicker entirely. WSLg gives the terminal
a native Linux PTY with no ConPTY in the path. macOS and native Linux never
exhibit the flicker — they have no Windows-terminal interop path.

## Decision

Take the Windows-terminal interop path out of the picture: the Windows
deployment runs the cockpit's terminal as a **Linux GUI application under
WSLg**, so the terminal talks to a native Linux PTY and ConPTY is no longer in
the render path.

This is a **Windows-deployment-only** change. Native Linux (tier 1) and macOS
(tier 2) never had the flicker and never had a Windows-terminal interop path;
they are unchanged.

The concrete terminal emulator and the launch/lifecycle architecture are
decided separately in **ADR 0104**.

## Consequences

- The inbound-burst flicker is eliminated on Windows, because ConPTY is no
  longer a re-rendering layer in the path.
- The codebase carries **no** flicker workaround — no output-buffering shim, no
  synchronized-output handling. The fix is structural, in the deployment.
- The Windows deployment now depends on WSLg, a compatibility layer with its
  own rough edges. That trade-off, and how it is contained, is the subject of
  ADR 0104.

## Alternatives considered

**Option C — tt++ output buffering / write coalescing.** Make tt++ emit the
burst as one write so it fits the relay's coalescing window regardless of
handler timing. Rejected: no such tt++ configuration exists; `stdbuf`
full-buffering breaks interactivity; patching TinTin++ is out of scope.

**Synchronized output (DEC private mode 2026).** Have the application bracket
the burst so the terminal batches it regardless of relay chunking. Rejected
with ConPTY in the path: ConPTY is itself a re-rendering middle layer, Windows
Terminal gained mode-2026 support only recently, and ConPTY's ANSI handling is
a documented bottleneck. Not a reliable fix while ConPTY is present — and once
ConPTY is removed (the chosen decision) it is unnecessary.

## Relation to other ADRs

- **ADR 0104** builds directly on this decision — it selects foot under WSLg
  and the supervisor-owned launch architecture.
- **ADR 0015** (Windows installer scope, 22H2+) is unaffected; the WSLg
  approach does not change the supported-Windows floor.
