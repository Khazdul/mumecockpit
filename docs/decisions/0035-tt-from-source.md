# 0035 — Build tt++ from source when system version is unsuitable

## Context

Ubuntu 22.04's apt package for `tintin++` ships version 2.02.03 — far below
the 2.02.20 floor the cockpit needs for stable GMCP behaviour. More critically,
the Ubuntu/Debian build of tt++ is compiled without GnuTLS linkage: without
TLS, `#session` in direct mode fails immediately on any MUME server that
requires encryption, making the cockpit's direct-mode path completely unusable
on a stock 22.04 install.

Ubuntu 24.04 ships `tintin++` version 2.02.20, which satisfies the version
floor. However, the Debian/Ubuntu packaging historically omits GnuTLS
regardless of Ubuntu version, so the TLS failure persists even on 24.04.

The original bootstrap unconditionally ran `apt-get install tintin++`. On
Ubuntu 22.04 WSL this always produced a non-functional binary. On 24.04 the
version is marginally acceptable but TLS is still absent.

## Decision

Remove `tintin++` from the unconditional apt PACKAGES list. After the apt
install block, run a probe-or-build step:

1. **Probe.** Check the installed `tt++` (if any) for:
   - Existence in PATH.
   - Version ≥ `TT_MIN_VERSION` (2.02.20), parsed from `tt++ -v`.
   - GnuTLS linkage, confirmed via `ldd`.
   If all three pass, log "looks good — keeping it" and skip the build.

2. **Build** (only when the probe fails). Install build deps
   (`build-essential`, `libpcre2-dev`, `libgnutls28-dev`, `zlib1g-dev`,
   `pkg-config`), clone tag `TT_BUILD_VERSION` (2.02.61) shallowly, and run
   `./configure && make && make install`. The binary lands at
   `/usr/local/bin/tt++`, which precedes `/usr/games` and `/usr/bin` in the
   default Ubuntu PATH and silently shadows any apt-installed binary.

3. **Post-build sanity check.** Re-probe version and TLS on the freshly built
   binary. Abort with a clear error pointing at `libgnutls28-dev` if TLS is
   still missing.

Version and tag pins live as named constants (`TT_MIN_VERSION`,
`TT_BUILD_VERSION`) at the top of `install/bootstrap-linux.sh`.

## Consequences

- First-run installs where the existing tt++ is absent or unsuitable gain
  ~1–2 minutes of compile time.
- The built binary lives at `/usr/local/bin/tt++`. Any apt-installed binary is
  shadowed, not removed — users who installed `tintin++` for other reasons are
  not surprised.
- Idempotent: re-running the bootstrap on an already-provisioned system takes
  the "looks good" path with no rebuild.
- Users with their own manually-built or updated tt++ in `/usr/local/bin` are
  left alone if it passes the version and TLS checks.
- Build deps are only installed when a build is actually needed.
- Future tt++ floor bumps require editing `TT_MIN_VERSION` and
  `TT_BUILD_VERSION` in `bootstrap-linux.sh` — two constants, one file.

## Rejected alternatives

- **Pure apt, trust the package.** Proven insufficient: Ubuntu 22.04 ships
  2.02.03 (too old), and the Debian/Ubuntu builds historically omit GnuTLS.
  Users on new 22.04 installs always got a non-functional binary.
- **Always build from source, skip the probe.** Wastes ~2 minutes on every
  bootstrap run, even for users who already have a working manually-built
  binary. The probe is free and makes the common re-run case instant.
- **Pin the minimum Ubuntu version to 24.04.** Does not fix the TLS omission
  (a packaging decision orthogonal to Ubuntu version), and does not help users
  already on 22.04 who want to install the cockpit today.
- **Ship a pre-built tt++ binary in the repo.** Binary blobs in git are bad
  practice; cross-distro glibc compatibility is fragile; we would own
  maintenance of the binary. Source build is simpler and more correct.
