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
7. When it finishes, double-click the new "MUME Cockpit" shortcut on your
   Desktop.

### What got installed

- Ubuntu (inside WSL2) with the cockpit dependencies
- Alacritty terminal emulator
- The MUME Cockpit repo at `/root/MUME` inside Ubuntu
- A Desktop shortcut and an Alacritty config in `%APPDATA%\alacritty\`
- A `.wslconfig` in your user profile that enables mirrored networking
  (needed for MMapper integration)

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

- apt packages: tmux, lua5.4, tintin++, git, python3-prompt-toolkit, python3-pyperclip
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
| tintin++             | tintin               | tintin (AUR)         |
| git                  | git                  | git                  |
| python3-prompt-toolkit | python3-prompt-toolkit | python-prompt-toolkit |
| python3-pyperclip    | python3-pyperclip    | python-pyperclip     |

Then clone the repo:

```
git clone https://github.com/Khazdul/mumecockpit.git ~/MUME
cd ~/MUME && ./start.sh
```

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

**Windows: the Desktop shortcut closes immediately**
The cockpit failed to start. Open PowerShell and run the shortcut's Target
plus Arguments manually to see the error. File a GitHub issue with the output.

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
- Delete the "MUME Cockpit" Desktop shortcut.
- Delete `%APPDATA%\alacritty\` (or just the cockpit config files inside it
  if you use Alacritty for other things).
- In an admin PowerShell, run `wsl --list` to find the Ubuntu distro name,
  then `wsl --unregister <name>` to remove it.
- Uninstall Alacritty via Settings -> Apps if you no longer want it.
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
apt packages can stay or be removed via:
```
sudo apt remove tmux lua5.4 tintin++ python3-prompt-toolkit
```

---

## Reporting problems

File an issue at https://github.com/Khazdul/mumecockpit/issues

This is alpha software. Feedback and bug reports are very welcome.
