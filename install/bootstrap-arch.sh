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
    echo "For macOS, use bootstrap-macos.sh." >&2
    exit 1
fi

if ! command -v pacman >/dev/null 2>&1; then
    echo "Error: pacman not found. This script targets Arch Linux (and the Arch family: CachyOS, EndeavourOS)." >&2
    echo "For Debian/Ubuntu, use bootstrap-linux.sh. For macOS, use bootstrap-macos.sh." >&2
    exit 1
fi

# Friendlier guard for non-Arch pacman environments (rare, but be explicit).
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [ "${ID:-}" != "arch" ] && [[ " ${ID_LIKE:-} " != *" arch "* ]]; then
        echo "Error: This does not look like an Arch-family distro (ID=${ID:-?}, ID_LIKE=${ID_LIKE:-})." >&2
        echo "For Debian/Ubuntu, use bootstrap-linux.sh. For macOS, use bootstrap-macos.sh." >&2
        exit 1
    fi
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
# Determine target home directory from the password database, not $HOME.
# ---------------------------------------------------------------------------
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

# Build deps for the tt++ source build (mirrors the Debian -dev packages). On
# Arch these same packages carry the runtime shared libs too — no -dev split.
# Runtime deps:
#   - lua54 (binary lua5.4), NOT bare `lua`: on current Arch `lua` is Lua 5.5
#     and the cockpit needs 5.4. start.sh's Linux lua-resolution block symlinks
#     lua5.4 into bridge/runtime/bin/lua at launch, so do NOT symlink here.
#   - python-prompt_toolkit keeps the underscore on Arch (unlike Debian's
#     python3-prompt-toolkit).
#   - python-fonttools is the launcher's quadrant-corner font-support backend
#     fallback; fontconfig's fc-list is preferred on Linux, so a missing
#     fonttools only degrades the probe to "block", never breaks startup.
# No terminal package: native Linux is BYO-terminal.
PACKAGES="base-devel pcre2 gnutls zlib pkgconf tmux lua54 git python-prompt_toolkit python-pyperclip python-fonttools"

# --needed makes this idempotent: already-installed packages are skipped.
# shellcheck disable=SC2086  # word-splitting of $PACKAGES is intentional
$RUN pacman -S --needed --noconfirm $PACKAGES

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
    # Build deps already installed above (base-devel pcre2 gnutls zlib pkgconf).

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
        echo "Error: tt++ built without TLS. Ensure gnutls is installed and re-run." >&2
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
# Done
# ---------------------------------------------------------------------------

echo "Installation complete."
echo "Run the cockpit with: cd $REPO_DIR && ./start.sh"

if [ ! -f "$TARGET_HOME/.config/alacritty/alacritty.toml" ]; then
    echo "An example Alacritty config is available at $REPO_DIR/install/examples/alacritty.toml if you want to try it."
fi
