# ADR 0016 — Default branch renamed from master to main

Date: 2026-04-27  
Status: Accepted

## Context

The GitHub repository `Khazdul/mumecockpit` was created before the
industry shift toward `main` as the default branch name.  Its default
branch was therefore named `master`.

Meanwhile, every new file that referenced the branch name was written
against `main`:

- `bridge/update.sh` — pulls the latest release from the `main` branch.
- `install/installer-core.ps1` — the curl pipeline fetches scripts from
  `raw.githubusercontent.com/…/main/…`.
- `install/README.md` and `docs/bridge-services.md` — documentation
  referred to `main` throughout.

This mismatch was latent until the repository went public.  At that
point `update.sh` and the Windows installer curl pipeline would silently
fail because the branch they referenced (`main`) did not exist on the
remote — making both self-update and fresh Windows installs
release-blocked.

**Why raw.githubusercontent.com URLs are affected.**  GitHub's web UI
automatically redirects branch-name references after a rename.
`raw.githubusercontent.com` does **not** redirect — a URL that encodes
`master` returns a 404 after the rename, and one that encodes `main`
returned a 404 before it.  This is why the installer curl pipeline was a
hard blocker rather than a cosmetic inconsistency.

## Decision

Rename the GitHub default branch from `master` to `main`.

Running a full audit (`grep -rni 'master'` across `*.sh`, `*.ps1`,
`*.md`, `*.tin`, `*.lua`, `*.py`) returned three hits, all unrelated to
git:

- `ttpp/sessions/bogger.tin` — TinTin++ game variable `{master}`
  storing a character name.
- `lua/core/affects_data.lua` (×2) — in-game spell-effect strings
  containing the word "Master's".

No source file required a change.  The rename alone resolves the
mismatch.

### Migration steps for existing clones

```bash
git branch -m master main
git fetch origin
git branch -u origin/main main
git remote set-head origin -a
git remote prune origin
```

## Consequences

- `update.sh`, the Windows installer, and all documentation are now
  consistent with the remote default branch name.
- Contributors with existing clones must run the migration steps above
  once.
- New clones are unaffected — `git clone` follows the remote default.

## Rejected alternatives

**Pin all branch references to `master`** — the codebase already
assumed `main` in four or more places.  Updating them to `master` would
be migrating in the wrong direction and would leave the repository out
of step with current convention.

**Dynamic detection at update time** — `update.sh` could determine the
default branch via `git symbolic-ref refs/remotes/origin/HEAD` instead
of hardcoding a name.  This is a valid future hardening but is parked
until there is a concrete need (see Out of scope).

## Out of scope

Dynamic default-branch detection in `update.sh` (using
`git symbolic-ref refs/remotes/origin/HEAD` or the GitHub API) is not
implemented here.  The current single-repo, single-branch setup makes
hardcoding `main` the simplest correct solution.
