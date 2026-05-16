# MUME Cockpit

A fast, terminal-based MUD client built for [MUME](https://mume.org)
and tuned for fast PvP. TinTin++ owns the socket, triggers, and keybinds
at the latency floor; a Lua brain runs above it for state, timers, and
anything that benefits from a real programming language; tmux composes
the game pane, an input pane, and up to six side panes into one window.

<!-- Screenshot goes here. Good candidates: the launcher About page,
     the full cockpit with the status / buffs / group / comm / ui
     panes visible, or the in-game ESC popup with the Statistics
     frame open. -->

<img width="494" height="309" alt="Screenshot 2026-05-16 020038" src="https://github.com/user-attachments/assets/7f100007-b3d9-44fc-8d7e-dfff595f7c13" />
<img width="494" height="309" alt="Screenshot 2026-05-16 015941" src="https://github.com/user-attachments/assets/8f7496e5-8b0e-481a-92ac-aea909fc2db9" />
<img width="494" height="309" alt="Screenshot 2026-05-16 010540" src="https://github.com/user-attachments/assets/19486c51-a9d1-4acf-86b9-27286eb5a0e4" />
<img width="494" height="309" alt="Screenshot 2026-05-16 010400" src="https://github.com/user-attachments/assets/deedfef8-f77a-45bc-96cb-d42c74488aaf" />

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

**GMCP** — full integration. Char, Comm.Channel, Event, Core, and Group
modules are negotiated at handshake and dispatched to Lua handlers.
Background collectors populate `state.char`, `state.comm`, `state.world`,
`state.run`, and `state.group` as messages arrive.

**Panes** — six right-column panes, each toggleable at runtime:

- **Character** — vitals, position, mood, alertness, in-game time,
  session XP/TP deltas with an XP-progress ruler that tracks the
  current level.
- **Buffs** — colour-coded grid of active spells, buffs, debuffs,
  and stored spells. Per-character observed durations are learned
  over time; expiring entries blink.
- **Group** — group member vitals with bar fills, threshold colours,
  and an overflow indicator when the party doesn't fit.
- **Communication** — clickable channel filters with per-channel
  colouring; right-click solos a channel. History survives reloads
  and reconnects.
- **UI** — structured status messages from scripts and core systems
  (kills, warnings, lifecycle events).
- **Developer** — live tail of `debug.log`.

Plus a dedicated **input pane** on its own line at the bottom —
repeat-last-on-empty-Enter, full-buffer select with one keystroke,
no auto-clear after send, mouse-click anywhere returns focus.

**Runs and statistics** — Every login starts a run. The cockpit
writes a per-run JSONL event stream (`run_start`, `kill`, `pkill`,
`xp_loss`, `level_up`, `achievement`, `group_changed`, `run_end`)
plus a raw microsecond-timestamped `.log` capture of all server
output. The in-game **Statistics** frame and the launcher's
**History** browser aggregate this into kills/PvPs (sortable),
allies, achievements, XP/h + TP/h sparklines, and an XP-linjal
showing the level span. A built-in **log player** replays archived
sessions with play / pause, scrubber, click-to-jump, and a cursor
in pause mode. Saved runs survive a 14-day retention sweep;
everything else is pruned automatically.

**In-game ESC popup** — Press ESC anywhere in the cockpit for a
fast overlay: Continue / Reconnect, Save run with a 0–5 star
rating, Statistics on the active run, Options (pane visibility,
pane background colour, scripts), and Exit. Auto-opens on
disconnect.

**Scripting** — Drop a self-contained `.lua` file in `lua/scripts/`,
call `register_script()`, and the cockpit auto-loads it at startup,
registers its commands, and lists it in `cp` help and on the
launcher Scripts page. Remove the file and the feature is gone —
no leftover state. Always-on GMCP collectors live in `lua/core/`;
per-profile triggers, aliases, macros, and highlights live in
`.tin` files under `ttpp/profiles/`.

**Launcher** — pre-tmux startup menu with profile picker
(create / copy / delete), per-pane options including background
colour, connection mode (MMapper / Direct / Custom), a History
browser for archived sessions, and a self-update flow that tracks
GitHub release tags.

**MMapper** integration via WSL2 mirrored networking on Windows,
or plain `localhost` on macOS / Linux. [MMapper][mmapper] is a
separate graphical companion app — install it and the cockpit
routes through it.

## Documentation

- [`architecture.md`](architecture.md) — stack, project structure,
  registration functions, design principles, current work.
- [`docs/`](docs/) — per-area references (GMCP, IPC, launcher, popup
  menu, session lifecycle, panes, clock, affects, runs, and more).
- [`docs/decisions/`](docs/decisions/) — ADRs for non-obvious design
  calls.
- [`install/README.md`](install/README.md) — install and troubleshooting
  for all three platforms.

## Status

Early but stable. The cockpit is in active development for a single
player's daily use. See "Current Work" in
[`architecture.md`](architecture.md).

Bug reports and feature requests welcome on
[GitHub Issues](https://github.com/Khazdul/mumecockpit/issues).

## Related

- [MUME](https://mume.org) — the game. Free, no subscription.
- [MMapper][mmapper] — graphical mapping companion for MUME.

## License

See [`LICENSE`](LICENSE).

[releases]: https://github.com/Khazdul/mumecockpit/releases
[mmapper]: https://github.com/MUME/MMapper/releases
