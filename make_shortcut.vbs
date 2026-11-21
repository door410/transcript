' Create the desktop shortcut. PURE ASCII ONLY.
Option Explicit
Dim sh, fso, base, lnk
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)

Dim old: old = sh.SpecialFolders("Desktop") & "\YouTube Transcript.lnk"
If fso.FileExists(old) Then fso.DeleteFile old
Set lnk = sh.CreateShortcut(sh.SpecialFolders("Desktop") & "\transcript.lnk")
lnk.TargetPath       = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\wscript.exe"
lnk.Arguments        = """" & base & "\start.vbs"""
lnk.WorkingDirectory = base
lnk.IconLocation     = base & "\icon.ico,0"
lnk.Description      = "Video to AI-ready transcript"
lnk.Save
