# Run from an elevated PowerShell (Set-ScheduledTask needs admin rights):
#   cd "C:\Users\Eva Ng\Desktop\ironman\repo"
#   .\scripts\fix_task_logontype.ps1
#
# Switches every CommsPlatform* scheduled task from LogonType=Interactive
# (only fires while the account is logged in) to S4U (fires on schedule
# regardless of logged-in state, no stored password needed) — see
# runbook.md "Found broken #2" for why this matters.

$tasks = @(
    "CommsPlatformOutlookSync",
    "CommsPlatformLinkedInSync-0900",
    "CommsPlatformLinkedInSync-1230",
    "CommsPlatformLinkedInSync-1530",
    "CommsPlatformLinkedInSync-1900",
    "CommsPlatformMonitor"
)

foreach ($t in $tasks) {
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
    Set-ScheduledTask -TaskName $t -Principal $principal
    Write-Output "fixed: $t"
}

Write-Output ""
Write-Output "--- verifying ---"
foreach ($t in $tasks) {
    $task = Get-ScheduledTask -TaskName $t
    Write-Output "$t | LogonType=$($task.Principal.LogonType)"
}
