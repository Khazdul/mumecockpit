# 0052 — Group vital-pair freshness inference

**Status:** Accepted

## Context

`Group.Update` is incremental: a single packet can carry the numeric value for
a vital (e.g. `{"id":2,"hp":200}`) or its band-string (`{"id":2,"hp-string":"fine"}`)
but not always both. Without inference, the cached value and string drift apart
between updates and the renderer can show contradictory information — for
example, a full green bar (pct=1.0 from a stale value) beside the label
"wounded" (from a fresh string update).

## Decision

At `Group.Update` merge time, each vital pair (hp/hp_string, mana/mana_string,
mp/mp_string) is handled according to which fields are present in the payload:

- **Both fields present (Case A):** store both; no inference needed — the
  server supplied a consistent snapshot in one packet.
- **Value only (Case B):** store value, clear cached string. The string
  referred to the previous percentage and is now stale.
- **String only (Case C):** if a cached value and maxv allow a percentage
  calculation, call `state.group.in_band(kind, pct_int, label)`. If the
  band excludes that percentage (`false`), the cached value is stale —
  clear it. If the label is unknown (`nil`) or the band includes the
  percentage (`true`), keep the value. Always store the new string.

`Group.Add` and `Group.Set` are full-payload paths and follow Case A semantics
per field present; absent fields are left nil. They need no inference.

Band tables are defined as inclusive integer-percent `{lo, hi}` ranges in
`lua/core/group_state.lua` and serve as the truth source for
value↔string consistency. The helper `state.group.in_band(kind, pct_int, label)`
encapsulates all band lookups.

## Alternatives rejected

**(a) Per-field timestamps.** More state. Two fields in the same partial update
arrive with the same timestamp, so timestamps cannot disambiguate which half of
a pair is fresher.

**(b) Last-write-wins per field (always clear the sibling on any update).** A
value-only update would clear the string even when the string is still accurate,
and a string-only update would always discard the value. In MUME's stream,
string-only updates are common and the cached value is frequently still valid —
clearing it unconditionally would degrade renderer accuracy unnecessarily.

**(c) Render-time reconciliation.** Pushes inconsistency detection into every
consumer. Centralising at merge time keeps `state.group.members` canonical and
lets the renderer trust what it reads.

## Consequences

- `state.group.members[id]` is internally consistent at every event boundary.
- Bands act as the single truth source for "value and string agree." If a band
  range is mis-calibrated, the bias is toward clearing the value and falling
  back to string-band rendering, which is less wrong than displaying
  contradictory data.
- MP bands are placeholder until server data is available to calibrate them.
  Mis-calibrated MP bands will produce false contradictions at boundaries, but
  the worst outcome is that the cached MP value is cleared more aggressively
  than necessary — not that stale data is shown.
- Unknown labels (not in the band table) are treated as `nil` (forward-compat):
  the cached value is preserved and a `dbg()` line is emitted for
  observability.
