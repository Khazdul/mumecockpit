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

PACKAGES="tmux lua5.4 python3 python3-prompt-toolkit python3-pyperclip git"

if [ "$IS_WSL" -eq 0 ]; then
    PACKAGES="$PACKAGES alacritty"
fi

$RUN apt-get update
# shellcheck disable=SC2086  # word-splitting of $PACKAGES is intentional
$RUN apt-get install -y $PACKAGES

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
