# 0014 — System-owned profile auto-save on session deactivation

**Status:** Accepted
**Date:** 2026-04-27

## Context

Auto-save was previously implemented as a SESSION DEACTIVATED handler in the
user profile file (`ttpp/profiles/default.tin`). That handler hardcoded the
class name and was never part of system code. It was removed without
replacement, leaving `cp -s` (the popup Save button) as the only working save
path. `cp -e` and the popup "Exit to main menu" flow all left runtime profile
changes unsaved.

## Decision

Move auto-save to system code in two layers:

**(a) Global SESSION DEACTIVATED handler in `system.tin`** — registered in
gts alongside the existing SESSION CONNECTED / DISCONNECTED / TIMED OUT
handlers. Uses `%0` dynamically as both the session name and the `#%0`
context prefix, so the `#class write` executes in the deactivating session
regardless of where the event handler runs. Internal sessions (`gts`, `lua`)
are filtered out identically to the other session event handlers.

**(b) Idempotent explicit save in `cp -e`** — immediately after `#gts` and
before any teardown logic. Runs after the SESSION DEACTIVATED handler fires
as defense in depth against tt++ event-context subtleties. Same file, same
content — writing twice is harmless.

SESSION DEACTIVATED is reserved as a system event going forward. User
profiles must not register their own SESSION DEACTIVATED handler.

## Consequences

- Save works correctly for any profile name without per-profile configuration.
- Behavior is independent of profile file contents — a new blank profile
  auto-saves on first exit.
- `cp -s` is unchanged and continues to work as the user-triggered save path.
- PROGRAM TERMINATION still does not save (the game session is already torn
  down by the time the event fires). Periodic save for terminal close /
  SIGKILL / crash is a separate future phase.
- **Footgun:** a user profile that registers its own SESSION DEACTIVATED
  handler will shadow the system handler, silently breaking auto-save. This
  is documented but not enforced; sanitizer enforcement is deferred.

## Alternatives considered

**Keep user-data handler in profile** — rejected. The handler hardcoded the
class name, was missing on new profiles, and was fragile to profile renames.
System code is the right owner.

**Single mechanism (event-only or explicit-only)** — rejected. tt++ event
semantics around session deactivation context are not fully documented; the
explicit save in `cp -e` is cheap and provides a documented call-site
guarantee independent of event delivery subtleties.

**Sanitizer enforcement of reserved-event rule** — deferred. Worth doing if
the footgun materializes in practice; not required to fix the present bug.
