@echo off
REM Daily Life Center restic backup (3-2-1 local leg), launched hidden via
REM run_life_center_backup.vbs. Output appended to life_center_backup.log.
REM
REM STEP 1 is not optional: Vaultwarden's SQLite runs in WAL mode, so copying
REM the live db.sqlite3 straight into restic can capture a TORN state. The USR1
REM signal makes Vaultwarden write a consistent db_<timestamp>.sqlite3 snapshot
REM first; that file is what a restore should actually be taken from.
REM
REM Deliberately NO `forget`/`prune` here. foundation.yml's own comment is the
REM reason: a credential that can rewrite or forget snapshots can destroy
REM recovery history, so the unattended daily job must not hold that power.
REM Retention is a separate, human-run maintenance step.
cd /d "%~dp0..\life-center-infra"
echo [%date% %time%] life_center_backup starting >> ..\life_center_backup.log

REM 1) consistent Vaultwarden SQLite snapshot (ignored if the container is down)
docker kill --signal=USR1 lc-vaultwarden >> ..\life_center_backup.log 2>&1

REM 2) restic backup of appdata + data
docker compose --project-directory . --env-file .env -f compose/foundation.yml ^
  --profile backup run --rm backup backup /appdata /data --tag life-center ^
  >> ..\life_center_backup.log 2>&1

echo [%date% %time%] life_center_backup exited (code %errorlevel%) >> ..\life_center_backup.log
