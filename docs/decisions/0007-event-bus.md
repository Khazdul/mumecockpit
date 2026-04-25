# 0007 — Lua event bus for core MUD triggers

**Status:** Accepted
**Date:** 2026-04-25

## Context

`autostab.lua` and `autobow.lua` both register `#action {%1 is dead! R.I.P.}`
and `#action {%1 disappears into nothing.}` in the game session. In tt++,
registering two actions with the same pattern in the same session is
undefined — the second registration shadows or races the first depending
on priority. Any additional subscriber (e.g. the upcoming session kill
tracker in phase B) would add a third, making the situation unmanageable.

## Decision

Introduce a Lua event bus (`events.subscribe` / `events.unsubscribe` /
`events.emit`) in `lua/core/events.lua`. A single set of high-priority core
triggers in `ttpp/core/mud_events.tin` (priority 3) owns the four mob-death
patterns and calls `events.emit("mob_death", name)` on each match. Scripts
subscribe to the event name rather than registering their own actions.

## Consequences

- Cross-cutting trigger ownership is now possible: any number of scripts can
  react to the same MUD output without registering duplicate actions.
- `ttpp/core/mud_events.tin` becomes the single audit point for "what does
  the client watch for" — a pattern never appears in more than one place.
- One extra layer of indirection in stack traces: a mob death shows
  `events.emit` → handler, rather than a direct tt++ → Lua call.
- Handlers must be defensive (`if not active then return end`) because the
  subscriber may receive an event after a prior run has aborted but before
  `unsubscribe` ran.

## Alternatives considered

**Per-script triggers (status quo).** Each script registers its own
`#action` for every MUD pattern it cares about. Simple but breaks on
duplicate patterns — two scripts cannot both own `%1 is dead!` without
racing. Does not scale beyond two scripts.

**Single super-script that owns triggers and dispatches.** One monolithic
script registers all patterns and calls into other scripts. Solves the
ownership collision but conflates ownership with logic and creates a hidden
dependency: every script must be known to the dispatcher. Adding a new
subscriber requires editing core infrastructure.
