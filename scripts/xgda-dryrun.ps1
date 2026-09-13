# XGDA one-click dry-run (PowerShell, pure ASCII to avoid GBK/UTF-8 corruption)
#
# Usage:
#   .\scripts\xgda-dryrun.ps1                    default args
#   .\scripts\xgda-dryrun.ps1 -NoL2              disable L2 verify
#   .\scripts\xgda-dryrun.ps1 -XgWeight 0.7      adjust XGDA weight
[CmdletBinding()]
param(
    [switch]$NoL2 = $false,
    [double]$XgWeight = 0.6
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$pyWin = Join-Path $root ".venv\Scripts\python.exe"
$pyNix = Join-Path $root ".venv/bin/python"

if (Test-Path $pyWin) { $py = $pyWin }
elseif (Test-Path $pyNix) { $py = $pyNix }
else {
    Write-Error "[xgda-dryrun] cannot find venv python; create .venv first"
    exit 1
}

Write-Host "[xgda-dryrun] starting mock + L2 link verification..."
Write-Host "[xgda-dryrun] Python: $py"
Write-Host ""

$args = @("scripts/run_real_live.py", "--dry")
if (-not $NoL2) { $args += "--l2-verify" }
$args += @("--xg-weight", "$XgWeight")

& $py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }