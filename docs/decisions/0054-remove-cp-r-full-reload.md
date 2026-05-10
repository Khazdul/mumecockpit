# 0054 — Remove cp -r full system reload

**Status:** Accepted
**Date:** 2026-05-10

## Context

The `cp -r` alias performed a full reload of the TinTin++ session and Lua
brain without tearing down tmux or the MUME TCP connection. Three forces
made it carry steadily more cost and steadily less value:

1. **Compounding complexity.** Each reload had to kill six tt++ register
   types, re-read `main.tin`, re-register five collector functions, write
   and sanitize the profile, and recreate the input pane. Every new
   right-column state file (status, buffs, group, comm, affects,
   stored_spells, runs, sess_kills) added a "what happens on cp -r?"
   question that had to be answered case by case. ADR 0044 added a
   resume mechanism in `lua/core/run_log.lua`. ADR 0051's companion fix
   was specified to plug a hole in pane-active signalling but never
   landed. The trend was clear: each addition needed bespoke awareness
   of the reload boundary.

2. **Already partially broken.** ADR 0044 documented an accepted
   limitation: `mark_mume_disconnected()` returns early on its
   idempotency guard after a cp -r resume, so the next disconnect emits
   no `run_ending` event and no "logged out" UI line. With the ADR 0051
   companion fix unimplemented, right-column panes blank entirely after
   cp -r mid-run because `connection.state` is never re-created, even
   though MUME stays connected. `state.char.name` and `state.char.level`
   stay nil for the rest of the connection (sticky GMCP modules are not
   re-emitted), so the status pane would render "—" for those fields if
   the panes lit up at all. `state.char.affects` is wiped and not
   restored. `state.session` is rebaselined to zero. The reload
   delivered a degraded experience by every measurable surface.

3. **No use case in the project's actual workflow.** The sole developer
   does not use cp -r. No external user has requested it. Standard MUD
   clients (Mudlet, MUSHclient, etc.) do not have an equivalent. The
   restart-via-launcher path (`cp -e` → `start.sh`) is clean,
   predictable, and already supported.

## Decision

Remove `cp -r` and all infrastructure that exists solely to support it.

### Removed

- `cp -r` alias in `ttpp/core/system.tin`.
- `cp -r` row in the cockpit help body
  (`_register_cockpit_help` in `lua/brain/registry.lua`).
- `character_name` rehydration from `connection.state` at brain startup
  in `lua/brain.lua`. The `_clear_connection_state()` call stays — it
  still clears stale state from a previously crashed brain.
- Mid-run resume block in `lua/core/run_log.lua`.
- `cp -r` line in `bridge/launcher/about.txt`.
- All cp -r references in `docs/*.md` and prior ADRs (this PR).

### Kept

- `bridge/runtime/connection.state` file. Still written by
  `mark_mume_connected()`, cleared by `mark_mume_disconnected()`, and
  read by the in-game popup, the status header, and every right-column
  pane via the ADR 0051 render-active flag.
- `_clear_connection_state()` at brain startup. Still required so a
  stale `connection.state` from a previously crashed brain does not
  leave panes erroneously rendering as "active".
- Orphan handling in `run_log.lua`. Crash recovery is independent of
  cp -r: an unsealed `current.jsonl` is sealed at the next `run_started`
  for the same character.
- Idempotency guards in `mark_mume_connected` /
  `mark_mume_disconnected`. They protect against duplicate signals
  from layered disconnect sources, which exist regardless of cp -r.
- `_register_run_log_capture` idempotency and the
  unset-before-register pattern from ADR 0049. Profile-class auto-save
  can still inject stale `_run_log_path` and `RECEIVED LINE` event
  bodies; the pattern stays valuable.
- `comm_state.lua` load-on-startup. Serves cross-launch continuity for
  the comm history; cp -r was a secondary motivation only.

## Consequences

- The "cp -r mid-run" question disappears from the design surface.
  New panes and state files no longer need to consider a mid-run brain
  reload as a distinct case.
- ADR 0044's "cp -r mid-run is data-safe" property is replaced by
  "brain crash mid-run is data-safe via orphan handling at next login".
  The data path that mattered is preserved; the unused user-driven path
  is gone.
- Recovery from a brain crash mid-run is `cp -e` (or wait for the
  cockpit to die) followed by `start.sh`, then reconnect from the
  launcher. The leftover `current.jsonl` is sealed at the next login
  for the same character.
- Iteration cost for Lua development is unaffected in this project's
  workflow: the sole developer does not use cp -r and has not used it
  for iteration. Documented here so a future maintainer reading this
  ADR understands the trade was made knowingly.
- ADR 0051's "companion fix" sub-problem disappears. The
  `connection.state` clearing at brain startup is now correct in all
  supported flows: a fresh brain has no run, and panes are correctly
  blank until the next `Char.Name` arrives.

## Rejected alternatives

- **Fix cp -r properly.** Would require landing the ADR 0051 companion
  fix, threading state-file rehydration through every right-column
  module (status, buffs, group, comm, affects, stored_spells), and
  re-emitting sticky GMCP fields somehow. Each addition compounds the
  obligation. Not justified by any actual workflow.
- **Keep cp -r in its current partially-broken state.** Documented
  edges (Name/Lv blank, panes blank, run_ending missed) violate the
  project's general "stale data is worse than blank, but blank still
  needs to be predictable" stance. Leaving it in keeps the
  cognitive overhead and adds nothing.
- **Build a soft-restart replacement (e.g., Lua-only reload without
  tmux/tt++ churn).** Considered. Same fundamental problem — sticky
  GMCP modules are not re-emitted, so any reload mid-run starts from
  partial state. Parked for future revisit if the actual workflow
  changes.

## Reversibility

Reintroducing `cp -r` would require rebuilding the resume mechanism
with awareness of every right-column state file (status, buffs, group,
comm, affects, stored_spells, runs, sess_kills) and revisiting ADR 0044's
accepted limitations. The cost grows with each new state surface added
in the meantime. This is documented to discourage casual reintroduction.

## Relation to other ADRs

- **Invalidates** the `### cp -r mid-run` subsection of ADR 0044
  (per-section invalidation; the rest of 0044 is unchanged).
- **Removes the open question** described in ADR 0051's "Companion fix"
  section by eliminating the gap that fix was meant to close.
- **Simplifies** ADR 0049's idempotency claim from "across both
  SESSION CONNECTED and cp -r" to "across SESSION CONNECTED"; the
  unset-before-register pattern stays.
