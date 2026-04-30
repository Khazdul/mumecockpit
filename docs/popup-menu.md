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

Five toggles (Character pane / Comm pane / UI / Dev / Pane dividers) + Back.
State is re-probed from tmux on every render — never cached. Toggling calls
`toggle_pane.sh --persist` directly; toggles do **not** route through tt++
so no `cp -X` lines appear in the game pane. The popup submenu is therefore
the persistent-toggle entry point; `cp` aliases remain runtime-only.

The input-pane menu bar (CHAR / BUFFS / COM / UI buttons in the bottom row)
is a sibling surface for the same three pane toggles. Both surfaces write
`startup.conf` via `toggle_pane.sh --persist`; each reflects changes made by
the other within ≤ 250 ms.

`cp -u`, `cp -d`, and `cp -h` are thin wrappers around
`bridge/toggle_pane.sh`. Each alias passes its target (`ui`, `dev`,
or `headers`) to the script via `#system`. The script also accepts an
optional `--persist` flag; the `cp` aliases invoke it without `--persist`,
so they remain runtime-only and never modify `startup.conf`.

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

## Auto-open on disconnect

The popup opens automatically whenever `mark_mume_disconnected()` transitions
the state from connected to disconnected (i.e. removes `bridge/session.state`).
All disconnect signals route through this single function:

- `Core.Goodbye` GMCP (graceful quit, both modes)
- `"Status: MUME closed the connection."` tt++ action (MMapper abrupt drop)
- `SESSION DISCONNECTED` → `clear_game_session()` → `mark_mume_disconnected()`
  (direct-mode abrupt drop and MMapper-process death)

**Dedup:** The transition guard in `mark_mume_disconnected()` returns early
when `session.state` is already absent, so a second signal for the same
disconnect event never reaches the popup trigger.

**Double-open guard:** `bridge/ingame_menu.sh` writes `bridge/.popup_open`
on start and removes it on exit (via the `EXIT INT TERM HUP` trap). The
trigger checks for this sentinel before calling `tmux display-popup` and
skips if present, so a popup already on screen is never disturbed.

**Bootstrap protection:** On fresh start `session.state` is absent, so
`mark_mume_disconnected()` is a no-op and no popup fires during the ~0.5–2 s
window before `Char.Name` arrives.

**Reconnect pre-highlighted:** `_rebuild_menu` places Reconnect at index 0
when `session.state` is absent and `_SEL=0` is the default, so the user
can hit Enter immediately.

**Stale sentinel cleanup:** `bridge/tmux_start.sh` removes `bridge/.popup_open`
at the top of each run, guarding against a crashed popup from a previous
cockpit session leaving the sentinel behind.

## Scope trims

Deliberately NOT in the popup:
- **About** — not enough value to justify the code.
- **Reload** — `cp -r` from the input pane is the intended path.
- **Profile switch / connection mode** — launcher-only; requires restart.
- **Layout mockup** — saves vertical space in the popup.

---
Back to [architecture.md](../architecture.md).
