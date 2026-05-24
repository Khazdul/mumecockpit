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

- Getting a fresh Windows machine from "nothing installed" to "double-click
  a shortcut and the cockpit launches".
- Installing: WSL2 + Ubuntu, Alacritty, tmux, lua5.4, python3 +
  prompt_toolkit, git, tt++, the cockpit repo.
- Writing the two Windows-specific config files required for MMapper mode
  (`.wslconfig`, `alacritty.toml`).
- A desktop shortcut / launcher that runs the cockpit.
- Lightweight bootstrap scripts for macOS (Homebrew) and Linux (apt).

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
whatever terminal they already prefer. Alacritty bundling is Windows-specific,
motivated by the lack of a sensible default WSL-aware terminal on that
platform.

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
2. `wsl --install -d Ubuntu --no-launch` — installs Ubuntu 24.04 silently,
   does **not** trigger the first-run OOBE dialog.
3. Write `%UserProfile%\.wslconfig` with `networkingMode=mirrored`.
4. `wsl --shutdown` so the `.wslconfig` change takes effect.
5. `wsl -d Ubuntu -u root -- bash -c "<bootstrap.sh contents>"` — runs
   the Linux bootstrap as root. Running as root inside WSL is fine here:
   the cockpit has no multi-user logic and no sudo paths. The OOBE
   user-creation dialog is never triggered. The bootstrap detects WSL
   and additionally provisions `~/MUME/bin/win32yank.exe` for the input
   pane's fast clipboard read — see the Linux flow below.
6. Install Alacritty (winget, MSI fallback) and write
   `%APPDATA%\alacritty\alacritty.toml`.
7. Create a desktop shortcut that runs:
   `alacritty.exe -e wsl -d Ubuntu -u root -- /root/MUME/bridge/launcher/launch.sh`.
   The launcher script handles the cd-and-exec on the Linux side; see
   [ADR 0028](decisions/0028-windows-shortcut-delegation.md) for rationale.
8. Verify `/root/MUME/bridge/launcher/launch.sh` and `/root/MUME/start.sh` are
   executable. Abort with a clear error if either is missing.

No reboot. No manual first-run. The user sees UAC once, a progress
indicator, then "done".

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

### `alacritty.toml`

On macOS and Linux, `alacritty.toml` is shipped as an example file at
`install/examples/alacritty.toml` and is **not** written by the installer.
Users who want the cockpit's canonical look can copy it to the path below.
Only the Windows installer writes the file directly — because there the user
typically has no existing Alacritty config.

Location:

- Windows: `%APPDATA%\alacritty\alacritty.toml`
- macOS:   `~/.config/alacritty/alacritty.toml`
- Linux:   `~/.config/alacritty/alacritty.toml`

Shared across all platforms except for two blocks: `[terminal.shell]`
(Windows only) and `[font.*].family` (per-OS font choice, see below).

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

[terminal.shell]   # Windows only — drop on macOS/Linux
program = "wsl.exe"

[scrolling]
history = 10000

[selection]
save_to_clipboard = true
```

### Font selection

Lucida Console is the canonical look — narrow, open, no ligatures,
pre-installed on every Windows since Windows 2000. On other platforms it
is absent, and Microsoft's licensing does not permit us to bundle or
redistribute it. Alacritty does not support a CSS-style fallback chain
inside a single `family` string: each weight takes one name, and if the
family is missing the OS substitutes its default monospace, which may be
something ugly.

The installer therefore writes a platform-specific `family` line:

| Platform | Family              | Rationale                                                    |
|----------|---------------------|--------------------------------------------------------------|
| Windows  | `Lucida Console`    | Preinstalled since Win 2000. Canonical look.                 |
| macOS    | `Menlo`             | System default monospace. Narrow, open, similar proportions. |
| Linux    | `DejaVu Sans Mono`  | Ubuntu/Debian default. Present on nearly all Linux desktops. |

All three are narrow, non-ligature monospace fonts with similar
proportions. Users never see a missing-font fallback; the file written at
install time already contains the correct family for their OS. No font is
bundled or installed by the installer.

If a user doesn't like the default they can edit `alacritty.toml`
afterwards — this is documented in the user-facing README, not owned by
the installer.

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
- **`winget` not available on policy-managed machines.** MSI fallback
  handles this case automatically.
- **tt++ apt version is stale and lacks TLS.** Handled: the bootstrap
  probes the installed binary for version ≥ 2.02.20 and GnuTLS linkage,
  then builds from source (tag 2.02.61) when either check fails. See
  [ADR 0035](decisions/0035-tt-from-source.md).
- **`pip install --break-system-packages`.** Required on Ubuntu 23.04+
  (PEP 668). Harmless on older releases; the flag can stay unconditional.
- **Running as root inside WSL.** Fine for the cockpit (no sudo paths,
  no multi-user logic) but surprising to some users. The desktop
  shortcut makes this explicit via `-u root` so it's visible, not
  hidden. Documented in the README.

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
  in the desktop shortcut and bootstrap script. Custom paths are a v2
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
   Alacritty, desktop shortcut). Done. Windows 11 22H2+ only; slow path
   is explicitly out of scope, not deferred — see
   [ADR 0015](decisions/0015-windows-installer-scope.md).
3. **MMapper auto-detection + default `connection_mode`.** Next polish item.

## See also

- `start.sh` — runtime entry point. Currently installs tmux and lua
  on demand; assumes the rest is present. Will remain the runtime
  entry point after the installer lands — installer is a separate,
  one-shot story.
- `docs/bridge-services.md` — `bridge/runtime/startup.conf` format,
  `update.sh` behaviour and exit codes.
- `docs/input-pane.md` — prompt_toolkit and cursor-blink caveats
  relevant to the Alacritty config choices above.
- [ADR 0015](decisions/0015-windows-installer-scope.md) — scope decision
  for the Windows installer: why 22H2+, what was considered and rejected.
