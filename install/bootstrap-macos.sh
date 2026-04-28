#!/usr/bin/env bash
set -euo pipefail

trap 'echo "Error on line $LINENO. Check the output above for details." >&2' ERR

REPO_URL="https://github.com/Khazdul/mumecockpit.git"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ "$(uname -s)" != "Darwin" ]; then
    echo "Error: This script targets macOS." >&2
    echo "For Linux, use bootstrap-linux.sh." >&2
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "Error: Homebrew is not installed." >&2
    echo "Install it first: https://brew.sh" >&2
    exit 1
fi

if ! curl -sSf https://github.com >/dev/null 2>&1; then
    echo "Error: Cannot reach github.com. Check your network connection." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Install packages via Homebrew
# ---------------------------------------------------------------------------

# tintin is the formula name — no plus signs, unlike the Debian/Ubuntu package
# name (tintin++). Do not "fix" this.
brew install bash tmux lua tintin git python3

# ---------------------------------------------------------------------------
# Install prompt_toolkit via pip
# ---------------------------------------------------------------------------
# No brew formula tracks prompt_toolkit cleanly; pip is the right path here.
# Homebrew Python normally permits user-site installs without
# --break-system-packages. Try the clean install first and fall back if pip
# refuses with the externally-managed-environment error.

install_python_deps() {
    if python3 -m pip install --user prompt_toolkit pyperclip 2>/dev/null; then
        return 0
    fi
    echo "Clean pip install declined (externally-managed-environment). Retrying with --break-system-packages..."
    python3 -m pip install --user --break-system-packages prompt_toolkit pyperclip
}

install_python_deps

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

if [ ! -f "$HOME/.config/alacritty/alacritty.toml" ]; then
    echo "An example Alacritty config is available at ~/MUME/install/examples/alacritty.toml if you want to try it."
    echo "The example uses DejaVu Sans Mono by default; for the macOS-canonical look change 'family' to 'Menlo' (see docs/install-bootstrap.md for the font table)."
fi
