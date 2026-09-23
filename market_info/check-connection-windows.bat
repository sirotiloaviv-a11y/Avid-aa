@echo off
chcp 65001 >nul
cd /d "%~dp0"
where node >nul 2>nul || (echo Node.js is not installed. Download it from https://nodejs.org & pause & exit /b 1)
node scripts\check-connection.mjs
echo.
echo The report was saved to connection-report.txt (open it in Notepad to read the Hebrew text).
start "" notepad connection-report.txt
pause
