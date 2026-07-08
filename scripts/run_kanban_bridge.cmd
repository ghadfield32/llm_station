@echo off
REM Runs kanban_bridge on the Task Scheduler 15-min cadence, output captured to
REM kanban_bridge.log instead of a flashing console window. Launched hidden via
REM run_kanban_bridge.vbs (same pattern as start_gateway.vbs/start_gateway.cmd).
cd /d "%~dp0.."
echo [%date% %time%] kanban_bridge starting >> kanban_bridge.log
.venv\Scripts\python.exe -m command_center.cli.kanban_bridge --apply >> kanban_bridge.log 2>&1
echo [%date% %time%] kanban_bridge exited (code %errorlevel%) >> kanban_bridge.log
