@echo off
title Spot XAUUSD Event Finder Monitor
cd /d "C:\DATA\CODE\Stocks\EventFinder"
echo =======================================================
echo  Running Spot XAU/USD Event Finder & Level Monitor
echo =======================================================
python xauusd_event_finder.py
pause
