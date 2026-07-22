@echo off
set "ARG=%~1"
echo.%ARG%| findstr /I "export" >nul && goto :export
echo.%ARG%| findstr /I "runeod" >nul && goto :runeod
echo.%ARG%| findstr /I "run"    >nul && goto :runlist
start "" "C:\DATA\CODE\Stocks\EventFinder\data\screener_output\latest.html"
goto :eof
:export
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\DATA\CODE\Stocks\EventFinder\export_watchlist.py"
goto :eof
:runeod
cd /d "C:\DATA\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\DATA\CODE\Stocks\EventFinder\scheduler_run.py" --eod >> "C:\DATA\CODE\Stocks\EventFinder\data\screener_output\run.log" 2>&1
goto :eof
:runlist
cd /d "C:\DATA\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\DATA\CODE\Stocks\EventFinder\scheduler_run.py" --list >> "C:\DATA\CODE\Stocks\EventFinder\data\screener_output\run.log" 2>&1
goto :eof
