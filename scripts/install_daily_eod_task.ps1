$ErrorActionPreference = 'Stop'
$taskName = 'Stock Agents NSE Daily EOD'
$launcher = Join-Path $PSScriptRoot 'run_daily_eod.ps1'
$powershellPath = (Get-Command powershell.exe).Source
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $launcher + '"'
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments
# Every quarter-hour, the Python entrypoint checks the 18:30 IST due date and
# PostgreSQL completion record. Missed runs catch up after the machine resumes.
$trigger = New-ScheduledTaskTrigger -Once -At ([DateTime]::Today) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Select-Object TaskName, State
