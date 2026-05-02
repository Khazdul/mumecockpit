# MUME Cockpit

A fast, terminal-based MUD client built for [MUME](https://mume.org)
and tuned for fast PvP. TinTin++ owns the socket, triggers, and keybinds
at the latency floor; a Lua brain runs above it for state, timers, and
anything that benefits from a real programming language; tmux composes
game, input, character, comm, and UI panes into one window.

<!-- Screenshot goes here once available. Good candidates: the launcher
     About page, or the four-pane game window with status + comm + ui
     visible. -->

## Install

### Windows 11 22H2+

Download the installer zip from the [Releases page][releases], extract,
and double-click `cockpit-installer.bat`. Roughly 5 minutes on a fresh
machine. WSL2 must already be enabled — if it isn't, run `wsl --install`
in an admin PowerShell, reboot, and re-run the installer.

### macOS

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-macos.sh | bash
```

Requires [Homebrew](https://brew.sh).

### Linux (Debian / Ubuntu)

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-linux.sh | bash
```

Full requirements, troubleshooting, and steps for other distros in
[`install/README.md`](install/README.md).

## What's in the box

**GMCP** — full integration. Char, Comm.Channel, Event, and Core modules
are negotiated at handshake and dispatched into Lua handlers. Background
collectors populate `state.char`, `state.comm`, and `state.session` as
messages arrive.

**Panes** — toggleable at runtime:

- **Character panel** — vitals, position, mood, alertness, affects with
  observed durations learned per character, in-game time, session XP/TP
  deltas.
- **Communication pane** — clickable channel filters, 7-day per-profile
  history that survives reloads and reconnects.
- **UI pane** — structured status messages from scripts and core
  systems (kills, warnings, lifecycle events).
- **Dedicated input pane** on its own line — repeat-last-on-empty-Enter,
  full-buffer select with one keystroke, no auto-clear after send.

**Scripting** — drop a self-contained `.lua` file in `lua/scripts/`,
call `register_script()`, and the cockpit auto-loads it at startup,
registers its commands, and lists it in `cp` help and on the launcher
Scripts page. Remove the file and the feature is gone — no leftover
state. Per-profile triggers, aliases, macros, and highlights live in
`.tin` files under `ttpp/sessions/`.

**Launcher** — pre-tmux startup menu with profile picker, options, and
a self-update flow. ESC opens the same menu in-game without leaving
the prompt.

**MMapper** integration via WSL2 mirrored networking on Windows, or
plain `localhost` on macOS / Linux. [MMapper][mmapper] is a separate
graphical companion app — install it and the cockpit routes through it.

## Documentation

- [`architecture.md`](architecture.md) — stack, project structure,
  registration functions, design principles, current work.
- [`docs/`](docs/) — per-area references (GMCP, IPC, launcher, popup
  menu, session lifecycle, panes, clock, affects, and more).
- [`docs/decisions/`](docs/decisions/) — ADRs for non-obvious design
  calls.
- [`install/README.md`](install/README.md) — install and troubleshooting
  for all three platforms.

## Status

Early but stable. The cockpit is in active development for a single
player's daily use. Upcoming: session progress tracker, gameplay layout
presets, and a Getting Started page in the launcher. PvP keybind defaults
are still pending.
See "Current Work" in [`architecture.md`](architecture.md).

Bug reports and feature requests welcome on
[GitHub Issues](https://github.com/Khazdul/mumecockpit/issues).

## Related

- [MUME](https://mume.org) — the game. Free, no subscription.
- [MMapper][mmapper] — graphical mapping companion for MUME.

## License

See [`LICENSE`](LICENSE).

[releases]: https://github.com/Khazdul/mumecockpit/releases
[mmapper]: https://github.com/MUME/MMapper/releases