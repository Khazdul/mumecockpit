# 0058 — Reconnect UX: popup item, mode-aware bounce, sentinel-suppressed popup

**Status:** Accepted
**Date:** 2026-05-11

## Context

Three tightly coupled defects in the reconnect path surfaced together
during play and are addressed by a single change set.

**1. Silent disconnect has no popup UX path.** The popup auto-opens on
`mark_mume_disconnected()`, which fires from `Core.Goodbye`, MMapper's
"MUME closed the connection." text, or `SESSION DISCONNECTED`. A
half-open TCP link (NAT timeout, ISP blip, suspended laptop) produces
none of those signals: GMCP is silent, MMapper sees no FIN, and the
tt++ session stays alive. `connection.state` therefore stays present,
the popup's top item stays "Continue" only, and the player has no
in-popup affordance for "the link feels dead — bounce it." The
`reconnect` alias was usable from the input line, but only if the
player remembered the name and trusted that typing into a half-open
session would do anything useful.

**2. MMapper rejects `_connect` on a live link.** The reconnect alias's
MMapper branch sent a bare `_connect` to the game session. MMapper
treats that as a request to open a new connection while it already has
one and refuses with `already connected`. The reconnect was a no-op in
exactly the scenario it was designed for (working tt++↔MMapper socket,
silently dead MMapper↔MUME socket). Direct mode (`#zap` + `connect`)
was unaffected because the zap tears down the tt++ session before the
new connect attempt.

**3. User-initiated reconnect produces a spurious popup.** Both modes'
reconnect paths intentionally produce a disconnect signal — direct mode
zaps the session (triggers `SESSION DISCONNECTED` →
`clear_game_session()` → `mark_mume_disconnected()`); the new MMapper
flow sends `_disconnect` (triggers `Core.Goodbye` or the MMapper text
trigger). With the popup's auto-open routed through
`mark_mume_disconnected()`, that signal pops the menu in the ~1 s gap
before the follow-up connect arrives, on top of whatever the player was
doing. The popup then closes itself on the next `mark_mume_connected()`
write, but the flash is jarring and obscures the system_ui reconnect
trace.

The three defects share infrastructure (`mark_mume_disconnected`, the
`reconnect` alias, the popup menu) and a fix for any one in isolation
either fails to deliver the user-visible win or worsens one of the
other two. Bundled here.

## Decision

**Popup menu (`bridge/launcher/ingame_menu.sh`).** `_rebuild_menu` adds
Reconnect as a second item directly under Continue when
`connection.state` is present. Default selection (`_SEL=0`) still falls
on Continue when connected and Reconnect when disconnected, so neither
keyboard flow regresses. The reconnect action dispatch is unchanged —
both menu paths and the input-line alias route through the same
`reconnect` alias.

**Reconnect alias (`ttpp/core/system.tin`).** MMapper-mode reconnect
with an existing `&game_session` now sends `_disconnect`, then schedules
`_connect` via `#delay {1}`. Direct-mode reconnect retains the existing
`#zap` + `#delay {1} {connect}` pattern. Both modes now also set the
user-reconnect sentinel via `#lua {mark_user_reconnecting()}` before the
disconnect step and clear it from the post-`#delay` body as
belt-and-braces.

**User-reconnect sentinel (`bridge/runtime/.user_reconnecting`).** A
single-shot sentinel file. `lua/brain/connection.lua` exposes
`mark_user_reconnecting()` and `clear_user_reconnecting()` globals (used
by the alias) and consults the sentinel inside
`mark_mume_disconnected()`: if present, remove it and skip the popup
auto-open; otherwise behave as before. All other disconnect-side work
(state clear, `system_ui` logout line, `run_ending` emit, resets) runs
unchanged. `bridge/launcher/tmux_start.sh` removes the file at startup
alongside the other stale-sentinel cleanup, guarding against a crashed
reconnect leaving the file behind.

## Consequences

- Silent disconnect now has an in-popup affordance: ESC any time the
  link feels dead, Down once, Enter, and the alias bounces the
  connection.
- MMapper reconnect actually reconnects. The `already connected` error
  is gone in the silent-disconnect scenario the alias was designed for.
- User-initiated reconnect produces no popup flash. The system_ui
  reconnect trace remains visible in the UI pane.
- Real disconnects (graceful `quit`, MMapper text trigger,
  direct-mode abrupt drop) still open the popup as before. The sentinel
  is single-shot — a subsequent real disconnect after a user-initiated
  reconnect opens the popup normally.
- The 1 s `#delay` between disconnect and connect adds a deterministic
  gap to MMapper-mode reconnect; previously the gap was zero (and the
  reconnect failed). Direct mode's existing 1 s gap is unchanged.
- Two persistence touchpoints: the sentinel file and the alias body.
  Both live in named files documented in
  `docs/session-lifecycle.md` and `docs/popup-menu.md`; the alias links
  to this ADR.

## Alternatives considered

**mtime-based TTL on the sentinel.** Treat the sentinel as valid only
within N seconds of its mtime, so a crashed reconnect cannot suppress a
real disconnect indefinitely. Rejected: the sentinel is already
single-shot at consumption time (eaten by the first
`mark_mume_disconnected()` call), and `tmux_start.sh` clears it at
startup. The only window of "stale validity" is between a crash
mid-reconnect and the next startup, which is the same window in which
the cockpit isn't running at all. TTL adds complexity for a scenario
that is already covered.

**Context-aware Continue that auto-detects a dead link.** Have the
popup probe link liveness (e.g. ping freshness, GMCP heartbeat) and
relabel Continue → Reconnect when the link appears dead. Rejected: no
reliable signal that distinguishes "MUME has been quiet" from "link is
dead" without active probing, and active probing from the popup would
race against ongoing gameplay. Surfacing Reconnect as a second item is
strictly cheaper and gives the player explicit control.

**Popup-side close-on-reconnect-complete signal.** Leave the spurious
popup behaviour as-is and have `mark_mume_connected()` (or a Lua-side
hook) close the popup when the reconnect completes. Rejected: requires
inter-process tmux scripting from inside Lua (find the popup, send it a
kill signal) which is fragile across tmux versions, and the popup-flash
is still visible during the 1–2 s reconnect window. Suppressing the
auto-open at the source is simpler and cleaner.

**Skip the `#delay` and send `_connect` immediately after
`_disconnect`.** Removes the 1 s gap. Rejected: MMapper needs time to
release the previous socket before accepting the new one; back-to-back
`_disconnect` `_connect` on the same line collapsed into the same
"already connected" failure mode in early testing. The 1 s gap matches
the existing direct-mode delay and is well within the time the player
expects a reconnect to take.

## Relation to other ADRs

- **ADR 0050** introduced the single-dispatch-point discipline for
  disconnect signals (`mark_mume_disconnected()`). This ADR adds the
  first opt-out path to that dispatch point. The transition guard
  (no-op when state is already absent) and dedup semantics from ADR
  0050 are preserved unchanged; the sentinel layer sits in front of the
  popup-open branch only.
- **ADR 0057** clarified that `#nop` is not opaque to `;`. The new
  alias body adds a few extra `#nop` comment lines but no mid-text
  semicolons; the audit grep in 0057 stays clean.
