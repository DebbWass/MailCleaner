@echo off
chcp 65001 >nul
title MailCleaner Weekly
cd /d "D:\AI_Agents\MailCleaner"

echo ============================================================
echo    MailCleaner - Weekly Run
echo    Started: %date% %time%
echo ============================================================
echo ==== Run started %date% %time% ==== >> logs\weekly_run.log

echo.
echo [1/2] Scanning and organizing mail (progress below)...
echo ------------------------------------------------------------
python mail_cleaner.py --mode auto --max 100 --skip-spam
if %errorlevel% neq 0 (
    echo *** MailCleaner FAILED - see logs\cleaner.log ***
    echo ==== MailCleaner FAILED %date% %time% ==== >> logs\weekly_run.log
) else (
    echo ==== MailCleaner OK %date% %time% ==== >> logs\weekly_run.log
)

echo.
echo [2/2] Sending summary email...
echo ------------------------------------------------------------
python send_summary.py
if %errorlevel% neq 0 (
    echo *** Email FAILED ***
    echo ==== Email FAILED %date% %time% ==== >> logs\weekly_run.log
) else (
    echo ==== Email sent %date% %time% ==== >> logs\weekly_run.log
)

echo.
echo ============================================================
echo    DONE! Check your inbox: sendit2dorit@gmail.com
echo    Window closes in 60 seconds (or press any key)
echo ============================================================
timeout /t 60 >nul
