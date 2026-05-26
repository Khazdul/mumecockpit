# Install & Bootstrap

Cross-platform installation of the MUME cockpit. Windows is the primary
target — the only platform with current or prospective users who cannot be
expected to drive a terminal manually. macOS and Linux are documented for
completeness and to keep the install story honest.

End-user instructions live in `install/README.md`. This document is the
contributor-facing plan and rationale.

## Scope

**Windows support is limited to Windows 11 22H2 (build 22621) or newer.**
This is a deliberate floor, not a placeholder — the cockpit's MMapper
integration requires WSL2 mirrored networking, which is only available on
22H2+. See [ADR 0015](decisions/0015-windows-installer-scope.md) for the
full rationale and alternatives considered.

**In scope**

- Getting a fresh Windows machine from "nothing installed" to "click the
  MUME Cockpit entry in the Start Menu and the cockpit launches".
- Installing, on the Windows side: WSL2 + Ubuntu and `%UserProfile%\.wslconfig`.
- Installing, inside WSL: tmux, lua5.4, python3 + prompt_toolkit, git, tt++,
  the cockpit repo, the foot terminal, monospace fonts, `foot.ini`, an
  `/etc/wsl.conf` that pins the default user to root, and the WSLg
  `.desktop` entry (system-wide, with a system-theme icon) that surfaces
  the cockpit on the Windows Start Menu.
- Lightweight bootstrap scripts for macOS (Homebrew) and Linux (apt).

See [ADR 0104](decisions/0104-windows-deployment-architecture.md) for the
foot/WSLg deployment shape and [ADR 0103](decisions/0103-windows-terminal-decision.md)
for the flicker investigation that drove the move off Windows-Alacritty.

**Out of scope**

- Installing MMapper itself. MMapper is a separate Windows application with
  its own installer, map-file setup, and MUME routing config. The cockpit
  installer will *detect* MMapper (see Open questions) and default
  `connection_mode` accordingly, but it will not install or configure
  MMapper.
- Auto-upgrading Windows. The 22H2 floor is a hard prerequisite,
  documented below.
- Unattended installs in corporate-locked environments.

On macOS and Linux the installer provisions backend dependencies only (tmux,
lua, tt++, python3-prompt-toolkit, git) and clones the repo. It does **not**
install or configure the terminal emulator — users run the cockpit from
whatever terminal they already prefer. The bundled-terminal model (foot under
WSLg) is Windows-specific, motivated by the lack of a sensible default
WSL-aware terminal on that platform and by the flicker behaviour of
Windows-Alacritty driving a tmux-heavy UI — see
[ADR 0103](decisions/0103-windows-terminal-decision.md).

## Target platforms

| OS                             | Target                                                        | Priority |
|--------------------------------|---------------------------------------------------------------|----------|
| Windows 11 (22H2+)             | Primary                                                       | 1        |
| macOS (Apple Silicon or Intel) | Supported                                                     | 2        |
| Linux, Debian/Ubuntu family    | Supported                                                     | 2        |
| Linux, other distros           | Manual install; documented only                               | 3        |

Windows older than build 22621 is not supported. See the Scope section above.

## Windows flow

Implemented in `install/cockpit-installer.bat` + `install/installer-core.ps1`.

Requires WSL2 to already be enabled (`VirtualMachinePlatform` and
`Microsoft-Windows-Subsystem-Linux` features active). If either is disabled,
the installer exits with instructions to run `wsl --install` in an admin
PowerShell, reboot, then re-run.

Fully unattended beyond the initial UAC prompt:

1. Pre-flight: Windows build ≥ 22621, admin rights, WSL features enabled,
   internet reachable.
2. `wsl --install -d Ubuntu --no-launch` — installs Ubuntu silently, does
   **not** trigger the first-run OOBE dialog. Existing `Ubuntu` or `Ubuntu*`
   installs are detected and reused.
3. Write `%UserProfile%\.wslconfig` with `networkingMode=mirrored`. Existing
   `.wslconfig` files are never overwritten — the user is told to add the
   line manually if their file lacks it.
4. `wsl --shutdown` so the `.wslconfig` change takes effect (skipped if the
   file was already correct).
5. `wsl -d Ubuntu -u root -- bash -c "curl … bootstrap-linux.sh | bash"` —
   runs the Linux bootstrap as root. Running as root inside WSL is fine
   here: the cockpit has no multi-user logic and no sudo paths. The OOBE
   user-creation dialog is never triggered. The bootstrap detects WSL and
   additionally:
     - writes `/etc/wsl.conf` with `[user] default=root`, merging into any
       existing file. WSLg runs the `.desktop` Exec as whatever WSL
       considers the default user — on a pre-existing Ubuntu distro that
       can be a normal account, which cannot traverse `/root/`. Forcing
       `default=root` is what keeps the Start Menu launch working on a
       reused Ubuntu install. See
       [ADR 0106](decisions/0106-windows-installer-hardening.md) for the
       full rationale,
     - installs the `foot` terminal and a small set of monospace fonts
       (`fonts-dejavu`, `fonts-cascadia-code`, `fonts-jetbrains-mono`,
       `fonts-hack`) inside WSL; missing apt names degrade gracefully,
     - copies `install/examples/foot.ini` to `~/.config/foot/foot.ini`,
     - copies `install/assets/mume-cockpit-48.png` to
       `/usr/share/icons/hicolor/48x48/apps/mume-cockpit.png` and
       `install/assets/mume-cockpit.svg` to
       `/usr/share/icons/hicolor/scalable/apps/mume-cockpit.svg` (and
       refreshes the icon cache when `gtk-update-icon-cache` is present).
       Mirrors how the `foot` package ships its own (working) icon —
       WSLg's icon resolver finds 48x48 and scalable; 256x256 it does not,
     - copies `install/mume-cockpit.desktop` to
       `/usr/share/applications/mume-cockpit.desktop` — WSLg surfaces
       `.desktop` files from `/usr/share/applications/` to the Windows
       Start Menu reliably (per-user `~/.local/share/applications/` is
       not reliable across WSLg versions). The `.desktop`'s `Icon=` is
       the bare theme name `mume-cockpit`, resolved by freedesktop icon
       lookup against the system hicolor theme,
     - provisions `~/MUME/bin/win32yank.exe` for the input pane's fast
       clipboard read — see the Linux flow below.
6. `wsl --shutdown` — required so the bootstrap's `/etc/wsl.conf` change
   (default user → root) takes effect before the first Start Menu launch.
   Unconditional; safe on a brand-new distro as well.
7. Verify both `/root/MUME/bridge/supervisor.sh` and `/root/MUME/start.sh`
   are executable. Abort with a clear error if either is missing — better
   to fail loudly here than leave a broken Start Menu entry.

The Start Menu entry's `Exec=` line points at
`/root/MUME/bridge/supervisor.sh`. The supervisor:

- exports `MUME_TERMINAL=foot-managed` (Phase 2/3 read this to detect a
  managed terminal),
- clears any stale `bridge/runtime/.relaunch_terminal` sentinel,
- launches `foot -- bash /root/MUME/start.sh` and loops on the sentinel
  so a later phase can ask for a clean foot relaunch (e.g. font change)
  without exiting the cockpit. In Phase 1 nothing writes the sentinel, so
  the loop body runs exactly once.

The install itself requires no reboot, but a Windows restart is
**recommended before first launch** so the WSL graphics subsystem starts
cleanly — see the Pitfalls entry on blank first launches. No manual
first-run. No Alacritty install, no `alacritty.toml` written on Windows,
no Windows desktop shortcut. The user sees UAC once, a progress
indicator, then "done" with a restart recommendation, and finds
**MUME Cockpit** in the Windows Start Menu.

### Delivery form

User-facing entry point: `cockpit-installer.bat` (double-click to run).
Internal PowerShell script: `installer-core.ps1` (invoked by the `.bat`
after UAC elevation; not meant to be run directly). The Linux bootstrap
is fetched via curl from the repo and piped into `wsl ... -u root bash`.
Unsigned; SmartScreen may warn on first run — documented workaround:
right-click `installer-core.ps1`, Properties, Unblock, then run via
`cockpit-installer.bat`.

## macOS flow

Run `install/bootstrap-macos.sh` for the automated path. The script
installs backend dependencies (bash, tmux, lua, tintin, git, python3) via
Homebrew and prompt_toolkit via pip, then clones the repo to `~/MUME`.
**Homebrew must already be installed** — if it isn't, the script exits
with instructions pointing to https://brew.sh. No terminal emulator is
installed; run the cockpit from whichever terminal you already use.

**The cockpit requires bash 4+.** macOS ships `/bin/bash` 3.2 (Apple
avoids the GPLv3-licensed bash 4+). The bootstrap installs Homebrew bash 5
and the cockpit's `#!/usr/bin/env bash` shebangs pick it up via PATH
(`/opt/homebrew/bin` comes first on a brew-default Mac). See
[ADR 0020](decisions/0020-platform-support-policy.md) for the full
platform-support policy.

No networking tricks required — `localhost` works out of the box.

## Linux flow

**The cockpit requires tmux 3.2 or newer.** `display-popup -E` (used for the
in-game ESC popup) and the `pane-mode-changed` hook (used for
refocus-on-copy-mode-exit) both require 3.2+. Ubuntu 22.04 ships 3.2a; Ubuntu
24.04 ships 3.4; macOS Homebrew currently ships 3.5+. All current bootstrap
targets satisfy this floor.

Debian/Ubuntu family — automated via `bootstrap-linux.sh`:

1. `apt-get install -y tmux lua5.4 python3 python3-prompt-toolkit python3-pyperclip git`
2. **Probe-or-build tt++.** The script checks the installed `tt++` (if any)
   for version ≥ 2.02.20 and GnuTLS linkage. If either check fails (or no
   binary exists), it installs build deps and compiles tag 2.02.61 from
   source, landing the binary at `/usr/local/bin/tt++`. Re-running the
   bootstrap on an already-provisioned machine takes the "looks good —
   keeping it" path with no rebuild. See [ADR 0035](decisions/0035-tt-from-source.md).
3. Clone or update the repo to `~/MUME`.
4. **WSL only — provision `win32yank.exe`.** When `/proc/version` contains
   `microsoft`, the bootstrap downloads the pinned `v0.1.1` release of
   [equalsraf/win32yank](https://github.com/equalsraf/win32yank), extracts
   it with `python3 -m zipfile`, and lands the binary at
   `~/MUME/bin/win32yank.exe` (chmod +x). The input pane uses it as the
   fast clipboard-read path on WSL; without it, paste falls back to
   pyperclip (~100–300 ms cold). Skipped if the binary is already present
   (idempotent). Download failure is non-fatal — the bootstrap still
   succeeds and the input pane works via the fallback. Native Linux skips
   this step entirely; no `bin/` directory is created. See
   [docs/input-pane.md](input-pane.md) for the clipboard chain.

The source-build step adds ~1–2 minutes on first install. The build deps
(`build-essential`, `libpcre2-dev`, `libgnutls28-dev`, `zlib1g-dev`,
`pkg-config`) are only installed when a build is needed.

Other distros (Fedora, Arch, …) get a documented manual recipe; automating all
package managers is not a good use of time given the user base.

## Config files

### `.wslconfig` (Windows, `%UserProfile%\.wslconfig`)

```ini
[wsl2]
networkingMode=mirrored
```

Required on Windows for MMapper (running natively on the Windows side,
listening on `localhost:4242`) to be reachable from tt++ inside WSL.
`networkingMode=mirrored` requires **Windows 11 22H2 or newer**. Takes
effect only after `wsl --shutdown`.

### `foot.ini` (Windows/WSL, `~/.config/foot/foot.ini`)

The canonical foot config for the Windows/WSLg deployment, shipped at
`install/examples/foot.ini` and copied verbatim by `bootstrap-linux.sh`
into `~/.config/foot/foot.ini` when it detects WSL. Native Linux and
macOS do not use foot — the file is unread there.

Key fields:

- `initial-window-mode=fullscreen` — **required**. The supervisor relies
  on foot opening fullscreen; the cockpit assumes the tmux layout owns
  the entire terminal. There is no CLI flag for this; it must live in
  the config.
- `font=DejaVu Sans Mono:size=15` — the **managed font= line**. A later
  phase (the Terminal Settings UI) rewrites this single line for font
  and size changes. Keep it on its own line, matchable with `^font=`.
- `pad=0x0` — no padding; the cockpit paints its own borders.
- `selection-target=clipboard` — selecting text writes the system
  clipboard, in line with the cockpit's Alacritty preset.
- `[scrollback] lines=10000` — matches Alacritty's `history = 10000`.
- `[cursor] style=beam blink=yes` — matches the Alacritty beam-blink cursor.
- `[key-bindings] fullscreen=Control+Shift+f` — harmless escape hatch.
  The cockpit itself never invokes this binding; it leaves the user a
  way out of fullscreen if they ever want one.
- `[colors]` — the DOS palette, byte-for-byte mirror of
  `install/examples/alacritty.toml`. Foot under WSLg renders the cockpit
  with the same colours as Alacritty on macOS/Linux. (foot has no
  light/dark colour split; the section is just `[colors]`, not
  `[colors-dark]`.)

### `alacritty.toml`

`alacritty.toml` is **example-only**, shipped at
`install/examples/alacritty.toml` for macOS and Linux users who want to run
the cockpit under Alacritty. It is **not** written by any installer — neither
the Windows installer (which uses foot under WSLg, see below) nor the
macOS/Linux bootstraps. Users who want the cockpit's canonical Alacritty
look copy it themselves to:

- macOS:   `~/.config/alacritty/alacritty.toml`
- Linux:   `~/.config/alacritty/alacritty.toml`

Shared across both platforms except for `[font.*].family` (per-OS font
choice, see the Alacritty entry in "Font selection" below). The historical
`[terminal.shell]` block aimed at Windows is no longer needed.

```toml
[colors.primary]
foreground = "#C0C0C0"
background = "#000000"

[colors.normal]
black   = "#000000"
red     = "#800000"
green   = "#008000"
yellow  = "#808000"
blue    = "#000080"
magenta = "#800080"
cyan    = "#008080"
white   = "#C0C0C0"

[colors.bright]
black   = "#808080"
red     = "#FF0000"
green   = "#00FF00"
yellow  = "#FFFF00"
blue    = "#0000FF"
magenta = "#FF00FF"
cyan    = "#00FFFF"
white   = "#FFFFFF"

[cursor]
style = { shape = "Beam", blinking = "Always" }
blink_interval = 500
thickness = 0.15

[window]
dimensions = { columns = 80, lines = 24 }
startup_mode = "Windowed"
padding = { x = 0, y = 0 }
dynamic_padding = true
decorations = "Full"
decorations_theme_variant = "Dark"

[font]
size = 15

# font.*.family — see "Font selection" below.

[font.normal]
style = "Regular"

[font.bold]
style = "Bold"

[font.italic]
style = "Italic"

[font.bold_italic]
style = "Bold Italic"

[scrolling]
history = 10000

[selection]
save_to_clipboard = true
```

### Font selection

#### Windows (foot under WSLg)

The Windows installer drops a fixed `foot.ini` and provisions a small set
of monospace fonts inside WSL so the Terminal Settings UI (Phase 2+) has
real options to pick from. The whole story is built around one **managed
`font=` line** in `foot.ini` — a later phase rewrites that single line in
response to user font/size choices.

- **Default family.** `DejaVu Sans Mono`. Ubuntu's default monospace,
  present on every fresh `fonts-dejavu` install. Narrow, open, no
  ligatures — same visual register as Lucida Console / Menlo. This is
  the hard requirement.
- **Provisioned alternatives.** `bootstrap-linux.sh` (WSL branch) also
  installs `fonts-cascadia-code`, `fonts-jetbrains-mono`, and
  `fonts-hack`. Any package name that doesn't resolve on the host
  prints a warning and is skipped — the install does **not** fail. The
  user gets whichever subset their Ubuntu version ships.
- **Default size.** `15`, matching the macOS/Linux Alacritty preset.

Users who want to change family or size today can edit the `font=` line
in `~/.config/foot/foot.ini` and the change takes effect on the next
`foot` launch. The Terminal Settings UI (Phase 2/3) wraps that edit in
a proper picker.

No font is installed on the Windows side; the entire font story lives
inside WSL.

#### macOS and Linux (Alacritty example)

Lucida Console was historically the canonical look — narrow, open, no
ligatures — but Microsoft's licensing does not permit us to bundle it,
and Alacritty does not support a CSS-style fallback chain inside a
single `family` string. The example `alacritty.toml` therefore uses a
per-OS family that ships with the platform:

| Platform | Family              | Rationale                                                    |
|----------|---------------------|--------------------------------------------------------------|
| macOS    | `Menlo`             | System default monospace. Narrow, open, similar proportions. |
| Linux    | `DejaVu Sans Mono`  | Ubuntu/Debian default. Present on nearly all Linux desktops. |

Both are narrow, non-ligature monospace fonts with similar proportions.
Users who don't like the default edit `alacritty.toml` themselves — the
macOS/Linux bootstraps do not write or own that file.

## Pitfalls

### Windows

- **SmartScreen will warn on unsigned PowerShell.** Real code-signing
  certs are expensive and probably overkill. Documented workaround:
  right-click the `.ps1`, Properties, Unblock, then run as admin. The
  `.bat` wrapper helps a little here but doesn't eliminate the warning.
- **Corporate-locked Windows.** Often prevents enabling WSL at all,
  or blocks arbitrary installer downloads. No workaround — documented
  as a known limitation.
- **VPN + mirrored networking.** Mirrored mode interacts poorly with
  some corporate VPN clients. If MMapper stops reaching MUME, the
  user can fall back to `networkingMode=nat` + direct mode. Worth
  calling out in the user-facing README.
- **MMapper stays a manual install.** The installer cannot handle
  MMapper's map download or MUME routing config. The existing launcher
  already lets the user switch between MMapper and direct mode, which
  covers this cleanly.
- **tt++ apt version is stale and lacks TLS.** Handled: the bootstrap
  probes the installed binary for version ≥ 2.02.20 and GnuTLS linkage,
  then builds from source (tag 2.02.61) when either check fails. See
  [ADR 0035](decisions/0035-tt-from-source.md).
- **`pip install --break-system-packages`.** Required on Ubuntu 23.04+
  (PEP 668). Harmless on older releases; the flag can stay unconditional.
- **Running as root inside WSL.** Fine for the cockpit (no sudo paths,
  no multi-user logic) but surprising to some users. The `.desktop`
  entry installed by the bootstrap points at
  `/root/MUME/bridge/supervisor.sh`, so the root user is implicit;
  there is no `-u root` flag visible to the user. Documented in the
  README.
- **WSLg cursor-offset bug.** foot under WSLg can render the text
  cursor a few pixels off from where the terminal thinks it is
  (microsoft/wslg #1290, #935). Cosmetic only — input still goes to
  the right place. There is no workaround on our side; we ship with
  it and call it out so users do not file it as a cockpit bug.
- **WSLg Start Menu icon.** Some WSLg versions ignore the `.desktop`
  entry's `Icon=` and render a generic icon in the Windows Start Menu
  regardless. Cosmetic only — the launch itself works. The deployment
  ships the correct config (`Icon=mume-cockpit` themed name + PNG
  under `/usr/share/icons/hicolor/48x48/apps/` and SVG under
  `/usr/share/icons/hicolor/scalable/apps/`); WSLg builds that
  handle icons at all will pick it up.
- **First-run latency.** Clicking **MUME Cockpit** for the first time
  after a fresh boot spins up the Ubuntu WSL distro before the
  supervisor can launch foot. On most machines this is a 2–5 second
  pause with no visual feedback (no splash, no progress indicator);
  subsequent launches are near-instant because the distro stays warm.
  Document this in the user README so the first click does not look
  like a hang.
- **Blank cockpit window on first launch after install.** On a freshly
  installed machine, the first WSLg GUI launch can come up with a blank
  window because the host-side WSLg compositor was left in an
  inconsistent state by the installer's WSL operations. A full Windows
  restart resolves it; `wsl --shutdown` alone is not enough because the
  bad state lives in the Windows host, not the distro. The installer
  recommends a restart before first launch for this reason. Surface it
  in the user-facing README as well.

### macOS

- **Homebrew assumed as prerequisite.** Document it; don't try to
  install brew from inside our script.
- **`tintin` brew formula** — verify it's a current release before
  relying on it.
- **prompt_toolkit comes via pip, not brew.** No brew formula tracks
  it cleanly. Homebrew Python normally permits user-site installs
  without `--break-system-packages`; the bootstrap script tries the
  clean install first and falls back automatically if pip refuses with
  the externally-managed-environment error.

### Linux

- **Distro sprawl.** We target the Debian/Ubuntu family with apt;
  everything else gets a documented recipe, not an automated path.
- **Wayland vs X11 for Alacritty.** Distro/DE-specific; Alacritty
  handles both. Not our problem.

### All platforms

- **Repo path hardcoded.** `~/MUME` (or `/root/MUME` on Windows/WSL-as-root)
  in the WSLg `.desktop` entry and bootstrap script. Custom paths are a v2
  problem — document as a constraint.
- **Collision with `bridge/release/update.sh`.** Self-update expects a clean
  git tree. If the installer ever gains a "repair" mode, it must not
  clobber local user changes. Cross-reference with
  `docs/bridge-services.md`.

## Open questions

1. **MMapper detection.** Detect MMapper's presence on the Windows
   host from WSL (probe `localhost:4242` during the bootstrap) and default
   `connection_mode` accordingly? Low effort, high user value.
2. **Retire `misc/`.** This doc absorbs `misc/WSL and Terminal
   settings`. Once the installer ships, delete the `misc/` directory
   to remove duplication.
3. **macOS probe-port.** Apply the same TLS-probe-then-source-build
   pattern to `bootstrap-macos.sh`. `brew`'s `tintin` formula is
   generally current, but TLS support is not guaranteed across upgrades.
   Approach mirrors the Linux fix: detect existing `tt++`, check for
   gnutls/openssl linkage via `otool -L "$(command -v tt++)"`, skip if
   present; otherwise build from source via brew's build-from-tap or a
   manual clone. Lower priority since macOS is Tier 2 — see
   [ADR 0020](decisions/0020-platform-support-policy.md).

## Rollout phases

1. **macOS + Linux bootstrap script.** Done.
2. **Windows installer** (`.ps1` + `.bat`, Ubuntu install, `.wslconfig`,
   foot/WSLg terminal, `.desktop` Start Menu entry, `foot.ini`,
   `bridge/supervisor.sh`). Done. Windows 11 22H2+ only; slow path is
   explicitly out of scope, not deferred — see
   [ADR 0015](decisions/0015-windows-installer-scope.md) for the scope
   floor, [ADR 0103](decisions/0103-windows-terminal-decision.md) for
   the flicker investigation that drove the move off Windows-Alacritty,
   [ADR 0104](decisions/0104-windows-deployment-architecture.md) for
   the foot/WSLg deployment shape, and
   [ADR 0106](decisions/0106-windows-installer-hardening.md) for the
   `/etc/wsl.conf` default-user pin and system-wide `.desktop`/icon
   placement added after end-to-end validation on Win11.
3. **Terminal Settings UI** (font and size picker that rewrites the
   managed `font=` line; `MUME_TERMINAL` detection; `.relaunch_terminal`
   sentinel honoured by `bridge/supervisor.sh`). In progress; the
   launcher submenu lands in Phase 2, the supervisor-driven relaunch in
   Phase 3. Doc updates to `docs/launcher.md` are batched and land with
   Phase 3, not now.
4. **MMapper auto-detection + default `connection_mode`.** Next polish item.

## See also

- `start.sh` — runtime entry point. Currently installs tmux and lua
  on demand; assumes the rest is present. Will remain the runtime
  entry point after the installer lands — installer is a separate,
  one-shot story.
- `docs/bridge-services.md` — `bridge/runtime/startup.conf` format,
  `update.sh` behaviour and exit codes.
- `docs/input-pane.md` — prompt_toolkit and cursor-blink caveats
  relevant to the terminal config choices above.
- [ADR 0015](decisions/0015-windows-installer-scope.md) — scope decision
  for the Windows installer: why 22H2+, what was considered and rejected.
- [ADR 0103](decisions/0103-windows-terminal-decision.md) — flicker
  investigation and the decision to ship foot under WSLg instead of
  Windows-Alacritty.
- [ADR 0104](decisions/0104-windows-deployment-architecture.md) — the
  foot/WSLg deployment shape: supervisor, `.desktop` entry, managed
  `foot.ini`, `MUME_TERMINAL` env var.
- [ADR 0106](decisions/0106-windows-installer-hardening.md) — corrections
  applied after end-to-end Win11 validation: `[user] default=root` in
  `/etc/wsl.conf` and system-wide `.desktop`/icon placement.
