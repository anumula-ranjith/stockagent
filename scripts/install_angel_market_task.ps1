$ErrorActionPreference = 'Stop'
$taskName = 'QUANTORA Angel One Market Data'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'The project virtual environment is missing.' }
$action = New-ScheduledTaskAction -Execute $python -Argument '-m scripts.refresh_angel_market' -WorkingDirectory $root
$ist = [TimeZoneInfo]::FindSystemTimeZoneById('India Standard Time')
$nowIst = [TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $ist)
$first = $nowIst.Date.AddHours(15).AddMinutes(16)
if ($first -le $nowIst) { $first = $first.AddDays(1) }
$trigger = New-ScheduledTaskTrigger -Daily -At $first
$trigger.StartBoundary = ([datetimeoffset]::new([datetime]::SpecifyKind($first, 'Unspecified'), $ist.BaseUtcOffset)).ToString('yyyy-MM-ddTHH:mm:sszzz')
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 4 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$description = 'Capture NSE cash quotes at 15:16 IST on trading days. Credentials are loaded from the project environment at execution.'
try {
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Description $description -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
} catch [Microsoft.Management.Infrastructure.CimException] {
    if ($_.CategoryInfo.Category -ne 'PermissionDenied') { throw }
    # Windows can restrict background logon registration to administrators.
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Description $description -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
}
Get-ScheduledTask -TaskName $taskName | Format-Table TaskName, State, @{n='Logon';e={$_.Principal.LogonType}}
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime
