@echo off
REM Supervisor loop for the Growth OS channels gateway. Runs the EXACT command
REM that works by hand (python -m command_center.channels) from repo root using
REM the project venv, and relaunches it if it ever exits.
REM
REM The Python process now OWNS gateway.log via a size-bounded RotatingFileHandler
REM (see channels/__main__.configure_logging), so this supervisor no longer pipes
REM the high-volume app stream into it — that was how gateway.log reached 391 MB.
REM Supervisor start/exit markers and any pre-logging traceback go to a SEPARATE,
REM tiny gateway-supervisor.log so crashes stay visible without re-growing the
REM main log. Launched hidden by start_gateway.vbs; managed by gateway.ps1.
cd /d "%~dp0.."
:loop
echo [%date% %time%] gateway starting >> gateway-supervisor.log
.venv\Scripts\python.exe -m command_center.channels >> gateway-supervisor.log 2>&1
echo [%date% %time%] gateway exited (code %errorlevel%) - relaunching in 5s >> gateway-supervisor.log
timeout /t 5 /nobreak >nul
goto loop
