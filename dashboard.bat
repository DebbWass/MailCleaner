@echo off
cd /d "%~dp0"

echo ============================================================
echo    MailCleaner - Dashboard
echo ============================================================
echo.
echo The browser will open automatically at http://localhost:5000
echo.
echo IMPORTANT: Keep this window open while using the dashboard.
echo To stop: close this window, or press Ctrl+C.
echo ============================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo *** Python was not found on this computer ***
    echo Install Python from https://www.python.org and try again.
    echo.
    pause
    exit /b 1
)

rem Open the browser a few seconds after the server starts
start "" /b cmd /c "timeout /t 3 >nul && start http://localhost:5000"

rem Start the dashboard server (this window keeps it running)
python dashboard.py

echo.
echo ============================================================
echo    Dashboard stopped.
echo ============================================================
pause
