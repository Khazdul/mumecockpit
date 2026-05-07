# 0043 — Unified Character-Event Marker as `char_ui`

**Status:** Accepted

## Context

`affect_ui` was added to give affects a dedicated `◆`-family visual treatment
in the UI pane. Stored spells continued to use `script_ui("STORE", …)` → `▶`
because that helper predated `affect_ui`. Upcoming trackers (herblores, charm
timers) plus possible future character-state events (e.g. target
acquired/changed) need a single, predictable visual marker so the buffs pane
and the broader character-state surface read as one language.

## Decision

A single helper `char_ui(category, name, verb, detail?)` owns the `◆` prefix.
Scope: any character-state lifecycle event — not limited to buffs-pane content.
Categories form a small controlled vocabulary (`spell`, `buff`, `debuff`,
`store`; `herb` and `charm` reserved). Canonical verbs: `up`, `refreshed`,
`expiring`, `down`. Domain-specific verbs (`stored`, `recalled`, `decayed`, …)
are allowed when they read more naturally; the structure
`name verb [— detail].` is fixed.

## Alternatives considered

- **Parallel helpers** (`store_ui`, `herb_ui`, `charm_ui`) sharing a renderer
  — rejected; multiplies call-site names without semantic gain.
- **Keep `affect_ui` for affects only**, leave STORE on `script_ui`
  — rejected; visual fragmentation across the buffs pane.
- **Restrict `◆` to the buffs pane only** — rejected in favour of the broader
  "character-state lifecycle" rule so that future events (target changes, etc.)
  can join the family without reopening this decision.

## Consequences

- Existing `affect_ui` call sites renamed to `char_ui`; signature unchanged
  for `spell`/`buff`/`debuff`.
- Stored-spell state-change lines move to `◆`; operational STORE lines stay on
  `▶` and the lost-track warning stays on `⚠`.
- `expiring` is reserved as a verb but not yet emitted; expected consumers are
  upcoming "about to drop" alerts in affects, stored spells, herblores, and
  charms.
- `herb` and `charm` are reserved category names; their colours and verb sets
  are settled when the respective trackers land.
