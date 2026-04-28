# ADR 0020 — Platform support policy

Date: 2026-04-28
Status: Accepted

## Context

The cockpit started as a WSL/Ubuntu-only project. Over time it
gained a Linux-native bootstrap and a macOS bootstrap, but neither
was end-to-end validated against a real run of `start.sh`. The
macOS bootstrap installed packages but the cockpit code itself
contained Linux-specific assumptions (`stat -c`, `ping -W`,
bash 4+ syntax under macOS's bash 3.2) that broke at runtime.

A spike on a fresh macOS Tahoe machine surfaced these issues, all
of which were fixable but only by handling each platform explicitly.

## Decision

Three support tiers:

- **Tier 1 — Linux (incl. WSL/Ubuntu).** Primary development and
  runtime target. All features must work here. Breakage blocks
  merges.
- **Tier 1 — Windows (via WSL2 + Alacritty).** Treated as Linux
  runtime; the Windows installer is its own surface (see ADR 0015).
- **Tier 2 — macOS.** Best-effort. Code must not be gratuitously
  Linux-specific. Known platform differences (BSD vs GNU userland)
  are handled with detect-once helpers, not parallel implementations.
  No automated CI; validation is manual on a real Mac before
  releases that touch shell-level code.

## Consequences

- New shell code must avoid GNU-only flags when a portable
  alternative exists. Examples:
  - `stat -c '%Y'` (GNU) vs `stat -f '%m'` (BSD) — use `file_mtime`
    helper.
  - `ping -W 1` (1s on Linux, 1ms on Mac) — detect platform.
  - `sed -i` (GNU) vs `sed -i ''` (BSD) — prefer temp-file rewrite
    when scripts edit files in place.
  - `date -d` (GNU) vs `date -j -f` (BSD) — prefer Lua/Python for
    date math when both platforms must work.
- Bash 4+ features are allowed; macOS users install Homebrew bash 5
  and the bootstrap requires it. `#!/usr/bin/env bash` shebangs
  pick up the brew-installed bash via PATH.
- macOS bug reports are accepted; macOS-specific feature requests
  that significantly complicate the codebase may be declined.

## Rejected alternatives

**Drop macOS support entirely.** Rejected: the manual fixes for
macOS are small and well-contained. Most of them improve code
hygiene (explicit platform handling instead of accidental
GNU-isms).

**Maintain bash 3.2 compatibility for macOS.** Rejected: removing
bash 4+ features would touch most launcher and menu code, increase
regression risk, and impose a permanent discipline. Installing
brew bash is two extra lines in the bootstrap.

**Add CI for macOS.** Deferred. Manual validation on a real Mac
before shell-level releases is enough at current project size.
Revisit when contributor count justifies it.
