@echo off
REM One-time setup: registers a Windows scheduled task
REM Runs MailCleaner every Sunday at 08:00 and emails a summary
schtasks /Create /TN "MailCleaner Weekly" /TR "\"D:\AI_Agents\MailCleaner\run_weekly.bat\"" /SC WEEKLY /D SUN /ST 22:05 /F
if %errorlevel%==0 (
    echo.
    echo SUCCESS: "MailCleaner Weekly" scheduled - every Sunday 22:05
    echo To change day/time: Task Scheduler ^> MailCleaner Weekly
) else (
    echo.
    echo FAILED - try running this file as Administrator
)
pause
