# 0102 — Fast WSL clipboard read via win32yank

**Status:** Accepted
**Date:** 2026-05-24

## Context

ADR 0022 bound Ctrl+V in the input pane to a clipboard paste that reads
the system clipboard via `pyperclip.paste()`. On WSL, pyperclip has no
native clipboard access and delegates to `powershell.exe Get-Clipboard`.

ADR 0022's trade-off section described this as a "~200–500 ms on first
use" cost and judged it acceptable. That framing was wrong in one
respect: pyperclip does not cache, so every `paste()` call re-spawns
`powershell.exe`. The cost is per-paste, not one-off, and the
`powershell.exe` runtime initialisation dominates it. Players noticed
the delay on each Ctrl+V.

macOS and native Linux are unaffected: pyperclip there shells out to
`pbpaste` / `xclip` / `xsel` / `wl-paste`, all small native binaries
that spawn in low tens of milliseconds.

## Decision

Add a WSL-only fast path to `_read_clipboard()` in
`bridge/panes/input_pane.py`:

- On WSL (detected once at module load via `/proc/version`), read the
  clipboard by invoking `win32yank.exe -o --lf` at
  `~/MUME/bin/win32yank.exe`. `--lf` normalises Windows CRLF line
  endings to LF before the text reaches the command buffer.
- On any failure — binary missing, non-zero exit, exception — fall
  through to the existing `pyperclip.paste()` path. The fallback is
  silent and never crashes the input pane.
- On macOS and native Linux the code path is unchanged: `pyperclip`
  directly.

`win32yank` (pinned to release `v0.1.1`) is provisioned by a
WSL-guarded step in `install/bootstrap-linux.sh`. The step downloads
and extracts the binary to `~/MUME/bin/`, is idempotent (skips if the
binary already exists), and is non-fatal — a failed download prints a
warning and lets the bootstrap complete. `bin/` is gitignored; the
binary is never tracked. `install/installer-core.ps1` is not touched —
the Windows one-click installer already runs `bootstrap-linux.sh`
inside WSL, so the capability is added without changing the PowerShell
flow.

## Trade-offs

**Accepted:**

- Faster, but not instant. win32yank removes the expensive part — the
  `powershell.exe` runtime init — but the residual cost is the
  WSL→Windows interop process-spawn boundary itself: roughly tens of
  milliseconds, paid on every Ctrl+V. This is irreducible as long as
  Ctrl+V reads the live Windows clipboard through a Windows binary.
- A new downloaded binary dependency on WSL. It is gitignored and
  fetched at bootstrap time rather than vendored into the repo.
- The new bootstrap code path is not exercised on a machine that
  already has the binary (idempotent skip). Its first real run is a
  fresh WSL install.

**Gained:**

- Per-paste latency drops from ~200–500 ms (variable) to a small,
  consistent cost.
- macOS and native Linux carry zero regression risk — their code path
  is byte-for-byte unchanged.
- A failed win32yank download degrades to the old pyperclip path
  instead of breaking either the install or paste.

## Truly-instant path

Bracketed paste — `Ctrl+Shift+V`, middle-click — is handled by the
existing `Keys.BracketedPaste` binding. The terminal already holds the
clipboard contents and hands them straight to prompt_toolkit; there is
no subprocess and no interop boundary, so it is genuinely instant on
every platform. It remains the recommended path when latency matters.
Ctrl+V via win32yank is kept as the path that does not depend on the
terminal's own paste shortcut.

## Rejected alternatives

**OSC 52 read.** Query the clipboard with an OSC 52 read sequence.
Rejected for the same reasons ADR 0090 rejected it for the launcher:
off by default in most terminals, and Alacritty — the primary terminal
— implements only the write side of OSC 52. It would also require
stealing prompt_toolkit's stdin for a synchronous round-trip.

**Resident Windows-side helper + socket IPC.** A long-running Windows
process serving clipboard reads over a socket would eliminate the
per-paste spawn. Rejected as disproportionate machinery — a resident
process and an IPC channel — to save tens of milliseconds on an
occasional action.

**Background polling / caching.** Poll the clipboard on a timer and
serve Ctrl+V from a cache. Rejected: constant process churn to serve
an infrequent paste, plus a stale-cache race when the player copies
something and immediately pastes it.

**Long-lived `powershell.exe` process.** Keep one powershell process
warm and pipe commands to it. Rejected: process-lifecycle complexity
(detecting and restarting a dead process) for a smaller gain than
win32yank already delivers.

## Relation to other ADRs

- Refines ADR 0022. The pyperclip read path it introduced is retained
  as the fallback and as the macOS / native-Linux path. This ADR
  corrects 0022's "~first use" cost framing.
- Consistent with ADR 0090 (launcher clipboard: OSC 52 write, no read)
  — same reasoning about OSC 52 read, different surface.
