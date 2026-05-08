# ADR 0018 — update.sh preserves user-created files across the reset

**Status:** Accepted
**Date:** 2026-04-28

## Context

End users accumulate two kinds of data inside the repo tree that must survive
updates:

- **Profile files** in `ttpp/profiles/` — created via the launcher's Profile
  page and overwritten by the SESSION DEACTIVATED auto-save hook (ADR 0014)
  on every session exit.
- **Opt-in automation scripts** in `lua/scripts/` — the directory documented
  in ADR 0002 for user-written Lua automation modules.

Both directories also contain shipped product files (e.g. `autostab.lua`,
`bogger.tin`) that must receive their new tagged versions on update.

`ttpp/profiles/default.tin` is a third category: it ships in the repo as a
starting template, but the auto-save hook writes the user's live session state
to it. It is both a shipped file and live user data.

`update.sh` (ADR 0017) performs `git reset --hard refs/tags/$TAG`, which
overwrites every tracked file. Without intervention this destroys user-created
files in the two directories.

The dirty-tree guard (exit 21) also fired on these directories because
auto-save commits unstaged changes to them as part of normal cockpit operation.

## Decision

Classify each file in `ttpp/profiles/` and `lua/scripts/` as **shipped** or
**user-created** by checking its presence in the target release tag:

    git cat-file -e "refs/tags/$LATEST_TAG:$relpath"

- **Present in tag → shipped.** The reset overwrites it; no preservation.
- **Absent from tag → user-created.** Snapshotted to `bridge/.update_preserve/`
  before the reset and restored afterward with `cp -p`.

`ttpp/profiles/default.tin` is **always preserved** regardless of tag presence.

The dirty-tree guard is made permissive for `ttpp/profiles/` and `lua/scripts/`
using pathspec exclusions, so auto-save activity no longer triggers exit 21.

A bash `EXIT` trap prints a stderr message pointing to `bridge/.update_preserve/`
if the script exits non-zero after the snapshot is taken. On success the
preserve dir is deleted and the trap is disarmed via a flag variable.

## Consequences

- User profile files and custom scripts survive updates transparently.
- `default.tin` survives unconditionally; the user's live session data is never
  overwritten.
- **User edits to shipped files are silently overwritten.** Users who customize
  `autostab.lua` or similar shipped scripts directly will lose those edits on
  the next update. The mitigation is to copy the file under a new name.
- **Shipped files removed in a future tag remain on disk as harmless leftovers.**
  Because they are absent from the target tag, the preservation logic treats
  them as user-created and keeps them. Lua and tt++ tolerate extra unused files;
  users can `rm` manually. This is acceptable given that the two directories
  are flat by design.
- **Interrupted updates leave user data in `bridge/.update_preserve/`.** The
  script does not attempt auto-recovery; it tells the user where to look.
  `bridge/.update_preserve/` is gitignored so it does not pollute `git status`.

## Alternatives considered

**Compare against the from-version (tag at last update or pre-bump commit).**
Rejected: the from-version is ambiguous on fresh installs and requires
persisting extra state. The target-tag check is self-contained and stateless.

**Move all user data to `~/.config/mumecockpit/` and gitignore the in-repo
paths.** Cleaner long-term separation of product code and user data. Rejected
for now: requires reworking the launcher's Profile page, the auto-save hook,
the SESSION CONNECTED load sequence, and the `profile=` key in `startup.conf`.
Parked as a v0.3 candidate.

**Whitelist of shipped files in a manifest checked into the repo.** Rejected:
sync burden. Every new shipped script would require a manifest edit; omissions
would silently cause user files to be overwritten.

## Out of scope

- Conflict detection when a shipped file has local edits (the local edit is
  silently overwritten; documenting this is the chosen mitigation).
- Recursive preservation in subdirectories (`ttpp/profiles/` and `lua/scripts/`
  are flat by design; no subdirectories are expected).
- Migration tooling for users who have heavily modified shipped files.
