# ADR 0046 — GMCP dispatch via events bus

**Status:** Accepted  
**Date:** 2026-05-07

## Context

Downstream effects on GMCP packets were implemented by wrapping
`gmcp.handlers[Module]` in alphabetical-load-order chains. Six modules wrapped
`Char.Name`, three wrapped `Char.Vitals`, three wrapped `Comm.Channel.Text`,
and `state.char.reset` was wrapped by three modules. Two modules (`affects`,
`stored_spells`) installed their wraps lazily via `_install_hooks()`;
`buffs_state` even wrapped the global function `_affects_register_triggers` to
inject another wrap. This was fragile: the order was implicit, the chains were
invisible to callers, and `cp -r` correctness depended on `_installed` guards
that were easy to get wrong.

## Decision

Replace the wrap chains with a single primary writer per GMCP module plus
event subscriptions.

**Dispatch contract:** For every incoming GMCP packet, in order:
1. Parse JSON body.
2. If `gmcp.handlers[module]` is set, call it under `pcall` (the primary
   writer — there is at most one per module, owned by exactly one file in
   `lua/core/`).
3. `events.emit(module_to_event(module), body)` — always, regardless of whether
   step 2 ran.

**Invariant:** `state.*` is updated before any subscriber runs. No subscriber
priority is needed; order within an event equals alphabetical load order in
`lua/core/`.

**`module_to_event` mapping:** `"Char.StatusVars"` → `"gmcp_char_status_vars"`
(camelCase boundaries become underscores, dots become underscores, lowercased,
prefixed `gmcp_`).

**Primary-writer assignments:**
- `lua/core/char_state.lua` — `Char.Name`, `Char.StatusVars`, `Char.Vitals`
- `lua/core/comm_log.lua` — `Comm.Channel.Text`, `Comm.Channel.List`
- `lua/core/world_state.lua` — `Event.Sun`, `Event.Darkness`, `Event.Moon`, `Event.Moved`
- `lua/core/core_state.lua` — `Core.Goodbye`, `Core.Ping`

**`state.char.reset` via event:** `char_state.lua` keeps the wipe loop and
emits `char_reset` (no payload) at the end. Modules that previously wrapped
`state.char.reset` subscribe to `char_reset` instead.

**`event_sun` renamed:** The old `event_sun` event is replaced by the
automatically emitted `gmcp_event_sun`. `clock.lua` (sole subscriber) updated.

**`_install_hooks()` removed** from `affects.lua` and `stored_spells.lua`:
each cp -r produces a fresh Lua state where every top-level subscribe
is registered exactly once, making the `_installed` guard unnecessary.

**`_affects_register_triggers` wrap removed** from `buffs_state.lua`: with
load-order subscription, `affects.lua` (alphabetically first) subscribes to
`gmcp_char_name` before `buffs_state.lua`, so the order is correct without
a wrap.

## Alternatives rejected

**(a) Keep wrap chains.** Would leave the fragility in place. No benefit over
events-based approach, and breaks `cp -r` unless guards remain.

**(b) Remove `gmcp.handlers` entirely, use only events.** Introduces ambiguity
about who writes `state.*`. Keeping a single named primary writer makes
ownership explicit and searchable.

**(c) Explicit subscriber priority.** Unnecessary: the dispatch invariant
(`state.*` updated before emit) means downstream subscribers never need to
run before the primary writer. The remaining ordering requirement (within a
group of subscribers) is satisfied by alphabetical load order without any
extra mechanism.

## Consequences

- No functional regressions in steady state. All panes, trackers, and scripts
  behave identically from the player's perspective.
- `cp -r` reload is cleaner: no `_installed` guards, no lazy hook installation.
- Disconnect blanks both `bridge/status.state` and `bridge/buffs.state` within
  one poll tick (previously `buffs_state` only serialised on `affects_changed`,
  not on `char_reset`).
- With `events.trace = true`, each GMCP packet now produces an
  `[EVENTS] gmcp_<module> = ...` line. `gmcp_char_vitals` is added to
  `events.trace_skip` to suppress noise.
- New `gmcp_*` events and `char_reset` added to the event catalogue in
  `docs/events.md`.
