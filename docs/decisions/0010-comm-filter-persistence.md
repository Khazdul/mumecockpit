# 0010 — Sparse-map persistence for comm channel filters

**Status:** Accepted
**Date:** 2026-04-26

## Context

Channel filter state (which channels are shown in the comm pane) must survive
`cp -r` (Lua restart) so the player's configuration is not lost on reload. Two
persistence approaches were considered.

**Option A — Full map: write every known channel with its current state.**
`comm_filters.conf` always contains one line per channel advertised by the
server. On load, the full map is restored exactly.

**Option B — Sparse map: write only channels that were explicitly toggled.**
Missing entries are interpreted as "enabled" (the default). Only channels
whose state differs from the default need to be stored.

## Decision

Option B: `bridge/comm_filters.conf` is a sparse map. A missing key means
"enabled". Only channels explicitly disabled (or explicitly re-enabled after
being disabled) appear in the file.

File format: `name=true|false` (one line per explicitly-set channel).

## Consequences

- **New channels default to enabled automatically.** If the MUME server adds a
  new channel between sessions, it appears in the comm pane without any
  configuration action. This is almost always the desired behaviour.
- **`comm_filters.conf` stays minimal.** Most players who have never toggled
  any channel will have an empty file.
- **State is preserved across `cp -r`.** `comm_state.lua` reads the conf at
  load time, restoring all explicit overrides before the first `Comm.Channel.List`
  arrives.
- **Toggling a channel back to its default state (re-enabling a disabled channel)
  writes an explicit `name=true` entry.** This is harmless — an explicit `true`
  is semantically identical to an absent key. The file will accumulate one `true`
  line per channel that has ever been toggled twice. Acceptable: the number of
  channels is small (≤ 20 in practice) and the file is gitignored.
- **If a channel is removed by the server**, its entry stays in the conf file
  harmlessly — `state.comm.toggle()` validates against `state.comm.channels`
  and is a no-op for unknown names, so stale entries in the conf are ignored.

## Alternatives considered

- **Full map.** Rejected: requires knowing the complete channel list at write
  time (possible only after `Comm.Channel.List` arrives), and new channels would
  require a user action to appear. The sparse map's default-on behaviour is more
  appropriate for a log-like communication pane.
- **No persistence (in-memory only).** Rejected: filter state is lost on every
  `cp -r`, which is frequent during development. Players who disable busy channels
  (e.g. `news`) should not need to redo this on every reload.
