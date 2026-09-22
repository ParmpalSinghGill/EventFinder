@echo off
cd /d "C:\DATA\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\DATA\CODE\Stocks\EventFinder\stock\scheduler_run.py" >> "C:\DATA\CODE\Stocks\EventFinder\stock\data\screener_output\run.log" 2>&1
