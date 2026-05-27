# ADR 0110 — In-game popup profile editor via snapshot/apply handshake

**Status:** Accepted  
**Date:** 2026-05-27

## Context

The ProfileEditor was extracted into a reusable module (ADR 0109) so it
could run in both the launcher and the in-game popup. The launcher edits
a disk file that is not live — the editor reads, the user edits, ESC
saves. The popup faces a harder problem: the profile is loaded as a
live tt++ class inside the game session. Editing the disk file alone
would leave the live class out of sync, and editing the live class via
`#class kill` + `#class read` must be atomic enough that a corrupt edit
doesn't brick the session.

## Decision

### Connected path — snapshot/apply handshake

Two new tt++ aliases in `ttpp/core/system.tin`:

- `cp -profile-snapshot` — writes the live class to
  `bridge/runtime/profile_snapshot.tin`, echoes `ok` / `fail` into
  `.profile_snapshot_result`.
- `cp -profile-apply` — kills the live class, reads
  `bridge/runtime/profile_edit.tin` using the explicit
  `#class open` + `#read` + `#class close` pattern (mirroring
  SESSION CONNECTED, because `#class read`'s shorthand does not
  class-tag `#highlight` and `#macro` entries), checks a canary
  variable, and on failure rolls back to the snapshot.

The popup orchestrates: snapshot → parse → editor → dirty-check →
serialize to `profile_edit.tin` with canary → apply → poll result.

**Canary mechanism.** The popup appends `#var {_profile_load_canary} {ok}`
as the last line of `profile_edit.tin`. If `#class read` completes
successfully, the canary variable is set (variables are global, not
class-scoped — see ADR 0064). The apply alias checks it: present means
success, absent means mid-file abort → rollback to snapshot.

**Rollback.** On canary failure, `cp -profile-apply` kills the broken
class and re-reads `profile_snapshot.tin`. The snapshot is always a
known-good file written by `#class write` moments earlier.

**Class reopen.** After the `#class read` (success or rollback),
`cp -profile-apply` reopens the profile class with
`#class {$_profile} {open}`, mirroring the final-open step in the
`SESSION CONNECTED` load sequence. Without this, `#class read`'s
implicit close leaves no class open, and subsequent player-typed
`#alias` / `#action` commands land in the default class — invisible
to the next snapshot.

**Worker thread polling.** Both the snapshot and apply polls run in
daemon threads to avoid blocking the prompt_toolkit event loop.
`loop.call_soon_threadsafe` delivers results to the main thread.

### Disconnected path — disk-only

No live class exists, so the popup reads `ttpp/profiles/<name>.tin`
directly, opens the editor, and on ESC saves via `profile_io.save_profile`
+ `sanitize_profile.sh` — identical to launcher behaviour.

### Dirty detection

`profile_io.serialize_profile(profile)` is called before and after
editing. If the serialized text is identical, ESC pops silently. If
dirty: connected → push `profile_apply_confirm` modal; disconnected →
save to disk directly.

### Apply-confirm modal

Three-key modal: Y applies, N discards, ESC keeps editing. While the
apply poll runs, the frame shows "Applying…" and swallows keystrokes.

### EditorHost

`_PopupEditorHost` implements the protocol from ADR 0109. `terminal_bg`
is read from `bridge/runtime/layout.conf` (persisted by the launcher's
probe). The editor's frames use `DynamicContainer` lambdas and its
key bindings are merged via `DynamicKeyBindings`, matching the launcher
wiring.

## Consequences

- Profile editing works in-game without exiting to the launcher.
- The live tt++ class and the disk file stay in sync: the apply alias
  runs `_save_profile` after a successful class read.
- Corrupt edits cannot brick the session: the canary + rollback
  mechanism restores the snapshot.
- Runtime tempfiles (`profile_snapshot.tin`, `profile_edit.tin`, and
  both result sentinels) are cleaned up on popup exit.
- No changes to `profile_editor.py` or the launcher.
- `profile_io` drops `#class {…} {open|close}` lines at parse time
  (matching `sanitize_profile.sh`). Without this, the alphabetical
  group sort would interleave `#class close` mid-file and orphan every
  kind sorting after `c` when `cp -profile-apply` reads the result.
