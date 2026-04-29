# MUME Cockpit v0.5.0

First public release. A fast, terminal-based MUD client built for MUME
and tuned for fast PvP.

> _Drop screenshots / asciinema link here — launcher About page, the
> four-pane game window, and the in-game ESC popup are the three that
> sell it fastest._

## What it is

TinTin++ owns the socket, triggers, and keybinds at the latency floor.
A Lua brain runs above it for state, timers, and anything that benefits
from a real programming language. tmux composes game, input, character,
comm, and UI panes into one window. Starts in under a second, with
opt-in updates from the launcher, and behaves the same on every machine.

## What's in the release

### Connection
- MMapper integration via WSL2 mirrored networking on Windows, or
  `localhost` on macOS / Linux. MMapper is a separate application —
  install it from https://github.com/MUME/MMapper/releases.
- Direct mode (`mume.org:4242`) for a quick start without MMapper.
  Switchable from the launcher per profile.

### GMCP
Char, Comm.Channel, Event, and Core modules negotiated at handshake
and dispatched into Lua handlers. Background collectors populate
`state.char`, `state.comm`, and `state.session` as messages arrive —
vitals, kills, channel traffic, alertness, sneak, climb, swim, position.

### Panes
- **Character panel** — live vitals, position, mood, alertness, affects
  with observed durations learned per character, in-game time,
  session XP/TP deltas.
- **Communication pane** — clickable channel filters with solo mode,
  7-day per-profile history, survives `cp -r` reloads and reconnects.
- **UI pane** — structured status messages from scripts and core
  systems (kills, warnings, lifecycle events).
- **Dedicated input pane** on its own line — repeat-last-on-empty-Enter,
  full-buffer select, no auto-clear after send.

### Scripting
- Drop-in `.lua` files in `lua/scripts/` — call `register_script()`,
  the file auto-loads at startup, registers its own commands, shows
  up in `cp` help and on the launcher Scripts page. Remove the file
  and the feature is gone — no leftover state.
- Per-profile `.tin` files in `ttpp/sessions/` for triggers, aliases,
  macros, and highlights.

### Launcher and self-update
- Pre-tmux startup menu with profile picker, options, scripts list,
  About page, and an Update row when a newer release is published.
- In-game ESC popup mirrors the launcher options without leaving the
  game prompt.

## Install

### Windows 11 22H2+
Download `mumecockpit-installer.zip` below, extract, double-click
`cockpit-installer.bat`. Roughly 5 minutes on a fresh machine. WSL2
must already be enabled (`wsl --install` from an admin PowerShell if
not). Full troubleshooting in [`install/README.md`](install/README.md).

### macOS
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-macos.sh | bash
Requires Homebrew (https://brew.sh).

### Linux (Debian / Ubuntu)
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-linux.sh | bash
Other distros: package list and manual steps in [`install/README.md`](install/README.md).

## Requirements

- Windows 11 22H2 (build 22621) or newer for the installer; earlier
  Windows is not supported. (See ADR 0015 in
  [`docs/decisions/`](docs/decisions/) for rationale.)
- tmux 3.2 or newer on Linux. Ubuntu 22.04 ships 3.2a; 24.04 ships 3.4.
- bash 4+ (Homebrew bash on macOS — installed by the bootstrap).

## Known gaps

A few things are still on the way and tracked under "Current Work" in
[`architecture.md`](architecture.md):

- GMCP disconnect flow with mode-aware reconnect popup
- Spell timer system
- Tells history UI
- PvP keybind defaults

## Links

- Project page — https://github.com/Khazdul/mumecockpit
- MUME — https://mume.org
- MMapper — https://github.com/MUME/MMapper/releases
- License — see `LICENSE` in the repository root