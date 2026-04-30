# 0028 — Windows shortcut delegates to Linux-side launcher

**Status:** Accepted
**Date:** 2026-04-30

## Context

The original desktop shortcut embedded the full launch expression in its
Arguments field:

```
alacritty.exe -e wsl -d Ubuntu -u root -- bash -lc "cd /root/MUME && ./start.sh"
```

On at least one tested Windows host the alacritty → wsl → bash chain
mangled the quoted argument, surfacing as `./start.sh: No such file or
directory` even though the file existed and the same command worked from
PowerShell directly. The failure isolated to alacritty `-e` argv handling
on Windows, not to WSL or bash themselves.

## Decision

The shortcut now invokes a single unquoted path:

```
alacritty.exe -e wsl -d Ubuntu -u root -- /root/MUME/bridge/launch.sh
```

The shortcut's Arguments field contains no shell metacharacters. The
`cd`-and-exec logic lives in the Linux-side `bridge/launch.sh`.

The installer verifies that both `bridge/launch.sh` and `start.sh` are
executable before finishing; it aborts with a clear error if either is
missing.

## Consequences

- The quoting bug cannot recur: there is nothing to quote. The shortcut
  is immune to future argv-mangling anywhere in the alacritty → wsl →
  bash chain.
- One extra file to maintain (`bridge/launch.sh`), though it is trivial.
- macOS and Linux flows are unaffected — `launch.sh` exists in the repo
  but is not invoked on those platforms.

## Alternatives considered

**Keep the inline `bash -c` expression, find the right escaping.** The
escaping rules differ between `alacritty -e`, `wsl --`, and the Windows
shell. Future alacritty or WSL versions can reintroduce the bug
independently of each other. Surface area is too large. Rejected.

**Use `start.sh` directly as the shortcut target.** `start.sh` uses
`cd "$(dirname "$0")"` to locate itself, so it would work in this case.
But that couples the shortcut to an internal convention of `start.sh`
and makes the entry point implicit. The wrapper makes it explicit.
Rejected.
