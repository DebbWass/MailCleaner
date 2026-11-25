@echo off
chcp 65001 >nul
title MailCleaner Dashboard
cd /d "%~dp0"

echo ============================================================
echo    MailCleaner - Dashboard
echo ============================================================
echo.
echo הדפדפן ייפתח אוטומטית בכתובת http://localhost:5000
echo.
echo חשוב: אל תסגרי את החלון הזה כל עוד את עובדת בדשבורד.
echo כדי לעצור: סגרי את החלון הזה, או לחצי Ctrl+C.
echo ============================================================
echo.

rem Make sure Python exists before trying to run
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo *** לא נמצאה התקנת Python במחשב ***
    echo התקיני Python מ-https://www.python.org ואז נסי שוב.
    echo.
    pause
    exit /b 1
)

rem Open the browser a few seconds after the server starts
start "" /b cmd /c "timeout /t 3 >nul && start http://localhost:5000"

rem Start the dashboard server (this keeps the window open and running)
python dashboard.py

echo.
echo ============================================================
echo    הדשבורד נעצר.
echo ============================================================
pause
