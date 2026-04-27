# ADR 0017 — update.sh checks out release tags instead of resetting to main

Date: 2026-04-28  
Status: Accepted

## Context

The original `update.sh` implementation used:

    git fetch origin main --tags
    git reset --hard origin/main

This conflates "latest release" with "main HEAD". The self-update channel is
supposed to deliver stable releases — whatever `version_check.sh` advertises —
but `git reset --hard origin/main` delivers whatever commit main currently
points at, which may include unreleased work.

The concrete failure mode was discovered during end-to-end testing of v0.2.0:
the tag was placed on a commit where VERSION still said `0.1.0`. After a client
ran the update, `version.cache` cached `latest=v0.2.0`, but the working tree
VERSION read `0.1.0` (because main HEAD was the pre-bump commit). The Update
row reappeared on every launcher start — an update loop. The client could never
reach a state where VERSION ≥ `latest`.

More generally: any time main has commits between releases (the normal
development state), clients who run `update.sh` receive unreleased code. The
update loop is a narrower but reproducible symptom of the same root cause.

## Decision

`update.sh` checks out the latest release tag named in `bridge/version.cache`
instead of resetting to `origin/main`:

    git fetch --tags --quiet
    git -c advice.detachedHead=false checkout --quiet "refs/tags/$LATEST_TAG"
    git reset --hard "refs/tags/$LATEST_TAG" --quiet

The ahead-check (guard 4c) also compares against the tag rather than
`origin/main`:

    AHEAD=$(git rev-list --count "refs/tags/$LATEST_TAG"..HEAD)

`LATEST_TAG` is the value of `latest=` from `version.cache`, used verbatim
(it carries the `v` prefix as written by `version_check.sh`).

The stable channel now tracks releases exclusively. Main remains the
development branch; clients never see unreleased commits.

## Consequences

- Clients end up on detached HEAD after update. This is correct for end users:
  they are not on a branch, they are on a release. `git pull` does not work for
  them — they do not need it. Developers (whose email fingerprint matches repo
  history) are blocked from running `update.sh` by guard 4a regardless.
- The update loop is eliminated: `update.sh` checks out exactly the tag that
  `version_check.sh` advertised, so post-update VERSION matches `latest` by
  construction (provided the release process bumped VERSION before tagging).
- A new pre-tag sanity check (`bridge/check_release.sh`) and a release runbook
  (`docs/release-process.md`) accompany this change to prevent the class of
  error that triggered the fix.

## Rejected alternatives

**Keep main-reset; bump VERSION to `X.Y.Z-dev` right after each release.** This
eliminates the loop by ensuring main HEAD always has a VERSION newer than the
most recent tag. However, it introduces a different mismatch: `version.cache`
says `vX.Y.Z` but post-update VERSION says `X.Y.Z-dev`. The `_update_available`
comparator strips one leading `v` and does a string comparison, so `X.Y.Z-dev ≠
X.Y.Z` — the update row would reappear. Working around this would require
special-casing `-dev` suffixes throughout, adding complexity with no real gain.

**GitHub Actions enforcement: reject a tag push if VERSION doesn't match.**
Prevents the mistake at CI time, but does not fix the update loop for an
existing bad tag and adds CI infrastructure for a solo project. Worth
reconsidering if contributors join.

**Auto-bump VERSION via a tag-creation hook.** Too magical. An explicit
`chore: bump VERSION` commit is visible in `git log`, attributable, and
revertable. A hook that silently amends history or creates a commit on push is
harder to reason about.

## Out of scope

- Signed tags (GPG verification of release integrity).
- Client rollback to a specific older version.
- Multi-channel releases (stable/beta).
