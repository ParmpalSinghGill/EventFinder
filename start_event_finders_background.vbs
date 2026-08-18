' VBScript to launch Web Control Dashboard and Background Event Manager natively in Windows
Set WshShell = CreateObject("WScript.Shell")
strCwd = "C:\DATA\CODE\Stocks\EventFinder"
WshShell.CurrentDirectory = strCwd

strPythonW = "C:\Users\parmp\anaconda3\pythonw.exe"

' Launch pythonw.exe natively in background without console window
WshShell.Run """" & strPythonW & """ web_control_dashboard.py", 0, False
WshShell.Run """" & strPythonW & """ background_event_manager.py", 0, False
