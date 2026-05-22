# 0093 — Static metadata headers and opt-in script loading

**Status:** Accepted
**Date:** 2026-05-22

## Context

`lua/scripts/` modules were loaded unconditionally at brain startup: every
file in the directory was `dofile()`'d, and each file called
`register_script(meta)` at runtime to populate `_scripts`, build its
`cp -<name>` help box, and contribute a record to `bridge/runtime/scripts.cache`.

Two follow-ups against this scheme had been parked:

1. **Per-script enable/disable from the launcher.** ADR 0002 split
   `lua/core/` from `lua/scripts/` explicitly to make the opt-in tier
   addressable; the actual selection mechanism was deferred. The
   in-game popup's Scripts view and the launcher's Scripts page exist
   already, but both are read-only — there is no toggle.

2. **Surfacing disabled scripts as installed-but-off.** A disabled
   script that never runs cannot call `register_script(meta)`, so the
   runtime registry — and therefore `scripts.cache` — only ever
   contained scripts the user had already opted in to. The launcher
   has no way to display a script the user has not yet enabled.

The two problems are the same chicken-and-egg: runtime registration
only sees scripts that ran; opt-in needs to know about scripts that
have not run.

## Decision

Replace `register_script(meta)` with a static metadata header parsed
from each script file without executing it. Enable state lives in a
flat key=value config file. The loader reads both, parses every
header, then `dofile()`s only enabled scripts and writes a catalog of
all scripts (enabled + disabled) to `bridge/runtime/scripts.cache`.

### Metadata header format

The first contiguous run of `--` comment lines at the top of a script
is the header block. A blank line or any non-`--` line terminates it.
Inside the block, `-- @key value` lines are metadata; other comment
lines (decorative rules, prose) are ignored. Recognised keys:

- `@summary <text>` — one-line description.
- `@alias <name> <desc>` — repeatable; an alias the script provides.
  The first token is the alias name; the remainder is its description.
- `@help <text>` — repeatable; detailed help lines.

Unknown `@key` lines are silently skipped so future keys can be added
without changing the parser. A script's name is its filename without
`.lua`; there is no `@script` / `@name` key.

### scripts.conf — enabled state

Flat key=value file, same conventions as the other `bridge/runtime/`
configs (`startup.conf`, `layout.conf`, `comm_filters.conf`). Key is
the script filename stem; value is `1` (enabled) or `0` (disabled).
`#` comments and blank lines are ignored.

Effective state at brain startup:

1. `bridge/runtime/scripts.conf` if it exists, else
2. `bridge/launcher/templates/scripts.conf` (shipped), else
3. a script absent from both files defaults to **enabled**.

The shipped template lists every script in `lua/scripts/` as `=0`.
Example scripts are learning material, not silent behaviours that
turn themselves on for a fresh install. This mirrors ADR 0042's
"template is the shipped default" pattern for `blank_profile.tin`.

The runtime file is written by the launcher's Scripts view (Part 2 of
this work). The brain only reads.

### Loader behaviour

`load_scripts()` now:

1. Scans `lua/scripts/*.lua` and parses every header statically.
2. Resolves enabled state per the rules above.
3. `dofile()`s only enabled scripts, alphabetical order (unchanged).
4. Registers `cp -<name>` for each enabled script from its parsed
   header.
5. Writes the full catalog (enabled + disabled) to
   `bridge/runtime/scripts.cache`, with new `ENABLED:` and `ALIAS:`
   lines alongside the existing `SUMMARY:` / `HELP:`.

`lua/core/` loading is unchanged — always on, no opt-in.

### scripts.cache format

Line-prefixed, one record per script:

```
SCRIPT:<name>
ENABLED:<0|1>
SUMMARY:<text>
ALIAS:<name>|<description>
...
HELP:<line>
...
```

A new `SCRIPT:` line starts a new record. Every script in
`lua/scripts/` gets a record regardless of enabled state — disabled
scripts must be visible to the launcher's toggle UI.

### register_script is removed

The runtime registration call and the `_scripts` global it populated
both disappear. Every `lua/scripts/*.lua` file gets a header and drops
its `register_script({...})` block.

## Consequences

- The launcher can list every installed script with its full metadata
  whether or not the user has enabled it — the Part-2 Scripts view
  has the data it needs.
- Disabled scripts contribute nothing to the running session: no
  handlers, no triggers, no `cp -<name>` alias, no entry in the main
  `cp` Scripts list. They are visible only in the launcher's Scripts
  view, by design.
- Toggling a script's enabled state in the launcher takes effect at
  the next brain startup. The in-game popup's Scripts view is
  necessarily read-only — re-running the loader mid-session would
  have to tear down the script's aliases / triggers / event
  subscriptions individually, and scripts have no contract for that.
  Restarting the cockpit (Exit to main menu → reconnect) is the
  intended toggle path.
- Adding a new script is now header + drop in place. The drift risk
  of forgetting to call `register_script` is gone.
- The metadata header doubles as in-file documentation, readable
  even by a tool that does not execute Lua.

## Rejected alternatives

- **Sandbox-execute every script just to harvest metadata.** Keeps
  `register_script` and lets disabled scripts still register their
  metadata into a parallel registry by running their top-level code
  in a stub environment. Rejected: every script's top-level body
  calls `events.subscribe`, `game_cmd`, `session_cmd`, `send`, etc.
  — a sandbox sufficient to harvest metadata without side effects is
  itself bigger than the parsing problem, and one mistake leaks
  triggers into the real game session. Static parsing is the safer
  contract.
- **Manifest file listing all scripts and their metadata.** A single
  `bridge/launcher/templates/scripts.manifest` that the loader and
  launcher both read. Rejected: two-place sync — every new script
  needs to be added to the manifest AND committed to `lua/scripts/`
  — which is the exact problem ADR 0002 declined to solve with a
  manifest for the core/scripts split. Co-locating metadata with the
  code keeps them in sync by construction.
- **Convention-based discovery (filename = enabled, filename.off =
  disabled).** Encodes state in the filesystem. Rejected: makes the
  launcher's toggle action a `mv`, which is awkward to undo
  atomically and clashes with version-controlled scripts.

## Relation to other ADRs

- **Supersedes** the "Out of scope" note in ADR 0002 — per-script
  opt-in is now implemented; the directory split set up there is the
  foundation this work builds on.
- **Mirrors** ADR 0042's template-then-runtime resolution: shipped
  template under `bridge/launcher/templates/`, runtime file under
  `bridge/runtime/`, runtime shadows template.
- **Extends** ADR 0047's `bridge/runtime/` consolidation with a new
  conf file (`scripts.conf`) under the existing rule that runtime
  artefacts live under `bridge/runtime/` and are gitignored.
