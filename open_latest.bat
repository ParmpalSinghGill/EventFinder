@echo off
set "ARG=%~1"
echo.%ARG%| findstr /I "export" >nul && goto :export
echo.%ARG%| findstr /I "runeod" >nul && goto :runeod
echo.%ARG%| findstr /I "run"    >nul && goto :runlist
start "" "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder\data\screener_output\latest.html"
goto :eof
:export
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder\export_watchlist.py"
goto :eof
:runeod
cd /d "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder\scheduler_run.py" --eod >> "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder\data\screener_output\run.log" 2>&1
goto :eof
:runlist
cd /d "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder"
"C:\Users\parmp\anaconda3\envs\STOCK\python.exe" "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder\scheduler_run.py" --list >> "C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder\data\screener_output\run.log" 2>&1
goto :eof
