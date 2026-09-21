' YouTube Transcript Tool - silent launcher (no console window)
' NOTE: This file must stay pure ASCII. cmd/wscript read it with the
' system ANSI codepage (950 here), so non-ASCII bytes corrupt parsing.
Option Explicit

Dim sh, fso, base, script, exe
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base   = fso.GetParentFolderName(WScript.ScriptFullName)
script = base & "\ytscript.py"

If Not fso.FileExists(script) Then
    MsgBox "Cannot find ytscript.py next to this launcher.", 16, "YouTube Transcript Tool"
    WScript.Quit 1
End If

exe = FindPythonW()
If exe = "" Then
    MsgBox "Python was not found." & vbCrLf & vbCrLf & _
           "Install it from https://www.python.org/downloads/" & vbCrLf & _
           "and tick 'Add Python to PATH' during setup.", 16, "YouTube Transcript Tool"
    WScript.Quit 1
End If

sh.CurrentDirectory = base
sh.Run """" & exe & """ """ & script & """", 0, False

Function FindPythonW()
    Dim parts, i, p, folders, f
    FindPythonW = ""

    parts = Split(sh.ExpandEnvironmentStrings("%PATH%"), ";")
    For i = 0 To UBound(parts)
        p = Trim(parts(i))
        If Len(p) > 0 Then
            If Right(p, 1) <> "\" Then p = p & "\"
            If fso.FileExists(p & "pythonw.exe") Then
                FindPythonW = p & "pythonw.exe"
                Exit Function
            End If
        End If
    Next

    folders = Array("C:\python\pythonw.exe", "C:\Python313\pythonw.exe", _
                    "C:\Python312\pythonw.exe", "C:\Python311\pythonw.exe")
    For i = 0 To UBound(folders)
        If fso.FileExists(folders(i)) Then
            FindPythonW = folders(i)
            Exit Function
        End If
    Next

    p = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    If fso.FolderExists(p) Then
        For Each f In fso.GetFolder(p).SubFolders
            If fso.FileExists(f.Path & "\pythonw.exe") Then
                FindPythonW = f.Path & "\pythonw.exe"
                Exit Function
            End If
        Next
    End If
End Function
