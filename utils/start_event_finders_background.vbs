' Starts the dashboard (http://localhost:5050) and the gold/stock loop at logon.
' Paths come from this script's folder so a wrong shortcut working directory still works.
Option Explicit

Dim fso, sh, utilsDir, rootDir, pythonw, dash, mgr
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

utilsDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootDir = fso.GetParentFolderName(utilsDir)
sh.CurrentDirectory = rootDir

pythonw = ""
If fso.FileExists("C:\Users\parmp\anaconda3\pythonw.exe") Then
    pythonw = "C:\Users\parmp\anaconda3\pythonw.exe"
ElseIf fso.FileExists("C:\Users\parmp\anaconda3\python.exe") Then
    pythonw = "C:\Users\parmp\anaconda3\python.exe"
Else
    pythonw = "pythonw.exe"
End If

dash = fso.BuildPath(utilsDir, "web_control_dashboard.py")
mgr = fso.BuildPath(utilsDir, "background_event_manager.py")

If Not fso.FolderExists(fso.BuildPath(utilsDir, "logs")) Then
    fso.CreateFolder fso.BuildPath(utilsDir, "logs")
End If

sh.Run """" & pythonw & """ """ & dash & """", 0, False
sh.Run """" & pythonw & """ """ & mgr & """", 0, False
