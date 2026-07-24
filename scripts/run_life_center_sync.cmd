@echo off
REM Refreshes the Life Center health projection (Services/Overview/Operations
REM boards) on the Task Scheduler 15-min cadence, output captured to
REM life_center_sync.log instead of a flashing console window. Launched hidden
REM via run_life_center_sync.vbs (same pattern as run_kanban_bridge.vbs).
REM
REM Why a HOST-side schedule: the sync shells out to `docker compose ps` via
REM life-center-infra/lc.py, so it needs the Docker CLI + host-network access
REM that the containerized cockpit deliberately does NOT have. Without this
REM cadence the Overview projection ages past its 1-hour staleness threshold
REM and every service correctly reports "unknown / status stale" in the UI.
REM RETRY: the board store is single-writer (BoardWriteLocked). This job shares
REM it with the "CC kanban bridge" task and with any live agent session, so a
REM collision is routine, not exceptional -- observed live on the 20:19 run.
REM Without a retry the sync dies on contention and the projection silently ages
REM into "unknown / status stale", i.e. the exact failure this job prevents.
REM Three attempts, 20s apart, stays well inside the 15-min cadence.
cd /d "%~dp0.."
set KANBAN_EVENT_LOG=generated/kanban-events.jsonl
set KANBAN_BOARD_STORE=generated/boards
echo [%date% %time%] life_center_sync starting >> life_center_sync.log
set ATTEMPT=0
:lc_sync_retry
set /a ATTEMPT+=1
.venv\Scripts\python.exe -m command_center.cli.life_center_sync >> life_center_sync.log 2>&1
if %errorlevel%==0 goto lc_sync_done
if %ATTEMPT% GEQ 3 goto lc_sync_done
echo [%date% %time%] attempt %ATTEMPT% failed (likely BoardWriteLocked); retrying in 20s >> life_center_sync.log
timeout /t 20 /nobreak >nul
goto lc_sync_retry
:lc_sync_done
echo [%date% %time%] life_center_sync exited (code %errorlevel%) after %ATTEMPT% attempt(s) >> life_center_sync.log
