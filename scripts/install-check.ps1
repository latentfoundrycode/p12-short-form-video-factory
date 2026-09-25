<#
.SYNOPSIS
    PKG-4 lifecycle verification for the SFVF installer (Delivery-Conventions section 3).

    Proves install.ps1 silently and reversibly, per-user (no admin), following the six steps:
    precondition (not installed) -> install -> verify (files, launcher on the user PATH, `sfvf
    --version`, Apps & features entry) -> a data marker survives a reinstall (upgrade in place) ->
    uninstall removes the program + PATH + registry entry and KEEPS the data marker -> cleanup.

    This is the frozen contract for PKG-3: run it from the repo root with the runtime prerequisites
    present (Python 3.12.4+, ffmpeg/ffprobe, Node for the frontend build). It modifies the current
    user's %LOCALAPPDATA% and PATH registry entry only, and reverses every change (including the data
    it creates) before it exits, so it is safe to run on the owner's machine (Installer verification:
    local). Prints PASS, or the first failing assertion and exits non-zero.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Install = Join-Path $RepoRoot 'install.ps1'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\SFVF'
$DataDir = Join-Path $env:LOCALAPPDATA 'SFVF'
$Launcher = Join-Path $InstallDir 'bin\sfvf.cmd'
$RegKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SFVF'
$Version = (Get-Content (Join-Path $RepoRoot 'VERSION') -Raw).Trim()
$Marker = Join-Path $DataDir 'install-check-marker.txt'
$Report = Join-Path $RepoRoot 'install_report.txt'

function Fail([string]$msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }
function Step([string]$msg) { Write-Host "-- $msg" -ForegroundColor Cyan }

function Test-Installed {
    return (Test-Path $InstallDir) -or (Test-Path $RegKey)
}

# --- 1. Precondition: a clean machine (refuse to run over an existing install so the check is honest)
Step 'precondition: SFVF is not installed'
if (Test-Installed) { Fail "SFVF already installed at $InstallDir / $RegKey - run uninstall first" }
if (Test-Path $Marker) { Remove-Item $Marker -Force }

try {
    # --- 2. Install silently -----------------------------------------------------------------------
    Step 'install (silent)'
    & $Install -Silent
    if ($LASTEXITCODE -ne 0) { Fail "install.ps1 -Silent exited $LASTEXITCODE" }

    # --- 3. Verify: files, launcher, PATH entry, version, Apps & features ---------------------------
    Step 'verify install'
    if (-not (Test-Path $InstallDir)) { Fail "install dir missing: $InstallDir" }
    if (-not (Test-Path $Launcher)) { Fail "launcher missing: $Launcher" }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $binDir = Split-Path $Launcher -Parent
    if ($userPath -notlike "*$binDir*") { Fail "launcher bin dir not on the user PATH: $binDir" }
    if (-not (Test-Path $RegKey)) { Fail "Apps & features entry missing: $RegKey" }
    $dv = (Get-ItemProperty $RegKey).DisplayVersion
    if ($dv -ne $Version) { Fail "Apps & features DisplayVersion '$dv' != VERSION '$Version'" }
    if (-not (Test-Path $Report)) { Fail "install_report.txt was not written to $Report" }
    # Run the launcher by full path (avoids PATH-propagation flakiness in this process).
    $out = & $Launcher --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "sfvf --version exited $LASTEXITCODE" }
    if (($out -join "`n") -notmatch [regex]::Escape($Version)) { Fail "sfvf --version did not print '$Version': $out" }

    # --- 4. Data marker (in the data dir, outside the install dir) ----------------------------------
    Step 'write a data marker'
    if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Force -Path $DataDir | Out-Null }
    'keep me across upgrade and uninstall' | Set-Content -Path $Marker -Encoding utf8

    # --- 5. Upgrade in place: reinstall, marker survives, still one registry entry ------------------
    Step 'upgrade in place (reinstall silent)'
    & $Install -Silent
    if ($LASTEXITCODE -ne 0) { Fail "install.ps1 -Silent (upgrade) exited $LASTEXITCODE" }
    if (-not (Test-Path $Marker)) { Fail 'data marker did not survive the upgrade' }
    if (-not (Test-Path $RegKey)) { Fail 'Apps & features entry missing after upgrade' }

    # --- 6. Uninstall: program/PATH/registry gone, data KEPT ----------------------------------------
    Step 'uninstall (silent) keeps data'
    & $Install -Uninstall -Silent
    if ($LASTEXITCODE -ne 0) { Fail "install.ps1 -Uninstall -Silent exited $LASTEXITCODE" }
    if (Test-Path $InstallDir) { Fail "install dir not removed on uninstall: $InstallDir" }
    if (Test-Path $RegKey) { Fail 'Apps & features entry not removed on uninstall' }
    $userPath2 = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath2 -like "*$binDir*") { Fail 'launcher bin dir still on the user PATH after uninstall' }
    if (-not (Test-Path $Marker)) { Fail 'uninstall wrongly removed the user data marker' }

    Write-Host 'PASS' -ForegroundColor Green
    exit 0
}
finally {
    # --- Cleanup: reverse everything this check created, best-effort --------------------------------
    if (Test-Installed) { try { & $Install -Uninstall -Silent } catch { } }
    if (Test-Path $DataDir) { try { Remove-Item $DataDir -Recurse -Force } catch { } }
    if (Test-Path $Report) { try { Remove-Item $Report -Force } catch { } }
}
