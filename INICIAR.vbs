' MRD TOOL CONTROL - Lanzador silencioso
' Arranca el icono de bandeja del sistema SIN ninguna ventana CMD visible.
' Doble clic para iniciar, o se ejecuta automaticamente al arrancar Windows.

Option Explicit

Dim WshShell, sDir, sPythonW, sScript, fso

sDir     = "C:\mrd tool\mrd_tool_control"
sPythonW = sDir & "\venv\Scripts\pythonw.exe"
sScript  = sDir & "\mrd_tray.py"

Set WshShell = WScript.CreateObject("WScript.Shell")
WshShell.CurrentDirectory = sDir

Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(sPythonW) Then
    sPythonW = "pythonw.exe"
End If

' WINDOW STYLE 0 = completamente invisible (sin CMD, sin consola)
WshShell.Run """" & sPythonW & """ """ & sScript & """", 0, False
