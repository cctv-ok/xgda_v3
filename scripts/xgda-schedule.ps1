# XGDA 9:25 Scheduled Task Manager (PowerShell)
# Pure ASCII to avoid GBK/UTF-8 encoding corruption on Windows.
#
# Usage:
#   .\scripts\xgda-schedule.ps1 -Action install
#   .\scripts\xgda-schedule.ps1 -Action uninstall
#   .\scripts\xgda-schedule.ps1 -Action status
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("install","uninstall","status")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$taskName = "XGDA_0925_RealSelect"
$batPath = Join-Path $root "scripts\xgda-live.bat"
$logDir = Join-Path $root "logs"
$logFile = Join-Path $logDir "xgda-schedule.log"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

if (-not (Test-Path $batPath)) {
    Write-Log "[schedule] ERROR: cannot find xgda-live.bat at $batPath"
    exit 1
}

switch ($Action) {
    "install" {
        Write-Log "[schedule] install requested"
        try {
            $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            if ($existing) {
                Write-Log "[schedule] task exists, unregister first"
                Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            }

            Write-Log "[schedule] step 1/5: building task action"
            $taskAction = New-ScheduledTaskAction `
                -Execute $batPath `
                -WorkingDirectory $root

            Write-Log "[schedule] step 2/5: building trigger (weekdays 09:25)"
            $taskTrigger = New-ScheduledTaskTrigger `
                -Weekly `
                -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
                -At "09:25:00"

            Write-Log "[schedule] step 3/5: building principal"
            $taskPrincipal = New-ScheduledTaskPrincipal `
                -UserId $env:USERNAME `
                -LogonType S4U `
                -RunLevel Highest

            Write-Log "[schedule] step 4/5: building settings"
            $taskSettings = New-ScheduledTaskSettingsSet `
                -StartWhenAvailable `
                -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

            Write-Log "[schedule] step 5/5: registering task"
            Register-ScheduledTask `
                -TaskName $taskName `
                -Action $taskAction `
                -Trigger $taskTrigger `
                -Principal $taskPrincipal `
                -Settings $taskSettings `
                -Description "XGDA 9:25 trading session stock selector (weekdays, requires TDX L2 client config)" `
                -Force | Out-Null

            Write-Log "[schedule] OK installed: $taskName"
            Write-Log "  Trigger: weekdays 09:25:00"
            Write-Log "  Command: $batPath"
            Write-Log "  Logfile: $logFile"
        } catch {
            Write-Log "[schedule] FAILED at install: $($_.Exception.Message)"
            Write-Log "  Stack: $($_.ScriptStackTrace)"
            exit 2
        }
    }

    "uninstall" {
        Write-Log "[schedule] uninstall requested"
        $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $existing) {
            Write-Log "[schedule] task not found, nothing to do"
            exit 0
        }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Log "[schedule] OK uninstalled: $taskName"
    }

    "status" {
        $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $existing) {
            Write-Log "[schedule] task NOT installed: $taskName"
            exit 0
        }
        Write-Log "[schedule] task FOUND: $taskName"
        Write-Log "  State:   $($existing.State)"
        Write-Log "  Actions: $($existing.Actions.Execute -join '; ')"
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        if ($info) {
            Write-Log "  LastRun: $($info.LastRunTime)"
            Write-Log "  NextRun: $($info.NextRunTime)"
        }
        foreach ($t in $existing.Triggers) {
            if ($t.DaysOfWeek) {
                Write-Log "  Days:    $($t.DaysOfWeek -join ',')"
            }
            if ($t.StartBoundary) {
                Write-Log "  Start:   $($t.StartBoundary)"
            }
        }
    }
}