# installer-core.ps1 -- MUME Cockpit Windows installer
#
# Requires Windows 11 22H2 (build 22621) or newer. Older Windows is rejected
# at pre-flight because WSL2 mirrored networking -- required for MMapper mode
# -- is not available on earlier builds.
#
# Run via cockpit-installer.bat, which handles UAC elevation automatically.
# Safe to re-run: every step checks state before acting, so a second run
# on the same machine produces no destructive changes.
#
# To start over: remove the "MUME Cockpit" Start Menu entry (via Settings or
# by deleting /usr/share/applications/mume-cockpit.desktop inside WSL),
# run 'wsl --unregister Ubuntu' in an admin PowerShell, then double-click
# cockpit-installer.bat again.

Write-Host ""
Write-Host "MUME Cockpit -- Windows Installer"
Write-Host "================================="
Write-Host ""

# -- Step 1: Pre-flight checks ------------------------------------------------

# Elevation -- should always pass when launched via the .bat, but checked
# here as defence in depth in case someone runs the .ps1 directly.
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run as Administrator."
    Write-Host "       Double-click cockpit-installer.bat instead of running this .ps1 directly."
    exit 1
}

# Windows build -- mirrored networking requires Windows 11 22H2 (build 22621)+.
$build = [Environment]::OSVersion.Version.Build
Write-Host "Windows build: $build"
if ($build -lt 22621) {
    Write-Host ""
    Write-Host "ERROR: This installer requires Windows 11 22H2 (build 22621) or newer."
    Write-Host "       Detected build: $build."
    Write-Host "       The cockpit needs WSL2 mirrored networking for MMapper mode,"
    Write-Host "       which is only available on Windows 11 22H2+. Older versions"
    Write-Host "       of Windows are not supported."
    Write-Host ""
    Write-Host "       If you only intend to play in direct mode (no MMapper), you"
    Write-Host "       can install the cockpit manually inside WSL using"
    Write-Host "       install/bootstrap-linux.sh -- but the Start Menu entry and"
    Write-Host "       foot config must then be set up by hand."
    exit 1
}

# VirtualMachinePlatform and WSL feature -- a Win 11 22H2 machine can still
# have WSL disabled (uncommon but possible). Instruct the user to enable it
# manually and re-run.
Write-Host "Checking WSL prerequisites..."
$vmp = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
if ($vmp.State -ne 'Enabled') {
    Write-Host ""
    Write-Host "WSL2 is not enabled on this machine. Enable it first by running:"
    Write-Host ""
    Write-Host "    wsl --install"
    Write-Host ""
    Write-Host "in an admin PowerShell, then reboot, and re-run this installer."
    exit 1
}

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
if ($wslFeature.State -ne 'Enabled') {
    Write-Host ""
    Write-Host "WSL2 is not enabled on this machine. Enable it first by running:"
    Write-Host ""
    Write-Host "    wsl --install"
    Write-Host ""
    Write-Host "in an admin PowerShell, then reboot, and re-run this installer."
    exit 1
}

# Internet connectivity.
Write-Host "Checking internet connectivity..."
try {
    Invoke-WebRequest -UseBasicParsing -Method Head https://github.com -TimeoutSec 5 | Out-Null
} catch {
    Write-Host ""
    Write-Host "ERROR: No internet connection detected."
    Write-Host "       Please check your network and try again."
    exit 1
}

Write-Host "Pre-flight checks passed."
Write-Host ""

# -- Step 2: Install Ubuntu ---------------------------------------------------
#
# --no-launch is critical: without it, wsl --install opens the Ubuntu OOBE
# first-run dialog and blocks the script waiting for a username and password.

Write-Host "Checking WSL Ubuntu distribution..."

# wsl --list --quiet outputs UTF-16 with embedded null bytes on some Windows
# versions; strip nulls before matching so the check is reliable.
$wslList = & wsl --list --quiet 2>&1 | ForEach-Object { "$_" -replace '\x00', '' }

# Priority: exact 'Ubuntu' > first 'Ubuntu*' match > install fresh 'Ubuntu'.
$distroName = $null
$exactMatch = $wslList | Where-Object { $_.Trim() -eq 'Ubuntu' } | Select-Object -First 1
if ($exactMatch) {
    $distroName = 'Ubuntu'
} else {
    $prefixMatch = $wslList | Where-Object { $_ -match '^Ubuntu' } | Select-Object -First 1
    if ($prefixMatch) {
        $distroName = $prefixMatch.Trim()
    }
}

if ($distroName) {
    Write-Host "Using WSL distribution: $distroName"
} else {
    Write-Host "Installing Ubuntu (this may take several minutes)..."
    & wsl --install -d Ubuntu --no-launch
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ERROR: 'wsl --install -d Ubuntu --no-launch' failed (exit code $LASTEXITCODE)."
        Write-Host "       Try running it manually in an admin PowerShell and check the output."
        exit 1
    }
    $distroName = 'Ubuntu'
    Write-Host "Using WSL distribution: $distroName"
}
Write-Host ""

# -- Step 3: Write %UserProfile%\.wslconfig -----------------------------------
#
# networkingMode=mirrored lets processes inside WSL reach services listening
# on localhost on the Windows host (e.g. MMapper on port 4242).
# All supported builds (22H2+) support this setting.
#
# Never overwrite an existing .wslconfig -- the user's existing config is theirs.

$wroteWslConfig = $false
$wslConfigPath = Join-Path $env:USERPROFILE '.wslconfig'
if (Test-Path $wslConfigPath) {
    $existing = Get-Content $wslConfigPath -Raw
    if ($existing -match 'networkingMode\s*=\s*mirrored') {
        Write-Host ".wslconfig already contains networkingMode=mirrored -- skipping."
    } else {
        Write-Host ""
        Write-Host "WARNING: $wslConfigPath already exists with different contents."
        Write-Host "         It has not been modified. For MMapper mode to work, add"
        Write-Host "         the following line under [wsl2] in that file manually:"
        Write-Host ""
        Write-Host "             networkingMode=mirrored"
        Write-Host ""
    }
} else {
    "[wsl2]`r`nnetworkingMode=mirrored" | Set-Content -Path $wslConfigPath -Encoding UTF8
    Write-Host "Wrote $wslConfigPath with networkingMode=mirrored."
    $wroteWslConfig = $true
}

# -- Step 4: Cycle WSL --------------------------------------------------------
#
# .wslconfig changes only take effect after a full WSL shutdown.
# Skip if we did not write the file -- no need to interrupt a running WSL.

if ($wroteWslConfig) {
    Write-Host "Restarting WSL so .wslconfig takes effect..."
    & wsl --shutdown
    Write-Host "WSL restarted."
}
Write-Host ""

# -- Step 4b: Detect primary monitor resolution -------------------------------
#
# foot's initial-window-size-pixels (windowed mode) defaults to ~60% width
# x ~80% height of the primary monitor. We detect on the Windows side because
# in-WSL detection under WSLg's Wayland/RAIL has no reliable single-screen
# query -- see ADR 0107 point 4. The bootstrap reads MUME_FOOT_WINDOW_PX and
# seeds the placed foot.ini. Detection failure must never abort the install:
# we simply leave the variable unset and the bootstrap keeps the template
# placeholder. DPI scaling may yield logical rather than physical pixels;
# that is acceptable -- this is a sensible default, not a pixel-exact value.

$footWindowPx = $null
try {
    Add-Type -AssemblyName System.Windows.Forms
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    if ($bounds.Width -gt 0 -and $bounds.Height -gt 0) {
        $w = [int][Math]::Round($bounds.Width  * 0.60)
        $h = [int][Math]::Round($bounds.Height * 0.80)
        if ($w -lt 800) { $w = 800 }
        if ($h -lt 600) { $h = 600 }
        $footWindowPx = "${w}x${h}"
        Write-Host "Primary monitor: $($bounds.Width)x$($bounds.Height) -- seeding foot window size $footWindowPx."
    }
} catch {
    Write-Host "Could not detect primary monitor resolution -- foot.ini will keep its template default."
}
Write-Host ""

# -- Step 5: Run Linux bootstrap ----------------------------------------------
#
# All Linux-side provisioning (tmux, Lua, TinTin++, Python, repo clone) is
# delegated to bootstrap-linux.sh, which already exists and is tested.
# Running as root inside WSL is intentional: the cockpit has no sudo paths.
# The .desktop entry installed inside WSL invokes /root/MUME/bridge/supervisor.sh
# directly, so the root user is implicit (no -u root flag visible to the user).

Write-Host "Running Linux bootstrap inside Ubuntu (as root)..."
Write-Host "This installs tmux, Lua, TinTin++, and the cockpit repo."
Write-Host ""

$bootstrapCmd = "curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-linux.sh | bash"
if ($footWindowPx) {
    $bootstrapCmd = "export MUME_FOOT_WINDOW_PX=$footWindowPx; $bootstrapCmd"
}
& wsl -d $distroName -u root -- bash -c $bootstrapCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Linux bootstrap failed (exit code $LASTEXITCODE)."
    Write-Host "       Check the output above. Once you've fixed the issue, re-run this"
    Write-Host "       installer -- it is safe to run again."
    exit 1
}
Write-Host ""
Write-Host "Linux bootstrap complete."
Write-Host ""

# -- Step 5a: Cycle WSL so /etc/wsl.conf takes effect -------------------------
#
# The bootstrap writes /etc/wsl.conf with [user] default=root so WSLg launches
# the .desktop's Exec as root (the cockpit lives under /root/MUME). That
# setting is only honoured after a full WSL shutdown. We do this unconditionally
# here even if Step 4 already restarted WSL — a fresh distro install or a
# pre-existing distro that just got its first /etc/wsl.conf both need it.

Write-Host "Restarting WSL so /etc/wsl.conf default user takes effect..."
& wsl --shutdown
Write-Host "WSL restarted."
Write-Host ""

# -- Step 5b: Verify cockpit artifacts ----------------------------------------
#
# The WSLg .desktop entry invokes bridge/supervisor.sh, which in turn calls
# start.sh. Probe both now so a partially-failed bootstrap fails loudly here
# instead of leaving a broken Start Menu entry.

Write-Host "Verifying cockpit installation..."
& wsl -d $distroName -u root -- test -x /root/MUME/bridge/supervisor.sh
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Cockpit installation looks incomplete."
    Write-Host "       /root/MUME/bridge/supervisor.sh is missing or not executable."
    Write-Host "       This usually means the bootstrap step did not finish cleanly."
    Write-Host "       Re-run this installer; if the problem persists, file an issue."
    exit 1
}
& wsl -d $distroName -u root -- test -x /root/MUME/start.sh
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: /root/MUME/start.sh is missing or not executable."
    Write-Host "       Re-run this installer; if the problem persists, file an issue."
    exit 1
}
Write-Host "Verification passed."
Write-Host ""

# -- Step 6: Done -------------------------------------------------------------
#
# Alacritty install, alacritty.toml write, and Windows desktop-shortcut
# creation have all moved to WSL: foot is installed by bootstrap-linux.sh,
# foot.ini is copied from install/examples/foot.ini, and the .desktop entry
# at /usr/share/applications/mume-cockpit.desktop is surfaced to the
# Windows Start Menu by WSLg automatically.

Write-Host "Installation complete."
Write-Host "A ""MUME Cockpit"" entry has been added to your Windows Start Menu."
Write-Host "Search for it from the Start Menu, or pin it to the taskbar, to launch."
Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "  RECOMMENDED: Restart Windows before launching MUME Cockpit" -ForegroundColor Yellow
Write-Host "  for the first time. This lets the WSL graphics subsystem" -ForegroundColor Yellow
Write-Host "  start cleanly." -ForegroundColor Yellow
Write-Host ""
Write-Host "  If the cockpit window appears blank on first launch," -ForegroundColor Yellow
Write-Host "  restart Windows and try again." -ForegroundColor Yellow
Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
