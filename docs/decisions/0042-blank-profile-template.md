# 0042 — Blank-profile template + runtime-seeded default.tin

**Status:** Accepted
**Date:** 2026-05-04

## Context

Two failure-mode observations converged on this change:

- tt++ errors on `#read` of an empty file. The SESSION DEACTIVATED
  auto-save (ADR 0014) calls `#class {<profile>} {write}` on every
  graceful exit. If the profile class has zero registrations — the
  state of any brand-new profile before the user has typed a single
  alias — the resulting file is empty. The next session connect then
  fails on `#read`.
- The shipped `ttpp/profiles/default.tin` and the launcher's "Create
  blank profile" flow both produced new-profile content, with no
  shared source. Any future addition to that content (default macros,
  comments, conventions) would need to land in both places.

The simplest fix for the first problem is to ship at least one
registration in every new profile. Doing that without duplication
requires the second problem to be solved first.

## Decision

`bridge/templates/blank_profile.tin` is the single source of truth
for new-profile content. It contains a header comment block and ten
default `#macro` registrations binding numpad keys (NumLock on,
keypad application mode) to common MUME commands.

Two consumers copy from this template:

- `start.sh` seeds `ttpp/profiles/default.tin` from the template if
  the file is missing. The check runs unconditionally on every launch
  (both `--no-menu` and menu paths) and is idempotent — a no-op when
  the file is already present.
- `bridge/launcher.sh`'s "Create blank profile" flow `cp`s from the
  template into the chosen profile path, with a defensive fallback if
  the template is somehow missing.

`ttpp/profiles/default.tin` is removed from the repo. ADR 0018's
preservation loop continues to protect existing users — its
special-case is keyed on filename, not on tag presence, so the
behaviour for users with a customised `default.tin` is unchanged
across updates.

## Consequences

- Single source of truth: future changes to default new-profile
  content land in one file.
- Fresh installs always have a `default.tin` with at least one
  registration. The empty-file failure mode after auto-save is
  eliminated for new profiles.
- Existing users keep their `default.tin` across updates by ADR
  0018's preserve loop. The seed step in `start.sh` is a no-op for
  them.
- `#nop` header comments in the template are lost on the first
  auto-save (`#class write` only emits registrations, not comments).
  This is acceptable: comments are informational for first-time
  readers only; the macros themselves survive.
- Existing users who have already hit the empty-file bug and have a
  zero-byte `default.tin` are not auto-healed — the seed check is on
  file existence, not size. Workaround is trivial (`rm
  ttpp/profiles/default.tin` then relaunch). Accepted given near-zero
  current user count.

## Alternatives considered

**Inline heredoc in launcher + duplicate content in shipped
`default.tin`.** Simplest implementation, no new file. Rejected: two
places to keep in sync, drift risk grows with every future addition.

**Ship `default.tin` in the repo as a checked-in copy of the
template.** Single source of truth at edit time but two physical
copies that can drift between commits, plus the awkward semantics of
shipping a file that auto-save will overwrite on first use. Rejected.

**Sanitizer fallback that injects a `#nop` line into empty files.**
Addresses the symptom (empty file rejected by `#read`) but not the
cause (zero registrations producing the empty file). Could be added
later as belt-and-suspenders if a regression appears. Out of scope
for this change.

**Heal existing empty-file installs by changing the seed condition
from `[ ! -f ]` to `[ ! -f ] || [ ! -s ]`.** Trivially small change,
but rejected on grounds of caution: a future change could legitimately
produce a momentarily empty `default.tin` mid-write, and overwriting
it would be a footgun. Near-zero affected user count makes the
manual workaround (`rm` + relaunch) acceptable.

## Relation to ADR 0018

ADR 0018's preservation loop special-cases `ttpp/profiles/default.tin`
by filename. That special-case is unchanged and still correct: the
loop iterates only over existing files, so the file's absence from
the repo does not affect preservation for users who have one on
disk. The framing in ADR 0018 ("default.tin ships in the repo as a
starting template") is now historical — default.tin is no longer
shipped — but the behavioural contract is the same.
