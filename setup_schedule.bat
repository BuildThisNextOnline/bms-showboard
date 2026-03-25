@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==========================================
echo  BMS Show Board -- Schedule Sunday Run
echo ==========================================
echo.
echo This creates a Windows Task Scheduler task that runs the
echo BMS scraper automatically every Sunday at 9:00 AM.
echo.
echo Press any key to set up the scheduled task, or Ctrl+C to cancel.
pause >nul

set TASK_NAME=BMS Show Board Weekly Scrape
set SCRIPT_PATH=%~dp0run_bms_scheduled.bat

REM Delete existing task if present
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM Use PowerShell to create the task -- handles spaces in paths correctly
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$scriptPath = '%SCRIPT_PATH%';" ^
  "$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "' + $scriptPath + '"');" ^
  "$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '09:00';" ^
  "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable;" ^
  "Register-ScheduledTask -TaskName '%TASK_NAME%' -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null;" ^
  "Write-Host 'Task created OK'"

if errorlevel 1 (
    echo.
    echo ERROR: PowerShell could not create the task.
    echo.
    echo Set it up manually in Task Scheduler:
    echo 1. Open Task Scheduler from Start menu
    echo 2. Click "Create Basic Task" on the right
    echo 3. Name: BMS Show Board Weekly Scrape
    echo 4. Trigger: Weekly, Sunday, 9:00 AM
    echo 5. Action: Start a program
    echo 6. Program/script: cmd.exe
    echo 7. Add arguments: /c "%SCRIPT_PATH%"
    echo 8. Click Finish
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Done. Task scheduled for every Sunday at 9:00 AM.
echo  To verify: open Task Scheduler and find
echo  "%TASK_NAME%"
echo ==========================================
echo.
pause
