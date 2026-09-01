# Run from an elevated PowerShell (right-click PowerShell -> Run as administrator):
#   cd "C:\Users\Eva Ng\Desktop\ironman\repo"
#   .\scripts\fix_whatsapp_task_startup.ps1
#
# Re-registers CommsPlatformWhatsApp and CommsPlatformDashboard to:
# 1. Start automatically when Windows boots (AtStartup trigger)
# 2. Keep running even if nobody is logged in (LogonType S4U)

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

$tasks = @{
    "CommsPlatformWhatsApp"   = "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_whatsapp_connector.bat"
    "CommsPlatformDashboard"  = "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_dashboard.bat"
}

foreach ($name in $tasks.Keys) {
    $action = New-ScheduledTaskAction -Execute $tasks[$name]
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Force
    Write-Output "registered: $name"
}

Write-Output ""
Write-Output "--- verifying ---"
foreach ($name in $tasks.Keys) {
    $task = Get-ScheduledTask -TaskName $name
    Write-Output "$name | LogonType=$($task.Principal.LogonType)"
}
