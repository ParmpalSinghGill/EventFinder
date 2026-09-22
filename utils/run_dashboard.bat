@echo off
title Event Finder Web Dashboard Launcher
echo Starting Event Finder Control Center Dashboard...
start http://localhost:5050
cd /d "C:\DATA\CODE\Stocks\EventFinder"
python utils\web_control_dashboard.py
pause
