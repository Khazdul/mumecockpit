# Install & Bootstrap

Plan for cross-platform one-click installation of the MUME cockpit. Windows
is the primary target — the only platform with current or prospective users
who cannot be expected to drive a terminal manually. macOS and Linux are
documented for completeness and to keep the install story honest.

This is a **plan document**. Nothing here is implemented yet. Touch this
file when the installer work is scheduled, when a platform constraint
changes, or when decisions in "Open questions" are resolved.

## Scope

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
- Auto-upgrading Windows. Required version floors are hard prerequisites,
  documented below.
- Unattended installs in corporate-locked environments.

## Target platforms

| OS                             | Target                                                        | Priority |
|--------------------------------|---------------------------------------------------------------|----------|
| Windows 11 (22H2+)             | Primary                                                       | 1        |
| Windows 10 (build 19041+)      | Secondary — no mirrored networking, must use direct mode      | 2        |
| macOS (Apple Silicon or Intel) | Supported                                                     | 3        |
| Linux, Debian/Ubuntu family    | Supported                                                     | 3        |
| Linux, other distros           | Manual install; documented only                               | 4        |

Windows older than build 19041 is unsupported — WSL2 requires that baseline.

## Windows flow

Two realistic paths depending on whether WSL is already active on the
machine. The installer detects which path to take via
`Get-WindowsOptionalFeature -FeatureName VirtualMachinePlatform`.

### Fast path — WSL already active (common on modern Windows 11)

Fully unattended, no reboot, no user interaction after the initial UAC
prompt:

1. Pre-flight: Windows build ≥ 19041, admin rights, internet reachable.
2. `wsl --install -d Ubuntu --no-launch` — installs Ubuntu 24.04 silently,
   does **not** trigger the first-run OOBE dialog.
3. Write `%UserProfile%\.wslconfig` with `networkingMode=mirrored` (Windows
   11 22H2+ only).
4. `wsl --shutdown` so the `.wslconfig` change takes effect.
5. `wsl -d Ubuntu -u root -- bash -c "<bootstrap.sh contents>"` — runs
   Phase 2 as root. Running as root inside WSL is fine here: the cockpit
   has no multi-user logic and no sudo paths. The OOBE user-creation
   dialog is never triggered.
6. Install Alacritty (winget, MSI fallback) and write
   `%APPDATA%\alacritty\alacritty.toml`.
7. Create a desktop shortcut that runs:
   `alacritty.exe -e wsl -d Ubuntu -u root -- bash -lc "cd /root/MUME && ./start.sh"`.

No reboot. No manual first-run. The user sees UAC once, a progress
indicator, then "done".

### Slow path — VMP or WSL feature not yet enabled (rare on modern Windows 11)

Reboot required between phases because Windows features cannot be
enabled live:

1. Pre-flight as above.
2. Enable `VirtualMachinePlatform` and `Microsoft-Windows-Subsystem-Linux`
   via `dism` or `Enable-WindowsOptionalFeature`.
3. Clear instruction to reboot, with the installer writing a marker file
   so re-running it after reboot resumes at step 4 automatically.
4. After reboot: continue with the fast path from step 2.

Resume-after-reboot is done by checking for a marker file at launch, not
by scheduled tasks (scheduled tasks trigger antivirus friction). User
re-runs the shortcut once; installer detects marker, continues.

### Delivery form

Phase 1 is a single PowerShell `.ps1` wrapped in a `.bat` that sets
execution policy and invokes the script. Phase 2 is a shell script fetched
via curl from the repo and piped into `wsl ... -u root bash`. See Open
questions for code-signing vs unblock-on-first-run.

## macOS flow

A single shell script:

```bash
brew install --cask alacritty
brew install tmux lua python3 git tintin
pip3 install prompt_toolkit
git clone https://github.com/<user>/MUME.git ~/MUME
chmod +x ~/MUME/start.sh
```

Write `~/.config/alacritty/alacritty.toml` with the macOS font mapping
(see Config files below).

No networking tricks required — `localhost` works out of the box.

## Linux flow

Debian/Ubuntu family, the macOS flow with `apt`:

```bash
sudo apt install -y tmux lua5.4 python3 python3-prompt-toolkit \
                    git tintin++ alacritty
git clone https://github.com/<user>/MUME.git ~/MUME
chmod +x ~/MUME/start.sh
```

Same Alacritty config path as macOS, with the Linux font mapping. Other
distros (Fedora, Arch, …) get a documented manual recipe; automating all
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

- **Reboot only in the slow path.** On modern Windows 11 with WSL already
  active — the common case — `wsl --install -d Ubuntu --no-launch` runs
  without a reboot and the entire flow is unattended. Reboot is only
  required when `VirtualMachinePlatform` or the WSL feature itself has to
  be enabled from scratch. The installer detects this and branches.
- **`networkingMode=mirrored` is Windows 11-only (22H2+).** Windows 10
  users cannot use MMapper mode with this approach. The installer must
  detect the OS build and pin `connection_mode=direct` in
  `bridge/startup.conf` on older Windows.
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
- **`winget` is not everywhere.** Pre-1809 Windows 10 lacks it;
  policy-managed machines sometimes disable it. MSI fallback needed.
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

### Linux

- **Distro sprawl.** We target the Debian/Ubuntu family with apt;
  everything else gets a documented recipe, not an automated path.
- **Wayland vs X11 for Alacritty.** Distro/DE-specific; Alacritty
  handles both. Not our problem.

### All platforms

- **Repo path hardcoded.** `~/MUME` (or `/root/MUME` on Windows/WSL-as-root)
  in the desktop shortcut and Phase 2 script. Custom paths are a v2
  problem — document as a constraint.
- **Collision with `bridge/update.sh`.** Self-update expects a clean
  git tree. If the installer ever gains a "repair" mode, it must not
  clobber local user changes. Cross-reference with
  `docs/bridge-services.md`.

## Open questions

1. **Packaged tt++ version.** Is `tintin++` in Ubuntu 24.04's apt
   recent enough for our needs? If yes, Phase 2 stays short. If no,
   we add a source-build path and bring in `build-essential` +
   `libpcre2-dev`.
2. **Phase-1 delivery.** `.bat` wrapping `.ps1` is the usable answer.
   A signed `.exe` wrapper is nicer but requires a real code-signing
   cert ($$ per year). Defer until there are enough users to justify.
3. **Where the bootstrap lives.** Top-level `install/` directory in
   the repo, separate repo, or a gist? Same repo is simplest and
   keeps versioning aligned.
4. **MMapper detection.** Detect MMapper's presence on the Windows
   host from WSL (probe `localhost:4242` during Phase 2) and default
   `connection_mode` accordingly? Low effort, high user value.
5. **Retire `misc/`.** This doc absorbs `misc/WSL and Terminal
   settings`. Once the installer ships, delete the `misc/` directory
   to remove duplication.

## Rollout phases

Suggested sequence; each a separate chunk of work:

1. **macOS + Linux bootstrap script.** Trivial, proves the model,
   useful immediately for any non-Windows contributors.
2. **Windows Phase 2 (`bootstrap.sh` inside Ubuntu).** Reusable
   regardless of how Phase 1 is delivered; worth building first.
3. **Windows Phase 1 (`.ps1` + `.bat`).** Depends on 2. Starts with the
   fast path; slow path + resume-after-reboot added as a follow-up.
4. **Desktop shortcut + Alacritty config writer.** Integrates with 3.
5. **MMapper auto-detection + default `connection_mode`.** Polish.

## See also

- `start.sh` — runtime entry point. Currently installs tmux and lua
  on demand; assumes the rest is present. Will remain the runtime
  entry point after the installer lands — installer is a separate,
  one-shot story.
- `docs/bridge-services.md` — `bridge/startup.conf` format,
  `update.sh` behaviour and exit codes.
- `docs/input-pane.md` — prompt_toolkit and cursor-blink caveats
  relevant to the Alacritty config choices above.