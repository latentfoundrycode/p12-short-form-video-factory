# Per-user SFVF installer (Delivery-Conventions section 3). PowerShell 5.1 compatible.
param(
    [switch]$Silent,
    [switch]$Uninstall,
    [switch]$RemoveData
)
$ErrorActionPreference = 'Stop'

$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\SFVF'
$DataDir = Join-Path $env:LOCALAPPDATA 'SFVF'
$BinDir = Join-Path $InstallDir 'bin'
$Launcher = Join-Path $BinDir 'sfvf.cmd'
$RegKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SFVF'
$RepoRoot = $PSScriptRoot
$MinPython = [version]'3.12.4'
$InstallReport = Join-Path $RepoRoot 'install_report.txt'

function Write-Info([string]$Message) {
    if (-not $Silent) { Write-Host $Message }
}

function Get-PythonVersionFromText([string]$Text) {
    if ($Text -match 'Python\s+(\d+\.\d+\.\d+)') {
        return [version]$Matches[1]
    }
    return $null
}

function Find-PythonExe {
    $candidates = @(
        @{ Cmd = 'py'; Prefix = @('-3.12') },
        @{ Cmd = 'python'; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Cmd -ErrorAction SilentlyContinue)) { continue }
        # PS 5.1: 2>&1 + EAP Stop turns native stderr into a terminating NativeCommandError.
        $savedEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $versionArgs = $candidate.Prefix + @('--version')
            $text = & $candidate.Cmd @versionArgs 2>&1 | Out-String
            $ver = Get-PythonVersionFromText $text
            if (-not $ver -or $ver -lt $MinPython) { continue }
            $probeArgs = $candidate.Prefix + @('-c', 'import sys; print(sys.executable)')
            $exe = (& $candidate.Cmd @probeArgs 2>&1 | Out-String).Trim()
            if ($exe -and (Test-Path -LiteralPath $exe)) { return $exe }
        }
        catch {
            continue
        }
        finally {
            $ErrorActionPreference = $savedEap
        }
    }
    return $null
}

function Test-OnPath([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Prerequisites {
    $missing = New-Object System.Collections.Generic.List[string]
    $pythonExe = Find-PythonExe
    if (-not $pythonExe) {
        [void]$missing.Add("Python $MinPython+  (winget install Python.Python.3.12)")
    }
    if (-not (Test-OnPath 'ffmpeg')) {
        [void]$missing.Add('ffmpeg on PATH  (winget install Gyan.FFmpeg)')
    }
    if (-not (Test-OnPath 'ffprobe')) {
        [void]$missing.Add('ffprobe on PATH  (winget install Gyan.FFmpeg)')
    }
    if (-not (Test-OnPath 'npm')) {
        [void]$missing.Add('Node.js / npm  (winget install OpenJS.NodeJS.LTS)')
    }
    if ($missing.Count -gt 0) {
        Write-Host 'Missing prerequisites. Install the items below, then re-run this installer.'
        foreach ($item in $missing) { Write-Host "  $item" }
        exit 1
    }
    return $pythonExe
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = '',
        [string]$FailMessage
    )
    if ($WorkingDirectory) {
        Push-Location -LiteralPath $WorkingDirectory
        try {
            & $FilePath @ArgumentList
            $code = $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }
    else {
        & $FilePath @ArgumentList
        $code = $LASTEXITCODE
    }
    if ($code -ne 0) {
        if (-not $FailMessage) { $FailMessage = "$FilePath failed with exit code $code" }
        throw $FailMessage
    }
}

function Copy-RuntimeDirectory {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Missing source to copy: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $exclude = @('__pycache__', 'node_modules', '.venv', '.git', 'venvs', 'runs', 'cache', 'library')
    & robocopy.exe $Source $Destination /MIR /XD $exclude /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Copy failed (robocopy $LASTEXITCODE): $Source -> $Destination"
    }
}

function Add-UserPath([string]$Entry) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not [string]::IsNullOrEmpty($userPath)) {
        $normalized = $Entry.TrimEnd('\')
        foreach ($part in ($userPath -split ';')) {
            if ([string]::IsNullOrWhiteSpace($part)) { continue }
            if ($part.TrimEnd('\') -ieq $normalized) { return }
        }
    }
    if ([string]::IsNullOrEmpty($userPath)) {
        $newPath = $Entry
    }
    elseif ($userPath.EndsWith(';')) {
        $newPath = $userPath + $Entry
    }
    else {
        $newPath = $userPath + ';' + $Entry
    }
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
}

function Remove-UserPath([string]$Entry) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([string]::IsNullOrEmpty($userPath)) { return }
    $normalized = $Entry.TrimEnd('\')
    $kept = New-Object System.Collections.Generic.List[string]
    foreach ($part in ($userPath -split ';')) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        if ($part.TrimEnd('\') -ieq $normalized) { continue }
        [void]$kept.Add($part)
    }
    [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
}

function Read-RepoVersion {
    $versionFile = Join-Path $RepoRoot 'VERSION'
    if (-not (Test-Path -LiteralPath $versionFile)) {
        throw "VERSION file not found at $versionFile"
    }
    return (Get-Content -LiteralPath $versionFile -Raw).Trim()
}

function Write-UninstallRegistry([string]$Version) {
    if (-not (Test-Path -LiteralPath $RegKey)) {
        New-Item -Path $RegKey -Force | Out-Null
    }
    $uninstall = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$InstallDir\install.ps1`" -Uninstall"
    Set-ItemProperty -Path $RegKey -Name DisplayName -Value 'SFVF'
    Set-ItemProperty -Path $RegKey -Name DisplayVersion -Value $Version
    Set-ItemProperty -Path $RegKey -Name Publisher -Value 'SFVF'
    Set-ItemProperty -Path $RegKey -Name InstallLocation -Value $InstallDir
    Set-ItemProperty -Path $RegKey -Name UninstallString -Value $uninstall
    New-ItemProperty -Path $RegKey -Name NoModify -PropertyType DWord -Value 1 -Force | Out-Null
    New-ItemProperty -Path $RegKey -Name NoRepair -PropertyType DWord -Value 1 -Force | Out-Null
}

function Write-Launcher {
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $python = Join-Path $InstallDir '.venv\Scripts\python.exe'
    $lines = @(
        '@echo off',
        'set "SFVF_DATA_DIR=%LOCALAPPDATA%\SFVF"',
        "set `"PYTHONPATH=$InstallDir`"",
        "`"$python`" -m app.serve %*"
    )
    [System.IO.File]::WriteAllText($Launcher, ($lines -join "`r`n") + "`r`n")
}

function Confirm-AlreadyInstalled {
    Write-Host 'SFVF is already installed.'
    Write-Host '  [U] Upgrade / reinstall (keeps data)'
    Write-Host '  [N] Uninstall'
    Write-Host '  [C] Cancel'
    while ($true) {
        $answer = Read-Host 'Choose U, N, or C'
        switch -Regex ($answer) {
            '^[uU]' { return 'upgrade' }
            '^[nN]' { return 'uninstall' }
            '^[cC]' { return 'cancel' }
        }
    }
}

function Uninstall-Sfvf {
    Remove-UserPath $BinDir
    if (Test-Path -LiteralPath $RegKey) {
        Remove-Item -LiteralPath $RegKey -Recurse -Force
    }
    if (Test-Path -LiteralPath $InstallDir) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
    $wipeData = [bool]$RemoveData
    if (-not $Silent -and -not $wipeData -and (Test-Path -LiteralPath $DataDir)) {
        $answer = Read-Host "Remove user data at $DataDir as well? [y/N]"
        if ($answer -match '^[yY]') { $wipeData = $true }
    }
    if ($wipeData -and (Test-Path -LiteralPath $DataDir)) {
        Remove-Item -LiteralPath $DataDir -Recurse -Force
    }
}

function Install-Sfvf {
    $pythonExe = Test-Prerequisites
    if (Test-Path -LiteralPath $RegKey) {
        if (-not $Silent) {
            $choice = Confirm-AlreadyInstalled
            if ($choice -eq 'cancel') { exit 0 }
            if ($choice -eq 'uninstall') { Uninstall-Sfvf; exit 0 }
        }
    }

    $version = Read-RepoVersion

    $frontend = Join-Path $RepoRoot 'frontend'
    Write-Info 'Installing frontend dependencies...'
    Invoke-Native -FilePath 'npm' -ArgumentList @('--prefix', $frontend, 'ci') -FailMessage 'npm ci failed. Fix frontend dependencies and re-run the installer.'
    Write-Info 'Building the frontend...'
    Invoke-Native -FilePath 'npm' -ArgumentList @('--prefix', $frontend, 'run', 'build') -FailMessage "Frontend build failed. Fix the errors from 'npm --prefix frontend run build' and re-run the installer."

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $dirs = @('app', 'sdk', 'workflows', 'rules', 'skills', 'assets')
    foreach ($name in $dirs) {
        Copy-RuntimeDirectory -Source (Join-Path $RepoRoot $name) -Destination (Join-Path $InstallDir $name)
    }
    foreach ($name in @('VERSION', 'requirements.txt', 'install.ps1')) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot $name) -Destination (Join-Path $InstallDir $name) -Force
    }

    $venvDir = Join-Path $InstallDir '.venv'
    if (Test-Path -LiteralPath $venvDir) {
        Remove-Item -LiteralPath $venvDir -Recurse -Force
    }
    Write-Info 'Creating the isolated environment...'
    Invoke-Native -FilePath $pythonExe -ArgumentList @('-m', 'venv', $venvDir) -FailMessage "Failed to create venv at $venvDir"
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    Invoke-Native -FilePath $venvPython -ArgumentList @('-m', 'pip', 'install', '-r', 'requirements.txt') -WorkingDirectory $InstallDir -FailMessage 'pip install of requirements.txt failed.'

    Write-Launcher
    Add-UserPath $BinDir
    Write-UninstallRegistry $version

    $installed = @{
        version       = $version
        installed_utc = [DateTime]::UtcNow.ToString('o')
        location      = $InstallDir
    }
    $json = $installed | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $InstallDir 'installed.json'), $json)

    Write-Info "SFVF $version installed. Open a new terminal and run 'sfvf' to start the server."
}

$script:TranscriptStarted = $false
try {
    try {
        Start-Transcript -Path $InstallReport -Force | Out-Null
        $script:TranscriptStarted = $true
    }
    catch {
    }

    try {
        if ($Uninstall) {
            Uninstall-Sfvf
            Write-Host 'SFVF install: SUCCESS'
            exit 0
        }
        Install-Sfvf
        Write-Host 'SFVF install: SUCCESS'
        exit 0
    }
    catch {
        Write-Host $_
        Write-Host "SFVF install: FAILED - $_"
        exit 1
    }
}
finally {
    if ($script:TranscriptStarted) {
        try {
            Stop-Transcript | Out-Null
        }
        catch {
        }
    }
}
