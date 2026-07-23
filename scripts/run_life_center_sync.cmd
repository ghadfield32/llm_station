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
cd /d "%~dp0.."
set KANBAN_EVENT_LOG=generated/kanban-events.jsonl
set KANBAN_BOARD_STORE=generated/boards
echo [%date% %time%] life_center_sync starting >> life_center_sync.log
.venv\Scripts\python.exe -m command_center.cli.life_center_sync >> life_center_sync.log 2>&1
echo [%date% %time%] life_center_sync exited (code %errorlevel%) >> life_center_sync.log
