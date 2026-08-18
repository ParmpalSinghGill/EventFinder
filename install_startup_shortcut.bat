@echo off
title Install Event Finder Windows Startup Service
echo Adding Event Finder Background Service to Windows Startup...

set "TARGET=C:\DATA\CODE\Stocks\EventFinder\start_event_finders_background.vbs"
set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\EventFinderBackground.lnk"

powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath='%TARGET%'; $s.Save()"

echo.
echo [SUCCESS] Event Finder is now registered with Windows Startup!
echo It will automatically start in the background whenever you turn on your laptop.
echo.
pause
