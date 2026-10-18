' Silent launcher for the local video editor.
Option Explicit

Dim shell, fso, root, script, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
script = root & "\start-silent.ps1"
command = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & script & """"

' Used by automated verification without opening Edge.
If WScript.Arguments.Named.Exists("NoBrowser") Then
    command = command & " -NoBrowser"
End If

' Window style 0 keeps the PowerShell host hidden.
shell.Run command, 0, False
