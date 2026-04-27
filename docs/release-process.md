# Release Process

A runbook for shipping a new version. Written for the tired-at-11pm case.
Do steps in order — the sequence matters.

---

## 1. Decide the version number

Use semver: `MAJOR.MINOR.PATCH`.

- `PATCH` — bug fixes, no new features.
- `MINOR` — new features, backwards-compatible.
- `MAJOR` — breaking changes or major milestones.

---

## 2. Bump VERSION on main

Edit `VERSION` to contain exactly the new version string (no `v` prefix, no
trailing newline beyond what the editor adds):

    0.3.0

Commit and push:

    git add VERSION
    git commit -m "chore: bump VERSION to X.Y.Z"
    git push origin main

**Why VERSION-bump must come before the tag.**  `update.sh` checks out the
release tag and then reads VERSION from the resulting working tree. If the tag
points at a commit where VERSION still says an older value, the client's
post-update VERSION is older than the tag it just fetched. The next launcher
launch re-runs the version check, finds the cached tag still newer than
VERSION, and shows the Update row again — an update loop. The fix is always to
tag the commit that already has the correct VERSION.

This is the v0.2.0 lesson: the tag was placed on a commit where VERSION still
read `0.1.0`. Clients that ran the update found themselves at `v0.2.0` by tag
but `0.1.0` by VERSION file. The update row never went away. Fix: delete the
tag, bump VERSION on main, retag on the bump commit (see Recovery below).

---

## 3. Verify VERSION matches the tag

Run the pre-tag sanity check:

    bash bridge/check_release.sh vX.Y.Z

Expected output:

    VERSION matches vX.Y.Z. Safe to tag.

If it says `Bump VERSION first` — stop, go back to step 2.

---

## 4. Create and push the tag

Tag the bump commit (the HEAD of main after step 2):

    git tag vX.Y.Z
    git push origin vX.Y.Z

---

## 5. Create the GitHub release

    gh release create vX.Y.Z --generate-notes

The `--generate-notes` flag fills the release body from merged PRs and commits
since the last tag.

**The release MUST exist** (not just the tag). `version_check.sh` queries
`/releases/latest`, which only returns formal GitHub releases. A pushed tag
with no associated release will not be picked up by clients.

---

## 6. Verify the cache

Force a fresh version check and confirm the cache reflects the new tag:

    bash bridge/version_check.sh --force && cat bridge/version.cache

Expected:

    latest=vX.Y.Z
    checked_at=<epoch>

If `latest` shows a different tag, check that the GitHub release was created
(not just the tag) and that the release is not marked as a pre-release or
draft.

---

## What about main between releases?

Main may have unreleased commits at any time — that is normal. End users never
see them. `update.sh` checks out the release tag named in `version.cache`, not
main HEAD, so the stable channel is fully decoupled from development activity
on main. Developers running on main are explicitly on the dev path; the email
fingerprint guard already prevents them from accidentally running `update.sh`.

---

## Recovery: tag points at wrong commit

Use this when you tagged too early (VERSION was wrong) or tagged the wrong
commit. This is the procedure used to fix v0.2.0.

**Delete the tag locally and on origin:**

    git tag -d vX.Y.Z
    git push origin :refs/tags/vX.Y.Z

**Delete the GitHub release** (must be done before recreating, to avoid
`/releases/latest` returning stale data):

    gh release delete vX.Y.Z --yes

**Verify VERSION on the correct commit** (usually main HEAD after the bump
commit is pushed):

    bash bridge/check_release.sh vX.Y.Z

**Retag on the correct commit and push:**

    git tag vX.Y.Z
    git push origin vX.Y.Z

**Recreate the GitHub release:**

    gh release create vX.Y.Z --generate-notes

**Verify:**

    bash bridge/version_check.sh --force && cat bridge/version.cache
