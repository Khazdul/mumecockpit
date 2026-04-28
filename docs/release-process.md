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

---

# Orchestration: running the release process via VS Code Claude

This section is written for VS Code Claude. When given a prompt such as:

> Make a new release. Follow the runbook in docs/release-process.md.
> Summarize what's new since the last release based on commit history.

Claude should execute the steps below autonomously, confirming each step in
chat as it completes.

## Preconditions

Before starting, verify silently:

1. Working directory is the repo root (a `VERSION` file exists).
2. On branch `main` — `git branch --show-current` returns `main`.
3. Working tree is clean — `git status --porcelain` returns nothing.
4. Local branch is up to date with origin — `git fetch origin main` followed
   by `git rev-list HEAD..origin/main --count` returns `0`.
5. `gh auth status` exits 0 (GitHub CLI is authenticated).
6. The most recent release tag exists and is reachable —
   `git describe --tags --abbrev=0` should succeed.

If any precondition fails, report which one and stop. Do not attempt to fix it.

## Determining the next version

Read `VERSION`. That is the currently installed version (no `v` prefix).

Determine the bump by inspecting commit subjects since the last release tag:

    git log $(git describe --tags --abbrev=0)..HEAD --oneline

Apply these rules to the subjects:

- Any subject matching `feat!:` or containing `BREAKING CHANGE:` → **MAJOR**
  bump (X+1.0.0).
- Any subject matching `feat(` or `feat:` (without `!`) → **MINOR** bump
  (X.Y+1.0).
- Otherwise → **PATCH** bump (X.Y.Z+1).

Use the highest-priority signal found. State the chosen bump and the reasoning
(which subject triggered it, or "all fixes/chores") in chat before proceeding.

For explicit pre-release versions (e.g. `v0.3.0-rc1`), the user must supply
the exact version string. Default behaviour is always a stable release.

## Generating the commit summary

Read the commits since the last tag:

    git log $(git describe --tags --abbrev=0)..HEAD --oneline

Group them by type prefix (`feat`, `fix`, `refactor`, `docs`, `chore`, etc.).
Write 3–5 bullet points describing what changed at user-visible level. Each
bullet starts with an imperative verb and is at most ~80 characters. Skip
pure-internal items such as `chore: bump VERSION`. Output this summary in chat
for human reference before executing the release steps.

## Execution sequence

Run steps 2–6 from this document in order. After each step, confirm in one
line what happened. Exact commands:

**Step 1 — Bump VERSION on main:**

    echo "X.Y.Z" > VERSION
    git add VERSION
    git commit -m "chore: bump VERSION to X.Y.Z"
    git push origin main

**Step 2 — Run the pre-tag sanity check:**

    bash bridge/check_release.sh vX.Y.Z

Expected output: `VERSION matches vX.Y.Z. Safe to tag.`
If it fails, stop and report the output. Do not proceed to the tag step.

**Step 3 — Tag and push:**

    git tag vX.Y.Z
    git push origin vX.Y.Z

**Step 4 — Create the GitHub release:**

For a stable release:

    gh release create vX.Y.Z --generate-notes

For a pre-release:

    gh release create vX.Y.Z --generate-notes --prerelease

**Step 5 — Verify the cache:**

    bash bridge/version_check.sh --force && cat bridge/version.cache

Confirm that the output contains `latest=vX.Y.Z`. If it does not (and this is
not a pre-release), report the anomaly and stop. Do not attempt to fix it.

## Failure handling

- If any step exits non-zero, **stop immediately**. Do not attempt automatic
  recovery.
- Report: which step failed, the exact command that ran, and the full error
  output.
- If the failure occurred after the tag was pushed, refer the user to the
  Recovery section above.
- Never delete a tag or release without explicit user confirmation.
- Never force-push.

## What not to do autonomously

- Do not edit any file other than `VERSION`. If commits since the last release
  imply something else should change (e.g. a hardcoded version string),
  surface the question to the user; do not change it silently.
- Do not edit ADRs or other documentation as part of a release. Documentation
  updates are a separate concern handled outside the release flow.
- Do not edit the release note body after creation. If the generated notes look
  incorrect, surface the release URL for the user to edit manually.

Stable releases are visible to end users via `version_check.sh`; pre-releases
are not.
