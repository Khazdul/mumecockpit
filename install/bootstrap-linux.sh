#!/usr/bin/env bash
set -euo pipefail

trap 'echo "Error on line $LINENO. Check the output above for details." >&2' ERR

REPO_URL="https://github.com/Khazdul/mumecockpit.git"

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
# Install packages
# ---------------------------------------------------------------------------

# tintin++ is the correct apt package name — the plus signs are part of the
# package name; do not "fix" them to tintin or tintin-plus.
PACKAGES="tmux lua5.4 python3 python3-prompt-toolkit git tintin++"

if [ "$IS_WSL" -eq 0 ]; then
    PACKAGES="$PACKAGES alacritty"
fi

$RUN apt-get update
# shellcheck disable=SC2086  # word-splitting of $PACKAGES is intentional
$RUN apt-get install -y $PACKAGES

# ---------------------------------------------------------------------------
# Clone or update the cockpit repo
# ---------------------------------------------------------------------------

if [ ! -d "$HOME/MUME" ]; then
    git clone "$REPO_URL" "$HOME/MUME"
else
    echo "~/MUME already exists — pulling latest changes."
    if ! git -C "$HOME/MUME" pull --ff-only 2>&1; then
        echo "Warning: git pull failed (local changes or diverged history). Continuing with existing state." >&2
    fi
fi

chmod +x "$HOME/MUME/start.sh"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo "Installation complete."
echo "Run the cockpit with: cd ~/MUME && ./start.sh"

if [ "$IS_WSL" -eq 0 ] && [ ! -f "$HOME/.config/alacritty/alacritty.toml" ]; then
    echo "An example Alacritty config is available at ~/MUME/install/examples/alacritty.toml if you want to try it."
fi
