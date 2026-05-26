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
7. When it finishes, open the Start Menu and search for **MUME Cockpit**.
   Pin it to the taskbar if you want it one click away.
8. The very first launch waits a few seconds while the Ubuntu WSL distro
   spins up. Subsequent launches are near-instant.

### What got installed

- Ubuntu (inside WSL2) with the cockpit dependencies
- The MUME Cockpit repo at `/root/MUME` inside Ubuntu
- The `foot` terminal and a small set of monospace fonts
  (`fonts-dejavu`, `fonts-cascadia-code`, `fonts-jetbrains-mono`,
  `fonts-hack`) inside WSL — any font package your Ubuntu version
  does not ship is skipped silently
- A managed `foot.ini` at `~/.config/foot/foot.ini` inside WSL
- A **MUME Cockpit** Start Menu entry (surfaced from WSLg via
  `~/.local/share/applications/mume-cockpit.desktop`) that runs
  `bridge/supervisor.sh`
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

- Homebrew formulae: tmux, lua, tintin, git, python3
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

- Debian or Ubuntu with apt. Other distros: see "Other Linux distributions"
  below.
- Internet connection. About 5 minutes.

### Install

```
curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-linux.sh | bash
```

### What got installed

- apt packages: tmux, lua5.4, git, python3-prompt-toolkit, python3-pyperclip
- tt++ at `/usr/local/bin/tt++` — built from source on first install if the system tt++ is missing or lacks TLS support
- Alacritty (on native Linux only -- skipped on WSL since the Windows
  installer handles the terminal there)
- The MUME Cockpit repo at `~/MUME`

### Run

```
cd ~/MUME && ./start.sh
```

### Other Linux distributions

The bootstrap script is apt-based and will refuse to run on Fedora, Arch, and
other non-Debian distributions. On those distros, install the equivalent
packages manually and clone the repo:

| Package              | Fedora (dnf)         | Arch (pacman)        |
|----------------------|----------------------|----------------------|
| tmux                 | tmux                 | tmux                 |
| lua5.4               | lua                  | lua                  |
| git                  | git                  | git                  |
| python3-prompt-toolkit | python3-prompt-toolkit | python-prompt-toolkit |
| python3-pyperclip    | python3-pyperclip    | python-pyperclip     |

For tt++, build from source (the distro packages are often too old or lack
TLS). Build dependencies:

| Dep (apt)            | Fedora (dnf)         | Arch (pacman)        |
|----------------------|----------------------|----------------------|
| build-essential      | gcc make             | base-devel           |
| libpcre2-dev         | pcre2-devel          | pcre2                |
| libgnutls28-dev      | gnutls-devel         | gnutls               |
| zlib1g-dev           | zlib-devel           | zlib                 |
| pkg-config           | pkgconf              | pkgconf              |

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

**macOS: "brew: command not found"**
Install Homebrew first from https://brew.sh, then re-run the curl command.

**Linux: package not found**
Your distro is probably not Debian or Ubuntu. Install the equivalent packages
manually -- see "Other Linux distributions" above.

**Any platform: launcher does not start**
Verify that `cd ~/MUME && ./start.sh` works at the command line. If it does
not, file a GitHub issue with the error message.

---

## Uninstall

**Windows**
- Remove the "MUME Cockpit" Start Menu entry by deleting
  `~/.local/share/applications/mume-cockpit.desktop` from inside WSL. WSLg
  will drop the Start Menu shortcut on the next sync.
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
apt packages and the source-built tt++ can be removed via:
```
sudo rm -f /usr/local/bin/tt++
sudo apt remove tmux lua5.4 python3-prompt-toolkit python3-pyperclip
```

---

## Reporting problems

File an issue at https://github.com/Khazdul/mumecockpit/issues

This is alpha software. Feedback and bug reports are very welcome.
