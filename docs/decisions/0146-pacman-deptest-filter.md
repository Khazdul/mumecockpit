# 0146 — pacman installs routed through a `pacman -T` deptest filter

**Status:** Accepted
**Date:** 2026-08-16

## Context

`install/bootstrap-arch.sh` named `zlib` in its package list as a tt++ build
dependency, mirroring the `zlib1g-dev` entry the Debian bootstrap installs
(ADR 0035). CachyOS ships `zlib-ng-compat`, an optimised drop-in that
`provides` zlib and `conflicts` with it. `pacman -S --needed --noconfirm` saw
two packages owning the same files, `--noconfirm` answered N to the removal
prompt, and the transaction aborted:

    error: zlib-1:1.3.2-3.1 and zlib-ng-compat-2.3.3-2 are in conflict
    error: failed to prepare transaction (conflicting dependencies)

The script died at the package step, before doing anything else. The bootstrap
was not degraded on CachyOS — it was completely non-functional. CachyOS is the
largest Arch derivative among the target audience, so this took out most of the
reason Arch support exists at all.

The shape of the failure matters as much as the failure. The dependency that
killed the run was a *build* dependency, on a machine where the tt++ probe
would have taken the no-build path: a package needed for work that was never
going to happen aborted the entire install.

## Decision

A `pac_install()` helper owns every pacman install in the script. It runs
`pacman -T` (deptest) over the requested list and passes only the entries
deptest reports as unsatisfied to `pacman -S --needed --noconfirm`; when
nothing is missing, pacman is not invoked at all.

deptest resolves `provides`. `zlib` therefore reads as satisfied by the
installed `zlib-ng-compat` and never enters the transaction, so the conflict
that aborted the run cannot arise. deptest exits non-zero when anything is
missing, so the call is guarded with `|| true` under `set -e`.

The package list was also split into a runtime set and a build set, with the
build set (`base-devel`, `pcre2`, `gnutls`, `zlib`, `pkgconf`) installed only
inside the `tt_needs_build` branch. This matches `bootstrap-linux.sh` and
ADR 0035's "build deps are only installed when a build is actually needed"
consequence, and means the failing dependency above is no longer even
requested on a machine that takes the no-build path.

## Consequences

- **The fix generalises.** Any future drop-in replacement shipped by CachyOS
  or another derivative is handled without the script needing to know it
  exists. The question "is this dependency satisfied on this system?" is asked
  of pacman rather than answered by us.
- **An installed-but-outdated package reads as satisfied and is left alone.**
  The bootstrap installs what is missing and never upgrades what is present.
  On a rolling release this is the desired behaviour: partial upgrades are the
  standard way to break an Arch install, and a bootstrap script is the wrong
  place to decide a user is due for a `-Syu`. This was not the motivation for
  the change, and is recorded here so it is not reverted later as an oversight.
- **`base-devel` behaves either way.** It is a meta package on current Arch and
  resolves like any other entry; on older systems where it is still a group,
  deptest reports it unsatisfied on every run. Harmless, because
  `pacman -S --needed` on a group is idempotent.
- Re-runs on a fully provisioned machine skip pacman entirely, which is the
  common case and now costs nothing.

## Rejected alternatives

- **Drop `zlib` from the list.** Fixes CachyOS by accident and leaves plain
  Arch without an explicitly declared build dependency. It also fixes exactly
  one provider conflict and nothing else — the next drop-in replacement breaks
  the script again.
- **Detect CachyOS via `/etc/os-release` and substitute `zlib-ng-compat`.**
  Hardcodes one derivative's packaging choice into the script and needs editing
  for every future variant. deptest asks pacman the question instead of us
  answering it.
- **Answer the conflict prompt with `--noconfirm` semantics that accept the
  removal.** Would uninstall the distro's chosen zlib provider from under the
  user. Unacceptable for a bootstrap script.
- **Run `pacman -Syu` first.** Longer, riskier, and takes ownership of the
  user's system state for no benefit to the install.

## References

- [ADR 0035](0035-tt-from-source.md) — the probe-or-build shape the build-dep
  deferral aligns with.
- `docs/install-bootstrap.md`, "Linux flow" → Arch family — the user-facing
  description of the filter and its behaviour.
