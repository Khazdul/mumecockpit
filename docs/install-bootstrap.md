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

The realistic sequence, given that WSL install requires a reboot and Ubuntu
first-run is interactive:

### Phase 1 — Windows side (run once, as Administrator)

1. Pre-flight: Windows build ≥ 19041, admin rights, internet reachable.
2. `wsl --install -d Ubuntu` — installs the WSL2 kernel and Ubuntu 24.04.
3. Write `%UserProfile%\.wslconfig` with `networkingMode=mirrored` — **only
   on Windows 11 22H2+**. On older Windows, skip this step and flag that
   MMapper mode will not work.
4. Install Alacritty via winget:
   `winget install Alacritty.Alacritty`.
   Fall back to an MSI download if winget is unavailable.
5. Write `%APPDATA%\alacritty\alacritty.toml` (see Config files below).
6. Create a desktop shortcut that runs:
   `alacritty.exe -e wsl -- bash -lc "cd ~/MUME && ./start.sh"`.
7. Instruct the user to reboot, complete Ubuntu's first-run setup (pick a
   Linux username + password), then run Phase 2 manually.

### Phase 2 — Inside Ubuntu (run once, after first-run setup)

A single bootstrap shell script, fetched via curl from the repo, performs:

1. `sudo apt update && sudo apt install -y tmux lua5.4 python3 python3-pip git build-essential`.
2. `pip install prompt_toolkit --break-system-packages`.
3. Install tt++: `apt install -y tintin++` if the packaged version is
   recent enough; otherwise build from tintin.mudhalla.net. See Open
   questions.
4. `git clone https://github.com/<user>/MUME.git ~/MUME`.
5. `chmod +x ~/MUME/start.sh`.
6. Print "Done — close this shell and launch from the desktop icon."

### Delivery form

Most likely: a signed (or unblock-on-first-run) PowerShell `.ps1` for
Phase 1 and a `bootstrap.sh` (curl | bash) for Phase 2. See Open questions.

## macOS flow

A single shell script:

```bash
brew install --cask alacritty
brew install tmux lua python3 git tintin
pip3 install prompt_toolkit
git clone https://github.com/<user>/MUME.git ~/MUME
chmod +x ~/MUME/start.sh
```

Write `~/.config/alacritty/alacritty.toml` (same content as the Windows
file, minus the `[terminal.shell]` block).

No networking tricks required — `localhost` works out of the box.

## Linux flow

Debian/Ubuntu family, the macOS flow with `apt`:

```bash
sudo apt install -y tmux lua5.4 python3 python3-prompt-toolkit \
                    git tintin++ alacritty
git clone https://github.com/<user>/MUME.git ~/MUME
chmod +x ~/MUME/start.sh
```

Same Alacritty config path as macOS. Other distros (Fedora, Arch, …) get a
documented manual recipe; automating all package managers is not a good
use of time given the user base.

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

[font.normal]
family = "Lucida Console"
style = "Regular"

[font.bold]
family = "Lucida Console"
style = "Bold"

[font.italic]
family = "Lucida Console"
style = "Italic"

[font.bold_italic]
family = "Lucida Console"
style = "Bold Italic"

[terminal.shell]   # Windows only — drop on macOS/Linux
program = "wsl.exe"
args = []

[scrolling]
history = 10000

[selection]
save_to_clipboard = true
```

Almost entirely cosmetic. The `[terminal.shell]` block on Windows is the
only functional line — it makes Alacritty spawn into WSL by default.
`blinking = "On"` can be changed to `"Always"` if a blinking cursor is
preferred inside the input pane; see `docs/input-pane.md` for the
steady-cursor caveat.

## Pitfalls

### Windows

- **WSL install requires a reboot.** No way around it. The installer
  must stop cleanly, instruct the user to reboot, and rely on the user
  to return for Phase 2. A scheduled-task trick to resume post-reboot
  is possible but adds antivirus friction for little gain.
- **Ubuntu first-run is interactive.** Setting a Linux username and
  password happens in the Ubuntu terminal, not in the `.ps1`. We
  cannot automate this without running everything as root, which is
  a bad default.
- **`networkingMode=mirrored` is Windows 11-only (22H2+).** Windows 10
  users cannot use MMapper mode with this approach. The installer
  must detect the OS build and pin `connection_mode=direct` in
  `bridge/startup.conf` on older Windows.
- **SmartScreen will warn on unsigned PowerShell.** Real code-signing
  certs are expensive and probably overkill. Documented workaround:
  right-click the `.ps1`, Properties, Unblock, then run as admin.
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
  (PEP 668). Harmless on older releases; the flag can stay
  unconditional.

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

- **Repo path hardcoded to `~/MUME`** in the desktop shortcut and
  Phase 2 script. Custom paths are a v2 problem — document as a
  constraint.
- **Collision with `bridge/update.sh`.** Self-update expects a clean
  git tree. If the installer ever gains a "repair" mode, it must not
  clobber local user changes. Cross-reference with
  `docs/bridge-services.md`.

## Open questions

1. **Packaged tt++ version.** Is `tintin++` in Ubuntu 24.04's apt
   recent enough for our needs? If yes, Phase 2 stays short. If no,
   we add a source-build path and bring in `build-essential` +
   `libpcre2-dev`.
2. **Phase-1 delivery.** `.ps1` vs `.bat` vs a small signed `.exe`
   wrapper. `.ps1` is the honest answer; a `.bat` wrapper that sets
   the execution policy and invokes the real script is probably the
   usable answer.
3. **Resume-after-reboot.** Keep Phase 2 as a manual step the user
   runs themselves, or attempt a scheduled-task trick? Manual is
   boring and reliable; automated is "one-click" but fragile.
4. **Where the bootstrap lives.** Top-level `install/` directory in
   the repo, separate repo, or a gist? Same repo is simplest and
   keeps versioning aligned.
5. **MMapper detection.** Detect MMapper's presence on the Windows
   host from WSL (probe `localhost:4242` during Phase 2) and default
   `connection_mode` accordingly? Low effort, high user value.
6. **Retire `misc/`.** This doc absorbs `misc/WSL and Terminal
   settings`. Once the installer ships, delete the `misc/` directory
   to remove duplication.

## Rollout phases

Suggested sequence; each a separate chunk of work:

1. **macOS + Linux bootstrap script.** Trivial, proves the model,
   useful immediately for any non-Windows contributors.
2. **Windows Phase 2 (`bootstrap.sh` inside Ubuntu).** Reusable
   regardless of how Phase 1 is delivered; worth building first.
3. **Windows Phase 1 (`.ps1`).** Depends on 2.
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