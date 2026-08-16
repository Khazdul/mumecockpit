# MUME Cockpit - Installation

MUME Cockpit is a terminal client for MUME (Multi-Users in Middle-Earth).

Windows users get a double-clickable installer zip from GitHub Releases.
macOS and Linux users run a single curl command. All three end up with the
same cockpit; only the bootstrap surface differs.

---

## Windows

### Requirements

- Windows 11 22H2 or newer. Run `winver` to check -- you need build 22621 or
  higher.
- About 5 minutes and an internet connection.
- Optional but recommended: MMapper installed and running on the Windows side.
  MMapper is a separate application; the cockpit installer does not install it.
  Get it at https://github.com/MUME/MMapper/releases

### Install steps

1. Download the latest zip from the GitHub Releases page.
2. Extract it somewhere convenient (Desktop, Downloads, wherever).
3. Double-click `cockpit-installer.bat`.
4. **Windows SmartScreen will probably show a blue warning** ("Windows
   protected your PC"). Click "More info", then "Run anyway". This warning
   appears because the installer is not code-signed. Both files in the zip are
   plain text and can be opened in Notepad before you run anything.
5. Click "Yes" on the UAC prompt.
6. Wait. The installer prints what it is doing as it goes. Total time is
   roughly 5 minutes on a fresh machine, less if WSL or Ubuntu are already
   installed.
7. When it finishes, the installer prints a recommendation to restart
   Windows before launching the cockpit for the first time. The install
   itself is done — the restart just lets the WSL graphics subsystem start
   cleanly so the first launch is reliable.
8. After the restart, open the Start Menu and search for **MUME Cockpit**.
   Pin it to the taskbar if you want it one click away.
9. The very first launch waits a few seconds while the Ubuntu WSL distro
   spins up. Subsequent launches are near-instant.

### What got installed

- Ubuntu (inside WSL2) with the cockpit dependencies
- The MUME Cockpit repo at `/root/MUME` inside Ubuntu
- The `foot` terminal and a set of monospace fonts
  (`fonts-dejavu`, `fonts-cascadia-code`, `fonts-jetbrains-mono`,
  `fonts-hack`, `fonts-firacode`, `fonts-ibm-plex`, `fonts-3270`,
  `fonts-mononoki`, `fonts-agave`, `fonts-anonymous-pro`,
  `fonts-fantasque-sans`, `fonts-go`, `fonts-hermit`,
  `fonts-inconsolata`, `fonts-noto-mono`) inside WSL — any font package
  your Ubuntu version does not ship is skipped silently
- A managed `foot.ini` at `~/.config/foot/foot.ini` inside WSL
- A **MUME Cockpit** Start Menu entry (surfaced from WSLg via
  `/usr/share/applications/mume-cockpit.desktop`, with its icon at
  `/usr/share/icons/hicolor/256x256/apps/mume-cockpit.png`) that runs
  `bridge/supervisor.sh`
- `/etc/wsl.conf` inside WSL with `[user] default=root` (merged into any
  existing file), so the Start Menu launch runs as root and can reach
  `/root/MUME`
- A `.wslconfig` in your Windows user profile that enables mirrored
  networking (needed for MMapper integration). Only created if you
  did not already have one — your existing `.wslconfig` is never
  overwritten.

---

## macOS

### Requirements

- Homebrew installed. Get it at https://brew.sh if you do not have it.
- Internet connection. About 5 minutes.

macOS does not ship with a MUME-friendly terminal bundled. The installer sets
up the cockpit itself; you keep using whatever terminal you already prefer.

### Install

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-macos.sh | bash
```

### What got installed

- Homebrew formulae: bash, tmux, lua@5.4, tintin, git, python3
- prompt_toolkit, pyperclip via pip
- The MUME Cockpit repo at `~/MUME`
- An optional Alacritty config example at `~/MUME/install/examples/alacritty.toml`
  if you want to switch terminals -- not installed automatically

### Run

```
cd ~/MUME && ./start.sh
```

---

## Linux

### Requirements

- Debian/Ubuntu with apt, or an Arch-family distro with pacman (Arch,
  CachyOS, EndeavourOS). Other distros: see "Other Linux distributions"
  below.
- Internet connection. About 5 minutes.

Each family has its own bootstrap script. Pick the one that matches your
distro -- both scripts check which package manager they are running on and
exit without touching anything if you picked wrong.

No terminal emulator is installed on either path: the bootstrap sets up the
cockpit itself and you keep using whatever terminal you already prefer. An
optional Alacritty config example is available at
`~/MUME/install/examples/alacritty.toml` if you want it -- not installed
automatically.

### Debian / Ubuntu

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-linux.sh | bash
```

**What got installed**

- apt packages: tmux, lua5.4, git, python3-prompt-toolkit, python3-pyperclip
- tt++ at `/usr/local/bin/tt++` — built from source on first install if the system tt++ is missing or lacks TLS support
- The MUME Cockpit repo at `~/MUME`

### Arch / CachyOS

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-arch.sh | bash
```

**What got installed**

- pacman packages: tmux, lua54, git, python-prompt_toolkit, python-pyperclip,
  python-fonttools, wl-clipboard, xclip
- tt++ at `/usr/local/bin/tt++` — built from source on first install if the
  system tt++ is missing or lacks TLS support
- The MUME Cockpit repo at `~/MUME`

Notes specific to this path:

- `wl-clipboard` and `xclip` are what make Ctrl+V work in the input pane on
  Wayland and X11 respectively. Both are installed so paste works whichever
  session you are in.
- Bare `lua` on current Arch is 5.5; the cockpit needs 5.4, which the `lua54`
  package provides as `lua5.4`. `start.sh` finds it and uses it -- nothing to
  configure.
- Packages you already have are left alone, including outdated ones. The
  script installs what is missing and never upgrades your system for you, so
  it cannot leave you in a partial-upgrade state. Run `sudo pacman -Syu`
  yourself first if you like to be current.
- Verified end-to-end on CachyOS on 2026-08-16 for a re-run over an existing
  install (everything already present). A first install on a clean machine --
  in particular building tt++ from source on Arch -- has not been tested in
  the field yet. If it breaks, please file an issue with the output.

### Run

```
cd ~/MUME && ./start.sh
```

### Other Linux distributions

Fedora and other non-Debian, non-Arch distributions have no bootstrap script
-- `bootstrap-linux.sh` is apt-based and `bootstrap-arch.sh` is pacman-based,
and each refuses to run elsewhere. On those distros, install the equivalent
packages manually and clone the repo:

| Package                | Fedora (dnf)           |
|------------------------|------------------------|
| tmux                   | tmux                   |
| lua5.4                 | lua                    |
| git                    | git                    |
| python3-prompt-toolkit | python3-prompt-toolkit |
| python3-pyperclip      | python3-pyperclip      |

Also install a clipboard helper for the input pane's paste path --
`wl-clipboard` under Wayland, `xclip` under X11 -- and make sure the `lua` on
your PATH is 5.4.x. If your distro ships a newer `lua` as the default, install
its 5.4 package as well; `start.sh` looks for `lua5.4` and `lua54` and uses
whichever it finds.

For tt++, build from source (the distro packages are often too old or lack
TLS). Build dependencies:

| Dep (apt)            | Fedora (dnf)         |
|----------------------|----------------------|
| build-essential      | gcc make             |
| libpcre2-dev         | pcre2-devel          |
| libgnutls28-dev      | gnutls-devel         |
| zlib1g-dev           | zlib-devel           |
| pkg-config           | pkgconf              |

Then build and install:

```
git clone --depth 1 --branch 2.02.61 https://github.com/scandum/tintin
cd tintin/src && ./configure && make && sudo make install
```

Then clone the repo:

```
git clone https://github.com/Khazdul/mumecockpit.git ~/MUME
cd ~/MUME && ./start.sh
```

Distro tintin packages may lack TLS support. If `#ssl` fails in direct mode, build from source — see `install/bootstrap-linux.sh` for the exact configure/make steps.

For the full package list and rationale, see `docs/install-bootstrap.md`.

---

## Pinning to a specific version

The curl commands above follow the `main` branch and always install the latest
code. To pin to a specific release, replace `main` in the URL with the release
tag, for example:

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/v0.2.0/install/bootstrap-macos.sh | bash
```

Note that pinning also pins any bugs present at that tag.

---

## Troubleshooting

**Windows: "This installer requires Windows 11 22H2 or newer"**
Your Windows is too old. Run `winver` to check; you need build 22621 or
higher. Older Windows can still run the cockpit but you must set it up
manually inside WSL.

**Windows: "WSL is not enabled on this machine"**
Open an admin PowerShell, run `wsl --install`, reboot, then re-run the
installer.

**Windows: SmartScreen will not let me run it**
Right-click `cockpit-installer.bat`, choose Properties, tick "Unblock" at
the bottom, click OK, then try running it again.

**Windows: the Start Menu entry opens a terminal that closes immediately**
The cockpit failed to start inside WSL. Open a WSL shell
(`wsl -d Ubuntu -u root`) and run `/root/MUME/bridge/supervisor.sh` by
hand to see the error. File a GitHub issue with the output.

**Windows: the cockpit window appears blank on first launch after install**
Restart Windows and try again. The first launch after a fresh install can
catch the WSL graphics subsystem in an inconsistent state; a full Windows
restart (not just `wsl --shutdown`) clears it. The installer recommends
this restart at the end of the install for the same reason.

**Windows: the Start Menu shows a generic icon instead of the cockpit one**
Cosmetic only — a WSLg rendering limitation on some WSLg versions. The
app launches and runs normally; nothing to do on your side.

**macOS: "brew: command not found"**
Install Homebrew first from https://brew.sh, then re-run the curl command.

**Linux: package not found**
Your distro is probably neither Debian/Ubuntu nor Arch-family. Install the
equivalent packages manually -- see "Other Linux distributions" above.

**Linux: "pacman not found. This script targets Arch Linux" or "apt-get not
found. This script targets Debian/Ubuntu"**
You ran the wrong bootstrap for your distro. Nothing was installed. Use
`bootstrap-linux.sh` on Debian/Ubuntu and `bootstrap-arch.sh` on
Arch/CachyOS -- see the two install blocks above.

**Any platform: launcher does not start**
Verify that `cd ~/MUME && ./start.sh` works at the command line. If it does
not, file a GitHub issue with the error message.

---

## Uninstall

**Windows**
- Remove the "MUME Cockpit" Start Menu entry by deleting
  `/usr/share/applications/mume-cockpit.desktop` (and optionally
  `/usr/share/icons/hicolor/256x256/apps/mume-cockpit.png`) from inside
  WSL. WSLg will drop the Start Menu shortcut on the next sync.
- In an admin PowerShell, run `wsl --list` to find the Ubuntu distro name,
  then `wsl --unregister <name>` to remove it. This also wipes the cockpit
  install, foot, and the foot config inside that distro.
- Delete `%UserProfile%\.wslconfig` if you do not use WSL for anything else.

**macOS**
```
rm -rf ~/MUME
```
Homebrew packages (tmux, lua, tintin, etc.) can stay or be removed via
`brew uninstall tmux lua tintin` as you prefer.

**Linux**
```
rm -rf ~/MUME
```
The source-built tt++ and the packages can be removed via:
```
sudo rm -f /usr/local/bin/tt++

# Debian/Ubuntu
sudo apt remove tmux lua5.4 python3-prompt-toolkit python3-pyperclip

# Arch/CachyOS
sudo pacman -Rs tmux lua54 python-prompt_toolkit python-pyperclip python-fonttools
```

---

## Reporting problems

File an issue at https://github.com/Khazdul/mumecockpit/issues

This is alpha software. Feedback and bug reports are very welcome.
