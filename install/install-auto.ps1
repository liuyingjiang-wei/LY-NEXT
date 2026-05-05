param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
$win = Join-Path $here "install-windows.ps1"
$unix = Join-Path $here "install.sh"

if ($IsWindows) {
    Write-Host "Detected Windows. Running install-windows.ps1" -ForegroundColor Cyan
    if ($DryRun) { Write-Host "[DryRun] $win" -ForegroundColor DarkYellow; exit 0 }
    & powershell -ExecutionPolicy Bypass -File $win
    exit $LASTEXITCODE
}

Write-Host "Detected non-Windows. Running install.sh" -ForegroundColor Cyan
if ($DryRun) { Write-Host "[DryRun] bash $unix" -ForegroundColor DarkYellow; exit 0 }
& bash $unix
exit $LASTEXITCODE

