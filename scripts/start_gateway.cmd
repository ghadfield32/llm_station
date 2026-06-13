@echo off
REM Supervisor loop for the Growth OS channels gateway. Runs the EXACT command
REM that works by hand (python -m command_center.channels) from repo root using
REM the project venv, and relaunches it if it ever exits. Every start and exit
REM is timestamped into gateway.log so crashes are visible, never swallowed.
REM Launched hidden by start_gateway.vbs; managed by gateway.ps1.
cd /d "%~dp0.."
:loop
echo [%date% %time%] gateway starting >> gateway.log
.venv\Scripts\python.exe -m command_center.channels >> gateway.log 2>&1
echo [%date% %time%] gateway exited (code %errorlevel%) - relaunching in 5s >> gateway.log
timeout /t 5 /nobreak >nul
goto loop
