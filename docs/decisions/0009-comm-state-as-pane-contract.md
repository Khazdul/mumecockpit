# 0009 — comm.state as the stable Lua-to-pane contract

**Status:** Accepted
**Date:** 2026-04-26

## Context

The comm pane renderer (`bridge/comm_pane.py`) needs access to channel history,
channel metadata (names, labels, captions), and filter state. Two approaches
were considered for how Lua exposes this data to the Python renderer.

**Option A — Direct access to Lua internals.**
The renderer reads internal storage structures directly, either by inspecting
Lua data-file dumps of `state.comm.history` and `state.comm.channels`, or by
coupling its schema to the exact field names and list formats that `comm_log.lua`
uses at any given time.

**Option B — A serialised projection as explicit contract.**
`lua/core/comm_state.lua` builds a projection of Lua state and writes it to
`bridge/comm.state` as a stable, explicitly documented JSON file. The renderer
reads only this file; it has no knowledge of internal history-storage decisions.

## Decision

Option B: `bridge/comm.state` is the stable, documented contract between the
Lua brain and `comm_pane.py`. The file is owned by `lua/core/comm_state.lua`,
written atomically (tmp + rename), and polled by the renderer via mtime.

The schema is specified in `docs/comm-pane.md`. Any change to internal storage
(e.g. switching `state.comm.history` from a flat array to a ring-buffer, adding
per-session log files, or sharding by channel) only requires updating
`comm_state.lua`'s `serialize()` function — the renderer is unaffected.

## Consequences

- Adding a new field to `comm.state` is a backwards-compatible extension; the
  renderer ignores unknown keys.
- Removing or renaming a field is a two-step migration: update `comm_state.lua`
  and `comm_pane.py` together.
- The serialisation cost (JSON encode + atomic write) is paid on every
  `Comm.Channel.Text` and `Comm.Channel.List` event. At expected message
  rates (tens per minute during active play, short bursts during group chat),
  this is negligible. If volume grows significantly, `comm_state.lua` can batch
  writes with a short debounce timer without changing the renderer.
- `bridge/comm.state` is gitignored (runtime artefact). The schema is documented
  in `docs/comm-pane.md` (checked in), which is the source of truth.

## Alternatives considered

- **Direct file access without a contract.** Rejected: tightly couples the
  renderer to internal storage, making refactors of `comm_log.lua` silently
  break the UI.
- **IPC via a Unix socket or named pipe.** Rejected: adds a persistent process
  and error recovery complexity. mtime polling with an atomic file is the
  pattern already established by `status.state` — reusing it keeps the system
  uniform and simple.

## 2026-04-26 update

`comm.state` is now also read by `lua/core/comm_state.lua` at load time,
populating `state.comm.history` and `state.comm.channels` from the previous run.
This works around the one-shot nature of `Comm.Channel.List` on persistent TCP
connections, so the pane is not blank after `cp -r`.

The schema dropped the `filters` field — filter state is now owned by
`comm_pane.py` directly. See ADR 0010 update.
