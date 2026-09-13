# XGDA one-click real 9:25 stock selector (PowerShell, pure ASCII)
#
# Usage:
#   .\scripts\xgda-live.ps1                    block until 09:25:01, then run
#   .\scripts\xgda-live.ps1 -Once              run immediately (override timing)
#   .\scripts\xgda-live.ps1 -NoL2              disable L2 verify
#   .\scripts\xgda-live.ps1 -XgWeight 0.7      adjust XGDA weight
[CmdletBinding()]
param(
    [switch]$Once = $false,
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
    Write-Error "[xgda-live] cannot find venv python; create .venv first"
    exit 1
}

Write-Host "[xgda-live] starting real 9:25 stock selector..."
Write-Host "[xgda-live] Python: $py"
Write-Host ""

$args = @("scripts/run_real_live.py")
if ($Once) { $args += "--once" } else { $args += "--once" }
if (-not $NoL2) { $args += "--l2-verify" }
$args += @("--xg-weight", "$XgWeight")

& $py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }