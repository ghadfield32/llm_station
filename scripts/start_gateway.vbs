' Run start_gateway.cmd with no visible console window (0 = hidden).
' Point a Startup-folder shortcut at THIS file for a clean, no-admin autostart.
Dim sh, here
Set sh = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.Run "cmd /c """ & here & "start_gateway.cmd""", 0, False
