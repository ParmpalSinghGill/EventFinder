@echo off
title Event Finder Web Dashboard Launcher
echo Starting Event Finder Control Center Dashboard...
cd /d "%~dp0.."
start http://localhost:5050
python utils\web_control_dashboard.py
pause
