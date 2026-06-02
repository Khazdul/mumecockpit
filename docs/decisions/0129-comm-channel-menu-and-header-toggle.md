# 0129 — Menu-driven comm channel filters and channel-header toggle

**Status:** Accepted
**Date:** 2026-06-03

## Context

ADR 0010 established `comm_filters.conf` as a *sparse map* of channel filter
state: `name=true|false`, one line per explicitly-toggled channel, a missing
key meaning "enabled". Its 2026-04-26 update moved ownership entirely to
`comm_pane.py` — filters are UI preferences, not game state, and routing them
through tt++ caused the alias text to echo in the game pane. Lua no longer
references filters at all; `comm_pane.py` read and wrote the file by itself,
loading it once at startup.

This PR adds a **Communication** menu to both Options surfaces — the launcher
and the in-game popup — that lets the player toggle individual channels on and
off without typing aliases. It also adds a new **show channel header**
preference for the comm pane. Both surfaces are processes *other than*
`comm_pane.py`, so they need to write filter state that `comm_pane.py` owns,
and they need somewhere to store the new header preference.

Two facts shape the design:

1. The menu code lives in `bridge/launcher`; the comm pane lives in
   `bridge/panes`. Per ADR 0126, the two packages are launched as separate
   processes with separate `sys.path` roots and share no module — neither can
   import the other's tables. The conf files are the only cross-package
   contract.
2. ADR 0010's anti-tt++ reasoning (alias echo) only bound the *Lua/tt++* path.
   The new writers are Python and write the file directly, so they do not
   re-introduce that problem.

## Decision

### 1. Additional Python writers; live re-read in the pane

`comm_filters.conf` gains additional writers — the launcher and the popup (via
a new `comm_channels.py` helper) — alongside `comm_pane.py`. ADR 0010's sparse
semantics are **unchanged**: a missing key still means "enabled", and the
writers only emit explicitly-toggled channels.

Because the file can now change from another process while the pane is running,
`comm_pane.py` **re-reads `comm_filters.conf` live on its 250 ms poll** instead
of only at startup. To avoid self-triggering on its own writes, the pane bumps
its own tracked mtime after each self-write, so a re-read sees no change.

### 2. Header visibility in a separate `comm_prefs.conf`

The new "show channel header" preference lives in its own file,
`comm_prefs.conf` (key `show_header=true|false`, default `true`), **not** as a
reserved key inside `comm_filters.conf`. Keeping the two apart preserves ADR
0010's channel-map schema: every key in `comm_filters.conf` is still a channel
name, with no reserved-word exceptions to special-case on read.

### 3. Menu-side channel tables restated, not imported

The menu's channel tables (`CHANNEL_ORDER`, the per-channel colours, and
`CHANNEL_DISPLAY`) are **restated** in `comm_channels.py`, not imported from
`comm_pane.py`. Per ADR 0126, `bridge/launcher` and `bridge/panes` share no
import path; the conf files are the cross-package contract, and the tables on
each side are an independent copy of the same channel vocabulary.

### 4. Fresh-install defaults come from absence, not seeding

No template is shipped and nothing is seeded on install. Defaults fall out of
absence: with no `comm_filters.conf`, every channel is on (the sparse
default-on of ADR 0010); with no `comm_prefs.conf`, the header is shown (code
default `True`). A fresh install therefore opens the menu with all channels
enabled and the header visible, with both files empty/absent until the player
changes something.

## Consequences

- **Multi-writer + live re-read.** Three processes may now write
  `comm_filters.conf`, and the pane picks up external changes within one
  250 ms poll. The mtime bump after self-writes keeps the pane from reacting to
  its own edits.
- **An external filter edit drops runtime-only solo.** Because the pane re-reads
  the whole file, a hand-edit (or a menu toggle) applies live with no restart.
- **Restated tables must be kept in sync.** `comm_channels.py` and
  `comm_pane.py` each carry their own copy of the channel order, colours, and
  display names. If a future custom channel name is added in only one place,
  the two drift. The cross-reference and this ADR are the only mitigation;
  there is no compile-time link.
- **0010's anti-tt++ reasoning still holds.** The new writers are Python and
  bypass tt++/Lua entirely, so no alias text echoes in the game pane.
- **Clean schema preserved.** `comm_filters.conf` remains a pure channel map;
  the header preference is isolated in `comm_prefs.conf`.

## Alternatives considered

- **Reserved key in `comm_filters.conf` for the header preference.** Rejected:
  it pollutes ADR 0010's channel-map schema with a non-channel key that every
  reader would have to special-case.
- **Routing menu toggles through tt++/Lua.** Rejected: it re-introduces the
  alias-echo problem that ADR 0010's 2026-04-26 update fixed by moving filters
  out of tt++.
- **Seeding all-true on install.** Rejected: it defeats the sparse map — a
  fresh file would carry one `true` line per channel, when absence already
  means "all on".
- **Importing `comm_pane.py`'s tables into the launcher.** Rejected: there is
  no shared import path between `bridge/launcher` and `bridge/panes` (ADR
  0126); the conf files are the contract, and restating the tables is the
  established pattern.

## Relation

Extends ADR 0010 — it does **not** supersede the sparse-map decision; the
sparse semantics and the anti-tt++ ownership both stand. Relates to ADR 0126
(restate-don't-import across bridge packages).
