# 0106 — Windows installer hardening: root default user and system-wide placement

**Status:** Accepted
**Date:** 2026-05-26

## Context

ADR 0104 established the Windows deployment: foot under WSLg, launched from a
WSLg-surfaced `.desktop` entry via a supervisor. End-to-end validation of that
deployment on a real Windows 11 machine falsified two assumptions that the
Phase 1 implementation had baked in implicitly.

**The default-user assumption.** The deployment assumes the WSL distro's
default user is root — the `.desktop` `Exec=` and `Icon=` use `/root/MUME`
paths, the bootstrap runs as root, and the cockpit is installed under `/root`.
`install-bootstrap.md` justified this: a fresh install via
`wsl --install --no-launch` skips the OOBE user-creation dialog, leaving root
as the default user.

That holds only on a *pristine* machine. On a machine with a pre-existing
Ubuntu distro — a normal user account already created — the installer reuses
that distro and the default user is the normal account, not root. WSLg runs a
`.desktop`'s `Exec=` as the distro's **default user**; there is no per-`.desktop`
equivalent of `wsl -u root`. The old Alacritty deployment forced root
explicitly — its shortcut ran `wsl -d Ubuntu -u root -- …` (ADR 0028). The
migration to a WSLg `.desktop` silently dropped that guarantee. As the
non-root default user, WSLg launches the supervisor, which cannot traverse
`/root/` (mode 0700) → permission denied → a silent launch failure.

**The placement assumption.** Phase 1 placed `mume-cockpit.desktop` in the
per-user `~/.local/share/applications/` and referenced the icon by absolute
path. Validation showed WSLg does not reliably surface `.desktop` files from a
user's `~/.local/share/applications/`, nor reliably resolve icons from a
per-user `~/.local/share/icons/`. WSLg reliably uses the system-wide
`/usr/share/applications/` and `/usr/share/icons/hicolor/`.

## Decision

The installer hardens the deployment so it does not depend on the falsified
assumptions.

**Guarantee root as the default user.** The Linux bootstrap writes
`/etc/wsl.conf` with:

    [user]
    default=root

merge-safe (existing `/etc/wsl.conf` content is preserved). The installer
issues a `wsl --shutdown` after the bootstrap so the setting takes effect
before first launch. Root is now the default user deterministically, on a
fresh install and a pre-existing distro alike — rather than being assumed.

**Place the `.desktop` and icon system-wide.** `mume-cockpit.desktop` is
installed to `/usr/share/applications/`, and the icon to
`/usr/share/icons/hicolor/256x256/apps/mume-cockpit.png`, with the `.desktop`
referencing it by theme name (`Icon=mume-cockpit`) rather than an absolute
path. System-wide placement is what WSLg reliably surfaces, and it is the
correct location for a system/root install regardless.

## Consequences

- The deployment launches correctly whether the installer runs on a pristine
  machine or one with a pre-existing non-root-default Ubuntu distro.
- The `-u root` guarantee that ADR 0028's Alacritty shortcut provided — and
  that the WSLg `.desktop` model structurally cannot — is restored by the
  installer at the distro-configuration level instead.
- Writing `[user] default=root` changes the default user for *all* use of that
  WSL distro. For the intended use case this is correct: the installer
  provisions a single-purpose distro for the cockpit. A user who shares the
  distro with other work will find its default user changed.
- WSLg's icon rendering remains imperfect: on some WSLg versions the Start
  Menu entry shows a generic icon regardless of correct, system-wide,
  theme-named icon configuration. This is a WSLg bug, not fixable from the
  deployment side. It is accepted as one of the WSLg cosmetic warts ADR 0104
  already documents, and noted in `install-bootstrap.md`.

## Alternatives considered

**Rely on the OOBE-skip for a root default user.** This is the Phase 1
behaviour. Rejected: it holds only on a pristine install; it provides no
guarantee on a machine with a pre-existing distro, and the failure is silent.

**Per-user placement of the `.desktop` and icon**
(`~/.local/share/applications`, `~/.local/share/icons`). Rejected: WSLg does
not reliably surface or resolve from per-user locations. System-wide placement
both works and is correct for a system install.

**Absolute-path `Icon=` in the `.desktop`.** Rejected in favour of a theme
name: WSLg's icon resolution is more reliable with a themed name resolved
through the standard icon-theme search path, and a theme name is the
freedesktop-conventional form.

## Relation to other ADRs

- Corrects implicit assumptions in **ADR 0104** (the foot/WSLg deployment).
- Restores, at the distro-configuration level, the explicit-root guarantee
  that **ADR 0028**'s Alacritty shortcut provided via `wsl -u root` and that
  the WSLg `.desktop` model cannot express.
