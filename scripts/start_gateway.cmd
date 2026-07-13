@echo off
REM Supervisor loop for the Growth OS channels gateway. Runs the EXACT command
REM that works by hand (python -m command_center.channels) from repo root using
REM the project venv, and relaunches it if it ever exits.
REM
REM The Python process now OWNS gateway.log via a size-bounded RotatingFileHandler
REM (see channels/__main__.configure_logging), so this supervisor no longer pipes
REM the high-volume app stream into it — that was how gateway.log reached 391 MB.
REM Supervisor start/exit markers and any pre-logging traceback go to a SEPARATE
REM gateway-supervisor.log so crashes stay visible without re-growing the main
REM log. That file is NOT immune to the same problem, though: an actual crash
REM loop (e.g. a broken dependency import, one line per exit + a traceback every
REM iteration) can grow it unbounded too — observed 2026-07-02, ~2400 crash
REM cycles over a few hours. So it gets the same treatment: a plain size check
REM before each iteration, one backup kept, no extra process spawned. Launched
REM hidden by start_gateway.vbs; managed by gateway.ps1.
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set SUPERVISOR_LOG=gateway-supervisor.log
set SUPERVISOR_LOG_MAX_BYTES=26214400
:loop
if exist "%SUPERVISOR_LOG%" (
  for %%A in ("%SUPERVISOR_LOG%") do set SUPERVISOR_LOG_SIZE=%%~zA
  if !SUPERVISOR_LOG_SIZE! GTR %SUPERVISOR_LOG_MAX_BYTES% (
    if exist "%SUPERVISOR_LOG%.old" del /f /q "%SUPERVISOR_LOG%.old"
    ren "%SUPERVISOR_LOG%" "%SUPERVISOR_LOG%.old"
  )
)
echo [%date% %time%] gateway starting >> %SUPERVISOR_LOG%
.venv\Scripts\python.exe -m command_center.channels >> %SUPERVISOR_LOG% 2>&1
echo [%date% %time%] gateway exited (code %errorlevel%) - relaunching in 5s >> %SUPERVISOR_LOG%
timeout /t 5 /nobreak >nul
goto loop
