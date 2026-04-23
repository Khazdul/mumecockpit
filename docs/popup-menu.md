# In-Game Popup Menu

Implementation details for `bridge/ingame_menu.sh` — the ESC-triggered
overlay that appears during play. Touch this file when changing popup
submenus, the status header, `cp -s` internals, or toggle-pane persistence
behaviour.

## Overview

ESC from any pane opens a tmux display-popup overlay via a tmux root
keybinding in `tmux_start.sh` — this works regardless of pane focus.
The popup renders via `bridge/ingame_menu.sh`, sharing `bridge/menu_render.sh`
helpers with the launcher.

The top menu item is context-aware: "Continue" when connected (dismisses
popup) or "Reconnect" when disconnected (fires `reconnect` alias then
dismisses). Both states are rebuilt from `bridge/session.state` on every
render.

## Status header

The status header at the top of the popup shows Profile · Mode · Link.
Backed by `bridge/session.state` (connection status) and
`bridge/ping.cache` (link quality). Example:

    Profile: default  ·  MMapper  ·  Link: 38ms (stable)

State is re-probed from the files on every render — never cached.

## Options submenu

Four toggles (UI / Dev / Input / Pane headers) + Back. State is re-probed
from tmux on every render — never cached. Toggling calls
`toggle_pane.sh --persist` directly; toggles do **not** route through tt++
so no `cp -X` lines appear in the game pane. The popup submenu is therefore
the persistent-toggle entry point; `cp` aliases remain runtime-only.

`cp -u`, `cp -d`, `cp -i`, and `cp -h` are thin wrappers around
`bridge/toggle_pane.sh`. Each alias passes its target (`ui`, `dev`,
`input`, or `headers`) to the script via `#system`. The script also
accepts an optional `--persist` flag; the `cp` aliases invoke it without
`--persist`, so they remain runtime-only and never modify `startup.conf`.

## Scripts submenu

Ports the launcher's Scripts page into the popup. Reads `bridge/scripts.cache`
on each render — picks up cache changes if `cp -r` fires while the submenu
is open. Scrollable with UP/DOWN; scroll hint appears in the footer only
when content exceeds visible rows. Rendering is identical to the launcher
(A:/S:/H:/B:/M: tags, 60-col block centred). Parser and renderer are
duplicated from `launcher.sh` — not extracted into `menu_render.sh` — to
keep the shared helper stable. Not covered: live script state
(IDLE/RUNNING/FIRING) and a stop-all-scripts button — both parked.

## Save profile (`cp -s`)

The "Save profile" row is always visible — save works even after link loss,
since tt++ keeps the disconnected session alive. Selecting it triggers
`cp -s` via `tmux send-keys`; an inline "Saved ✓" flashes in `_MR_ACCENT`
for ~1 s.

`cp -s` runs `#class {$_profile} {write} {ttpp/sessions/$_profile.tin}`
inside the profile's tt++ session via a `#gts { #$_profile { ... } }`
wrapper. Uses `$_profile` (stable, set once at tt++ startup from
`startup.conf`) rather than `$game_session` (cleared on disconnect) so
save works after link loss as well as during a live connection. Success
and error messages are routed to the UI pane via `#lua {system_ui(...)}`
and `#lua {ui_err(...)}` respectively, not `#showme` to the game pane.

## Scope trims

Deliberately NOT in the popup:
- **About** — not enough value to justify the code.
- **Reload** — `cp -r` from the input pane is the intended path.
- **Profile switch / connection mode** — launcher-only; requires restart.
- **Layout mockup** — saves vertical space in the popup.

---
Back to [architecture.md](../architecture.md).
