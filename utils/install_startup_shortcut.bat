@echo off
title Install Event Finder Windows Startup Service
cd /d "%~dp0.."

echo Adding Event Finder (dashboard + background loop) to Windows Startup...

python utils\install_startup.py
if errorlevel 1 (
    echo [ERROR] Could not register or start Event Finder.
    if /I not "%~1"=="nopause" pause
    exit /b 1
)

echo.
echo [SUCCESS] Event Finder starts at Windows logon.
echo Dashboard: http://localhost:5050
echo.
if /I not "%~1"=="nopause" pause
