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

## 2. Build the Windows installer zip

Build the zip from the `install/` directory. The subshell `cd` ensures files
land at the archive root (no `install/` prefix inside the zip):

    mkdir -p release
    (cd install && zip ../release/MUME-Cockpit-vX.Y.Z.zip \
        cockpit-installer.bat installer-core.ps1 README.md)

Commit and push alongside (or just before) the VERSION bump:

    git add release/MUME-Cockpit-vX.Y.Z.zip
    git commit -m "chore: build vX.Y.Z installer zip"
    git push origin main

**Why commit the zip rather than only upload it as a release asset.**
Committing to `release/` means that checking out the tag yields the exact
zip that shipped — no dependency on GitHub assets being available. If
GitHub release assets are ever lost or the release is accidentally deleted
and recreated, the in-repo copy is the authoritative artifact.

---

## 3. Bump VERSION on main

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

## 4. Verify VERSION matches the tag

Run the pre-tag sanity check:

    bash bridge/check_release.sh vX.Y.Z

Expected output:

    VERSION matches vX.Y.Z. Safe to tag.

If it says `Bump VERSION first` — stop, go back to step 2.

---

## 5. Create and push the tag

Tag the bump commit (the HEAD of main after step 2):

    git tag vX.Y.Z
    git push origin vX.Y.Z

---

## 6. Create the GitHub release

    gh release create vX.Y.Z --generate-notes

The `--generate-notes` flag fills the release body from merged PRs and commits
since the last tag.

**The release MUST exist** (not just the tag). `version_check.sh` queries
`/releases/latest`, which only returns formal GitHub releases. A pushed tag
with no associated release will not be picked up by clients.

---

## 7. Upload the installer zip as a release asset

    gh release upload vX.Y.Z release/MUME-Cockpit-vX.Y.Z.zip

This is the same file committed in step 2 — the in-repo copy and the
release asset are identical by design. End users get a download button on
the release page; the in-repo copy remains the authoritative artifact.

---

## Release notes body

`--generate-notes` produces a detailed changelog but does not answer the
user's first question on the release page: "does this affect me, and should
I update?" Hand-edit the release body to prepend a short **Summary** block
before the auto-generated content.

**Which template to use:**
- PATCH release (bug fixes only) → patch template.
- MINOR or MAJOR release (new features or breaking changes) → minor/major
  template.

After editing, verify that the `## Summary` heading renders as a heading and
bold text renders as bold. If the body shows a literal `##` prefix or bare
asterisks, the editor was in text mode — re-open "Edit release", switch to
Markdown mode, and re-paste. This was the failure mode in the v0.5.1
first-paste attempt.

### Patch template

    ## Summary

    **Who this affects:** <audience>

    **What changed:** <one short paragraph>

    **Action needed:** <action>

    ---

Keep it prose — one change, one paragraph. No bullet list. The
auto-generated content follows after the `---` separator; do not delete it.

### Minor / major template

    ## Summary

    <One or two sentences framing what this release is about overall —
    the narrative direction, not a feature list.>

    **Who this affects:** <audience>

    **Highlights:**
    - <bullet — end-user language, not commit subject>
    - <bullet>
    - <bullet>

    **Action needed:** <action>

    ---

For a MAJOR release with breaking changes, add a `**Breaking changes:**`
subsection immediately above the `---` separator, listing what users must
do to migrate. The auto-generated content follows after `---`; do not
delete it.

### Worked example — v0.5.1 (patch)

    ## Summary

    **Who this affects:** Windows users only.

    **What changed:** The Windows desktop shortcut now reliably launches the
    cockpit on all hosts. Previously some installs left a broken shortcut
    that opened a terminal and immediately closed with
    `./start.sh: No such file or directory`.

    **Action needed:** If your existing install works, no action — this
    release does not change runtime behaviour. If you have a broken shortcut
    from a v0.5.0 install, delete it and re-run `cockpit-installer.bat`
    from the v0.5.1 zip below.

    macOS and Linux users are unaffected.

    ---

---

## 8. Verify the cache

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

The in-repo zip in `release/` is still correct (its content does not depend
on tag placement), but the release-asset upload must be redone after recreating
the release: `gh release upload vX.Y.Z release/MUME-Cockpit-vX.Y.Z.zip`.

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

Run steps 2–8 from this document in order. After each step, confirm in one
line what happened. Exact commands:

**Step 1 — Build the Windows installer zip:**

    mkdir -p release
    (cd install && zip ../release/MUME-Cockpit-vX.Y.Z.zip \
        cockpit-installer.bat installer-core.ps1 README.md)
    git add release/MUME-Cockpit-vX.Y.Z.zip
    git commit -m "chore: build vX.Y.Z installer zip"
    git push origin main

**Step 2 — Bump VERSION on main:**

    echo "X.Y.Z" > VERSION
    git add VERSION
    git commit -m "chore: bump VERSION to X.Y.Z"
    git push origin main

**Step 3 — Run the pre-tag sanity check:**

    bash bridge/check_release.sh vX.Y.Z

Expected output: `VERSION matches vX.Y.Z. Safe to tag.`
If it fails, stop and report the output. Do not proceed to the tag step.

**Step 4 — Tag and push:**

    git tag vX.Y.Z
    git push origin vX.Y.Z

**Step 5 — Create the GitHub release:**

For a stable release:

    gh release create vX.Y.Z --generate-notes

For a pre-release:

    gh release create vX.Y.Z --generate-notes --prerelease

**Step 6 — Draft the Summary block:**

Based on the bump type already determined in this run, select the matching
template from the "Release notes body" section above:

- PATCH bump → patch template.
- MINOR or MAJOR bump → minor/major template.

Fill in the audience, what changed, and action needed using the commit summary
already drafted. Output the completed block as a fenced code block in chat.

Then say to the user:

> Paste the block above into the GitHub release body via **Edit release** on
> the release page. Prepend it before the auto-generated content, keeping the
> `---` separator between them. Do not delete the auto-generated section. After
> saving, confirm the paste is done, then spot-check that the `## Summary`
> heading renders as a heading (not as literal `## Summary`) and that bold text
> appears bold. If either looks wrong, the editor was in text mode — re-open
> Edit release, switch to Markdown mode, and re-paste.

Do NOT use `gh release edit --notes` to do this automatically. The hand-paste
step is intentional: it gives the user a beat to review and adjust the wording
before the release goes public, and it avoids shell-quoting issues with
multi-line `--notes` content.

Wait for the user to confirm the paste is done before proceeding.

**Step 7 — Upload the installer zip as a release asset:**

    gh release upload vX.Y.Z release/MUME-Cockpit-vX.Y.Z.zip

**Step 8 — Verify the cache:**

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

- Do not edit any file other than `VERSION` and the new `release/` zip artifact
  created in step 2. If commits since the last release imply something else
  should change (e.g. a hardcoded version string), surface the question to the
  user; do not change it silently.
- Do not edit ADRs or other documentation as part of a release. Documentation
  updates are a separate concern handled outside the release flow.
- Do not edit the release note body via `gh release edit`. Draft the Summary
  block in chat and let the user paste it manually via the GitHub web UI
  (see step 6 in the execution sequence above).

Stable releases are visible to end users via `version_check.sh`; pre-releases
are not.
