# MUME Cockpit

A fast, terminal-based MUD client built for [MUME](https://mume.org)
and tuned for fast PvP. TinTin++ owns the socket, triggers, and keybinds
at the latency floor; a Lua brain runs above it for state, timers, and
anything that benefits from a real programming language; tmux composes
the game pane, an input pane, and up to six side panes into one window.

<!-- HERO IMAGE: full cockpit, multiple right-column panes visible.
     Add as: <p align="center"><img src="..." alt="..." width="..."></p> -->
<img width="384" height="216" alt="20260611 startup" src="https://github.com/user-attachments/assets/0563756c-0265-4213-b1be-52840a6fee43" />
<img width="384" height="216" alt="20260611 gameplay with mmapper" src="https://github.com/user-attachments/assets/911bb23b-300f-4f08-8666-9c765b8893bb" />
<img width="384" height="216" alt="20260611 profile lite" src="https://github.com/user-attachments/assets/8dedeebe-8b76-4499-8ce6-33c131de3d78" />
<img width="384" height="216" alt="20260611 panes" src="https://github.com/user-attachments/assets/65f29300-b2a4-4317-809d-31d9b40423f0" />
<img width="384" height="216" alt="20260611 timers" src="https://github.com/user-attachments/assets/657f8603-f974-45aa-925e-712601e4176d" />
<img width="384" height="216" alt="20260611 coms" src="https://github.com/user-attachments/assets/9cced84f-c76e-4d78-a6e6-175f56c420f6" />
<img width="384" height="216" alt="20260611 readability2" src="https://github.com/user-attachments/assets/c32cac98-6b3c-434a-ae15-1710666455b5" />
<img width="384" height="216" alt="20260611 scripts_keymanager" src="https://github.com/user-attachments/assets/021da6bc-b1a0-401e-8d87-27a3bff6542f" />
<img width="384" height="216" alt="20260611 History" src="https://github.com/user-attachments/assets/c6be14a2-33ea-4fe7-86db-a513084299f4" />
<img width="384" height="216" alt="20260611 spotlights" src="https://github.com/user-attachments/assets/a6228912-ce98-4cab-ab2a-da3ff3c723e6" />

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
- **Timers** — colour-coded grid of active spells, buffs, debuffs,
  and stored spells. Per-character observed durations are learned
  over time; expiring entries blink.
- **Group** — vitals for group members and labelled NPCs (e.g. hired
  mercenaries) with bar fills, threshold colours, and an overflow
  indicator when the party doesn't fit.
- **Communication** — clickable channel filters with per-channel
  colouring; right-click solos a channel. History survives reloads
  and reconnects.
- **UI** — structured status messages from scripts and core systems
  (kills, warnings, lifecycle events).
- **Developer** — live tail of `debug.log`.

Plus a dedicated **input pane** on its own line at the bottom —
repeat-last-on-empty-Enter, full-buffer select with one keystroke,
no auto-clear after send, mouse-click anywhere returns focus.

<!-- IMAGE: in-game Statistics frame or the log player with scrubber -->

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

<!-- IMAGE: the ESC popup overlay -->

**In-game ESC popup** — Press ESC anywhere in the cockpit for a
fast overlay: Continue / Reconnect, Save run with a 0–5 star
rating, Statistics on the active run, Options (pane visibility,
pane background colour, scripts), and Exit. Auto-opens on
disconnect.

**Scripting** — Drop a self-contained `.lua` file in `lua/scripts/`,
declare its metadata in an `@`-tagged header at the top of the file,
and the cockpit picks it up at startup: parses the header without
running the file, lists it on the launcher's Scripts page (enabled
or disabled), and — if enabled in `scripts.conf` — registers its
commands and lists it in `cp` help. Remove the file and the feature
is gone — no leftover state. Always-on GMCP collectors live in
`lua/core/`; per-profile triggers, aliases, macros, and highlights
live in `.tin` files under `ttpp/profiles/`.

<!-- IMAGE: launcher main menu or the Panes colour grid -->

**Launcher** — pre-tmux startup menu with profile picker
(create / copy / delete), per-pane options including background
colour, connection mode (MMapper / Direct / Custom), a History
browser for archived sessions, a Spotlights reel that replays
highlights — kills, deaths, level-ups, achievements — across every
character, and a self-update flow that tracks GitHub release tags.

<!-- IMAGE: profile editor in Editor mode, syntax highlighting visible -->

**Profile editor** — a two-mode editor for tt++ profiles, reached from the
launcher's Profile page. *Lite mode* is a form-based GUI for aliases,
actions, macros, highlights, and substitutes, with per-kind detail widgets,
a colour-palette picker for highlights, and key-capture for macros.
*Editor mode* is a full plain-text view of the serialised profile with
tt++ syntax highlighting, brace auto-close and matching, undo/redo,
word/line selection, and an in-app clipboard. Both modes edit the same
profile; round-trip preserves unknown tt++ commands and entry priorities
verbatim.

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
