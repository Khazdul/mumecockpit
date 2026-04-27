# Install & Bootstrap

Cross-platform installation of the MUME cockpit. Windows is the primary
target — the only platform with current or prospective users who cannot be
expected to drive a terminal manually. macOS and Linux are documented for
completeness and to keep the install story honest.

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

Implemented in `install/install-windows.bat` + `install/install-windows.ps1`.

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
   user-creation dialog is never triggered.
6. Install Alacritty (winget, MSI fallback) and write
   `%APPDATA%\alacritty\alacritty.toml`.
7. Create a desktop shortcut that runs:
   `alacritty.exe -e wsl -d Ubuntu -u root -- bash -lc "cd /root/MUME && ./start.sh"`.

No reboot. No manual first-run. The user sees UAC once, a progress
indicator, then "done".

### Delivery form

A single PowerShell `.ps1` wrapped in a `.bat` that sets execution policy
and invokes the script. The Linux bootstrap is fetched via curl from the
repo and piped into `wsl ... -u root bash`. Unsigned; SmartScreen may warn
on first run — documented workaround: right-click the `.ps1`, Properties,
Unblock, then run via the `.bat`.

## macOS flow

Run `install/bootstrap-macos.sh` for the automated path. The script
installs backend dependencies (tmux, lua, tintin, git, python3) via
Homebrew and prompt_toolkit via pip, then clones the repo to `~/MUME`.
**Homebrew must already be installed** — if it isn't, the script exits
with instructions pointing to https://brew.sh. No terminal emulator is
installed; run the cockpit from whichever terminal you already use.

No networking tricks required — `localhost` works out of the box.

## Linux flow

Debian/Ubuntu family, the macOS flow with `apt`:

```bash
sudo apt install -y tmux lua5.4 python3 python3-prompt-toolkit \
                    git tintin++
git clone https://github.com/<user>/MUME.git ~/MUME
chmod +x ~/MUME/start.sh
```

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
style = { shape = "Beam", blinking = "On" }
blink_interval = 500
thickness = 0.15

[window]
startup_mode = "Windowed"
padding = { x = 6, y = 6 }
dynamic_padding = true
decorations = "Full"

[font]
size = 15

# font.normal.family / font.bold.family / etc. — see "Font selection" below.

[terminal.shell]   # Windows only — drop on macOS/Linux
program = "wsl.exe"
args = ["-d", "Ubuntu", "-u", "root"]

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
- **tt++ apt version may be stale.** If Ubuntu 24.04's `tintin++`
  package is too old for our needs, we fall back to source build —
  adds `libpcre2-dev` and a few minutes of compile time.
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
- **Collision with `bridge/update.sh`.** Self-update expects a clean
  git tree. If the installer ever gains a "repair" mode, it must not
  clobber local user changes. Cross-reference with
  `docs/bridge-services.md`.

## Open questions

1. **Packaged tt++ version.** Is `tintin++` in Ubuntu 24.04's apt
   recent enough for our needs? If yes, the bootstrap stays short. If no,
   we add a source-build path and bring in `build-essential` +
   `libpcre2-dev`. Decided: shipping apt-only first and validating
   against real cockpit usage in WSL. Source-build fallback is parked
   until a missing feature actually surfaces.
2. **MMapper detection.** Detect MMapper's presence on the Windows
   host from WSL (probe `localhost:4242` during the bootstrap) and default
   `connection_mode` accordingly? Low effort, high user value.
3. **Retire `misc/`.** This doc absorbs `misc/WSL and Terminal
   settings`. Once the installer ships, delete the `misc/` directory
   to remove duplication.

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
- `docs/bridge-services.md` — `bridge/startup.conf` format,
  `update.sh` behaviour and exit codes.
- `docs/input-pane.md` — prompt_toolkit and cursor-blink caveats
  relevant to the Alacritty config choices above.
- [ADR 0015](decisions/0015-windows-installer-scope.md) — scope decision
  for the Windows installer: why 22H2+, what was considered and rejected.
