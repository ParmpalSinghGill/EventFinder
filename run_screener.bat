@echo off
cd /d "C:\DATA\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\DATA\CODE\Stocks\EventFinder\scheduler_run.py" >> "C:\DATA\CODE\Stocks\EventFinder\data\screener_output\run.log" 2>&1
