' Run run_kanban_bridge.cmd with no visible console window (0 = hidden).
' The "CC kanban bridge" Scheduled Task action points at THIS file instead of
' cmd.exe directly, so the 15-min cadence no longer flashes a console window.
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.Run "cmd /c """ & here & "run_kanban_bridge.cmd""", 0, True
