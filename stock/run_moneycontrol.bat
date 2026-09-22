@echo off
cd /d "C:\DATA\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\DATA\CODE\Stocks\EventFinder\stock\scrape_moneycontrol_stocks.py" >> "C:\DATA\CODE\Stocks\EventFinder\stock\data\screener_output\run_moneycontrol.log" 2>&1
