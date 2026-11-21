param(
    [string]$Distro = ""
)

$ErrorActionPreference = "Stop"
$source = $PSScriptRoot

function Get-WslDistros {
    $raw = @(wsl --list --quiet 2>$null)
    return @($raw | ForEach-Object { ($_ -replace "`0", "").Trim() } |
        Where-Object { $_ -and $_ -notmatch 'Windows Subsystem|distribution|子系统' })
}

$distros = Get-WslDistros
if (-not $Distro) {
    if ($distros.Count -eq 0) {
        Write-Host "No WSL distro found. Installing Ubuntu 24.04 (a reboot may be required)..."
        wsl --install -d Ubuntu-24.04
        Write-Host "INSTALL STARTED. Reboot Windows if asked, then run this script again."
        exit 0
    }
    $Distro = $distros[0]
}

Write-Host "==> Using WSL distro: $Distro"
$target = "\\wsl`$$Distro\tmp\jarvis-asterisk"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $source "conf\*") -Destination $target -Force
Copy-Item -Path (Join-Path $source "setup_asterisk_wsl.sh") -Destination $target -Force

Write-Host "==> Configuring Asterisk inside WSL (free, no Twilio)"
$repoRoot = Split-Path $source -Parent
wsl -d $Distro -e bash /tmp/jarvis-asterisk/setup_asterisk_wsl.sh /tmp/jarvis-asterisk "$repoRoot"
if ($LASTEXITCODE -ne 0) {
    throw "Asterisk setup failed inside WSL (exit $LASTEXITCODE)."
}
