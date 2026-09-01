# Run from an elevated PowerShell (right-click PowerShell -> Run as administrator):
#   cd "C:\Users\Eva Ng\Desktop\ironman\repo"
#   .\scripts\fix_whatsapp_task_startup.ps1
#
# Re-registers CommsPlatformWhatsApp to:
# 1. Start automatically when Windows boots (AtStartup trigger)
# 2. Keep running even if nobody is logged in (LogonType S4U)

$action = New-ScheduledTaskAction -Execute "C:\Users\Eva Ng\Desktop\ironman\repo\scripts\run_whatsapp_connector.bat"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

Unregister-ScheduledTask -TaskName "CommsPlatformWhatsApp" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "CommsPlatformWhatsApp" -Action $action -Trigger $trigger -Principal $principal -Force

Write-Output ""
Write-Output "--- verifying ---"
$task = Get-ScheduledTask -TaskName "CommsPlatformWhatsApp"
Write-Output "LogonType=$($task.Principal.LogonType)"
$task.Triggers | Format-List
