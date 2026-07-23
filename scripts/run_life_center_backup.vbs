' Run run_life_center_backup.cmd with no visible console window (0 = hidden).
' The "LC daily backup" Scheduled Task action points at THIS file instead of
' cmd.exe directly, so the daily run no longer flashes a console window.
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.Run "cmd /c """ & here & "run_life_center_backup.cmd""", 0, True
