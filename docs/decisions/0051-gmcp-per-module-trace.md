# ADR 0051 — Per-module GMCP trace via gmcp.trace_only

**Status:** Accepted  
**Date:** 2026-05-09

## Context

`gmcp.trace = true` dumps every decoded GMCP body to `debug.log`. During
active play this floods the log across all subscribed modules. The common
discovery workflow targets a single module or package; a surgical knob is
needed that does not change the meaning of the existing flag.

## Decision

Add `gmcp.trace_only` as an opt-in whitelist table in `lua/brain/gmcp.lua`.

Matching logic (evaluated in order):
1. If `gmcp.trace` is truthy → always trace (catch-all; overrides whitelist).
2. If `gmcp.trace_only` is nil → no trace.
3. If `gmcp.trace_only[module]` is truthy → exact key match; trace.
4. Extract package via `module:match("^([^%.]+)")`. If `gmcp.trace_only[package]`
   is truthy → prefix match; trace all messages in that package.
5. Otherwise no trace.

Default state is unchanged: both `gmcp.trace` and `gmcp.trace_only` default
to falsy, so no implicit tracing occurs.

## Alternatives rejected

**(a) Blacklist (`trace_except`)** — discovery is the common case, not
gagging known-noisy modules. A whitelist matches the mental model better.

**(b) Make `gmcp.trace` polymorphic (boolean OR table)** — breaks the "is
tracing on?" mental model and makes config inspection harder. Two named
knobs read more clearly than one overloaded one.

**(c) Per-module verbosity levels** — overkill; on/off per module is all
we need.

## Consequences

- `gmcp.trace` semantics preserved exactly.
- Default state unchanged (no implicit tracing).
- Discovery workflow: set `gmcp.trace_only = { Char = true }`, restart the
  brain, observe, revert.

## Relation to other ADRs

Independent of ADR 0046 (event dispatch). Refines the existing trace
mechanism without touching dispatch semantics.
