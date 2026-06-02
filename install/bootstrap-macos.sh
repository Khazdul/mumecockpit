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

# Homebrew refuses to run as root, and the from-source builds must not run as
# root either. Run the whole bootstrap as the normal user; brew elevates via
# sudo only where it needs to.
if [ "$(id -u)" -eq 0 ]; then
    echo "Error: Do not run this script as root (no sudo)." >&2
    echo "Run it as your normal user; you will be prompted for a password where needed." >&2
    exit 1
fi

if ! curl -sSf https://github.com >/dev/null 2>&1; then
    echo "Error: Cannot reach github.com. Check your network connection." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Ensure Homebrew is installed and on PATH
# ---------------------------------------------------------------------------
# The official installer is interactive: it prompts for the sudo password and,
# on a fresh machine, triggers the Xcode Command Line Tools GUI install. CLT
# provides the compiler the tt++ from-source build needs, so we wait for it to
# resolve before proceeding. Running from a terminal, interactive is fine.

if [ "$(uname -m)" = "arm64" ]; then
    BREW_PREFIX="/opt/homebrew"
else
    BREW_PREFIX="/usr/local"
fi

if ! command -v brew >/dev/null 2>&1 \
    && [ ! -x /opt/homebrew/bin/brew ] \
    && [ ! -x /usr/local/bin/brew ]; then
    echo "Homebrew not found — installing it now."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # The installer normally installs the Command Line Tools, but make sure the
    # compiler is present before any from-source build runs.
    if ! xcode-select -p >/dev/null 2>&1; then
        echo "Triggering Xcode Command Line Tools install — complete the GUI prompt."
        xcode-select --install 2>/dev/null || true
        echo "Waiting for Command Line Tools to finish installing..."
        until xcode-select -p >/dev/null 2>&1; do
            sleep 5
        done
    fi
fi

# Put brew on PATH for the rest of this script.
eval "$("$BREW_PREFIX/bin/brew" shellenv)"

# ---------------------------------------------------------------------------
# Install packages via Homebrew
# ---------------------------------------------------------------------------

# TODO (parked): probe-then-build for tt++, mirroring bootstrap-linux.sh.
# brew's `tintin` formula is current on most installs but TLS support is not
# guaranteed across upgrades. See `docs/install-bootstrap.md` open questions.

# tintin is the formula name — no plus signs, unlike the Debian/Ubuntu package
# name (tintin++). Do not "fix" this.
brew install bash tmux lua@5.4 tintin git python3

# Bundled terminal. kitty ships only as an .app cask (no formula); font-dejavu
# provides DejaVu Sans Mono for the preset below. Casks are no-ops if already
# present, so this is safe to re-run.
brew install --cask kitty
brew install --cask font-dejavu

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
# Install the kitty preset
# ---------------------------------------------------------------------------
# Mirrors the cockpit DOS palette. Never clobber a user's existing config:
# back it up with a timestamp and tell them where it went.

KITTY_CONFIG_DIR="$HOME/.config/kitty"
KITTY_CONFIG="$KITTY_CONFIG_DIR/kitty.conf"
mkdir -p "$KITTY_CONFIG_DIR"

if [ -f "$KITTY_CONFIG" ]; then
    backup="$KITTY_CONFIG.bak.$(date +%Y%m%d%H%M%S)"
    mv "$KITTY_CONFIG" "$backup"
    echo "Existing kitty.conf backed up to $backup"
fi

cp "$HOME/MUME/install/examples/kitty.conf" "$KITTY_CONFIG"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo "Installation complete."
echo "Run the cockpit with: cd ~/MUME && ./start.sh"
