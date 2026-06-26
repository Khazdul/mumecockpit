#!/usr/bin/env bash
set -euo pipefail

trap 'echo "Error on line $LINENO. Check the output above for details." >&2' ERR

REPO_URL="https://github.com/Khazdul/mumecockpit.git"

TT_BUILD_VERSION="2.02.61"

# Privilege wrapper: prepend sudo when not running as root
if [ "$(id -u)" -eq 0 ]; then
    RUN=""
else
    RUN="sudo"
fi

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ "$(uname -s)" != "Linux" ]; then
    echo "Error: This script targets Linux." >&2
    echo "For macOS, use bootstrap-macos.sh (not yet shipped)." >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Error: apt-get not found. This script targets Debian/Ubuntu." >&2
    echo "For other distros, see the manual recipe in docs/install-bootstrap.md." >&2
    exit 1
fi

if ! curl -sSf https://github.com >/dev/null 2>&1; then
    echo "Error: Cannot reach github.com. Check your network connection." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    if ! sudo -v 2>/dev/null; then
        echo "Error: This script requires root or sudo access." >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Detect WSL (covers both WSL1 and WSL2)
# ---------------------------------------------------------------------------

IS_WSL=0
if grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=1
fi

# ---------------------------------------------------------------------------
# Determine target home directory from the password database, not $HOME.
# When invoked via `wsl ... -- bash -c` from a Windows process, $HOME
# may inherit a Windows path and corrupt every `~`-expansion downstream.
TARGET_USER="$(id -un)"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
if [ -z "$TARGET_HOME" ] || [ ! -d "$TARGET_HOME" ]; then
    echo "ERROR: Could not determine a valid home directory for user $TARGET_USER." >&2
    echo "       getent returned: $TARGET_HOME" >&2
    exit 1
fi
REPO_DIR="$TARGET_HOME/MUME"

# ---------------------------------------------------------------------------
# Install packages
# ---------------------------------------------------------------------------

# python3-fonttools is the fontTools fallback backend for the launcher's
# quadrant-corner font-support probe (frame_corners.py); fontconfig's
# fc-list is the preferred backend on Linux, so a missing fonttools only
# degrades the probe to "block", never breaks startup.
PACKAGES="tmux lua5.4 python3 python3-prompt-toolkit python3-pyperclip python3-fonttools git"

if [ "$IS_WSL" -eq 1 ]; then
    # WSL deployment: foot under WSLg is the cockpit's managed terminal.
    # Native Linux installs no terminal — users run the cockpit from their own.
    PACKAGES="$PACKAGES foot"
fi

$RUN apt-get update
# shellcheck disable=SC2086  # word-splitting of $PACKAGES is intentional
$RUN apt-get install -y $PACKAGES

# ---------------------------------------------------------------------------
# WSL only: install bundled monospace fonts so the Terminal Settings UI
# (Phase 2+) has real options to choose from. DejaVu is the hard requirement
# and near-certainly already present; the others degrade gracefully if their
# apt package name does not resolve on the host.
# ---------------------------------------------------------------------------

if [ "$IS_WSL" -eq 1 ]; then
    FONT_PACKAGES="fonts-dejavu fonts-cascadia-code fonts-jetbrains-mono fonts-hack fonts-firacode fonts-ibm-plex fonts-3270 fonts-mononoki fonts-agave fonts-anonymous-pro fonts-fantasque-sans fonts-go fonts-hermit fonts-inconsolata fonts-noto-mono"
    for pkg in $FONT_PACKAGES; do
        if ! $RUN apt-get install -y "$pkg" 2>/dev/null; then
            echo "Warning: font package $pkg not available — skipping." >&2
        fi
    done
    fc-cache -f >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# Provision tt++ (probe existing binary; build from source when needed)
# ---------------------------------------------------------------------------

tt_needs_build=0
tt_build_reason=""

if ! tt_path="$(command -v tt++ 2>/dev/null)"; then
    tt_needs_build=1
    tt_build_reason="tt++ not installed"
elif ! ldd "$tt_path" 2>/dev/null | grep -qiE 'gnutls|libssl'; then
    tt_needs_build=1
    tt_build_reason="tt++ at $tt_path lacks TLS support"
else
    echo "tt++ at $tt_path has TLS support — keeping it."
fi

if [ "$tt_needs_build" -eq 1 ]; then
    echo "tt++: $tt_build_reason — building from source (tag $TT_BUILD_VERSION)."
    $RUN apt-get install -y build-essential libpcre2-dev libgnutls28-dev zlib1g-dev pkg-config

    tt_tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tt_tmpdir"' EXIT

    git clone --depth 1 --branch "$TT_BUILD_VERSION" \
        https://github.com/scandum/tintin "$tt_tmpdir/tintin"
    (
        cd "$tt_tmpdir/tintin/src"
        ./configure
        make
    )
    $RUN make -C "$tt_tmpdir/tintin/src" install
    hash -r

    tt_new_path="$(command -v tt++ 2>/dev/null)" || {
        echo "Error: tt++ not found after build." >&2
        exit 1
    }
    if ! ldd "$tt_new_path" 2>/dev/null | grep -qiE 'gnutls|libssl'; then
        echo "Error: tt++ built without TLS. Ensure libgnutls28-dev is installed and re-run." >&2
        exit 1
    fi
    echo "tt++ built and installed at $tt_new_path (TLS confirmed)."
fi

# ---------------------------------------------------------------------------
# Clone or update the cockpit repo
# ---------------------------------------------------------------------------

if [ ! -d "$REPO_DIR" ]; then
    git clone "$REPO_URL" "$REPO_DIR"
else
    echo "$REPO_DIR already exists — pulling latest changes."
    if ! git -C "$REPO_DIR" pull --ff-only 2>&1; then
        echo "Warning: git pull failed (local changes or diverged history). Continuing with existing state." >&2
    fi
fi

chmod +x "$REPO_DIR/start.sh"
chmod +x "$REPO_DIR/bridge/launcher/launch.sh"
chmod +x "$REPO_DIR/bridge/supervisor.sh"

# ---------------------------------------------------------------------------
# WSL only: enforce default=root, install the managed foot config, and the
# system-wide WSLg .desktop entry and icon. WSLg surfaces .desktop entries
# from /usr/share/applications/ to the Windows Start Menu reliably;
# ~/.local/share/applications/ is not reliable across WSLg versions.
# ---------------------------------------------------------------------------

if [ "$IS_WSL" -eq 1 ]; then
    # The .desktop's Exec points at /root/MUME/bridge/supervisor.sh; WSLg runs
    # that Exec as the WSL default user. On a pre-existing Ubuntu distro the
    # default user can be a normal account, which cannot traverse /root/ →
    # silent launch failure. Force default=root in /etc/wsl.conf, merging
    # into any existing file. The Windows installer runs `wsl --shutdown`
    # after the bootstrap so this takes effect before first launch.
    $RUN python3 - <<'PYEOF'
import os
import re

path = "/etc/wsl.conf"
content = open(path).read() if os.path.exists(path) else ""
lines = content.splitlines()

user_start = None
user_end = None
for i, line in enumerate(lines):
    m = re.match(r'^\s*\[([^\]]+)\]\s*$', line)
    if m:
        if user_start is not None and user_end is None:
            user_end = i
        if m.group(1).strip() == "user":
            user_start = i
            user_end = None
if user_start is not None and user_end is None:
    user_end = len(lines)

if user_start is None:
    if lines and lines[-1].strip() != "":
        lines.append("")
    lines.append("[user]")
    lines.append("default=root")
else:
    block = lines[user_start + 1 : user_end]
    replaced = False
    for j, ln in enumerate(block):
        if re.match(r'^\s*default\s*=', ln):
            block[j] = "default=root"
            replaced = True
            break
    if not replaced:
        insert_at = len(block)
        while insert_at > 0 and block[insert_at - 1].strip() == "":
            insert_at -= 1
        block.insert(insert_at, "default=root")
    lines[user_start + 1 : user_end] = block

new_content = "\n".join(lines)
if new_content and not new_content.endswith("\n"):
    new_content += "\n"

if new_content != content:
    with open(path, "w") as f:
        f.write(new_content)
    print("Set /etc/wsl.conf [user] default=root.")
else:
    print("/etc/wsl.conf already has [user] default=root — skipping.")
PYEOF

    mkdir -p "$TARGET_HOME/.config/foot"
    cp "$REPO_DIR/install/examples/foot.ini" "$TARGET_HOME/.config/foot/foot.ini"

    # Seed initial-window-size-pixels from the Windows installer's resolution
    # probe (MUME_FOOT_WINDOW_PX=WIDTHxHEIGHT). The template line is
    # guaranteed present, so this is a clean in-place rewrite -- see ADR 0107
    # points 3 and 4. Unset or malformed -> keep the template placeholder.
    if [ -n "${MUME_FOOT_WINDOW_PX:-}" ] && [[ "$MUME_FOOT_WINDOW_PX" =~ ^[0-9]+x[0-9]+$ ]]; then
        sed -i "s/^initial-window-size-pixels=.*/initial-window-size-pixels=$MUME_FOOT_WINDOW_PX/" \
            "$TARGET_HOME/.config/foot/foot.ini"
    fi

    # System icon under the hicolor theme. The .desktop entry references the
    # bare theme name `mume-cockpit`; freedesktop icon lookup resolves that to
    # these files. WSLg's icon resolver finds 48x48 and scalable; the 256x256
    # path it does not. Mirrors how the foot package ships its (working) icon.
    # Refresh the icon cache so the entry is in the theme before WSLg
    # generates the Start Menu shortcut.
    $RUN mkdir -p /usr/share/icons/hicolor/48x48/apps
    $RUN mkdir -p /usr/share/icons/hicolor/scalable/apps
    $RUN cp "$REPO_DIR/install/assets/mume-cockpit-48.png" \
        /usr/share/icons/hicolor/48x48/apps/mume-cockpit.png
    $RUN cp "$REPO_DIR/install/assets/mume-cockpit.svg" \
        /usr/share/icons/hicolor/scalable/apps/mume-cockpit.svg
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        $RUN gtk-update-icon-cache -f -q /usr/share/icons/hicolor 2>/dev/null || true
    fi

    # System-wide .desktop entry — WSLg surfaces /usr/share/applications/
    # reliably; per-user ~/.local/share/applications/ does not.
    $RUN install -m 0644 "$REPO_DIR/install/mume-cockpit.desktop" \
        /usr/share/applications/mume-cockpit.desktop
    if command -v update-desktop-database >/dev/null 2>&1; then
        $RUN update-desktop-database -q /usr/share/applications 2>/dev/null || true
    fi
fi

# ---------------------------------------------------------------------------
# Provision win32yank.exe (WSL only — fast clipboard read for the input pane)
# ---------------------------------------------------------------------------

if [ "$IS_WSL" -eq 1 ]; then
    win32yank_bin="$REPO_DIR/bin/win32yank.exe"
    if [ -f "$win32yank_bin" ]; then
        echo "win32yank.exe already present at $win32yank_bin — skipping download."
    else
        # Pinned release; do not track "latest".
        WIN32YANK_VERSION="v0.1.1"
        WIN32YANK_URL="https://github.com/equalsraf/win32yank/releases/download/${WIN32YANK_VERSION}/win32yank-x64.zip"
        echo "Provisioning win32yank.exe ${WIN32YANK_VERSION} for WSL clipboard fast path…"

        win32yank_tmpdir="$(mktemp -d)"
        if curl -fsSL "$WIN32YANK_URL" -o "$win32yank_tmpdir/win32yank.zip" \
            && python3 -m zipfile -e "$win32yank_tmpdir/win32yank.zip" "$win32yank_tmpdir" \
            && [ -f "$win32yank_tmpdir/win32yank.exe" ]; then
            mkdir -p "$REPO_DIR/bin"
            mv "$win32yank_tmpdir/win32yank.exe" "$win32yank_bin"
            chmod +x "$win32yank_bin"
            echo "win32yank.exe installed at $win32yank_bin."
        else
            echo "Warning: failed to download or extract win32yank.exe — continuing without it." >&2
            echo "         The input pane will fall back to pyperclip for clipboard paste." >&2
        fi
        rm -rf "$win32yank_tmpdir"
    fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo "Installation complete."
echo "Run the cockpit with: cd $REPO_DIR && ./start.sh"

if [ "$IS_WSL" -eq 0 ] && [ ! -f "$TARGET_HOME/.config/alacritty/alacritty.toml" ]; then
    echo "An example Alacritty config is available at $REPO_DIR/install/examples/alacritty.toml if you want to try it."
fi

if [ "$IS_WSL" -eq 1 ]; then
    echo "WSLg .desktop entry installed — look for \"MUME Cockpit\" in the Windows Start Menu."
fi
