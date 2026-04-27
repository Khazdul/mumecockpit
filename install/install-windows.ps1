# install-windows.ps1 — MUME Cockpit Windows installer (fast path)
#
# Run via install-windows.bat, which handles UAC elevation automatically.
# Safe to re-run: every step checks state before acting, so a second run
# on the same machine produces no destructive changes.
#
# To start over: delete the desktop shortcut, run 'wsl --unregister Ubuntu'
# in an admin PowerShell, then double-click install-windows.bat again.

Write-Host ""
Write-Host "MUME Cockpit — Windows Installer"
Write-Host "================================="
Write-Host ""

# ── Step 1: Pre-flight checks ────────────────────────────────────────────────

# Elevation — should always pass when launched via the .bat, but checked
# here as defence in depth in case someone runs the .ps1 directly.
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: This script must be run as Administrator."
    Write-Host "       Double-click install-windows.bat instead of running this .ps1 directly."
    exit 1
}

# Windows build — WSL2 requires 19041+.
$build = [Environment]::OSVersion.Version.Build
Write-Host "Windows build: $build"
if ($build -lt 19041) {
    Write-Host ""
    Write-Host "ERROR: Your Windows version (build $build) is not supported."
    Write-Host "       WSL2 requires Windows 10 build 19041 or newer."
    exit 1
}

# VirtualMachinePlatform and WSL feature — if either is Disabled the machine
# needs a reboot to enable them, which the fast-path installer cannot do.
Write-Host "Checking WSL prerequisites..."
$vmp = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
if ($vmp.State -ne 'Enabled') {
    Write-Host ""
    Write-Host "WSL2 is not enabled on this machine. The slow-path installer that"
    Write-Host "handles this case is not yet available. For now, run:"
    Write-Host ""
    Write-Host "    wsl --install"
    Write-Host ""
    Write-Host "in an admin PowerShell, reboot, then re-run this installer."
    exit 1
}

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
if ($wslFeature.State -ne 'Enabled') {
    Write-Host ""
    Write-Host "WSL2 is not enabled on this machine. The slow-path installer that"
    Write-Host "handles this case is not yet available. For now, run:"
    Write-Host ""
    Write-Host "    wsl --install"
    Write-Host ""
    Write-Host "in an admin PowerShell, reboot, then re-run this installer."
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

# ── Step 2: Detect Windows 11 22H2+ ─────────────────────────────────────────
#
# networkingMode=mirrored requires build 22621 (Windows 11 22H2) or newer.
# On older Windows, MMapper mode is unavailable; the user must use direct mode.

$useMirrored = ($build -ge 22621)
if ($useMirrored) {
    Write-Host "Windows 11 22H2+ detected — mirrored networking will be configured."
} else {
    Write-Host "Pre-22H2 Windows detected — mirrored networking is not available."
}
Write-Host ""

# ── Step 3: Install Ubuntu ───────────────────────────────────────────────────
#
# --no-launch is critical: without it, wsl --install opens the Ubuntu OOBE
# first-run dialog and blocks the script waiting for a username and password.

Write-Host "Checking WSL Ubuntu distribution..."

# wsl --list --quiet outputs UTF-16 with embedded null bytes on some Windows
# versions; strip nulls before matching so the check is reliable.
$wslList = & wsl --list --quiet 2>&1 | ForEach-Object { "$_" -replace '\x00', '' }
$ubuntuInstalled = $wslList | Where-Object { $_ -match 'Ubuntu' }

if ($ubuntuInstalled) {
    Write-Host "Ubuntu is already registered in WSL — skipping installation."
} else {
    Write-Host "Installing Ubuntu (this may take several minutes)..."
    & wsl --install -d Ubuntu --no-launch
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "ERROR: 'wsl --install -d Ubuntu --no-launch' failed (exit code $LASTEXITCODE)."
        Write-Host "       Try running it manually in an admin PowerShell and check the output."
        exit 1
    }
    Write-Host "Ubuntu installed."
}
Write-Host ""

# ── Step 4: Write %UserProfile%\.wslconfig ───────────────────────────────────
#
# networkingMode=mirrored lets processes inside WSL reach services listening
# on localhost on the Windows host (e.g. MMapper on port 4242).
# Only write on Windows 11 22H2+; the setting is silently ignored on older
# builds but we avoid writing a confusing config on machines that can't use it.
#
# Never overwrite an existing .wslconfig — the user's existing config is theirs.

$wroteWslConfig = $false
if ($useMirrored) {
    $wslConfigPath = Join-Path $env:USERPROFILE '.wslconfig'
    if (Test-Path $wslConfigPath) {
        $existing = Get-Content $wslConfigPath -Raw
        if ($existing -match 'networkingMode\s*=\s*mirrored') {
            Write-Host ".wslconfig already contains networkingMode=mirrored — skipping."
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
}

# ── Step 5: Cycle WSL ────────────────────────────────────────────────────────
#
# .wslconfig changes only take effect after a full WSL shutdown.
# Skip if we did not write the file — no need to interrupt a running WSL.

if ($wroteWslConfig) {
    Write-Host "Restarting WSL so .wslconfig takes effect..."
    & wsl --shutdown
    Write-Host "WSL restarted."
}
Write-Host ""

# ── Step 6: Run Linux bootstrap ──────────────────────────────────────────────
#
# All Linux-side provisioning (tmux, Lua, TinTin++, Python, repo clone) is
# delegated to bootstrap-linux.sh, which already exists and is tested.
# Running as root inside WSL is intentional: the cockpit has no sudo paths
# and the desktop shortcut makes the -u root flag visible to the user.

Write-Host "Running Linux bootstrap inside Ubuntu (as root)..."
Write-Host "This installs tmux, Lua, TinTin++, and the cockpit repo."
Write-Host ""

& wsl -d Ubuntu -u root -- bash -c "curl -fsSL https://raw.githubusercontent.com/Khazdul/mumecockpit/main/install/bootstrap-linux.sh | bash"
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Linux bootstrap failed (exit code $LASTEXITCODE)."
    Write-Host "       Check the output above. Once you've fixed the issue, re-run this"
    Write-Host "       installer — it is safe to run again."
    exit 1
}
Write-Host ""
Write-Host "Linux bootstrap complete."
Write-Host ""

# ── Step 7: Install Alacritty ────────────────────────────────────────────────
#
# Prefer winget (present on Windows 10 1809+ and Windows 11).
# Fall back to downloading the MSI from the latest GitHub release.
# Skip entirely if alacritty is already on PATH.

Write-Host "Checking Alacritty..."

$alacrittyCmd = Get-Command alacritty -ErrorAction SilentlyContinue
if ($alacrittyCmd) {
    Write-Host "Alacritty is already installed at $($alacrittyCmd.Source) — skipping."
} else {
    $installed = $false

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Alacritty via winget..."
        & winget install --id Alacritty.Alacritty --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) {
            $installed = $true
            Write-Host "Alacritty installed via winget."
        } else {
            Write-Host "winget install failed (exit code $LASTEXITCODE) — trying MSI fallback."
        }
    } else {
        Write-Host "winget not found — trying MSI fallback."
    }

    if (-not $installed) {
        try {
            Write-Host "Fetching latest Alacritty release info from GitHub..."
            $release = Invoke-RestMethod -Uri "https://api.github.com/repos/alacritty/alacritty/releases/latest"
            $msiAsset = $release.assets | Where-Object { $_.name -like "*.msi" } | Select-Object -First 1
            if (-not $msiAsset) { throw "No .msi asset found in latest Alacritty release." }

            $msiPath = Join-Path $env:TEMP $msiAsset.name
            Write-Host "Downloading $($msiAsset.name)..."
            Invoke-WebRequest -UseBasicParsing -Uri $msiAsset.browser_download_url -OutFile $msiPath
            Write-Host "Running MSI installer..."
            Start-Process msiexec -ArgumentList "/i `"$msiPath`" /qn" -Wait -NoNewWindow
            $installed = $true
            Write-Host "Alacritty installed via MSI."
        } catch {
            Write-Host ""
            Write-Host "ERROR: Could not install Alacritty automatically: $_"
            Write-Host "       Please install it manually from:"
            Write-Host "       https://github.com/alacritty/alacritty/releases"
            Write-Host "       Then re-run this installer."
            exit 1
        }
    }

    # Refresh PATH from the system and user environment so Get-Command picks
    # up the newly installed alacritty.exe in the same session.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}
Write-Host ""

# ── Step 8: Write %APPDATA%\alacritty\alacritty.toml ─────────────────────────
#
# Write the canonical Windows config only if no config file exists yet.
# The user's existing alacritty.toml is never overwritten.

$alacrittyConfigDir  = Join-Path $env:APPDATA 'alacritty'
$alacrittyConfigPath = Join-Path $alacrittyConfigDir 'alacritty.toml'

if (Test-Path $alacrittyConfigPath) {
    Write-Host "Alacritty config already exists at $alacrittyConfigPath — not overwriting."
} else {
    New-Item -ItemType Directory -Path $alacrittyConfigDir -Force | Out-Null
    $tomlLines = @(
        '# Alacritty config - MUME Cockpit, Windows.',
        '# Written by install-windows.ps1. Edit freely; the installer will not touch',
        '# this file on subsequent runs.',
        '',
        '[colors.primary]',
        'foreground = "#C0C0C0"',
        'background = "#000000"',
        '',
        '[colors.normal]',
        'black   = "#000000"',
        'red     = "#800000"',
        'green   = "#008000"',
        'yellow  = "#808000"',
        'blue    = "#000080"',
        'magenta = "#800080"',
        'cyan    = "#008080"',
        'white   = "#C0C0C0"',
        '',
        '[colors.bright]',
        'black   = "#808080"',
        'red     = "#FF0000"',
        'green   = "#00FF00"',
        'yellow  = "#FFFF00"',
        'blue    = "#0000FF"',
        'magenta = "#FF00FF"',
        'cyan    = "#00FFFF"',
        'white   = "#FFFFFF"',
        '',
        '[cursor]',
        'style = { shape = "Beam", blinking = "On" }',
        'blink_interval = 500',
        'thickness = 0.15',
        '',
        '[window]',
        'startup_mode = "Windowed"',
        'padding = { x = 6, y = 6 }',
        'dynamic_padding = true',
        'decorations = "Full"',
        '',
        '[font]',
        'size = 15',
        '',
        '[font.normal]',
        'family = "Lucida Console"',
        '',
        '[font.bold]',
        'family = "Lucida Console"',
        '',
        '[font.italic]',
        'family = "Lucida Console"',
        '',
        '[font.bold_italic]',
        'family = "Lucida Console"',
        '',
        '[terminal.shell]',
        'program = "wsl.exe"',
        'args = ["-d", "Ubuntu", "-u", "root"]',
        '',
        '[scrolling]',
        'history = 10000',
        '',
        '[selection]',
        'save_to_clipboard = true'
    )
    $tomlLines | Set-Content -Path $alacrittyConfigPath -Encoding UTF8
    Write-Host "Wrote $alacrittyConfigPath."
}
Write-Host ""

# ── Step 9: Create desktop shortcut ──────────────────────────────────────────
#
# Overwrites any existing shortcut — it is a regenerable artifact, not user
# state. Resolves alacritty.exe via Get-Command so the path is correct
# regardless of whether winget or MSI installed it.

Write-Host "Creating desktop shortcut..."

# Refresh PATH one more time in case Alacritty was just installed above.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

$alacrittyCmd = Get-Command alacritty -ErrorAction SilentlyContinue
if ($alacrittyCmd) {
    $alacrittyExe = $alacrittyCmd.Source
} else {
    # Common install locations as a fallback when PATH isn't updated yet.
    $alacrittyExe = $null
    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Alacritty\alacritty.exe",
        "$env:ProgramFiles\Alacritty\alacritty.exe"
    )) {
        if (Test-Path $candidate) { $alacrittyExe = $candidate; break }
    }
    if (-not $alacrittyExe) {
        Write-Host "WARNING: Could not locate alacritty.exe. The shortcut will use"
        Write-Host "         'alacritty.exe' and requires it to be on PATH at launch time."
        $alacrittyExe = "alacritty.exe"
    }
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MUME Cockpit.lnk'
$wsh      = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath   = $alacrittyExe
$shortcut.Arguments    = '-e wsl -d Ubuntu -u root -- bash -lc "cd /root/MUME && ./start.sh"'
$shortcut.IconLocation = "$alacrittyExe,0"
$shortcut.Save()
Write-Host "Desktop shortcut created: $shortcutPath"
Write-Host ""

# ── Step 10: Done ────────────────────────────────────────────────────────────

Write-Host "Installation complete."
Write-Host "A ""MUME Cockpit"" shortcut has been added to your desktop."
Write-Host "Double-click it to launch."

if (-not $useMirrored) {
    Write-Host ""
    Write-Host "Note: MMapper mode requires 'networkingMode=mirrored' in .wslconfig,"
    Write-Host "which is only available on Windows 11 22H2 (build 22621) or newer."
    Write-Host "Your Windows version does not support it. You can play in direct mode."
    Write-Host "See docs/install-bootstrap.md for details."
}
Write-Host ""
