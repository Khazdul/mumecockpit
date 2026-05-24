# 0101 — Single source of truth for startup.conf fresh-install defaults

**Status:** Accepted
**Date:** 2026-05-24

## Context

Fresh-install defaults for `bridge/runtime/startup.conf` were defined in
three places that had drifted apart:

1. The `_CONF_DEFAULTS` dict in `bridge/launcher/launcher.py`.
2. A `printf`-ed seed block in `bridge/launcher/tmux_start.sh` (`if [ !
   -f "$CONF" ]` branch). That seed only wrote a partial subset of the
   keys — notably `show_buffs` and `show_group` were absent.
3. The `${show_*:-N}` fallback guards in
   `bridge/launcher/build_initial_layout.sh`.

`launcher.py` only writes `startup.conf` on Options Back / ESC — not on
"Enter MUME". A true fresh install (no menu visit, or menu visit
without entering Options) was therefore seeded by `tmux_start.sh`'s
partial block, and missing keys then fell through to
`build_initial_layout.sh`'s guards. Several guards defaulted to `0`
(buffs, comm, status), which produced a cockpit with several panes
silently off on a fresh install — at odds with the launcher's own
`_CONF_DEFAULTS` saying those panes were on.

This mirrors prior ADRs in the codebase that drained drift by promoting
a shipped template to the single source of truth: ADR 0042 for
`templates/blank_profile.tin` and ADR 0093 for `templates/scripts.conf`.

## Decision

Ship `bridge/launcher/templates/startup.conf` as the single source of
truth for fresh-install defaults. Every other component derives from
it:

- `tmux_start.sh` seeds a missing `bridge/runtime/startup.conf` by
  copying the template (`cp` of the template file), instead of
  emitting an inline `printf` block. Both the menu path and the
  `--no-menu` / `-d` / `-u` paths funnel through this seeding.
- `launcher.py` parses the template at import time via the same
  `_parse_conf` helper used at runtime, and uses the result as
  `_CONF_DEFAULTS`. A minimal hardcoded dict remains as a defensive
  backstop if the template file is absent at import time, so the
  launcher still starts.
- `build_initial_layout.sh`'s `${show_*:-N}` fallback guards are
  aligned with the template values. They now only matter for upgraded
  installs whose `startup.conf` pre-dates a given key — a fresh install
  always gets a complete file from the template.

Fresh-install pane policy, baked into the template: every right-column
pane defaults on, plus pane headers; the developer pane defaults off.

A unit test (`bridge/launcher/tests/test_startup_conf_template.py`)
pins the template's key set against the explicit key tuple in
`launcher.py`'s `_save_conf`, so neither side can drift silently. The
same test asserts `show_dev=0` and every other `show_*` key = `1`.

## Consequences

- One file changes mean one location to update. No more partial seed
  block to keep in sync with the dict and the guards.
- Fresh installs now open Char + Buffs + Group + COMS + UI panes with
  headers, no Dev pane — uniform and predictable.
- The launcher's Panes grid and the cockpit boot path see the same
  defaults; the Options frame on a fresh install accurately reflects
  what the cockpit will open with.
- Upgraded installs missing a `show_*` key will now open that pane on
  the next start (the guards default to `:-1` except for `show_dev`).
  Previously the `:-0` guards preserved a per-key "no-surprise" stance
  for upgrades. See the alternative below.

## Alternatives considered

**Keep the per-pane `:-0` guards for buffs / comm / status to preserve
"no-surprise on upgrade".** Rejected: the asymmetry between the
fresh-install policy ("everything on except dev") and the upgrade
fallback policy ("buffs/comm/status off") was the original source of
the drift. The upgrade path now matches the install path. Users whose
existing `startup.conf` already contains explicit values are unaffected
— only installs missing a key see the new default.

**Generate `_CONF_DEFAULTS` from the template via a build step.**
Rejected as overkill. Parsing at import time costs nothing measurable
and keeps the launcher a single-file artefact.
