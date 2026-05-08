# 0003 — GMCP-driven MUME connection state

## Context

`bridge/runtime/connection.state` was previously driven by tt++'s `SESSION CONNECTED` /
`SESSION DISCONNECTED` events. In direct mode this coincides with the MUME
connection. In MMapper mode it does not — the tt++ session is against
`localhost:4242` and stays alive as long as MMapper does, regardless of
whether MUME itself is reachable. The popup therefore reported "connected"
even after a MUME-side disconnect.

## Decision

Separate the two concepts.

- `GAME_SESSION` / `$game_session` continues to track the tt++ session's
  lifetime (unchanged).
- `bridge/runtime/connection.state` now tracks the MUME connection and is driven by
  GMCP: `Char.Name` → connected, `Core.Goodbye` → disconnected. MMapper
  abrupt-close is caught via a tt++ `#action` on
  `"Status: MUME closed the connection."`. `SESSION DISCONNECTED` remains a
  fallback via `clear_game_session`, covering direct-mode abrupt-drops and
  MMapper process death.

## Consequences

- The popup reflects real MUME status in both connection modes.
- There is a short bootstrap window (~0.5–2 s) where `connection.state` is absent
  before the first `Char.Name` arrives. Acceptable — the `reconnect` alias
  handles this case correctly.
- Silent disconnects (half-open TCP) are still not detected automatically;
  the user uses the popup's Reconnect button manually. A future heuristic
  (GMCP-silence detection) is parked for its own ADR when it becomes relevant.

## Rejected alternatives

- **Polling MUME status via GMCP ping** — rejected for day one; complexity
  without clear gain.
- **TCP keepalive on the tt++ socket** — does not help in MMapper mode where
  the socket is against localhost.
- **Keeping SESSION events as the primary source and patching MMapper mode
  with heuristics** — treats the symptom, not the cause.
