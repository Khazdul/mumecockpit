# 0116 — Pin Lua runtime to 5.4 across platforms

## Status

Accepted — 2026-05-29.

## Context

`brain.lua` and the `lua/core/*.lua` infrastructure use Lua 5.4 semantics.
The proven trigger is the `<const>` attribute on locals (e.g.
`local name <const> = ...` in `lua/core/readability.lua`); other 5.4-only
constructs may exist elsewhere.

Homebrew's rolling `lua` formula upgraded to Lua 5.5 around April 2026.
The macOS bootstrap installed the rolling formula by name, so any fresh
macOS install (or any `brew upgrade`) after that point silently picked
up Lua 5.5. The failure mode was unhelpful at the surface:

- `lua/core/readability.lua` errored on script load with
  `attempt to assign to const variable 'name'`.
- That error killed the `lua` sub-session started by
  `#run {lua} {lua lua/brain.lua}` in `main.tin`.
- With no `lua` session alive, the 4 Hz `#ticker {clock}` in
  `ttpp/core/clock.tin` spammed `#ERROR: UNKNOWN TINTIN COMMAND 'lua'`
  on every tick.

Linux was unaffected: the apt package `lua5.4` is pinned by name. The
risk is symmetric in principle — a future Ubuntu release could ship
`lua5.5` as the default — but we had no mechanism to detect a version
mismatch on either platform until the symptoms appeared at runtime.

The parallel pattern for runtime pinning already exists for tt++ on
Linux — see [ADR 0035](0035-tt-from-source.md). This ADR mirrors that
rationale and tone for Lua.

## Decision

1. macOS bootstrap installs `lua@5.4` instead of `lua`.
   `lua@5.4` is keg-only on Homebrew, so the binary does not land on
   PATH automatically.
2. `start.sh` prepends brew's `lua@5.4` keg to PATH on macOS, via
   `brew --prefix lua@5.4`. Linux is left alone — `apt`'s `lua5.4`
   binary is on PATH directly.
3. `start.sh` adds a pre-flight version check that aborts startup
   with a clear error if `lua -v` does not report `5.4.x`. The check
   runs on all platforms and is what protects us against future
   silent drift (brew removes `lua@5.4`, apt switches default to
   `lua5.5`, user's PATH overrides ours, …).
4. `main.tin`'s `#run {lua} {lua lua/brain.lua}` is left unchanged.
   The PATH prepend in `start.sh` is what makes that line resolve to
   the right interpreter.

## Alternatives considered

- **Source-build Lua 5.4 in bootstrap**, parallel to ADR 0035 for tt++.
  Rejected for now: Lua is far more stable than tt++ as a dependency,
  `lua@5.4` is a long-supported Homebrew formula, and the pre-flight
  check converts any future formula removal into an actionable error
  rather than silent degradation. If `lua@5.4` is ever removed from
  brew or apt drops `lua5.4`, source-build becomes the next step.
- **Make `brain.lua` and friends compatible with Lua 5.5.** Rejected:
  Lua 5.5 was released in early 2026 and is not widely deployed yet;
  the maintenance cost of dual-version compatibility outweighs the
  benefit while 5.4 remains the standard runtime everywhere else.
- **Vendor a Lua binary inside the repo.** Rejected as overkill for a
  well-packaged interpreter. Binary blobs in git are bad practice and
  cross-distro glibc compatibility is fragile.
- **Probe Lua's version inside `brain.lua` itself.** Rejected: by the
  time `brain.lua` runs, the sub-session is already alive and a bad
  interpreter will have failed on the first script load. A pre-flight
  check in `start.sh` fails earlier and with a clearer error.

## Consequences

- macOS users get a deterministic Lua 5.4 runtime regardless of
  brew's rolling formula state.
- The pre-flight check protects all platforms against future silent
  version drift — including a future Ubuntu shipping `lua5.5` as
  the default `lua` binary.
- If `lua@5.4` is ever removed from brew, bootstrap installs will
  fail loudly at the `brew install` step, and `start.sh` will refuse
  to launch the cockpit until Lua is resolved. Action: switch to
  source-build, documented as a deferred follow-up in
  `docs/install-bootstrap.md`.
- Does **not** address tt++ runtime fragility on macOS. That remains
  a separate concern — see `docs/install-bootstrap.md` Open
  question 3, now scoped to TLS-pinning only.

## Amendment — 2026-08-16 (Linux resolution verified on CachyOS)

Decision point 2 scoped Linux out of PATH resolution because apt's
`lua5.4` binary lands on PATH directly. That reasoning holds for the
Debian/Ubuntu family only. Arch-family distros ship bare `lua` at 5.5+
and put the 5.4 build under a versioned name, so the same failure the
ADR documented on macOS was reachable there. A Linux resolution block
in `start.sh` now mirrors the macOS keg-prepend: when bare `lua` does
not report 5.4.x, it probes the candidates `lua5.4` then `lua54`,
symlinks the first match to `bridge/runtime/bin/lua`, and prepends that
directory to PATH. Debian/Ubuntu stays a no-op. The pinning decision
therefore now covers Linux distros where bare `lua` has moved past 5.4,
not macOS alone.

That block was implemented but unverified in the field until now. It is
verified on CachyOS (Arch family) as of this date:

- Bare `lua` reports Lua 5.5.1. The `lua54` package provides the binary
  as `lua5.4` (version 5.4.8), so the first candidate in the probe
  order matches.
- `start.sh` created `bridge/runtime/bin/lua` as a symlink to
  `/usr/bin/lua5.4`, and the pre-flight version check passed.
- The cockpit started with the Lua brain alive: no `<const>` load error
  in `lua/core/readability.lua`, and no `#ERROR: UNKNOWN TINTIN COMMAND
  'lua'` spam from the clock ticker — the two symptoms the Context
  section documented on macOS.

The interaction with the update channel is a verified non-issue rather
than an open risk. `git status --short` was clean after the run:
`bridge/runtime/` is gitignored, so the generated symlink does not dirty
the working tree. This matters because `update.sh` guard 4b rejects an
update when untracked files exist outside `ttpp/profiles/` and
`lua/scripts/`. Had `bridge/runtime/` not been ignored, every Arch-family
user would have hit exit 21 on their first launcher update.
